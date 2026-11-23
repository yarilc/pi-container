# Spec Delta

## ADDED Requirements

### Requirement: Only the systemd cgroup manager delegates controllers

A reported cgroup v2 controller SHALL count as delegated only when the verified rootless engine also reports the `systemd` cgroup manager. With `cgroupfs` or any other manager, no controller SHALL count as delegated, whatever the engine reports. An unverifiable cgroup manager response SHALL stop startup before image operations.

#### Scenario: cgroupfs engine reporting every controller

- **WHEN** a session starts on a rootless engine with the `cgroupfs` manager that reports `cpu`, `memory` and `pids`
- **THEN** the container is created without memory, CPU or cgroup process limits
- **AND** the session prints notices that the memory and CPU budgets are not enforced, naming the `cgroupfs` cgroup manager
- **AND** the process budget follows the process rlimit fallback

#### Scenario: systemd engine

- **WHEN** a session starts on a rootless engine with the `systemd` manager that reports `cpu`, `memory` and `pids`
- **THEN** the memory, CPU and cgroup process limits are applied as before

#### Scenario: Unverifiable cgroup manager

- **WHEN** the engine's cgroup manager response is empty, malformed or has more than one record
- **THEN** the wrapper exits non-zero before image operations or container creation

### Requirement: Process budget falls back to the process rlimit

When the verified engine does not delegate the `pids` controller and the engine host counts the process rlimit per container, the agent container SHALL be created with a soft and hard process rlimit equal to the selected process budget. When per-container counting is not established, the process budget SHALL stay unenforced. The memory and CPU budgets SHALL have no fallback.

#### Scenario: Process controller missing on a per-container host

- **WHEN** a session starts with the default budgets on an engine delegating `cpu` and `memory` but not `pids`, on a host that counts the process rlimit per container
- **THEN** the container is created with a soft and hard process rlimit of 512 and without a cgroup process limit
- **AND** the memory and CPU limits are applied as before

#### Scenario: Process controller delegated

- **WHEN** the engine delegates the `pids` controller
- **THEN** the process budget is enforced only by the cgroup process limit
- **AND** the wrapper sets no process rlimit

#### Scenario: Per-container counting not established

- **WHEN** the engine does not delegate `pids` and the host is not known to count the process rlimit per container
- **THEN** the wrapper requests neither a cgroup process limit nor a process rlimit for the container
- **AND** the session continues with a notice that names the unenforced process budget and why the fallback was not applied

#### Scenario: Memory controller missing

- **WHEN** the engine does not delegate the `memory` controller
- **THEN** the memory budget stays unenforced and no substitute memory limit is set

#### Scenario: The session cannot raise its process rlimit

- **WHEN** a process in a session on the fallback tries to raise its soft or hard process rlimit above the selected budget
- **THEN** the attempt fails, because the session has no capabilities and no-new-privileges is set

#### Scenario: Concurrent sessions have independent limits

- **WHEN** two sessions on the fallback run at the same time and the first holds processes up to its limit
- **THEN** the second session can still create processes up to its own limit

### Requirement: Process rlimit fallback is verified

When the process budget uses the rlimit fallback, each launch SHALL require the created agent container to carry a soft and hard process rlimit equal to the selected budget. Setup smoke and restricted qualification SHALL measure the same effective limit inside the agent container. A mismatch SHALL stop startup or setup with an actionable diagnostic, without a retry using weaker limits.

#### Scenario: Engine drops the process rlimit

- **WHEN** the created container reports no process rlimit, or a soft or hard value different from the selected budget
- **THEN** the wrapper removes only its own container and exits non-zero before the application starts
- **AND** the diagnostic names the process rlimit fallback

#### Scenario: Effective rlimit is measured

- **WHEN** setup smoke or the restricted qualification probe runs inside an agent container on the fallback
- **THEN** it reads the effective soft and hard process rlimit and requires both to equal the selected budget
- **AND** it requires the cgroup process interface to be absent or unlimited

## MODIFIED Requirements

### Requirement: Sessions have explicit resource budgets

Every Pi and shell container SHALL be created with a memory limit, a CPU limit and a process limit for each budget whose cgroup v2 controller (`memory`, `cpu`, `pids`) the verified rootless engine delegates. The defaults SHALL be 4 GiB memory, 2 CPUs and 512 processes. `PI_CONTAINER_MEMORY_LIMIT`, `PI_CONTAINER_CPU_LIMIT` and `PI_CONTAINER_PIDS_LIMIT` SHALL override them. Only an unset variable SHALL select its default; no value SHALL disable a budget, and only a missing controller SHALL leave it unenforced.

#### Scenario: Accepted formats

- **WHEN** the operator sets a budget variable
- **THEN** memory accepts a positive integer with unit `k`, `m` or `g`, CPU accepts a positive decimal with at most three fractional digits up to 1024, and the process limit accepts an integer from 1 to 4194304

#### Scenario: Default budgets

- **WHEN** a session starts with none of the budget variables set on an engine delegating the `cpu`, `memory` and `pids` controllers
- **THEN** the container is created with 4 GiB memory, 2 CPUs and 512 processes

#### Scenario: Operator overrides budgets

- **WHEN** the operator sets `PI_CONTAINER_MEMORY_LIMIT=8g`, `PI_CONTAINER_CPU_LIMIT=1.5` and `PI_CONTAINER_PIDS_LIMIT=1024` on an engine delegating all three controllers
- **THEN** the container is created with exactly those limits

#### Scenario: Invalid or unbounded budget value

- **WHEN** a budget variable is set but empty or whitespace, zero, negative, `-1`, `max`, non-numeric, out of range, or has an unsupported unit
- **THEN** the wrapper exits with status 1 and names the variable before any engine query, state creation or image operation

#### Scenario: Controller not delegated

- **WHEN** the verified engine does not delegate the `cpu` controller
- **THEN** the container is created without a CPU limit, while the memory and process limits are still applied when their controllers are delegated
- **AND** the session continues and prints a notice naming the unenforced CPU budget and why it is unenforced

#### Scenario: Process controller not delegated

- **WHEN** the verified engine does not delegate the `pids` controller
- **THEN** the container is created with an explicitly unlimited cgroup process setting, so no engine default requests the missing controller
- **AND** the process budget follows the process rlimit fallback

### Requirement: Resource budgets are verified, not assumed

Before starting the application, each launch SHALL inspect the created container and require each cgroup-enforced budget to equal its selected value and each budget whose controller is not delegated to have no cgroup limit. A mismatch or missing enforced limit SHALL stop startup with an actionable diagnostic, without a retry using weaker limits. Runtime verification SHALL measure the effective cgroup v2 limits inside the session in the same way.

#### Scenario: Engine ignores a budget

- **WHEN** the created container reports no limit or a different limit for a budget whose controller the engine delegates
- **THEN** the wrapper removes only its own container and exits non-zero before the application starts
- **AND** the diagnostic names rootless cgroup v2 controller delegation and the controllers the engine reported

#### Scenario: Unenforced budget unexpectedly present

- **WHEN** the created container reports a cgroup limit for a budget whose controller the engine does not delegate
- **THEN** the wrapper removes only its own container and exits non-zero before the application starts

#### Scenario: Effective limits are measured

- **WHEN** the real-engine runtime checks run a session with default and overridden budgets
- **THEN** the container's cgroup v2 `memory.max`, `pids.max` and `cpu.max` match the selected budgets for every delegated controller, and are absent or unlimited for the others
- **AND** on the process rlimit fallback, the session's soft and hard process rlimit equal the selected process budget
- **AND** a process count beyond the process limit fails inside the session, unless the process budget is unenforced

### Requirement: Hardening controls are documented

Wrapper help and the README SHALL document the budget variables with defaults and accepted formats, the lifetime variable, the unsafe-workspace override with the refused directories, and that capabilities are dropped in every mode. They SHALL document the process rlimit fallback, its per-session scope, the condition under which it applies, and that memory and CPU have no fallback. They SHALL state that budgets and tmpfs sizes do not bound workspace or state storage growth. Help SHALL remain free of engine queries and state creation.

#### Scenario: Operator reads wrapper help

- **WHEN** the operator runs `--container-help`
- **THEN** the output lists `PI_CONTAINER_MEMORY_LIMIT`, `PI_CONTAINER_CPU_LIMIT`, `PI_CONTAINER_PIDS_LIMIT`, `PI_CONTAINER_RUN_TIMEOUT` and `PI_CONTAINER_ALLOW_UNSAFE_WORKSPACE` with their defaults
- **AND** it states that capabilities are dropped and budgets do not limit persistent storage
- **AND** no engine query or state creation occurs

#### Scenario: Operator reads about the process rlimit fallback

- **WHEN** the operator reads the README or wrapper help
- **THEN** it states that, without the `pids` controller, the process budget is enforced through the process rlimit per session when the host counts it per container
- **AND** it states that the usable process count is slightly below the budget because of container startup tasks

# Spec Delta

## MODIFIED Requirements

### Requirement: Explicit bounded ephemeral storage

Read-only sessions SHALL explicitly provide `/tmp`, `/var/tmp`, `/run`, the container home and a separate npm cache with finite capacities, nosuid/nodev, deliberate execution modes, and mapped-user access. Automatic read-only tmpfs provisioning SHALL add no writable path beyond these explicit temporary and device mounts. Podman storage SHALL follow the same policy. Temporary contents SHALL disappear after the session.

#### Scenario: Declared temporary mount policy

- **WHEN** a default session starts
- **THEN** `/tmp` and `/var/tmp` each provide 256 MiB and `/run` 32 MiB with rw,noexec,nosuid,nodev,mode=1777, `/pi-home` provides a noexec,nosuid,nodev home, and `/pi-home/.npm` provides rw,noexec,nosuid,nodev with caller access and a default 256 MiB capacity configurable by `PI_NPM_CACHE_SIZE`.

#### Scenario: Writable scope and lifetime

- **WHEN** the mapped user writes in every temporary location, attempts a root-filesystem write, and starts a second session
- **THEN** temporary writes succeed within capacity, the root write fails, and previous temporary data is absent while writable persistent state remains.

### Requirement: Sessions have explicit resource budgets
Every Pi and shell container SHALL be created with a memory limit, a CPU limit and a process limit for each budget whose cgroup v2 controller (`memory`, `cpu`, `pids`) the verified rootless engine reports as available. The defaults SHALL be 4 GiB memory, 2 CPUs and 512 processes. `PI_CONTAINER_MEMORY_LIMIT`, `PI_CONTAINER_CPU_LIMIT` and `PI_CONTAINER_PIDS_LIMIT` SHALL override them. Only an unset variable SHALL select its default; no value SHALL disable a budget, and only a missing controller SHALL leave it unenforced.

#### Scenario: Accepted formats
- **WHEN** the operator sets a budget variable
- **THEN** memory accepts a positive integer with unit `k`, `m` or `g`, CPU accepts a positive decimal with at most three fractional digits up to 1024, and the process limit accepts an integer from 1 to 4194304

#### Scenario: Default budgets
- **WHEN** a session starts with none of the budget variables set on an engine reporting the `cpu`, `memory` and `pids` controllers
- **THEN** the container is created with 4 GiB memory, 2 CPUs and 512 processes

#### Scenario: Operator overrides budgets
- **WHEN** the operator sets `PI_CONTAINER_MEMORY_LIMIT=8g`, `PI_CONTAINER_CPU_LIMIT=1.5` and `PI_CONTAINER_PIDS_LIMIT=1024` on an engine reporting all three controllers
- **THEN** the container is created with exactly those limits

#### Scenario: Invalid or unbounded budget value
- **WHEN** a budget variable is set but empty or whitespace, zero, negative, `-1`, `max`, non-numeric, out of range, or has an unsupported unit
- **THEN** the wrapper exits with status 1 and names the variable before any engine query, state creation or image operation

#### Scenario: Controller not delegated
- **WHEN** the verified engine does not report the `cpu` controller
- **THEN** the container is created without a CPU limit, while the memory and process limits are still applied when their controllers are reported
- **AND** the session continues and prints a notice naming the unenforced CPU budget and the missing controller

#### Scenario: Process controller not delegated
- **WHEN** the verified engine does not report the `pids` controller
- **THEN** the container is created with an explicitly unlimited process setting, so no engine default requests the missing controller

### Requirement: Resource budgets are verified, not assumed
Before starting the application, each launch SHALL inspect the created container and require each enforced budget to equal its selected value and each unenforced budget to be absent. A mismatch or missing enforced limit SHALL stop startup with an actionable diagnostic, without a retry using weaker limits. Runtime verification SHALL measure the effective cgroup v2 limits inside the session in the same way.

#### Scenario: Engine ignores a budget
- **WHEN** the created container reports no limit or a different limit for a budget whose controller the engine reports as available
- **THEN** the wrapper removes only its own container and exits non-zero before the application starts
- **AND** the diagnostic names rootless cgroup v2 controller delegation and the controllers the engine reported

#### Scenario: Unenforced budget unexpectedly present
- **WHEN** the created container reports a limit for a budget whose controller the engine does not report
- **THEN** the wrapper removes only its own container and exits non-zero before the application starts

#### Scenario: Effective limits are measured
- **WHEN** the real-engine runtime checks run a session with default and overridden budgets on an engine reporting all three controllers
- **THEN** the container's cgroup v2 `memory.max`, `pids.max` and `cpu.max` match the selected budgets
- **AND** a process count beyond the process limit fails inside the session

## ADDED Requirements

### Requirement: Engine default secrets mount is masked
Every Pi and shell container SHALL be created with an empty read-only tmpfs at `/run/secrets`, in every network mode and with or without Podman access. An engine default mount there, such as RHEL subscription secrets from `mounts.conf`, SHALL then be neither visible nor writable. No host configuration change SHALL be required.

#### Scenario: Host with a default secrets mount
- **WHEN** the engine's `mounts.conf` maps `/usr/share/rhel/secrets` to `/run/secrets`
- **THEN** the session has exactly one mount at `/run/secrets`, an empty tmpfs mounted read-only
- **AND** no host subscription file is readable inside the session

#### Scenario: Host without a default secrets mount
- **WHEN** the engine adds no mount at `/run/secrets`
- **THEN** the session still has the empty read-only tmpfs there and behaves as before

### Requirement: Terminal-compatible device mounts
Every Pi and shell container SHALL provide its own `/dev` tmpfs with `nosuid,noexec`, mode `755` and a 64 MiB limit, an explicit `devpts` at `/dev/pts`, and an empty read-only tmpfs at `/dev/shm`. A terminal SHALL then attach where the engine would otherwise mount `/dev` read-only. Automatic read-only tmpfs provisioning SHALL add no writable path beyond the explicit temporary and device mounts.

#### Scenario: Terminal attaches on an engine that mounts /dev read-only
- **WHEN** an interactive session starts with a terminal on Podman 5 with crun 1.27
- **THEN** the terminal attaches and Pi starts without any host configuration change
- **AND** `/dev` is not executable, `/dev/pts` is present, and `/dev/shm` is read-only and empty

#### Scenario: Executables cannot run from /dev
- **WHEN** a session copies an executable into `/dev`
- **THEN** the mount policy prevents its direct execution

#### Scenario: Temporary mounts keep their Pi policy
- **WHEN** a session starts with the device mounts
- **THEN** `/tmp`, `/var/tmp` and `/run` keep their `noexec` 256, 256 and 32 MiB policy, and the home and npm cache keep theirs
- **AND** no writable `/var/log` tmpfs or writable `/dev/shm` is introduced by automatic provisioning

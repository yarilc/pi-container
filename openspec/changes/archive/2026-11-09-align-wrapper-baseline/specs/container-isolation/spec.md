# Spec Delta

## ADDED Requirements

### Requirement: Sessions have explicit resource budgets

Every Pi and shell container SHALL be created with a memory limit, a CPU limit and a process limit. The defaults SHALL be 4 GiB memory, 2 CPUs and 512 processes. `PI_CONTAINER_MEMORY_LIMIT`, `PI_CONTAINER_CPU_LIMIT` and `PI_CONTAINER_PIDS_LIMIT` SHALL override them. Only an unset variable SHALL select its default; no value SHALL disable a budget.

#### Scenario: Accepted formats

- **WHEN** the operator sets a budget variable
- **THEN** memory accepts a positive integer with unit `k`, `m` or `g`, CPU accepts a positive decimal with at most three fractional digits up to 1024, and the process limit accepts an integer from 1 to 4194304

#### Scenario: Default budgets

- **WHEN** a session starts with none of the budget variables set
- **THEN** the container is created with 4 GiB memory, 2 CPUs and 512 processes

#### Scenario: Operator overrides budgets

- **WHEN** the operator sets `PI_CONTAINER_MEMORY_LIMIT=8g`, `PI_CONTAINER_CPU_LIMIT=1.5` and `PI_CONTAINER_PIDS_LIMIT=1024`
- **THEN** the container is created with exactly those limits

#### Scenario: Invalid or unbounded budget value

- **WHEN** a budget variable is set but empty or whitespace, zero, negative, `-1`, `max`, non-numeric, out of range, or has an unsupported unit
- **THEN** the wrapper exits with status 1 and names the variable before any engine query, state creation or image operation

### Requirement: Resource budgets are verified, not assumed

Before starting the application, each launch SHALL inspect the created container and require its configured memory, CPU and process limits to equal the selected budgets. A mismatch or missing limit SHALL stop startup with an actionable diagnostic, without a retry using weaker limits. Runtime verification SHALL measure the effective cgroup v2 limits inside the session.

#### Scenario: Engine ignores a budget

- **WHEN** the created container reports no limit or a different limit for memory, CPU or processes
- **THEN** the wrapper removes only its own container and exits non-zero before the application starts
- **AND** the diagnostic names rootless cgroup v2 controller delegation

#### Scenario: Effective limits are measured

- **WHEN** the real-engine runtime checks run a session with default and overridden budgets
- **THEN** the container's cgroup v2 `memory.max`, `pids.max` and `cpu.max` match the selected budgets
- **AND** a process count beyond the process limit fails inside the session

### Requirement: Hardening controls are documented

Wrapper help and the README SHALL document the budget variables with defaults and accepted formats, the lifetime variable, the unsafe-workspace override with the refused directories, and that capabilities are dropped in every mode. They SHALL state that budgets and tmpfs sizes do not bound workspace or state storage growth. Help SHALL remain free of engine queries and state creation.

#### Scenario: Operator reads wrapper help

- **WHEN** the operator runs `--container-help`
- **THEN** the output lists `PI_CONTAINER_MEMORY_LIMIT`, `PI_CONTAINER_CPU_LIMIT`, `PI_CONTAINER_PIDS_LIMIT`, `PI_CONTAINER_RUN_TIMEOUT` and `PI_CONTAINER_ALLOW_UNSAFE_WORKSPACE` with their defaults
- **AND** it states that capabilities are dropped and budgets do not limit persistent storage
- **AND** no engine query or state creation occurs

## MODIFIED Requirements

### Requirement: Physical workspace binds without host relabeling

The default workspace source, destination, and workdir SHALL be the exact physical absolute current directory. Workspace and state binds SHALL omit automatic SELinux relabeling. The sensitive-workspace refusal of the `workspace-mounts` capability SHALL apply to the exposed workspace, including the parent selected by worktree mode. Access failures SHALL not trigger relabeling or confinement bypasses.

#### Scenario: Symlinked launch directory

- **WHEN** a session starts through a symlink to a project, including a path with spaces
- **THEN** the bind source/destination and workdir retain the physical absolute path and no `:z` or `:Z` mount option is used.

#### Scenario: Sensitive parent or SELinux denial

- **WHEN** worktree mode exposes a refused parent without `PI_CONTAINER_ALLOW_UNSAFE_WORKSPACE=1`, or host policy denies mount access
- **THEN** startup fails with an actionable diagnostic and does not change host labels or disable security enforcement.

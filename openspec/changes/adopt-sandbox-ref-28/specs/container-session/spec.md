# Spec Delta

## MODIFIED Requirements

### Requirement: Qualification binds agent hardening settings
The qualification identity of a restricted installation SHALL include:
- the agent capability and no-new-privileges settings;
- the selected memory, CPU and process budgets;
- the set of agent and proxy budgets actually enforced, as determined by the controllers the engine delegates;
- the mechanism enforcing each agent and proxy process budget: cgroup controller, process rlimit, or none;
- the session lifetime setting.

A launch whose effective settings differ from the qualified identity SHALL stop with requalification guidance.

#### Scenario: Budget changed after qualification
- **WHEN** an installation was qualified with default budgets and the operator launches with `PI_CONTAINER_PIDS_LIMIT=1024`
- **THEN** the qualification check reports mismatched evidence and Pi does not start

#### Scenario: Matching settings
- **WHEN** the operator qualifies and launches with the same budgets and lifetime
- **THEN** the qualification check accepts the report

#### Scenario: Controller delegation changed after qualification
- **WHEN** an installation was qualified while `cpu` was not delegated and the engine later delegates `cpu`
- **THEN** the qualification check reports mismatched evidence and requires requalification

#### Scenario: Process budget mechanism changed after qualification
- **WHEN** an installation was qualified with the agent process budget on the process rlimit fallback and the engine later delegates `pids`
- **THEN** the qualification check reports mismatched evidence and requires requalification

### Requirement: Unenforced budgets are announced
Each launch SHALL print one notice per unenforced agent or proxy budget, naming the budget, its container and the reason: the missing cgroup controller, or a cgroup manager that applies no cgroup limits. A process budget enforced through the process rlimit fallback SHALL get one notice naming the budget, its container and the rlimit mechanism instead. Notices SHALL NOT ask for confirmation. When every budget is enforced by its cgroup controller, no notice SHALL be printed.

#### Scenario: CPU controller missing
- **WHEN** a session starts on an engine delegating only `memory` and `pids`
- **THEN** stderr shows a notice that the agent CPU budget is not enforced because the `cpu` controller is not delegated to the rootless engine
- **AND** the session starts without waiting for input

#### Scenario: All controllers delegated
- **WHEN** the engine delegates `cpu`, `memory` and `pids`
- **THEN** no budget notice is printed

#### Scenario: Engine with the cgroupfs manager
- **WHEN** a session starts on a rootless engine with the `cgroupfs` cgroup manager that reports `cpu`, `memory` and `pids`
- **THEN** stderr shows notices that the agent memory and CPU budgets are not enforced because the rootless engine uses the `cgroupfs` cgroup manager, which applies no cgroup limits
- **AND** the process budget notice names the process rlimit fallback, or the reason it was not applied

#### Scenario: Process budget on the rlimit fallback
- **WHEN** a session starts on an engine delegating `cpu` and `memory` but not `pids`, on a host that counts the process rlimit per container
- **THEN** stderr shows a notice that the agent process budget is enforced through the process rlimit because the `pids` controller is not delegated
- **AND** the notice states that the limit counts the session user's tasks, threads included
- **AND** no notice reports the agent process budget as unenforced

#### Scenario: Process rlimit fallback not applied
- **WHEN** a session starts without the `pids` controller on a host where per-container counting is not established
- **THEN** stderr shows a notice that the agent process budget is not enforced, naming the missing `pids` controller and why the rlimit fallback was not applied

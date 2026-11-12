# Spec Delta

## MODIFIED Requirements

### Requirement: Qualification binds agent hardening settings
The qualification identity of a restricted installation SHALL include:
- the agent capability and no-new-privileges settings;
- the selected memory, CPU and process budgets;
- the set of agent and proxy budgets actually enforced, as determined by the controllers the engine reports;
- the session lifetime setting.

A launch whose effective settings differ from the qualified identity SHALL stop with requalification guidance.

#### Scenario: Budget changed after qualification
- **WHEN** an installation was qualified with default budgets and the operator launches with `PI_CONTAINER_PIDS_LIMIT=1024`
- **THEN** the qualification check reports mismatched evidence and Pi does not start

#### Scenario: Matching settings
- **WHEN** the operator qualifies and launches with the same budgets and lifetime
- **THEN** the qualification check accepts the report

#### Scenario: Controller delegation changed after qualification
- **WHEN** an installation was qualified while `cpu` was not delegated and the engine later reports `cpu`
- **THEN** the qualification check reports mismatched evidence and requires requalification

## ADDED Requirements

### Requirement: Unenforced budgets are announced
Each launch SHALL print one notice per unenforced agent or proxy budget, naming the budget, its container and the missing cgroup controller, without asking for confirmation. When every budget is enforced, no notice SHALL be printed.

#### Scenario: CPU controller missing
- **WHEN** a session starts on an engine reporting only `memory` and `pids`
- **THEN** stderr shows a notice that the agent CPU budget is not enforced because the `cpu` controller is not delegated to the rootless engine
- **AND** the session starts without waiting for input

#### Scenario: All controllers delegated
- **WHEN** the engine reports `cpu`, `memory` and `pids`
- **THEN** no budget notice is printed

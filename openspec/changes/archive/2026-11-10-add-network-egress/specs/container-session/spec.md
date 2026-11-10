## ADDED Requirements

### Requirement: Explicit network mode admission
Ordinary Pi and shell launches SHALL require a nonempty `PI_CONTAINER_NETWORK`. An unset or empty mode SHALL stop before engine queries, state creation or image operations, with a message naming the variable and its values. Wrapper help and `--container-qualify` SHALL keep their own checks. The check SHALL apply equally to Pi, shell, build, worktree and YOLO invocations.

#### Scenario: Existing invocation without a mode
- **WHEN** a user runs `pi-container.sh` with no `PI_CONTAINER_NETWORK`
- **THEN** it exits nonzero before any engine call, naming `offline`, `provider` and `unrestricted` and stating that `unrestricted` keeps the previous behavior

#### Scenario: Help without a mode
- **WHEN** `--container-help` runs with no mode
- **THEN** help succeeds without engine calls or state side effects

### Requirement: Restricted launches require current local qualification
Before ordinary offline or provider execution, the wrapper SHALL validate a protected successful qualification report matching the current host, engine and enforcement inputs. Missing or mismatched evidence SHALL stop startup with requalification guidance. A report SHALL NOT replace per-launch engine, protected-path, guard, policy or readiness checks. Unrestricted launches and help SHALL NOT require it.

#### Scenario: Changed environment or artifacts
- **WHEN** boot, engine version, backend or endpoint, effective security policy, guard or code, runtime or proxy image identity, hardening, gate revision or selected mode, profile or policy differs from the report
- **THEN** ordinary restricted startup fails before application execution and requests `--container-qualify`
- **AND** changing environment variables never suppresses that failure

#### Scenario: Matching evidence
- **WHEN** a trusted complete report matches the effective restricted workflow and all per-launch checks pass
- **THEN** Pi starts with its existing argument, stdin, terminal and exit-status semantics
- **AND** a locally qualified combination without release acceptance is visibly identified as not release-measured

#### Scenario: Explicit qualification operation
- **WHEN** the operator runs `--container-qualify` without a current report
- **THEN** only the protected gate fixtures run through normal confinement and resource preparation
- **AND** no supplied application command or writable fixture can execute through the report-check exception

### Requirement: Consistent restricted prerequisite decisions
Restricted startup and qualification SHALL use the same protected platform eligibility rules and diagnostic categories. Malformed or unavailable engine or platform evidence SHALL fail closed. The rules SHALL keep launch endpoint verification and SHALL NOT reject SELinux or AppArmor merely for being enabled.

#### Scenario: Qualification and startup receive the same evidence
- **WHEN** qualification and direct restricted startup inspect equivalent host and engine evidence
- **THEN** they agree on eligibility and identify the same failed prerequisite

### Requirement: Qualification binds agent hardening settings
The qualification identity of a restricted installation SHALL include the agent capability and no-new-privileges settings, the selected memory, CPU and process budgets, and the session lifetime setting. A launch whose effective settings differ from the qualified identity SHALL stop with requalification guidance.

#### Scenario: Budget changed after qualification
- **WHEN** an installation was qualified with default budgets and the operator launches with `PI_CONTAINER_PIDS_LIMIT=1024`
- **THEN** the qualification check reports mismatched evidence and Pi does not start

#### Scenario: Matching settings
- **WHEN** the operator qualifies and launches with the same budgets and lifetime
- **THEN** the qualification check accepts the report

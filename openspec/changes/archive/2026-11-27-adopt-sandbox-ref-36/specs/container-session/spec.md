# Spec Delta

## MODIFIED Requirements

### Requirement: Explicit network mode admission

Ordinary Pi and shell launches SHALL use the effective `PI_CONTAINER_NETWORK`, explicit or from the managed launcher. An unset or empty mode SHALL select `provider`. A provider launch without its protected installation or provider settings SHALL exit with status 1 and a `setup required:` message. The message SHALL name `--container-setup` and the explicit-mode alternative. The refusal SHALL come before engine queries, state creation or image operations. It SHALL NOT prompt, run setup or start an application. Help, setup, `--container-toolchain` and `--container-qualify` keep their own checks.

#### Scenario: Existing invocation without a mode

- **WHEN** a user runs `pi-container.sh` with no `PI_CONTAINER_NETWORK` and no provider settings, interactively or with redirected input
- **THEN** it exits with status 1 and the setup-required message before any engine call, without application output, state or runtime resources
- **AND** the message names `bash <wrapper> --container-setup` and states that an operator can set `PI_CONTAINER_NETWORK` explicitly

#### Scenario: Empty mode with provider settings

- **WHEN** `PI_CONTAINER_NETWORK` is empty and the provider settings select a protected installation
- **THEN** the launch runs in provider mode

#### Scenario: Help without a mode

- **WHEN** `--container-help` runs with no mode
- **THEN** help succeeds without engine calls or state side effects

#### Scenario: Options and other settings do not imply setup

- **WHEN** an unconfigured launch uses shell, build, worktree or YOLO, `PI_CONTAINER_MAINTENANCE=1`, or state, image, endpoint or policy settings
- **THEN** it receives the same setup-required refusal
- **AND** files in the current directory never admit the launch

### Requirement: Read-only engine queries are bounded

Every read-only engine query (`info`, `version`, `ps`, image and container existence and inspection) SHALL be bounded by a timeout. A response with a carriage return or extra records SHALL be refused. `create`, `start`, `build` and `pull` SHALL NOT be bounded.

#### Scenario: Stalled engine query

- **WHEN** a read-only engine query does not answer
- **THEN** the wrapper stops after the query timeout with the query's diagnostic and creates no container

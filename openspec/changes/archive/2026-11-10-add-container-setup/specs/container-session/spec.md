# Spec Delta

## MODIFIED Requirements

### Requirement: Explicit network mode admission
Ordinary Pi and shell launches SHALL require a nonempty effective `PI_CONTAINER_NETWORK`, explicit or from the managed launcher. An unset or empty mode SHALL exit with status 1 and a `setup required:` message naming `--container-setup` and the explicit-mode alternative, before runtime prerequisite checks, engine queries, state creation or image operations. It SHALL NOT prompt, run setup or start an application; help, setup and `--container-qualify` keep their own checks.

#### Scenario: Existing invocation without a mode
- **WHEN** a user runs `pi-container.sh` with no `PI_CONTAINER_NETWORK`, interactively or with redirected input
- **THEN** it exits with status 1 and the setup-required message before any engine call, without application output, state or runtime resources
- **AND** the message names `bash <wrapper> --container-setup` and states that an operator can set `PI_CONTAINER_NETWORK` explicitly

#### Scenario: Help without a mode
- **WHEN** `--container-help` runs with no mode
- **THEN** help succeeds without engine calls or state side effects

#### Scenario: Options and other settings do not imply setup
- **WHEN** an unconfigured launch uses shell, build, worktree or YOLO, `PI_CONTAINER_MAINTENANCE=1`, or state, image, endpoint, policy or delegation settings
- **THEN** it receives the same setup-required refusal before validating those settings
- **AND** files in the current directory never admit the launch

## ADDED Requirements

### Requirement: First-user setup and migration guidance
README, wrapper help and setup guidance SHALL name `--container-setup` as the first step for new users, explain the managed launcher and the explicit operator alternative, state that offline sessions cannot reach any model provider, and give the migration path for direct invocations from versions without network modes.

#### Scenario: User follows first-run guidance
- **WHEN** a new user reads the help or the README
- **THEN** they find how to run setup and then use its managed launcher
- **AND** they learn that offline cannot reach any model provider and that no unrestricted fallback is automatic

#### Scenario: Operator migrates an existing direct invocation
- **WHEN** an operator reads the migration guidance
- **THEN** it explains that earlier versions needed no network mode, that `PI_CONTAINER_NETWORK=unrestricted` keeps the previous networking, and that builds need `PI_CONTAINER_MAINTENANCE=1`
- **AND** it does not imply that selecting a mode proves restricted readiness

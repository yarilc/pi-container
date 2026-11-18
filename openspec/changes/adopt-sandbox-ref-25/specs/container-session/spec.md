## ADDED Requirements

### Requirement: Extra variables forwarded by name
`PI_CONTAINER_ENV_VARS` SHALL list host variable names, separated by whitespace, to forward into the session by name, never by value. An invalid name SHALL stop the launch before any engine or state operation. Unset or empty variables SHALL NOT be forwarded. Reserved names SHALL be skipped with one notice each.

#### Scenario: Listed variable reaches the session
- **WHEN** `PI_CONTAINER_ENV_VARS="GH_TOKEN"` is set and `GH_TOKEN` has a value
- **THEN** the session receives `GH_TOKEN` by name and the value is absent from engine arguments

#### Scenario: Names reserved by mode
- **WHEN** the list names a variable the launcher sets, a proxy, CA or Pi optional-traffic setting in a restricted mode, or `OPENAI_API_KEY` in a provider session using the `anthropic-api` profile
- **THEN** that name is skipped with a notice and the session starts

#### Scenario: Invalid name
- **WHEN** the list contains a name such as `1BAD`
- **THEN** the launch stops before any engine query

### Requirement: Session environment is fixed by the launcher
Every Pi and shell session SHALL receive `TERM`, `COLORTERM`, `LANG` and `LC_ALL` when the host sets them, and SHALL set `USER` to the caller's name and `EDITOR` and `VISUAL` to `nano`. Unrestricted sessions SHALL also forward the host proxy variables in both cases, `ALL_PROXY` included. Restricted sessions SHALL NOT forward proxy variables. No session SHALL receive a credential except as the credential rules allow.

#### Scenario: Unrestricted environment
- **WHEN** an unrestricted session starts with `TERM`, `LANG` and `ALL_PROXY` set on the host
- **THEN** the session receives `TERM`, `LANG` and `ALL_PROXY`, `USER` with the caller's name, and `EDITOR=nano`

#### Scenario: Restricted environment
- **WHEN** an offline or provider session starts with `HTTPS_PROXY` set on the host
- **THEN** the session receives `TERM` when set, `USER` and `EDITOR=nano`, but not the host `HTTPS_PROXY`

### Requirement: Session name and init process
Each create attempt SHALL set `CONTAINER_NAME` to the reserved container name and run with stdin from `/dev/null`. Unrestricted sessions SHALL run with `--init`. A failed create whose name holds this session's own container SHALL never count as a collision: that container SHALL be removed, or reported as unresolved.

#### Scenario: Session name inside the container
- **WHEN** an unrestricted session starts as `<prefix>-3`
- **THEN** it runs with `--init` and `CONTAINER_NAME=<prefix>-3`

#### Scenario: Own container behind a failed create
- **WHEN** create fails without publishing an ID and the engine reports this session's ownership label for the name
- **THEN** the wrapper returns the create status without retrying and removes that container

### Requirement: Read-only engine queries are bounded
Every read-only engine query (`info`, `version`, `ps`, image and container existence and inspection, the delegation socket query) SHALL be bounded by a timeout. A response with a carriage return or extra records SHALL be refused. `create`, `start`, `build` and `pull` SHALL NOT be bounded.

#### Scenario: Stalled engine query
- **WHEN** a read-only engine query does not answer
- **THEN** the wrapper stops after the query timeout with the query's diagnostic and creates no container

### Requirement: First-user setup guidance
README, wrapper help and setup guidance SHALL name `--container-setup` as the first step for new users. They SHALL explain the managed launcher and the explicit operator alternative. They SHALL state that provider is the default mode, and that offline sessions cannot reach any model provider.

#### Scenario: User follows first-run guidance
- **WHEN** a new user reads the help or the README
- **THEN** they find how to run setup and then use its managed launcher
- **AND** they learn that offline cannot reach any model provider and that no unrestricted fallback is automatic

#### Scenario: Operator chooses a mode explicitly
- **WHEN** an operator reads the guidance
- **THEN** it explains that `PI_CONTAINER_NETWORK` selects offline, provider or unrestricted, that builds need `PI_CONTAINER_MAINTENANCE=1`, and that selecting a mode does not prove restricted readiness

## REMOVED Requirements

### Requirement: First-user setup and migration guidance
**Reason**: The project has no release, so the migration path from versions without network modes no longer applies, and a missing mode now selects provider.
**Migration**: Use "First-user setup guidance".

## MODIFIED Requirements

### Requirement: First-signal bounded attached shutdown
In Pi and shell modes, a handled TERM, INT or HUP SHALL start shutdown at once and SHALL select status 143, 130 or 129 respectively. The wrapper SHALL forward the first signal once to the owned attached session, allow up to five seconds for graceful exit, and then attempt forced owned-container removal. Shutdown SHALL complete within one 20-second deadline; each shutdown engine call SHALL be bounded by the time left, and local clients SHALL be terminated and reaped within it. Later signals SHALL neither replace the status nor restart shutdown or extend its deadline.

#### Scenario: Stubborn application and repeated signals
- **WHEN** an attached application ignores TERM and the wrapper receives TERM followed by INT/HUP
- **THEN** it returns 143 within the 20-second deadline, forces owned removal, bounds client reaping, and leaves a concurrent unrelated session running

#### Scenario: Engine control failure
- **WHEN** forwarding or removal fails or stalls
- **THEN** the relevant control call ends within the time left, the wrapper preserves the first interruption status, and diagnostics identify the owned resource requiring inspection

### Requirement: Interrupted creation has finite reconciliation
A handled signal during creation SHALL start shutdown at once. The wrapper SHALL terminate the pending create client within the 20-second shutdown deadline, then recover the container through the validated private CID record, the create output and the session ownership label, and attempt removal only of a verified owned container. It SHALL neither start nor retry an interrupted session, wait indefinitely on a live client, or claim that local cancellation stopped the server request.

#### Scenario: Creation never completes
- **WHEN** creation stalls before or after CID publication and the wrapper receives TERM, INT, or HUP
- **THEN** it exits with the first signal status within the deadline, removes only a verified ID, reports unresolved ownership otherwise, and releases private bookkeeping

#### Scenario: CID published during cancellation
- **WHEN** the create client publishes a valid CID while handling TERM during cancellation
- **THEN** the final reconciliation discovers and removes that ID without starting the session or losing the original interruption status

### Requirement: Explicit network mode admission
Ordinary Pi and shell launches SHALL use the effective `PI_CONTAINER_NETWORK`, explicit or from the managed launcher. An unset or empty mode SHALL select `provider`. A provider launch without its protected installation or provider settings SHALL exit with status 1 and a `setup required:` message. The message SHALL name `--container-setup` and the explicit-mode alternative. The refusal SHALL come before engine queries, state creation or image operations. It SHALL NOT prompt, run setup or start an application. Help, setup and `--container-qualify` keep their own checks.

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
- **WHEN** an unconfigured launch uses shell, build, worktree or YOLO, `PI_CONTAINER_MAINTENANCE=1`, or state, image, endpoint, policy or delegation settings
- **THEN** it receives the same setup-required refusal
- **AND** files in the current directory never admit the launch

### Requirement: Restricted launches require current local qualification
Before ordinary offline or provider execution, the wrapper SHALL validate a protected successful qualification report matching the current host, engine and enforcement inputs. The check SHALL use the mode the launcher resolved, including the provider default. Missing or mismatched evidence SHALL stop startup with requalification guidance. A report SHALL NOT replace per-launch engine, protected-path, guard, policy or readiness checks. Unrestricted launches and help SHALL NOT require it.

#### Scenario: Changed environment or artifacts
- **WHEN** boot, engine version, backend or endpoint, effective security policy, guard or code, launcher core or agent part, runtime or proxy image identity, hardening, gate revision or selected mode, profile or policy differs from the report
- **THEN** ordinary restricted startup fails before application execution and requests `--container-qualify`
- **AND** changing environment variables never suppresses that failure

#### Scenario: Default mode is qualified as provider
- **WHEN** `PI_CONTAINER_NETWORK` is unset and the provider settings are present
- **THEN** the launcher and every Python helper check the provider report

#### Scenario: Matching evidence
- **WHEN** a trusted complete report matches the effective restricted workflow and all per-launch checks pass
- **THEN** Pi starts with its existing argument, stdin, terminal and exit-status semantics
- **AND** a locally qualified combination without release acceptance is visibly identified as not release-measured

#### Scenario: Explicit qualification operation
- **WHEN** the operator runs `--container-qualify` without a current report
- **THEN** only the protected gate fixtures run through normal confinement and resource preparation
- **AND** no supplied application command or writable fixture can execute through the report-check exception

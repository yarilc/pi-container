# container-session Specification

## Purpose

Provide concurrent-safe session reservation and finite, ownership-safe termination without losing application input or exit status.

## Requirements

### Requirement: Atomic bounded name reservation

The wrapper SHALL sanitize a physical workspace-derived prefix into a valid nonempty container name, list running and stopped containers, and start above the highest matching bounded decimal suffix. It SHALL reserve through create, retry confirmed collisions at most 20 create attempts, propagate listing/lookup errors, and never replace an existing container. Session CONTAINER_NAME SHALL match the reserved name.

#### Scenario: Existing names and leading zeroes

- **WHEN** matching names include suffixes `0`, `3`, and `08`, plus malformed or overlong suffixes
- **THEN** the initial candidate is suffix 9, unrelated/malformed suffixes are ignored, and stopped containers participate.

#### Scenario: Concurrent reservation or engine failure

- **WHEN** another caller reserves the candidate, or listing/collision lookup fails
- **THEN** only confirmed collisions advance to another candidate, attempts stop after 20, and operational errors fail without replacing or deleting another session.

### Requirement: Private owned container identity

The wrapper SHALL track its container through a private creation record containing one full 64-character lowercase hexadecimal ID with at most one terminating LF. Malformed or additional records SHALL not authorize cleanup. Destructive lifecycle operations SHALL target only this invocation's verified owned full ID, never a reusable name or prefix.

#### Scenario: Failed create with an owned ID

- **WHEN** creation returns nonzero but its private record contains a valid full ID
- **THEN** the wrapper attempts bounded removal of that ID, does not retry the name, and preserves the primary failure status.

#### Scenario: Invalid ownership evidence

- **WHEN** the private record is missing or contains a short ID, NUL, CR, additional LF/records, or other malformed data
- **THEN** the wrapper does not start or remove an unverified container and reports any unresolved creation outcome for manual inspection.

### Requirement: Input and exit-code transparency

The wrapper SHALL retain redirected stdin and EOF when attaching, allocate TTY only if both stdin and stdout are terminals, and return the application/attach exit status, including 125, unless interrupted. Cleanup failures SHALL not replace the primary status.

#### Scenario: Nonterminal streams

- **WHEN** input is piped or redirected, or stdout is redirected while stdin is a terminal
- **THEN** attachment receives the original input/EOF and does not allocate a TTY.

#### Scenario: Application error and cleanup error

- **WHEN** the application exits 125 and removal subsequently fails
- **THEN** the wrapper returns 125 and reports the failed owned cleanup separately.

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

### Requirement: Optional session lifetime limit

`PI_CONTAINER_RUN_TIMEOUT` SHALL set the native engine lifetime of the session container in whole seconds. When it is unset, empty or `0`, no lifetime limit SHALL apply. Any other value that is not a positive decimal integer of at most ten digits SHALL fail with status 1 before engine queries. The limit SHALL be independent of the wrapper's interruption and cleanup deadlines.

#### Scenario: Lifetime disabled by default

- **WHEN** `PI_CONTAINER_RUN_TIMEOUT` is unset
- **THEN** the session container is created without a lifetime limit

#### Scenario: Lifetime expires

- **WHEN** `PI_CONTAINER_RUN_TIMEOUT=60` is set and the application is still running after 60 seconds
- **THEN** the engine stops the session container
- **AND** the wrapper prints a stderr notice that the session lifetime limit was reached
- **AND** the wrapper exits with the engine client's status and removes only its owned container

#### Scenario: Session ends before the limit

- **WHEN** the application exits before the limit
- **THEN** the wrapper propagates the application exit status unchanged and prints no lifetime notice

#### Scenario: Invalid lifetime value

- **WHEN** `PI_CONTAINER_RUN_TIMEOUT` is negative, fractional or non-numeric
- **THEN** the wrapper exits with status 1 and names the variable before any engine query or state creation

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

### Requirement: Consistent restricted prerequisite decisions
Restricted startup and qualification SHALL use the same protected platform eligibility rules and diagnostic categories. Malformed or unavailable engine or platform evidence SHALL fail closed. The rules SHALL keep launch endpoint verification and SHALL NOT reject SELinux or AppArmor merely for being enabled.

#### Scenario: Qualification and startup receive the same evidence
- **WHEN** qualification and direct restricted startup inspect equivalent host and engine evidence
- **THEN** they agree on eligibility and identify the same failed prerequisite

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

### Requirement: Unenforced budgets are announced
Each launch SHALL print one notice per unenforced agent or proxy budget, naming the budget, its container and the missing cgroup controller, without asking for confirmation. When every budget is enforced, no notice SHALL be printed.

#### Scenario: CPU controller missing
- **WHEN** a session starts on an engine reporting only `memory` and `pids`
- **THEN** stderr shows a notice that the agent CPU budget is not enforced because the `cpu` controller is not delegated to the rootless engine
- **AND** the session starts without waiting for input

#### Scenario: All controllers delegated
- **WHEN** the engine reports `cpu`, `memory` and `pids`
- **THEN** no budget notice is printed

### Requirement: Name collisions are confirmed by ownership
When container creation fails without returning an ID and a container with the candidate name exists, the wrapper SHALL treat it as another session's container only when its session ownership label differs from this session's token. A container carrying this session's label SHALL be reconciled and removed as this session's own, never skipped.

#### Scenario: Another session holds the name
- **WHEN** creation fails, no ID was returned, and the existing container with that name carries another session's label
- **THEN** the wrapper retries the next numeric name without touching that container

#### Scenario: The engine created this session's container
- **WHEN** creation fails without returning an ID, and the container with that name carries this session's label
- **THEN** the wrapper reports the original creation failure, does not retry, and removes that container during bounded cleanup

### Requirement: Interrupted creation is recovered by ownership label
When creation is interrupted or fails and no valid ID was published, cleanup SHALL look up containers carrying this session's ownership label, within the shutdown budget, and remove the one it confirms as owned. It SHALL report unresolved creation only when that lookup fails or finds no confirmed owned container.

#### Scenario: Engine created the container before the client was cancelled
- **WHEN** a handled signal interrupts creation, the client publishes no ID, and the engine has created this session's container
- **THEN** cleanup finds it by the session label, confirms the label, removes it, and the wrapper returns the interruption status

#### Scenario: Nothing was created
- **WHEN** creation is interrupted and no container carries this session's label
- **THEN** the wrapper removes nothing and returns the interruption status

#### Scenario: Lookup unavailable
- **WHEN** the label lookup fails or times out
- **THEN** the wrapper reports that creation is unresolved and that engine inspection is required, without removing any container

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

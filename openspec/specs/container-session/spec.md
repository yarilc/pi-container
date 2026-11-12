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

TERM, INT, and HUP SHALL select statuses 143, 130, and 129 respectively and forward the first signal once to the owned attached session. Later signals SHALL neither replace the status nor renew shutdown deadlines. Signal/removal control calls SHALL each have a 5s timeout plus 1s forced termination, application grace SHALL be at most 5s, and local-client termination SHALL allow at most 5s after TERM plus 1s after KILL.

#### Scenario: Stubborn application and repeated signals

- **WHEN** an attached application ignores TERM and the wrapper receives TERM followed by INT/HUP
- **THEN** it returns 143 within the fixed phases, forces owned removal, bounds client reaping, and leaves a concurrent unrelated session running.

#### Scenario: Engine control failure

- **WHEN** forwarding or removal fails or stalls
- **THEN** the relevant control call terminates within its bound, the wrapper preserves the first interruption status, and diagnostics identify the owned resource requiring inspection.

### Requirement: Interrupted creation has finite reconciliation

Interrupted creation SHALL allow at most 5s for completion, then bounded client cancellation of 5s after TERM and 1s after KILL. The wrapper SHALL read the private CID after cancellation and attempt removal within 5s plus 1s when ownership is verified. It SHALL neither start nor retry an interrupted session, wait indefinitely on a live client, or claim that local cancellation stopped the server request.

#### Scenario: Creation never completes

- **WHEN** creation stalls before or after CID publication and the wrapper receives TERM, INT, or HUP
- **THEN** it exits with the first signal status within the finite phases, removes only a verified ID, reports unresolved ownership otherwise, and releases private bookkeeping.

#### Scenario: CID published during cancellation

- **WHEN** the create client publishes a valid CID while handling TERM during cancellation
- **THEN** the final reconciliation discovers and removes that ID without starting the session or losing the original interruption status.

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

### Requirement: Unenforced budgets are announced
Each launch SHALL print one notice per unenforced agent or proxy budget, naming the budget, its container and the missing cgroup controller, without asking for confirmation. When every budget is enforced, no notice SHALL be printed.

#### Scenario: CPU controller missing
- **WHEN** a session starts on an engine reporting only `memory` and `pids`
- **THEN** stderr shows a notice that the agent CPU budget is not enforced because the `cpu` controller is not delegated to the rootless engine
- **AND** the session starts without waiting for input

#### Scenario: All controllers delegated
- **WHEN** the engine reports `cpu`, `memory` and `pids`
- **THEN** no budget notice is printed

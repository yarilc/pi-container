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

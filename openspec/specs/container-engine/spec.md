# container-engine Specification

## Purpose

Constrain launch and delegated Podman authority to verified Linux rootless services with explicit same-host connection boundaries.

## Requirements

### Requirement: Verified launch engine before image operations

The wrapper SHALL require a successful complete response reporting rootless `true`, OS `linux`, and ServiceIsRemote `true` or `false` before any image operation. It SHALL reject named connections, TCP/SSH endpoints, implicit remote contexts, and Unix endpoints without an absolute pathname beyond slash characters. No rootful override SHALL be honored.

#### Scenario: Local or explicit same-host Unix service

- **WHEN** a local engine reports `true linux false`, or an explicit same-host absolute Unix endpoint reports `true linux true`
- **THEN** launch verification succeeds independently of session delegation.

#### Scenario: Unsupported or unverifiable launch

- **WHEN** the engine is rootful, non-Linux, unreachable, incomplete, or selected through a forbidden connection, including `unix:///` or `unix:////`
- **THEN** startup fails before image inspection, building, or session creation even with `PI_ALLOW_ROOTFUL=1` or `0`.

### Requirement: Complete engine response validation

The wrapper SHALL retain query exit failures and complete record boundaries, allowing only the selected format and at most one terminating LF. Launch responses SHALL contain exactly three fields on one record. Delegation responses SHALL contain exactly rootless status and the complete reported socket pathname. CR characters, extra fields, extra records, and unexpected boolean values SHALL cause failure.

#### Scenario: Additional or malformed data

- **WHEN** either query emits extra blank/nonblank records, a CR, missing data, or an unexpected boolean, or exits nonzero after printing valid-looking data
- **THEN** verification fails before image operations rather than accepting partial data.

#### Scenario: Reported pathname containing spaces

- **WHEN** a successful delegated query reports an absolute socket pathname containing spaces in its path record
- **THEN** the complete pathname is preserved without field splitting or trimming.

### Requirement: Exact delegation opt-in

Host service delegation and conditional Podman client installation SHALL be enabled only by exact `PI_ENABLE_PODMAN=1`. Disabled delegation SHALL omit the socket bind and explicitly remove session `CONTAINER_HOST`, including requests through `PI_ENV_VARS`. Native Pi permissions and Bun selection SHALL remain independent.

#### Scenario: Non-enabling values

- **WHEN** `PI_ENABLE_PODMAN` is unset, empty, `0`, `false`, `true`, `yes`, or any value other than `1`
- **THEN** no delegated-service query or socket mount occurs, `INSTALL_PODMAN=0`, and session `CONTAINER_HOST` is absent even if forwarded by name.

#### Scenario: Enabled authority cannot be verified

- **WHEN** `PI_ENABLE_PODMAN=1` and selected socket verification fails
- **THEN** startup fails before image operations without silently degrading to an undelegated session or starting a host service.

### Requirement: Verified socket selection and host remapping

Enabled delegation SHALL select `PI_PODMAN_SOCKET`, then an explicit Unix `CONTAINER_HOST`, then `${XDG_RUNTIME_DIR:-/run/user/<uid>}/podman/podman.sock`. It SHALL require an absolute canonical accessible socket with read/write permission, query that exact endpoint, require rootless `true` and an absolute reported host pathname beyond slash characters, and bind that reported source to the session connection destination.

#### Scenario: Containerized caller with a remapped service

- **WHEN** the accessible override resolves to a socket at a different pathname than the service reports
- **THEN** verification targets the accessible canonical endpoint and the bind source uses the reported host path with session `CONTAINER_HOST=unix:///run/podman/podman.sock`.

#### Scenario: Invalid selected socket

- **WHEN** the selected path is relative, missing, not a socket, inaccessible, or served by a rootful or unverifiable service
- **THEN** startup fails with actionable diagnostics before image operations and does not fall back to another endpoint.

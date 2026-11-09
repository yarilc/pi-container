# Spec Delta

## MODIFIED Requirements

### Requirement: Exact delegation opt-in

Host service delegation and conditional Podman client installation SHALL be enabled only by exact `PI_CONTAINER_PODMAN=1`, or by the deprecated `PI_ENABLE_PODMAN=1` when the new name is unset. Disabled delegation SHALL omit the socket bind and explicitly remove session `CONTAINER_HOST`, including requests through `PI_ENV_VARS`. Native Pi permissions and Bun selection SHALL remain independent.

#### Scenario: Non-enabling values

- **WHEN** `PI_CONTAINER_PODMAN` is unset, empty, `0`, `false`, `true`, `yes`, or any value other than `1`, and no enabling alias applies
- **THEN** no delegated-service query or socket mount occurs, `INSTALL_PODMAN=0`, and session `CONTAINER_HOST` is absent even if forwarded by name.

#### Scenario: Enabled authority cannot be verified

- **WHEN** delegation is enabled and selected socket verification fails
- **THEN** startup fails before image operations without silently degrading to an undelegated session or starting a host service.

### Requirement: Verified socket selection and host remapping

Enabled delegation SHALL select `PI_CONTAINER_PODMAN_SOCKET` (or the deprecated `PI_PODMAN_SOCKET`), then an explicit Unix `CONTAINER_HOST`, then `${XDG_RUNTIME_DIR:-/run/user/<uid>}/podman/podman.sock`. It SHALL require an absolute canonical accessible socket with read/write permission, query that exact endpoint, require rootless `true` and an absolute reported host pathname beyond slash characters, and bind that reported source to the session connection destination.

#### Scenario: Containerized caller with a remapped service

- **WHEN** the accessible override resolves to a socket at a different pathname than the service reports
- **THEN** verification targets the accessible canonical endpoint and the bind source uses the reported host path with session `CONTAINER_HOST=unix:///run/podman/podman.sock`.

#### Scenario: Invalid selected socket

- **WHEN** the selected path is relative, missing, not a socket, inaccessible, or served by a rootful or unverifiable service
- **THEN** startup fails with actionable diagnostics before image operations and does not fall back to another endpoint.

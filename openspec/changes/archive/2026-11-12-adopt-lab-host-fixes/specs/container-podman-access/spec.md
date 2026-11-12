# Spec Delta

## MODIFIED Requirements

### Requirement: Verified socket selection and host remapping

Enabled delegation SHALL select `PI_CONTAINER_PODMAN_SOCKET` (or the deprecated `PI_PODMAN_SOCKET`), then an explicit Unix `CONTAINER_HOST`, then `${XDG_RUNTIME_DIR:-/run/user/<uid>}/podman/podman.sock`. It SHALL require an absolute canonical accessible socket with read/write permission, query that exact endpoint, require rootless `true` and an absolute reported host pathname beyond slash characters, and bind that reported source to the session connection destination. A host socket reported as a `unix://` URL SHALL be reduced to its pathname before validation.

#### Scenario: Containerized caller with a remapped service

- **WHEN** the accessible override resolves to a socket at a different pathname than the service reports
- **THEN** verification targets the accessible canonical endpoint and the bind source uses the reported host path with session `CONTAINER_HOST=unix:///run/podman/podman.sock`.

#### Scenario: Invalid selected socket

- **WHEN** the selected path is relative, missing, not a socket, inaccessible, or served by a rootful or unverifiable service
- **THEN** startup fails with actionable diagnostics before image operations and does not fall back to another endpoint.

#### Scenario: Podman 5 reports a socket URL

- **WHEN** the selected service reports its host socket as `unix:///run/user/1000/podman/podman.sock`
- **THEN** the wrapper binds `/run/user/1000/podman/podman.sock` to `/run/podman/podman.sock`

#### Scenario: Invalid socket URL

- **WHEN** the reported value is `unix://` followed by an empty, relative or slash-only pathname
- **THEN** the wrapper fails before image operations or startup

## MODIFIED Requirements

### Requirement: Exact delegation opt-in
Host service delegation SHALL be enabled only by exact `PI_CONTAINER_PODMAN=1`. Disabled delegation SHALL omit the socket bind and explicitly remove session `CONTAINER_HOST` and `CONTAINER_CONNECTION`, including requests through `PI_CONTAINER_ENV_VARS`. The Podman client SHALL be part of every image. Native Pi permissions SHALL remain independent.

#### Scenario: Non-enabling values
- **WHEN** `PI_CONTAINER_PODMAN` is unset, empty, `0`, `false`, `true`, `yes`, or any value other than `1`, also with the earlier `PI_ENABLE_PODMAN=1` set
- **THEN** no delegated-service query or socket mount occurs, and session `CONTAINER_HOST` is absent even if forwarded by name

#### Scenario: Enabled authority cannot be verified
- **WHEN** delegation is enabled and selected socket verification fails
- **THEN** startup fails before image operations without silently degrading to an undelegated session or starting a host service

### Requirement: Verified socket selection and host remapping
Enabled delegation SHALL select `PI_CONTAINER_PODMAN_SOCKET`, then an explicit Unix `CONTAINER_HOST`, then `${XDG_RUNTIME_DIR:-/run/user/<uid>}/podman/podman.sock`. It SHALL require an absolute canonical accessible socket with read/write permission, query that exact endpoint, require rootless `true` and an absolute reported host pathname, and bind that reported source to the session connection destination. A host socket reported as a `unix://` URL SHALL be reduced to its pathname before validation. The reported pathname SHALL NOT consist only of slash characters. When it exists in the wrapper's own filesystem namespace, it SHALL be a Unix socket; a pathname the wrapper cannot see is accepted as the remapped socket of a containerized wrapper, whose answer stays trusted. Delegated sessions SHALL get private tmpfs mounts at `/var/lib/containers` and `/run/containers`. Guided setup SHALL apply the same checks.

#### Scenario: Containerized caller with a remapped service
- **WHEN** the accessible override resolves to a socket at a different pathname than the service reports
- **THEN** verification targets the accessible canonical endpoint and the bind source uses the reported host path with session `CONTAINER_HOST=unix:///run/podman/podman.sock`

#### Scenario: Invalid selected socket
- **WHEN** the selected path is relative, missing, not a socket, inaccessible, or served by a rootful or unverifiable service
- **THEN** startup fails with actionable diagnostics before image operations and does not fall back to another endpoint

#### Scenario: Podman 5 reports a socket URL
- **WHEN** the selected service reports its host socket as `unix:///run/user/1000/podman/podman.sock`
- **THEN** the wrapper binds `/run/user/1000/podman/podman.sock` to `/run/podman/podman.sock`

#### Scenario: Invalid socket URL
- **WHEN** the reported value is `unix://` followed by an empty, relative or slash-only pathname, or a bare slash-only pathname such as `/`
- **THEN** the wrapper fails before image operations or startup, and the host root is never mounted

#### Scenario: Host socket path is not a socket
- **WHEN** the service reports a host socket path that exists in the wrapper's namespace as a directory, a regular file, a dangling link or another non-socket
- **THEN** the wrapper fails before image operations naming the reported path, and nothing is mounted from it

#### Scenario: Nested Podman storage
- **WHEN** a delegated session starts
- **THEN** `/var/lib/containers` and `/run/containers` are private tmpfs mounts, absent from sessions without delegation

## REMOVED Requirements

### Requirement: Deprecated gitconfig variable
**Reason**: `PI_MOUNT_GITCONFIG` is a legacy alias; the shared core removes aliases without compatibility hooks (launcher contract U2).
**Migration**: Use `PI_CONTAINER_GITCONFIG=1`.

### Requirement: Gitconfig migration notice
**Reason**: The notice describes a default that changed before any release, like the aliases U2 removes.
**Migration**: None; `~/.gitconfig` stays unmounted unless `PI_CONTAINER_GITCONFIG=1`.

## MODIFIED Requirements

### Requirement: Read-only persistent state remains available
With `PI_CONTAINER_READONLY_STATE` enabled (a boolean: `1`, `true` or `yes`, any case), the configuration directory and `.agents`, from shared state or from the isolated home, SHALL be mounted read-only below the ephemeral home after physical-path, directory, read, and traverse checks. This mode SHALL neither create missing state nor require write permission or silently copy credentials. The isolated home itself SHALL NOT be mounted, and the read-only directories SHALL NOT be writable inputs of restricted preparation.

#### Scenario: Readable state without write access
- **WHEN** read-only state is enabled and both state sources are readable and traversable
- **THEN** startup accepts them without writable-state ownership/privacy requirements and session writes to either mount fail

#### Scenario: Missing read-only state
- **WHEN** read-only state is enabled but either source is absent or unreadable
- **THEN** startup fails before image operations and does not create or modify the source

#### Scenario: Invalid switch value
- **WHEN** `PI_CONTAINER_READONLY_STATE` is set to a value such as `2`
- **THEN** the wrapper exits with status 1 naming the variable before engine queries

### Requirement: Explicit bounded ephemeral storage
Read-only sessions SHALL explicitly provide `/tmp`, `/var/tmp`, `/run`, the container home and a separate npm cache with finite capacities, `noexec`, nosuid/nodev, and mapped-user access. Automatic read-only tmpfs provisioning SHALL add no writable path beyond these explicit temporary and device mounts. Podman storage SHALL follow the same policy. Temporary contents SHALL disappear after the session.

#### Scenario: Declared temporary mount policy
- **WHEN** a default session starts
- **THEN** `/tmp` and `/var/tmp` each provide 512 MiB with rw,noexec,nosuid,nodev,mode=1777, and `/run` provides 32 MiB noexec,nosuid,nodev and is not writable by the session user
- **AND** `/pi-home` provides a 512 MiB noexec,nosuid,nodev home, and `/pi-home/.npm` provides rw,noexec,nosuid,nodev with caller access and a default 256 MiB capacity configurable by `PI_NPM_CACHE_SIZE`

#### Scenario: Writable scope and lifetime
- **WHEN** the mapped user writes in every writable temporary location, attempts a root-filesystem write, and starts a second session
- **THEN** temporary writes succeed within capacity, the root write fails, and previous temporary data is absent while writable persistent state remains

### Requirement: Host Git configuration requires exact opt-in
The wrapper SHALL mount the caller's `~/.gitconfig` read-only at `/pi-home/.gitconfig` only when `PI_CONTAINER_GITCONFIG` is exactly `1`, using the physical file as source. Any other value SHALL leave it unmounted without a notice. An opt-in without a regular `~/.gitconfig` file, or with a physical path containing a colon, CR or LF, SHALL stop with status 1 naming the variable and the path, before any engine query or state creation. No other host Git configuration file SHALL be mounted.

#### Scenario: Default launch with an existing gitconfig
- **WHEN** `~/.gitconfig` exists and `PI_CONTAINER_GITCONFIG` is not set
- **THEN** the generated engine arguments contain no mount of `~/.gitconfig` and stderr names no gitconfig

#### Scenario: Exact opt-in
- **WHEN** `PI_CONTAINER_GITCONFIG=1` is set and `~/.gitconfig` is a regular file or a symlink to one
- **THEN** its physical file is mounted read-only at `/pi-home/.gitconfig`, `git config --global` reads it, and a write attempt inside the session fails

#### Scenario: Non-exact opt-in
- **WHEN** `PI_CONTAINER_GITCONFIG` is `true`, `yes`, empty or any value other than `1`
- **THEN** `~/.gitconfig` is not mounted

#### Scenario: Opt-in without a file
- **WHEN** `PI_CONTAINER_GITCONFIG=1` is set and `~/.gitconfig` is missing or not a regular file
- **THEN** the wrapper exits with status 1 naming the variable and path, with no engine query or state creation

### Requirement: Dedicated container home
Sessions SHALL use `HOME=/pi-home`. In shared-state mode and with read-only state it SHALL be an ephemeral 512 MiB `noexec` tmpfs; with writable isolated state it SHALL be the isolated home. The persistent state, npm cache and opted-in gitconfig SHALL be mounted at fixed paths beneath it. The workspace SHALL keep its host absolute path. In shared-state mode, files written elsewhere below `/pi-home` SHALL NOT survive the session.

#### Scenario: Default layout
- **WHEN** a default session starts
- **THEN** `HOME` is `/pi-home`, and `~/.pi`, `~/.agents` and the npm cache tmpfs are at `/pi-home/.pi`, `/pi-home/.agents` and `/pi-home/.npm`
- **AND** Pi, npm extension installation and Git work as before, and host state is unchanged apart from Pi's own writes

### Requirement: Isolated persistent state option
`PI_CONTAINER_STATE_DIR` SHALL select a private host directory whose `.pi` and `.agents` replace `~/.pi` and `~/.agents`: mounted as the persistent `/pi-home` in writable mode, or read-only below an ephemeral home with `PI_CONTAINER_READONLY_STATE`. It SHALL be checked lexically (absolute, no colon, CR or LF) before engine queries, then created privately and validated before image operations. Every child the launcher uses below it, and the CA mount parent, SHALL be resolved before creation, SHALL stay inside it and SHALL be private. It SHALL NOT overlap the workspace or be combined with a nonempty `PI_CONTAINER_CONFIG_DIR`. An empty value selects shared state.

#### Scenario: Isolated writable state
- **WHEN** `PI_CONTAINER_STATE_DIR` names a missing absolute directory
- **THEN** it is created with its `.pi` and `.agents` private, mounted at `/pi-home`, and `~/.pi` and `~/.agents` are not mounted

#### Scenario: Invalid isolated state
- **WHEN** the value is relative, the directory is foreign-owned or grants group or other permissions, or it overlaps the workspace
- **THEN** the wrapper exits with status 1 naming the variable before any image operation and changes nothing
- **AND** a relative or overlapping value fails before any engine query

#### Scenario: Escaping or shared child
- **WHEN** `.pi` or `.agents` in the isolated home is a symlink leaving it, or grants group or other permissions
- **THEN** the wrapper exits with status 1 naming the path before any image operation

#### Scenario: Engine query fails
- **WHEN** a missing isolated state directory is selected and the engine query fails
- **THEN** the wrapper exits without creating the directory

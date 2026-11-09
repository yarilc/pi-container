# Spec Delta

## ADDED Requirements

### Requirement: Dedicated container home

Sessions SHALL use `HOME=/pi-home`, an ephemeral noexec tmpfs, with the persistent state, npm cache and opted-in gitconfig mounted at fixed paths beneath it. The workspace SHALL keep its host absolute path. Files written elsewhere below `/pi-home` SHALL NOT survive the session.

#### Scenario: Default layout

- **WHEN** a default session starts
- **THEN** `HOME` is `/pi-home`, and `~/.pi`, `~/.agents` and the npm cache tmpfs are at `/pi-home/.pi`, `/pi-home/.agents` and `/pi-home/.npm`
- **AND** Pi, npm extension installation and Git work as before, and host state is unchanged apart from Pi's own writes

### Requirement: Isolated persistent state option

`PI_CONTAINER_STATE_DIR` SHALL select a private host directory whose `.pi` and `.agents` replace `~/.pi` and `~/.agents`. In writable mode the directory SHALL be mounted as the persistent `/pi-home`. With `PI_READONLY_CONFIG`, its `.pi` and `.agents` SHALL be mounted read-only below an ephemeral home. The directory SHALL be created privately when missing and validated like the shared state before any engine query. It SHALL NOT overlap the workspace mount.

#### Scenario: Isolated writable state

- **WHEN** `PI_CONTAINER_STATE_DIR` names a missing absolute directory
- **THEN** it is created with its `.pi` and `.agents` private, mounted at `/pi-home`, and `~/.pi` and `~/.agents` are not mounted

#### Scenario: Invalid isolated state

- **WHEN** the value is relative or empty, the directory is foreign-owned or grants group or other permissions, or it overlaps the workspace
- **THEN** the wrapper exits with status 1 naming the variable before any engine query and changes nothing

## MODIFIED Requirements

### Requirement: Private writable persistent state

Before image operations the wrapper SHALL validate the physical `.pi` and `.agents` sources, from the host home or the isolated state directory, as directories owned by the caller, readable/writable/traversable, with no group/other permissions. Missing writable state SHALL be created with a scoped umask 077. Invalid existing state SHALL cause failure without chmod, chown, replacement, or credential import.

#### Scenario: Missing or acceptable writable state

- **WHEN** state directories are missing or already satisfy ownership, privacy, and access checks
- **THEN** missing directories are created privately and the validated physical paths are mounted at `/pi-home/.pi` and `/pi-home/.agents`.

#### Scenario: Existing insecure or unusable state

- **WHEN** either source is a file, dangling symlink, wrong-owner directory, inaccessible directory, or grants group/other permissions
- **THEN** startup fails before image operations with repair guidance and leaves existing content and permissions untouched.

### Requirement: Explicit bounded ephemeral storage

Read-only sessions SHALL disable automatic read-only tmpfs provisioning and explicitly provide `/tmp`, `/var/tmp`, `/run`, the container home and a separate npm cache with finite capacities, nosuid/nodev, deliberate execution modes, and mapped-user access. Podman storage SHALL follow the same policy. Temporary contents SHALL disappear after the session.

#### Scenario: Declared temporary mount policy

- **WHEN** a default session starts
- **THEN** `/tmp` and `/var/tmp` each provide 256 MiB and `/run` 32 MiB with rw,noexec,nosuid,nodev,mode=1777, `/pi-home` provides a noexec,nosuid,nodev home, and `/pi-home/.npm` provides rw,noexec,nosuid,nodev with caller access and a default 256 MiB capacity configurable by `PI_NPM_CACHE_SIZE`.

#### Scenario: Writable scope and lifetime

- **WHEN** the mapped user writes in every temporary location, attempts a root-filesystem write, and starts a second session
- **THEN** temporary writes succeed within capacity, the root write fails, and previous temporary data is absent while writable persistent state remains.

### Requirement: Host Git configuration requires exact opt-in

The wrapper SHALL mount the caller's `~/.gitconfig` read-only at `/pi-home/.gitconfig` only when `PI_CONTAINER_GITCONFIG` is exactly `1`, using the physical file as source. Any other value SHALL leave it unmounted. An opt-in without a regular `~/.gitconfig` file SHALL stop with status 1 naming the variable and the path, before any engine query or state creation. No other host Git configuration file SHALL be mounted.

#### Scenario: Default launch with an existing gitconfig

- **WHEN** `~/.gitconfig` exists and neither `PI_CONTAINER_GITCONFIG` nor `PI_MOUNT_GITCONFIG` is set
- **THEN** the generated engine arguments contain no mount of `~/.gitconfig`

#### Scenario: Exact opt-in

- **WHEN** `PI_CONTAINER_GITCONFIG=1` is set and `~/.gitconfig` is a regular file or a symlink to one
- **THEN** its physical file is mounted read-only at `/pi-home/.gitconfig`, `git config --global` reads it, and a write attempt inside the session fails

#### Scenario: Non-exact opt-in

- **WHEN** `PI_CONTAINER_GITCONFIG` is `true`, `yes`, empty or any value other than `1`
- **THEN** `~/.gitconfig` is not mounted

#### Scenario: Opt-in without a file

- **WHEN** `PI_CONTAINER_GITCONFIG=1` is set and `~/.gitconfig` is missing or not a regular file
- **THEN** the wrapper exits with status 1 naming the variable and path, with no engine query or state creation

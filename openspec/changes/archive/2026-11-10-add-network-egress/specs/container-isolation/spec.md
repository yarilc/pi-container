## MODIFIED Requirements

### Requirement: Private writable persistent state

Before image operations the wrapper SHALL validate the physical `.pi` and `.agents` sources, from the host home (or `PI_CONTAINER_CONFIG_DIR` for `.pi`) or the isolated state directory, as directories owned by the caller, readable/writable/traversable, with no group/other permissions. Missing writable state SHALL be created with a scoped umask 077. Invalid existing state SHALL cause failure without chmod, chown, replacement, or credential import.

#### Scenario: Missing or acceptable writable state

- **WHEN** state directories are missing or already satisfy ownership, privacy, and access checks
- **THEN** missing directories are created privately and the validated physical paths are mounted at `/pi-home/.pi` and `/pi-home/.agents`.

#### Scenario: Existing insecure or unusable state

- **WHEN** either source is a file, dangling symlink, wrong-owner directory, inaccessible directory, or grants group/other permissions
- **THEN** startup fails before image operations with repair guidance and leaves existing content and permissions untouched.

#### Scenario: Configuration directory override
- **WHEN** `PI_CONTAINER_CONFIG_DIR` names a private absolute directory
- **THEN** it replaces `~/.pi` and is mounted at `/pi-home/.pi`; a relative value fails before engine queries
- **AND** every session has `PI_CONTAINER_CONFIG_DIR=/pi-home/.pi`, and the host value is never forwarded

### Requirement: Isolated persistent state option

`PI_CONTAINER_STATE_DIR` SHALL select a private host directory whose `.pi` and `.agents` replace `~/.pi` and `~/.agents`: mounted as the persistent `/pi-home` in writable mode, or read-only below an ephemeral home with `PI_READONLY_CONFIG`. It SHALL be checked lexically before engine queries, then created privately and validated before image operations. It SHALL NOT overlap the workspace or be combined with a nonempty `PI_CONTAINER_CONFIG_DIR`. An empty value selects shared state.

#### Scenario: Isolated writable state

- **WHEN** `PI_CONTAINER_STATE_DIR` names a missing absolute directory
- **THEN** it is created with its `.pi` and `.agents` private, mounted at `/pi-home`, and `~/.pi` and `~/.agents` are not mounted

#### Scenario: Invalid isolated state

- **WHEN** the value is relative, the directory is foreign-owned or grants group or other permissions, or it overlaps the workspace
- **THEN** the wrapper exits with status 1 naming the variable before any image operation and changes nothing
- **AND** a relative or overlapping value fails before any engine query

#### Scenario: Engine query fails
- **WHEN** a missing isolated state directory is selected and the engine query fails
- **THEN** the wrapper exits without creating the directory

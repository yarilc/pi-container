# container-filesystem Specification

## Purpose

Define the identity and filesystem boundary used by Pi and shell sessions while preserving extension and tooling workflows.

## Requirements

### Requirement: Caller identity without additional capabilities

Sessions SHALL use keep-id user namespaces and the caller's numeric UID/GID, drop all capabilities without additions, and retain no-new-privileges and configured resource limits. Pi, npm extension installation, Git, and optional Bun SHALL operate without namespace-root privileges using the declared writable locations.

#### Scenario: Non-root workflow

- **WHEN** a caller starts a session and writes workspace/state files, installs an npm extension, commits a disposable Git change, or runs enabled Bun
- **THEN** the process and resulting files use the caller's identity and no DAC_OVERRIDE, CHOWN, SETGID, or SETUID capability is added.

### Requirement: Private writable persistent state

Before image operations the wrapper SHALL validate physical `~/.pi` and `~/.agents` sources as directories owned by the caller, readable/writable/traversable, with no group/other permissions. Missing writable state SHALL be created with a scoped umask 077. Invalid existing state SHALL cause failure without chmod, chown, replacement, or credential import.

#### Scenario: Missing or acceptable writable state

- **WHEN** state directories are missing or already satisfy ownership, privacy, and access checks
- **THEN** missing directories are created privately and the validated physical paths are mounted to their existing HOME-relative destinations.

#### Scenario: Existing insecure or unusable state

- **WHEN** either source is a file, dangling symlink, wrong-owner directory, inaccessible directory, or grants group/other permissions
- **THEN** startup fails before image operations with repair guidance and leaves existing content and permissions untouched.

### Requirement: Read-only persistent state remains available

With the existing read-only configuration option enabled, both persistent directories SHALL be mounted read-only after physical-path, directory, read, and traverse checks. This mode SHALL neither create missing state nor require write permission or silently copy credentials.

#### Scenario: Readable state without write access

- **WHEN** read-only configuration is enabled and both state sources are readable and traversable
- **THEN** startup accepts them without writable-state ownership/privacy requirements and session writes to either mount fail.

#### Scenario: Missing read-only state

- **WHEN** read-only configuration is enabled but either source is absent or unreadable
- **THEN** startup fails before image operations and does not create or modify the source.

### Requirement: Physical workspace binds without host relabeling

The default workspace source, destination, and workdir SHALL be the exact physical absolute current directory. Workspace and state binds SHALL omit automatic SELinux relabeling. Sensitive-directory guards SHALL remain applicable to the exposed workspace, including the parent selected by worktree mode. Access failures SHALL not trigger relabeling or confinement bypasses.

#### Scenario: Symlinked launch directory

- **WHEN** a session starts through a symlink to a project, including a path with spaces
- **THEN** the bind source/destination and workdir retain the physical absolute path and no `:z` or `:Z` mount option is used.

#### Scenario: Sensitive parent or SELinux denial

- **WHEN** worktree mode exposes a guarded parent without the existing unsafe-directory override, or host policy denies mount access
- **THEN** startup fails with an actionable diagnostic and does not change host labels or disable security enforcement.

### Requirement: Explicit bounded ephemeral storage

Read-only sessions SHALL disable automatic read-only tmpfs provisioning and explicitly provide `/tmp`, `/var/tmp`, `/run`, and a separate npm cache with finite capacities, nosuid/nodev, deliberate execution modes, and mapped-user access. Conditional Podman storage SHALL follow the same policy. Temporary contents SHALL disappear after the session.

#### Scenario: Declared temporary mount policy

- **WHEN** a default session starts
- **THEN** `/tmp` and `/var/tmp` each provide 256 MiB and `/run` 32 MiB with rw,noexec,nosuid,nodev,mode=1777, and HOME/.npm provides rw,noexec,nosuid,nodev with caller access and a default 256 MiB capacity configurable by `PI_NPM_CACHE_SIZE`.

#### Scenario: Writable scope and lifetime

- **WHEN** the mapped user writes in every temporary location, attempts a root-filesystem write, and starts a second session
- **THEN** temporary writes succeed within capacity, the root write fails, and previous temporary data is absent while writable persistent state remains.

# container-isolation Specification

## Purpose

Define the identity and filesystem boundary used by Pi and shell sessions while preserving extension and tooling workflows.

## Requirements

### Requirement: Caller identity without additional capabilities

Sessions SHALL use keep-id user namespaces and the caller's numeric UID/GID, drop all capabilities without additions, and retain no-new-privileges and configured resource limits. Pi, npm extension installation and Git SHALL operate without namespace-root privileges using the declared writable locations.

#### Scenario: Non-root workflow

- **WHEN** a caller starts a session and writes workspace/state files, installs an npm extension, or commits a disposable Git change
- **THEN** the process and resulting files use the caller's identity and no DAC_OVERRIDE, CHOWN, SETGID, or SETUID capability is added.

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

### Requirement: Read-only persistent state remains available

With the existing read-only configuration option enabled, both persistent directories SHALL be mounted read-only after physical-path, directory, read, and traverse checks. This mode SHALL neither create missing state nor require write permission or silently copy credentials.

#### Scenario: Readable state without write access

- **WHEN** read-only configuration is enabled and both state sources are readable and traversable
- **THEN** startup accepts them without writable-state ownership/privacy requirements and session writes to either mount fail.

#### Scenario: Missing read-only state

- **WHEN** read-only configuration is enabled but either source is absent or unreadable
- **THEN** startup fails before image operations and does not create or modify the source.

### Requirement: Physical workspace binds without host relabeling

The default workspace source, destination, and workdir SHALL be the exact physical absolute current directory. Workspace and state binds SHALL omit automatic SELinux relabeling. The sensitive-workspace refusal of the `workspace-mounts` capability SHALL apply to the exposed workspace, including the parent selected by worktree mode. Access failures SHALL not trigger relabeling or confinement bypasses.

#### Scenario: Symlinked launch directory

- **WHEN** a session starts through a symlink to a project, including a path with spaces
- **THEN** the bind source/destination and workdir retain the physical absolute path and no `:z` or `:Z` mount option is used.

#### Scenario: Sensitive parent or SELinux denial

- **WHEN** worktree mode exposes a refused parent without `PI_CONTAINER_ALLOW_UNSAFE_WORKSPACE=1`, or host policy denies mount access
- **THEN** startup fails with an actionable diagnostic and does not change host labels or disable security enforcement.

### Requirement: Explicit bounded ephemeral storage

Read-only sessions SHALL explicitly provide `/tmp`, `/var/tmp`, `/run`, the container home and a separate npm cache with finite capacities, nosuid/nodev, deliberate execution modes, and mapped-user access. Automatic read-only tmpfs provisioning SHALL add no writable path beyond these explicit temporary and device mounts. Podman storage SHALL follow the same policy. Temporary contents SHALL disappear after the session.

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

### Requirement: Deprecated gitconfig variable

`PI_MOUNT_GITCONFIG` SHALL remain a deprecated alias that prints one stderr warning naming `PI_CONTAINER_GITCONFIG`. Alone, `1` SHALL behave as the opt-in and `0` as the default. Values other than `0` and `1` SHALL stop with status 1 before engine queries.

#### Scenario: Old opt-in value

- **WHEN** only `PI_MOUNT_GITCONFIG=1` is set and `~/.gitconfig` exists
- **THEN** the file is mounted read-only and stderr contains one deprecation warning

#### Scenario: Conflicting values

- **WHEN** `PI_MOUNT_GITCONFIG=0` and `PI_CONTAINER_GITCONFIG=1` are both set, or `PI_MOUNT_GITCONFIG=1` and `PI_CONTAINER_GITCONFIG` is set to another value
- **THEN** the wrapper exits with status 1 naming both variables, before any engine query

### Requirement: Gitconfig migration notice

When neither `PI_CONTAINER_GITCONFIG` nor `PI_MOUNT_GITCONFIG` is set and `~/.gitconfig` exists, the wrapper SHALL print one stderr notice that the file is no longer mounted by default and how to opt in. The notice SHALL NOT include file contents and SHALL NOT change the exit status.

#### Scenario: Notice and silence

- **WHEN** `~/.gitconfig` exists and no variable is set
- **THEN** one notice naming `PI_CONTAINER_GITCONFIG=1` is printed and the session starts
- **AND** setting `PI_CONTAINER_GITCONFIG=0` suppresses the notice

### Requirement: Sessions have explicit resource budgets
Every Pi and shell container SHALL be created with a memory limit, a CPU limit and a process limit for each budget whose cgroup v2 controller (`memory`, `cpu`, `pids`) the verified rootless engine reports as available. The defaults SHALL be 4 GiB memory, 2 CPUs and 512 processes. `PI_CONTAINER_MEMORY_LIMIT`, `PI_CONTAINER_CPU_LIMIT` and `PI_CONTAINER_PIDS_LIMIT` SHALL override them. Only an unset variable SHALL select its default; no value SHALL disable a budget, and only a missing controller SHALL leave it unenforced.

#### Scenario: Accepted formats
- **WHEN** the operator sets a budget variable
- **THEN** memory accepts a positive integer with unit `k`, `m` or `g`, CPU accepts a positive decimal with at most three fractional digits up to 1024, and the process limit accepts an integer from 1 to 4194304

#### Scenario: Default budgets
- **WHEN** a session starts with none of the budget variables set on an engine reporting the `cpu`, `memory` and `pids` controllers
- **THEN** the container is created with 4 GiB memory, 2 CPUs and 512 processes

#### Scenario: Operator overrides budgets
- **WHEN** the operator sets `PI_CONTAINER_MEMORY_LIMIT=8g`, `PI_CONTAINER_CPU_LIMIT=1.5` and `PI_CONTAINER_PIDS_LIMIT=1024` on an engine reporting all three controllers
- **THEN** the container is created with exactly those limits

#### Scenario: Invalid or unbounded budget value
- **WHEN** a budget variable is set but empty or whitespace, zero, negative, `-1`, `max`, non-numeric, out of range, or has an unsupported unit
- **THEN** the wrapper exits with status 1 and names the variable before any engine query, state creation or image operation

#### Scenario: Controller not delegated
- **WHEN** the verified engine does not report the `cpu` controller
- **THEN** the container is created without a CPU limit, while the memory and process limits are still applied when their controllers are reported
- **AND** the session continues and prints a notice naming the unenforced CPU budget and the missing controller

#### Scenario: Process controller not delegated
- **WHEN** the verified engine does not report the `pids` controller
- **THEN** the container is created with an explicitly unlimited process setting, so no engine default requests the missing controller

### Requirement: Resource budgets are verified, not assumed
Before starting the application, each launch SHALL inspect the created container and require each enforced budget to equal its selected value and each unenforced budget to be absent. A mismatch or missing enforced limit SHALL stop startup with an actionable diagnostic, without a retry using weaker limits. Runtime verification SHALL measure the effective cgroup v2 limits inside the session in the same way.

#### Scenario: Engine ignores a budget
- **WHEN** the created container reports no limit or a different limit for a budget whose controller the engine reports as available
- **THEN** the wrapper removes only its own container and exits non-zero before the application starts
- **AND** the diagnostic names rootless cgroup v2 controller delegation and the controllers the engine reported

#### Scenario: Unenforced budget unexpectedly present
- **WHEN** the created container reports a limit for a budget whose controller the engine does not report
- **THEN** the wrapper removes only its own container and exits non-zero before the application starts

#### Scenario: Effective limits are measured
- **WHEN** the real-engine runtime checks run a session with default and overridden budgets on an engine reporting all three controllers
- **THEN** the container's cgroup v2 `memory.max`, `pids.max` and `cpu.max` match the selected budgets
- **AND** a process count beyond the process limit fails inside the session

### Requirement: Hardening controls are documented

Wrapper help and the README SHALL document the budget variables with defaults and accepted formats, the lifetime variable, the unsafe-workspace override with the refused directories, and that capabilities are dropped in every mode. They SHALL state that budgets and tmpfs sizes do not bound workspace or state storage growth. Help SHALL remain free of engine queries and state creation.

#### Scenario: Operator reads wrapper help

- **WHEN** the operator runs `--container-help`
- **THEN** the output lists `PI_CONTAINER_MEMORY_LIMIT`, `PI_CONTAINER_CPU_LIMIT`, `PI_CONTAINER_PIDS_LIMIT`, `PI_CONTAINER_RUN_TIMEOUT` and `PI_CONTAINER_ALLOW_UNSAFE_WORKSPACE` with their defaults
- **AND** it states that capabilities are dropped and budgets do not limit persistent storage
- **AND** no engine query or state creation occurs

### Requirement: Dedicated container home

Sessions SHALL use `HOME=/pi-home`, an ephemeral noexec tmpfs, with the persistent state, npm cache and opted-in gitconfig mounted at fixed paths beneath it. The workspace SHALL keep its host absolute path. Files written elsewhere below `/pi-home` SHALL NOT survive the session.

#### Scenario: Default layout

- **WHEN** a default session starts
- **THEN** `HOME` is `/pi-home`, and `~/.pi`, `~/.agents` and the npm cache tmpfs are at `/pi-home/.pi`, `/pi-home/.agents` and `/pi-home/.npm`
- **AND** Pi, npm extension installation and Git work as before, and host state is unchanged apart from Pi's own writes

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

### Requirement: Engine default secrets mount is masked
Every Pi and shell container SHALL be created with an empty read-only tmpfs at `/run/secrets`, in every network mode and with or without Podman access. An engine default mount there, such as RHEL subscription secrets from `mounts.conf`, SHALL then be neither visible nor writable. No host configuration change SHALL be required.

#### Scenario: Host with a default secrets mount
- **WHEN** the engine's `mounts.conf` maps `/usr/share/rhel/secrets` to `/run/secrets`
- **THEN** the session has exactly one mount at `/run/secrets`, an empty tmpfs mounted read-only
- **AND** no host subscription file is readable inside the session

#### Scenario: Host without a default secrets mount
- **WHEN** the engine adds no mount at `/run/secrets`
- **THEN** the session still has the empty read-only tmpfs there and behaves as before

### Requirement: Engine-provided device mounts allow pseudo-terminals
Every Pi and shell container SHALL keep automatic read-only tmpfs provisioning enabled and SHALL NOT mount its own `/dev` or `devpts`, so that the engine provides `/dev` and a `devpts` that allows pseudo-terminals. It SHALL mask `/dev/shm` with an empty read-only tmpfs. Automatic provisioning SHALL add no writable path beyond the explicit temporary mounts and the engine's `/dev`.

#### Scenario: Terminal attaches on an engine that mounts /dev read-only
- **WHEN** an interactive session starts with a terminal on Podman 5 with crun 1.27
- **THEN** the terminal attaches and Pi starts without any host configuration change
- **AND** `/dev/pts` is present and `/dev/shm` is read-only and empty

#### Scenario: Pseudo-terminals are available to tools
- **WHEN** a process inside the session opens a pseudo-terminal, as an interactive tool run by Pi or in the shell does
- **THEN** the allocation succeeds through `/dev/ptmx` and returns a terminal under `/dev/pts`

#### Scenario: Device masks stay empty and read-only
- **WHEN** a process inside the session lists or writes `/dev/shm` or `/run/secrets`
- **THEN** both are empty and the write fails

#### Scenario: Temporary mounts keep their Pi policy
- **WHEN** a session starts
- **THEN** `/tmp`, `/var/tmp` and `/run` keep their `noexec` 256, 256 and 32 MiB policy, and the home and npm cache keep theirs
- **AND** no writable `/var/log` tmpfs or writable `/dev/shm` is introduced by automatic provisioning

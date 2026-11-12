## ADDED Requirements

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

## REMOVED Requirements

### Requirement: Terminal-compatible device mounts
**Reason**: Its explicit `devpts` gets the kernel defaults `mode=600,ptmxmode=000`, so no pseudo-terminal can be opened in a session, and Podman rejects `ptmxmode` as a mount option. Its guarantee that executables cannot run from `/dev` depended on that explicit `/dev` tmpfs.
**Migration**: Replaced by "Engine-provided device mounts allow pseudo-terminals". On Podman 5 `/dev` is the engine's writable tmpfs without `noexec`; on Podman 4.9 it stays read-only. Restricted installations rerun `--container-setup`.

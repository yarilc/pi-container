# Spec Delta

## ADDED Requirements

### Requirement: Sessions receive no Podman socket

No Pi or shell session container SHALL receive a host Podman socket mount or private `/var/lib/containers` / `/run/containers` delegation mounts in any network mode. When no session container engine is started, both `CONTAINER_HOST` and `DOCKER_HOST` SHALL be absent from the session environment.

#### Scenario: Unrestricted session without library images

- **WHEN** an unrestricted session starts with no image toolchains in the library
- **THEN** `/run/podman/podman.sock` is absent and neither `CONTAINER_HOST` nor `DOCKER_HOST` is set

## MODIFIED Requirements

### Requirement: Caller identity without additional capabilities

Sessions SHALL use keep-id user namespaces and the caller's numeric UID/GID, drop all capabilities without additions, and retain no-new-privileges and configured resource limits, with or without a session container engine. Pi, npm extension installation and Git SHALL operate without namespace-root privileges using the declared writable locations.

#### Scenario: Non-root workflow

- **WHEN** a caller starts a session and writes workspace/state files, installs an npm extension, or commits a disposable Git change
- **THEN** the process and resulting files use the caller's identity and no DAC_OVERRIDE, CHOWN, SETGID, or SETUID capability is added.

### Requirement: Explicit bounded ephemeral storage

Read-only sessions SHALL explicitly provide `/tmp`, `/var/tmp`, `/run`, the container home and a separate npm cache with finite capacities, `noexec`, nosuid/nodev, and mapped-user access. Automatic read-only tmpfs provisioning SHALL add no writable path beyond these explicit temporary and device mounts. Temporary contents SHALL disappear after the session.

#### Scenario: Declared temporary mount policy

- **WHEN** a default session starts
- **THEN** `/tmp` and `/var/tmp` each provide 512 MiB with rw,noexec,nosuid,nodev,mode=1777, and `/run` provides 32 MiB noexec,nosuid,nodev and is not writable by the session user
- **AND** `/pi-home` provides a 512 MiB noexec,nosuid,nodev home, and `/pi-home/.npm` provides rw,noexec,nosuid,nodev with caller access and a default 256 MiB capacity configurable by `PI_NPM_CACHE_SIZE`

#### Scenario: Writable scope and lifetime

- **WHEN** the mapped user writes in every writable temporary location, attempts a root-filesystem write, and starts a second session
- **THEN** temporary writes succeed within capacity, the root write fails, and previous temporary data is absent while writable persistent state remains

### Requirement: Engine default secrets mount is masked

Every Pi and shell container SHALL be created with an empty read-only tmpfs at `/run/secrets`, in every network mode and with or without a session container engine. An engine default mount there, such as RHEL subscription secrets from `mounts.conf`, SHALL then be neither visible nor writable. No host configuration change SHALL be required.

#### Scenario: Host with a default secrets mount

- **WHEN** the engine's `mounts.conf` maps `/usr/share/rhel/secrets` to `/run/secrets`
- **THEN** the session has exactly one mount at `/run/secrets`, an empty tmpfs mounted read-only
- **AND** no host subscription file is readable inside the session

#### Scenario: Host without a default secrets mount

- **WHEN** the engine adds no mount at `/run/secrets`
- **THEN** the session still has the empty read-only tmpfs there and behaves as before

### Requirement: Engine-provided device mounts allow pseudo-terminals

Every Pi and shell container SHALL keep automatic read-only tmpfs provisioning enabled and SHALL NOT mount its own `/dev` or `devpts`, so that the engine provides `/dev` and a `devpts` that allows pseudo-terminals. It SHALL mask `/dev/shm` with an empty read-only tmpfs. Automatic provisioning SHALL add no writable path beyond the explicit temporary mounts and the engine's `/dev`. When a session joins its container engine's network namespace, Podman's read-only bind-mount of host `/sys` SHALL be documented without weakening the network namespace boundary.

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
- **THEN** `/tmp`, `/var/tmp` and `/run` keep their `noexec` 512, 512 and 32 MiB policy, and the home and npm cache keep theirs
- **AND** no writable `/var/log` tmpfs or writable `/dev/shm` is introduced by automatic provisioning

### Requirement: Process budget falls back to the process rlimit

When the verified engine does not delegate the `pids` controller and the engine host counts the process rlimit per container, the agent container's first process SHALL set its soft and hard process rlimit to the selected process budget before the container's program runs. The engine SHALL apply no process rlimit for the budget: one applied at creation counts every container of the user. Otherwise the process budget SHALL stay unenforced. Memory and CPU SHALL have no fallback.

#### Scenario: Process controller missing on a per-container host

- **WHEN** a session starts with the default budgets on an engine delegating `cpu` and `memory` but not `pids`, on a host that counts the process rlimit per container
- **THEN** the container's first process sets a soft and hard process rlimit of 512 before the application, or the guard in restricted modes, runs
- **AND** the container is created without a cgroup process limit and without a process rlimit requested from the engine
- **AND** the memory and CPU limits are applied as before

#### Scenario: Process controller delegated

- **WHEN** the engine delegates the `pids` controller
- **THEN** the process budget is enforced only by the cgroup process limit
- **AND** the wrapper sets no process rlimit

#### Scenario: Per-container counting not established

- **WHEN** the engine does not delegate `pids` and the host is not known to count the process rlimit per container
- **THEN** the wrapper requests neither a cgroup process limit nor a process rlimit for the container
- **AND** the session continues with a notice that names the unenforced process budget and why the fallback was not applied

#### Scenario: Memory controller missing

- **WHEN** the engine does not delegate the `memory` controller
- **THEN** the memory budget stays unenforced and no substitute memory limit is set

#### Scenario: The session cannot raise its process rlimit

- **WHEN** a process in a session on the fallback tries to raise its soft or hard process rlimit above the selected budget
- **THEN** the attempt fails, because the session has no capabilities and no-new-privileges is set

#### Scenario: Concurrent sessions have independent limits

- **WHEN** two sessions on the fallback run at the same time and the first holds processes up to its limit
- **THEN** the second session can still create processes up to its own limit

#### Scenario: Other containers do not consume the session's budget

- **WHEN** other containers of the same user, such as proxies, engines or their nested containers, together hold more processes than the session's budget
- **THEN** the session starts, and can create processes up to its own budget

#### Scenario: The limit cannot be set

- **WHEN** the container's first process cannot set the process rlimit to the selected budget
- **THEN** the container stops before the application or the guard runs, and the launch exits non-zero

### Requirement: Process rlimit fallback is verified

When the process budget uses the rlimit fallback, each launch SHALL require the created agent container to start with the step that sets the selected budget, and to carry no process rlimit requested by the wrapper. Setup smoke and restricted qualification SHALL measure the effective limit inside the agent container. A mismatch SHALL stop startup or setup with an actionable diagnostic, without a retry using weaker limits.

#### Scenario: Engine drops the process rlimit

- **WHEN** the created container does not start with the step that sets the selected budget, for example because the engine dropped or replaced its entry command, or the step sets another value, or the container carries a process rlimit requested by the wrapper
- **THEN** the wrapper removes only its own container and exits non-zero before the application starts
- **AND** the diagnostic names the process rlimit fallback

#### Scenario: Effective rlimit is measured

- **WHEN** setup smoke or the restricted qualification probe runs inside an agent container on the fallback
- **THEN** it reads the effective soft and hard process rlimit and requires both to equal the selected budget
- **AND** it requires the cgroup process interface to be absent or unlimited

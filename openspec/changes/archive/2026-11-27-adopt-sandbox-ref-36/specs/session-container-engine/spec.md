# Spec Delta

## Purpose

Give Pi sessions a private, rootless container engine that runs operator-installed library images inside the session's own network and filesystem boundaries, so agents can run container-based tests without host Podman authority.

## ADDED Requirements

### Requirement: Engine for sessions with library images

A session SHALL get a private container engine when the toolchain library is mounted and its image store holds at least one image. This SHALL apply in every network mode, to Pi and `--container-shell` sessions alike. Otherwise the launcher SHALL create no engine, and `CONTAINER_HOST` and `DOCKER_HOST` SHALL be absent from the session.

#### Scenario: Library with an image

- **GIVEN** the operator added a toolchain with an image
- **WHEN** an offline session starts
- **THEN** the session has a running engine and `CONTAINER_HOST` names it

#### Scenario: Library without images

- **WHEN** a session starts and the library holds only file toolchains, or no toolchains
- **THEN** no engine container exists for it, and `CONTAINER_HOST` and `DOCKER_HOST` are absent

#### Scenario: Library mount disabled

- **WHEN** a session starts with `PI_CONTAINER_TOOLCHAINS=0`
- **THEN** no engine container exists for it, even if the library holds images

#### Scenario: First image added during a session

- **GIVEN** a session started without an engine because the library held no image
- **WHEN** the operator adds the first image toolchain
- **THEN** that session still has no engine, and the next session started has one

### Requirement: Loopback endpoint for the session

The session SHALL reach its engine only through a loopback TCP endpoint in the session's own network namespace. The endpoint SHALL be given as `CONTAINER_HOST=tcp://127.0.0.1:<port>` and, for Docker-API clients, as `DOCKER_HOST` with the same value. No engine or host Unix socket SHALL be mounted into the session. The endpoint SHALL serve only that session's engine.

#### Scenario: Client in the session

- **WHEN** a process in the session runs `podman info` with the provided `CONTAINER_HOST`
- **THEN** the engine answers and reports rootless operation

#### Scenario: Docker-API client

- **WHEN** a test framework in the session reads `DOCKER_HOST` and starts a container through the Docker-compatible API
- **THEN** the container runs in the session's engine

#### Scenario: Two sessions

- **WHEN** two sessions with engines run at the same time
- **THEN** each session's endpoint reaches only its own engine, and neither sees the other's containers

### Requirement: Engine shares the session network boundary

The engine and every container it runs SHALL have no network path other than the session's:

- an offline session's engine SHALL reach no external service;
- a provider session's engine SHALL reach only what the session's proxy policy allows, through that proxy;
- an unrestricted session's engine SHALL have the session's network.

#### Scenario: Offline nested container

- **WHEN** a container started by an offline session's engine tries direct DNS, TCP or UDP to an external address, or the engine tries to pull an image
- **THEN** every attempt fails, and no network path appears that the session lacks

#### Scenario: Interfaces of a restricted session with an engine

- **WHEN** a restricted session with an engine lists the interfaces of its network namespace (`/proc/net/dev`)
- **THEN** only loopback is present, although the host's `/sys`, which Podman bind-mounts read-only into a container that joins another network namespace, lists the host's interfaces

#### Scenario: Unrestricted pull

- **WHEN** an unrestricted session's engine pulls an image that is not in the library
- **THEN** the pull uses the session's network and the image stays in the session's storage

### Requirement: Engine mounts only the workspace and the image store

The engine container SHALL mount these host paths and no other:

- the session workspace, and the worktree parent when selected, at the same absolute paths;
- the library's image store, read-only;
- the host CA bundle, read-only, when host CA trust is enabled.

It SHALL NOT mount state, configuration, credentials, the installation or any host Podman socket.

#### Scenario: Workspace bind from a nested container

- **WHEN** a process in the session runs a container that bind-mounts `$PWD` from inside the workspace
- **THEN** the nested container sees the workspace files at that path
- **AND** files that the nested container's root creates there belong to the caller

#### Scenario: Host path outside the workspace

- **WHEN** a nested container bind-mounts a path outside the workspace, such as `/home` or `/etc`
- **THEN** it sees the engine image's own files, never the host's, and no state or credential directory is reachable

### Requirement: Engine carries no secrets

The engine container SHALL receive no credential, agent variable or proxy credential. It SHALL keep `/run/secrets` masked by an empty read-only mount. It SHALL pass no host mounts to nested containers, so nested containers receive no engine-host secret either.

#### Scenario: Nested secrets directory

- **WHEN** a nested container lists `/run/secrets`
- **THEN** the directory is absent or empty

#### Scenario: Engine environment

- **WHEN** the engine container's environment is inspected
- **THEN** it contains only fixed engine settings, and no variable forwarded from the caller

### Requirement: Session-owned engine storage

The engine's writable storage SHALL belong to the session: containers, volumes, and images built, pulled or loaded during the session. It SHALL be removed with the engine when the session ends, including after failure, interruption or a stale session that a later launch cleans up. Only the library's image store SHALL persist between sessions.

#### Scenario: Image built in a session

- **WHEN** a session builds an image with its engine and a later session lists its engine's images
- **THEN** the built image is absent, and the library images are present

#### Scenario: Interrupted session

- **WHEN** a session with an engine ends abnormally
- **THEN** its engine container and storage are removed by the session-owned cleanup that applies to the session's other resources

### Requirement: Library images run offline from a read-only store

The engine SHALL resolve library images by their recorded references, including digest references, without network and without copying them into session storage. It SHALL NOT be able to change the store. An image added to the library during a session SHALL be usable by that session's engine without restart.

#### Scenario: Offline run by digest

- **WHEN** an offline session runs a library image by its `@sha256:` reference
- **THEN** the container starts without a pull

#### Scenario: Store is read-only to the engine

- **WHEN** the session asks its engine to remove a library image
- **THEN** the engine refuses, and the library is unchanged

#### Scenario: Image added during a session

- **WHEN** the operator adds an image toolchain while a session with an engine runs
- **THEN** that session's engine lists and runs the new image without a restart

### Requirement: Nested containers have private process and host-name views

Every nested container SHALL have its own procfs, showing only its own PID namespace. It SHALL have its own UTS namespace whose host name defaults to its container ID, as with a host engine.

#### Scenario: Process view

- **WHEN** a nested container started with a private PID namespace lists `/proc`
- **THEN** its PID 1 is its own process, and no process of the engine or of another nested container is visible

#### Scenario: Host name

- **WHEN** a nested container prints its host name
- **THEN** it is the container's short ID

### Requirement: Engine budgets

The engine container SHALL receive the session's memory, CPU and process budgets. Their enforcement, fallback, verification and announcement SHALL follow the agent container's rules. Where the engine's cgroup is enforced, the budgets SHALL bound the engine and all its nested containers together.

#### Scenario: Delegated controllers

- **WHEN** the rootless engine delegates `memory`, `cpu` and `pids` with the systemd cgroup manager
- **THEN** the engine container's effective limits equal the session budgets, and the launch verifies them

#### Scenario: Cgroupfs engine

- **WHEN** the rootless engine uses the cgroupfs cgroup manager
- **THEN** the launch announces the engine's unenforced budgets with the same reasons as the agent's, and applies the process rlimit fallback where the rules allow it

### Requirement: Fixed engine hardening exceptions

The engine container SHALL run as an unprivileged user after its startup step and relax only what nested containers and image builds need: user-namespace helper capabilities, `SYS_CHROOT`, FUSE and TUN devices, unmasked procfs, disabled SELinux labelling, `sethostname`/`setdomainname` over the host default seccomp profile, and the cgroup-delegation startup step. The wrapper SHALL NOT widen these exceptions for any nested tool.

#### Scenario: Engine container inspected

- **WHEN** an engine container is inspected
- **THEN** its configured user, capabilities, devices, masks, labels and seccomp profile match exactly the documented exceptions, and its running processes run as the engine user with the ownership-change capability only in their bounding set

#### Scenario: Image operations in a session

- **WHEN** a session builds an image with a `RUN` step, or loads an image whose layers its engine does not have
- **THEN** the operation succeeds within these exceptions

#### Scenario: Tool needs more

- **WHEN** a nested tool fails because it needs a privilege outside these exceptions
- **THEN** the wrapper adds nothing, and the limitation is recorded in the validation record

### Requirement: Engine lifecycle follows the session

The launcher SHALL start the engine before the application runs and verify that it answers as a rootless engine. A failure SHALL stop the launch before the application starts, naming the engine. The engine SHALL be stopped and removed when the session ends, and it SHALL never serve another session.

#### Scenario: Engine fails to start

- **WHEN** the engine container cannot start or does not answer within its timeout
- **THEN** the launch exits nonzero before the application runs, and no engine or session resource remains

#### Scenario: Session ends

- **WHEN** the application exits
- **THEN** the engine container and its storage are removed before the wrapper returns the application's status

### Requirement: Engine containment is qualified

Restricted local qualification SHALL include engine containment checks:

- no route outside the session;
- private procfs and UTS for nested containers;
- a read-only image store;
- no secrets;
- workspace-only mounts;
- unwritable limit files of the engine's cgroup root;
- on an eligible engine, nested cgroups below the engine's.

A restricted session SHALL NOT start an engine on an installation whose current qualification lacks them.

#### Scenario: Qualified installation

- **WHEN** qualification runs on an installation with the engine image
- **THEN** the report records the engine containment results and the engine's eligibility, bound to the engine image identity

#### Scenario: Qualification without engine checks

- **WHEN** a restricted session would start an engine and the installation's qualification predates the engine checks or failed them
- **THEN** the launch stops before the application with requalification guidance

#### Scenario: Ineligible engine host

- **WHEN** qualification runs where the engine is ineligible
- **THEN** the report records the engine as ineligible, the delegation check is not required, and the other engine checks still apply

### Requirement: Measured eligibility for cgroup delegation

Each engine start SHALL measure whether the engine is eligible for cgroup delegation: its cgroup namespace is private, and its root is a cgroup v2 directory mounted read-write with `nsdelegate` and owned by the root of the engine's user namespace. Eligibility SHALL NOT be inferred from the engine host's cgroup manager, and it SHALL NOT require a host change.

#### Scenario: Native Linux with the systemd cgroup manager

- **WHEN** an engine starts on a native Linux host whose rootless Podman uses the `systemd` cgroup manager with cgroup v2
- **THEN** the engine is eligible

#### Scenario: Windows Podman machine

- **WHEN** an engine starts in a Windows Podman machine whose rootless Podman uses the `cgroupfs` cgroup manager with cgroup v2 and delegates no controller
- **THEN** the engine is eligible

#### Scenario: Engine without a suitable cgroup v2 root

- **WHEN** an engine starts on a host with cgroup v1, or its cgroup root is not owned by the root of its user namespace, or is mounted without `nsdelegate`
- **THEN** the engine is ineligible, and nothing is delegated

### Requirement: Delegated engine cgroup subtree

On an eligible engine, the engine's startup step SHALL delegate a cgroup subtree below the engine's cgroup root to the engine user and enable the controllers available in the engine's cgroup. The engine's cgroup root and its limit files SHALL remain unwritable to the engine user and to nested containers.

#### Scenario: Nested container cgroup

- **WHEN** a nested container starts on an eligible engine
- **THEN** it runs in its own cgroup below the engine's cgroup

#### Scenario: Engine limits from inside the engine

- **WHEN** a process of the engine user, or the root of a nested container that mounts the engine's cgroup namespace read-write, writes any limit file of the engine's cgroup root
- **THEN** the write fails, and the session budgets are unchanged

#### Scenario: Delegation fails

- **WHEN** an eligible engine cannot complete the delegation
- **THEN** the engine does not start, and the launch stops before the application, naming the engine

### Requirement: Engine startup step

Only the engine's startup step SHALL run as the root of the engine's user namespace and hold the ownership-change capability, which it SHALL use only to delegate the engine's cgroup subtree. It SHALL then run the engine as the engine user. Afterwards the capability SHALL stay only in the bounding set, which no-new-privileges keeps unreachable. The launcher's own commands in the engine SHALL run as the engine user.

#### Scenario: Running engine processes

- **WHEN** the processes of a running engine are listed
- **THEN** none runs as the root of the engine's user namespace, the engine's init included, and none holds the ownership-change capability in its permitted, effective or ambient set in the engine's user namespace

#### Scenario: Launcher commands in the engine

- **WHEN** the launcher runs its readiness, process limit or eligibility checks in the engine
- **THEN** they run as the engine user

### Requirement: Systemd in nested containers

On an eligible engine, a nested container started in systemd mode with a systemd image SHALL boot systemd as its PID 1 to the `running` or `degraded` state. Systemd SHALL start units and keep their journal.

#### Scenario: Rocky Linux 9 target

- **WHEN** a session runs a Rocky Linux 9 image that starts `/sbin/init` with `podman run --systemd=always` on an eligible engine
- **THEN** once boot completes, `systemctl is-system-running` reports `running` or `degraded`

#### Scenario: Amazon Linux 2023 target

- **WHEN** a session runs an Amazon Linux 2023 image that starts `/sbin/init` with `podman run --systemd=always` on an eligible engine
- **THEN** once boot completes, `systemctl is-system-running` reports `running` or `degraded`

#### Scenario: Unit and journal

- **WHEN** a test starts a unit in a running nested systemd container
- **THEN** the unit becomes active, and `journalctl` shows its output

### Requirement: Explicit limits for nested containers

On an eligible engine, explicit limits requested for a nested container SHALL apply for every controller the engine has. A request that needs a controller the engine lacks, or any request on an ineligible engine, SHALL fail without starting the container.

#### Scenario: Engine with memory and pids controllers

- **WHEN** a nested container on an eligible engine with the `memory` and `pids` controllers is started with `--memory=64m --pids-limit=32`
- **THEN** its cgroup has `memory.max` 67108864 and `pids.max` 32

#### Scenario: Engine without the controller

- **WHEN** a nested container is started with `--memory=64m` on an engine without the `memory` controller, such as an engine in the Windows Podman machine
- **THEN** the container does not start, and the run reports an error

### Requirement: Ineligible engines are announced

When an engine is ineligible, the launch SHALL announce that systemd containers and explicit nested limits are unavailable in the session, with the reason. The session SHALL otherwise start as on an eligible engine.

#### Scenario: Ineligible engine

- **WHEN** a session starts with an ineligible engine
- **THEN** the launch prints the notice with the reason before the application starts, and the application runs

#### Scenario: Eligible engine

- **WHEN** a session starts with an eligible engine
- **THEN** no such notice is printed

### Requirement: Engine documentation

The README SHALL describe:

- when a session has an engine, its endpoint and how images reach it;
- its storage lifecycle, budgets and hardening exceptions;
- that a session with an engine sees the host's `/sys` read-only;
- systemd containers and explicit nested limits: the engines where they work, the delegation exception, and what a test cannot exercise on an engine without controllers.

#### Scenario: Operator reads the documentation

- **WHEN** an operator reads the README section on container tests
- **THEN** it shows how to add an image toolchain and run it from a session, and lists the engine's limits and exceptions

#### Scenario: Systemd containers documented

- **WHEN** an operator reads the README section on container tests
- **THEN** it shows how to run a systemd image from a session, names the platforms where it works, and states that resource-control unit settings have no effect on an engine without controllers

### Requirement: Engine image declares its capabilities

The engine image SHALL declare in its `io.containers.capabilities` label exactly the capabilities that the engine container is started with: `SETUID`, `SETGID`, `SYS_CHROOT` and `CHOWN`. Starting an engine SHALL therefore report no capability error. The label SHALL NOT add a capability to the engine: its capabilities stay the fixed hardening exceptions.

#### Scenario: Engine started by a session

- **WHEN** a session starts its engine through a Podman engine that reads the image's capability label
- **THEN** Podman reports no `Capabilities requested by user or image are not allowed by default` error, and the engine's bounding set is `SETUID`, `SETGID`, `SYS_CHROOT` and `CHOWN`

#### Scenario: Label and options drift apart

- **WHEN** the engine recipe's capability label differs from the capabilities of the engine container options
- **THEN** the shared engine recipe check fails, naming the difference

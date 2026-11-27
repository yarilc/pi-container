# Spec Delta

## ADDED Requirements

### Requirement: Saved delegation preferences are migrated

Setup SHALL accept saved preferences that enable delegation or name a delegation socket. It SHALL drop both settings, say what replaces them, and save preferences without them. The managed launcher SHALL refuse saved preferences that still enable delegation before any engine query, with guidance to rerun setup.

#### Scenario: Rerun with saved delegation

- **WHEN** setup runs over preferences that enable delegation in unrestricted mode
- **THEN** it keeps the other saved choices as proposals, states that delegation was removed, and the saved result has no delegation or delegation socket

#### Scenario: Launch with saved delegation

- **WHEN** a managed launch reads preferences that still enable delegation, because setup was not rerun
- **THEN** it exits nonzero before any engine query, asking to rerun setup

### Requirement: Setup re-verifies the toolchain library

After setup prepares the runtime image of a new release, it SHALL rerun the check of every installed toolchain whose verified base differs from that release's base, and record the new base for each check that passes. A failed check SHALL NOT fail setup: setup SHALL name the toolchain and its failure, and the toolchain SHALL keep its previous verified base.

#### Scenario: Base changed by an update

- **WHEN** a default toolchain was verified on the previous base and setup installs a release with a new base
- **THEN** setup reruns its check, and new sessions get its default environment without a manual `verify`

#### Scenario: Check fails after an update

- **WHEN** the rerun check of a toolchain fails on the new runtime image
- **THEN** setup completes with its usual result, names the toolchain and the failed check, and new sessions give that toolchain no default environment, with the launcher's usual warning

#### Scenario: Nothing to re-verify

- **WHEN** no toolchain is installed, or every installed toolchain was verified on the new base
- **THEN** setup runs no toolchain check

## MODIFIED Requirements

### Requirement: Optional authority requires deliberate selection

Setup SHALL explain and require explicit selection of unrestricted networking, permission bypass, worktree-parent exposure and host CA trust. Setup SHALL NOT offer host Podman delegation. Enabling the host launch service SHALL NOT implicitly grant its socket to the application.

#### Scenario: Restricted networking and delegation conflict

- **WHEN** a rerun finds saved preferences that enable delegation, with any network mode
- **THEN** setup explains that delegation was removed and that image toolchains replace it, and saves the preferences without it
- **AND** it never silently broadens networking

#### Scenario: Launch service without delegation

- **WHEN** setup enables the API service for restricted launch
- **THEN** no saved setting grants its socket, or any other Podman socket, to the application

### Requirement: Mode-specific image and guard preparation

Setup SHALL inspect or prepare the runtime image and the additional components required by the selected mode. Every mode SHALL also receive the session engine image (`localhost/pi-container-engine:latest`), built from its digest-pinned base, and the engine seccomp profile derived from the engine host's default profile. Restricted modes SHALL receive a validated static guard and digest manifest; provider mode SHALL also receive a valid selected policy, private runtime directory and immutable proxy image identity. Existing suitable artifacts SHALL be reused unless refresh is approved.

#### Scenario: Fresh provider setup

- **WHEN** provider setup is approved with no prepared artifacts
- **THEN** setup prepares the pinned build inputs, toolchain, runtime, engine and proxy images, compiles the guard and validates its manifest and policy
- **AND** launch preferences refer to an inspected immutable proxy image rather than an unresolved local tag

#### Scenario: Offline or unrestricted setup

- **WHEN** setup prepares offline mode
- **THEN** it prepares the runtime, the guard and the engine image without requiring a provider proxy image or authentication
- **AND** unrestricted setup requires neither the restricted guard nor provider proxy components

#### Scenario: Preparation fails

- **WHEN** an image build, image inspection, guard compilation or validation fails
- **THEN** setup reports the failed stage and leaves the last working installation selected
- **AND** it does not substitute a different policy, toolchain or network mode

#### Scenario: Engine image and profile recorded

- **WHEN** setup prepares any mode
- **THEN** the installation records the engine image identity and the engine seccomp profile, and a later setup reuses them unless their inputs or the engine host's default profile changed

### Requirement: Persistent non-secret managed launch preferences

Setup SHALL save versioned non-secret preferences (schema 3) and a managed launcher usable from any workspace without exports. Preferences and launcher code SHALL stay outside application-writable mounts and be validated before use. The launcher SHALL preserve arguments, stdin, terminal handling and the current directory. Direct invocation SHALL accept explicit runtime modes. An unset or empty effective mode SHALL select Pi's provider default, which needs the provider settings or gets setup guidance. The saved workspace scope SHALL apply only to session launches: host management commands such as `--container-toolchain` SHALL reach the wrapper with their arguments unchanged.

#### Scenario: New terminal and workspace

- **WHEN** the user invokes the managed launcher in a new terminal from a separate workspace
- **THEN** the saved network, profile, state, service, CA, workspace-scope and approval choices apply without modifying shell startup files
- **AND** the current directory determines the mounted workspace and container working directory

#### Scenario: Explicit environment overrides

- **WHEN** a supported runtime variable is explicitly present in the launch environment
- **THEN** its value, including an empty value, takes precedence over the saved default
- **AND** the effective configuration still passes existing conflict, privacy and enforcement checks

#### Scenario: Unsafe or malformed preferences

- **WHEN** managed preferences are untrusted, invalid or use an unsupported schema
- **THEN** the launcher fails before image operations or container creation without evaluating their contents as shell code

#### Scenario: Invoked dispatcher or alias is writable

- **WHEN** an invocation uses a dispatcher copy or a symlink chain with any entry inside a writable workspace or state mount
- **THEN** launch fails before application execution even if the configured command and final symlink target are protected
- **AND** relative paths and dot-dot components are interpreted with filesystem symlink semantics

#### Scenario: Legacy managed dispatcher needs migration

- **WHEN** an old managed dispatcher cannot identify its actual invocation path to the installed helper
- **THEN** normal launch fails with setup guidance while help and setup remain available
- **AND** setup atomically upgrades the recognized dispatcher without overwriting unrelated command files

#### Scenario: Saved mode supplies launch configuration

- **WHEN** a validated managed launcher supplies saved offline, provider or unrestricted mode and there is no network environment override
- **THEN** the wrapper uses that mode instead of its default
- **AND** existing mode-specific readiness and qualification checks still determine whether an application can start

#### Scenario: Empty network override is not replaced

- **WHEN** an operator explicitly sets `PI_CONTAINER_NETWORK` to an empty value for a managed launch whose saved mode is offline or unrestricted
- **THEN** the empty value overrides the saved mode and the wrapper applies its provider default, with setup guidance when the provider settings are missing
- **AND** it does not silently restore the saved mode

#### Scenario: Explicit direct operator workflow

- **WHEN** an operator invokes the wrapper directly with a valid nonempty network mode and its required configuration
- **THEN** it proceeds through existing runtime checks without requiring managed preferences
- **AND** mode selection alone does not authorize maintenance or restricted qualification

#### Scenario: Toolchain command with the saved worktree scope

- **WHEN** setup saved the worktree scope and the operator runs the managed launcher with `--container-toolchain list`, on Linux or through the Windows entry
- **THEN** the toolchain command lists the library and no session starts
- **AND** a session started by the same launcher still mounts the parent of the current directory

### Requirement: Setup without a launch service offers only unrestricted networking

Before asking for the network mode, setup SHALL check, read-only, whether a same-host Unix launch service answers at `CONTAINER_HOST`, the saved endpoint or the default endpoint, and whether a usable systemd user manager could start one. When neither holds, setup SHALL offer only unrestricted networking, explain why and require explicit confirmation.

#### Scenario: Host without systemd user manager or service

- **WHEN** setup runs where no launch service answers and `systemctl --user` is missing or fails, as in a Podman machine distribution on WSL
- **THEN** setup states that offline and provider networking need a same-host service and that none is available or startable
- **AND** it asks for explicit confirmation of unrestricted networking and saves the local engine as the launch endpoint

#### Scenario: Local endpoint leaves CONTAINER_HOST unset

- **WHEN** the saved launch endpoint is the local engine
- **THEN** the smoke check and managed launches run Podman without `CONTAINER_HOST`, and the launcher treats an empty `CONTAINER_HOST` or `CONTAINER_CONNECTION` as unset, because Podman treats a set variable as a remote context even when it is empty

#### Scenario: Confirmation declined

- **WHEN** the user declines unrestricted networking in that situation
- **THEN** setup ends with status 1 without changes and explains how to make a service available: start a same-host Podman service, or set `CONTAINER_HOST` to its Unix endpoint, then rerun setup

#### Scenario: Saved restricted mode without a service

- **WHEN** setup is rerun with saved offline networking and no service is reachable or startable any longer
- **THEN** setup does not propose offline, states that the saved mode cannot be kept, and changes to unrestricted only after explicit confirmation

#### Scenario: Service reachable or startable

- **WHEN** a launch service answers at one of the checked endpoints, or a usable systemd user manager exists
- **THEN** setup offers every mode the profile allows, as before

#### Scenario: Explanation names no runtime directory

- **WHEN** setup explains how to make a service available
- **THEN** the explanation refers to the setup guide and names no socket path derived from `XDG_RUNTIME_DIR`

### Requirement: Restricted modes propose a service endpoint

When the selected workflow needs a same-host Unix service and the saved launch endpoint is the local engine, setup SHALL propose `default` as the launch endpoint instead of the saved value.

#### Scenario: From unrestricted to offline

- **WHEN** a rerun moves an installation that saved unrestricted networking and the local endpoint to offline networking, and the user accepts the proposed endpoint
- **THEN** setup saves the `default` endpoint without refusing the answer first

#### Scenario: Unrestricted rerun

- **WHEN** a rerun keeps unrestricted networking
- **THEN** setup still proposes the saved local endpoint

# Spec Delta

## ADDED Requirements

### Requirement: Verified launch engine before image operations

The wrapper SHALL require a successful complete response reporting rootless `true`, OS `linux`, and ServiceIsRemote `true` or `false` before any image operation. It SHALL reject named connections, TCP/SSH endpoints, implicit remote contexts, and Unix endpoints without an absolute pathname beyond slash characters. No rootful override SHALL be honored.

#### Scenario: Local or explicit same-host Unix service

- **WHEN** a local engine reports `true linux false`, or an explicit same-host absolute Unix endpoint reports `true linux true`
- **THEN** launch verification succeeds

#### Scenario: Unsupported or unverifiable launch

- **WHEN** the engine is rootful, non-Linux, unreachable, incomplete, or selected through a forbidden connection, including `unix:///` or `unix:////`
- **THEN** startup fails before image inspection, building, or session creation even with `PI_ALLOW_ROOTFUL=1` or `0`

### Requirement: Complete launch verification responses

The wrapper SHALL retain query exit failures and complete record boundaries, allowing only the selected format and at most one terminating LF. Launch responses SHALL contain exactly three fields on one record. CR characters, extra fields, extra records, and unexpected boolean values SHALL cause failure.

#### Scenario: Additional or malformed data

- **WHEN** the launch query emits extra blank or nonblank records, a CR, missing data, or an unexpected boolean, or exits nonzero after printing valid-looking data
- **THEN** verification fails before image operations rather than accepting partial data

### Requirement: Leftover delegation opt-in is refused

Exact `PI_CONTAINER_PODMAN=1` SHALL stop every session launch and build-only operation before engine queries or image operations, stating that host Podman delegation was removed and pointing to image toolchains (`--container-toolchain add`). Any other value of `PI_CONTAINER_PODMAN`, and any value of `PI_CONTAINER_PODMAN_SOCKET`, SHALL be ignored.

#### Scenario: Leftover delegation opt-in in any mode

- **WHEN** an operator invokes `pi-container.sh` with `PI_CONTAINER_PODMAN=1` in offline, provider, or unrestricted mode, or with `--container-build`
- **THEN** the launch exits nonzero before any engine call and states that host Podman delegation was removed in favor of image toolchains

#### Scenario: Non-enabling delegation values ignored

- **WHEN** `PI_CONTAINER_PODMAN` is unset, empty, `0`, `false`, or `true`, or `PI_CONTAINER_PODMAN_SOCKET` is set
- **THEN** the launcher ignores those variables and mounts no host Podman socket

## MODIFIED Requirements

### Requirement: Build and shell session modes

`--container-build` with application arguments SHALL rebuild the image, using the layer cache, before starting the requested session. `--container-shell` SHALL start Bash instead of Pi and pass it the remaining arguments in every network mode, without the approval bypass. Build, shell, and ordinary sessions SHALL use the same applicable engine, state, and mount checks; shell mode SHALL retain session cleanup guarantees.

#### Scenario: Forced refresh followed by a shell

- **WHEN** build and shell modes are selected together with `-c "echo ok"`
- **THEN** successful preflights precede a build and an attached Bash session using the caller identity and normal filesystem policy
- **AND** Bash runs `-c` and `echo ok` as two arguments and prints `ok`

### Requirement: Single image variant with coherent freshness

The runtime image SHALL have a single variant without optional image inputs. Image freshness SHALL account for `Containerfile`, `.containerignore`, `.version`, `network/relay.py` and `network/mux.py`, and for no environment selection. `.version` SHALL remain Pi's version source. The Podman client SHALL be part of every image so sessions can talk to their private session container engine. The image SHALL NOT contain Bun.

#### Scenario: Recipe input changes

- **WHEN** an image exists and `Containerfile` or `.version` changes
- **THEN** the wrapper reports a stale image and names `--container-build`

#### Scenario: Former Bun variables have no effect

- **WHEN** a current image exists and `PI_ENABLE_BUN=1` and `PI_BUN_VERSION=bun-v1.2.0` are set
- **THEN** the launch starts without a stale-image stop, a build or a warning about either variable
- **AND** `bun` is not found in the session

#### Scenario: Podman client without delegation

- **WHEN** a session starts with no library images
- **THEN** the `podman` client is present in the image and no host socket is mounted

### Requirement: Verifiable operational documentation

README, SECURITY.md, CONTRIBUTING.md, and wrapper help SHALL describe identity, strict launch-engine checks, session container engine boundaries, state repair, temporary mounts, parent exposure, lifecycle deadlines, and residual-resource limitations consistently. Validation evidence SHALL distinguish synthetic tests, real rootless checks, and unperformed authenticated workflows.

#### Scenario: Validation handoff

- **WHEN** the implementation is declared complete
- **THEN** documentation and test guidance describe the implemented contract, record actual results and unavailable checks, and close `todo.md` items only with corresponding verification evidence.

### Requirement: Build-only image refresh

`--container-build` without application arguments SHALL validate every launch setting, build the runtime image and exit without creating a container. `--container-git-worktree` and `--container-shell` SHALL NOT count as application arguments. It SHALL validate the network mode, maintenance, budgets, lifetime, image name, state and configuration paths, leftover delegation refusal, host tools, the launch engine and the CA selection, and SHALL skip the workspace refusal, state creation, toolchains, cgroup checks and restricted preparation. It SHALL require the exact `PI_CONTAINER_MAINTENANCE=1` and SHALL use the same build arguments and `build-inputs-hash` label as a launch that builds, with no build timeout. With host CA trust enabled, it SHALL pass the selected bundle as the `build-ca` secret, as a launch that builds does.

#### Scenario: Build-only refresh

- **WHEN** `PI_CONTAINER_NETWORK=unrestricted PI_CONTAINER_MAINTENANCE=1 PI_CONTAINER_IMAGE=localhost/pi-container:setup-x pi-container.sh --container-build` runs
- **THEN** the image is built with Pi from `.version` and a matching staleness label, and the wrapper exits 0 without creating a container

#### Scenario: Build-only without maintenance

- **WHEN** `--container-build` is used alone without `PI_CONTAINER_MAINTENANCE=1`
- **THEN** the wrapper exits with status 1 naming the maintenance variable, without image operations

#### Scenario: Build-only with an invalid setting

- **WHEN** `--container-build` is used alone with an invalid budget or a relative `PI_CONTAINER_STATE_DIR`
- **THEN** the wrapper exits with status 1 naming the setting, without image operations

#### Scenario: Build-only refresh with host CA trust

- **WHEN** the build-only refresh runs with `PI_CONTAINER_TRUST_HOST_CA=1` and a selected bundle
- **THEN** the build receives `--secret id=build-ca,src=<bundle>` and the staleness label is unchanged by the secret
- **AND** an invalid bundle selection fails before any image operation

#### Scenario: Build-only refresh without host CA trust

- **WHEN** the build-only refresh runs with host CA trust disabled
- **THEN** the build receives no secret

### Requirement: Common variable names

Wrapper settings SHALL use the `PI_CONTAINER_` prefix, including `PI_CONTAINER_IMAGE`, `PI_CONTAINER_MEMORY_LIMIT`, `PI_CONTAINER_CPU_LIMIT`, `PI_CONTAINER_PIDS_LIMIT`, `PI_CONTAINER_RUN_TIMEOUT`, `PI_CONTAINER_ALLOW_UNSAFE_WORKSPACE`, `PI_CONTAINER_ENV_VARS`, `PI_CONTAINER_READONLY_STATE` and `PI_CONTAINER_GITCONFIG`. Exact `PI_CONTAINER_PODMAN=1` SHALL fail with migration guidance; other values of `PI_CONTAINER_PODMAN`, `PI_CONTAINER_PODMAN_SOCKET`, and earlier names SHALL have no effect and SHALL produce no notice.

#### Scenario: Earlier name alone

- **WHEN** only `PI_MEMORY_LIMIT=2g`, `PI_ENABLE_PODMAN=1`, `PI_NETWORK=host` or `PI_PULL_ALWAYS=1` is set
- **THEN** the launch behaves as if the variable were unset, with no deprecation or migration notice

#### Scenario: Earlier forwarding name

- **WHEN** `PI_ENV_VARS="CUSTOM"` is set and `PI_CONTAINER_ENV_VARS` is not
- **THEN** `CUSTOM` is not forwarded

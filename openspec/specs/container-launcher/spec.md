# container-launcher Specification

## Purpose

Expose container-specific controls while retaining native Pi arguments, image freshness, and the project's established optional tooling.

## Requirements

### Requirement: Side-effect-free wrapper help and native arguments
The wrapper SHALL consume `--container-build`, `--container-shell`, `--container-git-worktree`, `--container-qualify`, the internal `--container-qualify-probe` and `--container-help` without forwarding them to Pi. Wrapper help SHALL work without Podman, valid state, or `.version`, SHALL cause no builds or state creation, and SHALL use the layout of the shared launcher core followed by Pi's agent part. Native `--help` and all other arguments SHALL retain their values and order.

#### Scenario: Help without runtime prerequisites
- **WHEN** `--container-help` is requested with no Podman and a missing version file
- **THEN** help exits successfully, documents modes, variables and boundaries, and does not inspect engines, create state, or build images
- **AND** it lists every common `PI_CONTAINER_*` variable with its default, and then Pi's own variables

#### Scenario: Native Pi invocation
- **WHEN** Pi `--help`, prompts containing spaces, or other native arguments accompany wrapper options
- **THEN** a Pi session receives only the original native argument vector in its original order

#### Scenario: Help describes the network contract
- **WHEN** wrapper help is requested
- **THEN** it names `PI_CONTAINER_NETWORK` with its three values and the provider default, `PI_CONTAINER_MAINTENANCE`, the CA variables and `--container-qualify`
- **AND** it states the residual exfiltration limit of provider mode with each base profile's hosts

### Requirement: Build and shell session modes

`--container-build` with application arguments SHALL rebuild the image, using the layer cache, before starting the requested session. `--container-shell` SHALL start Bash instead of Pi and pass it the remaining arguments in every network mode, without the approval bypass. Build, shell, and ordinary sessions SHALL use the same applicable engine, state, and mount checks; shell mode SHALL retain session cleanup guarantees.

#### Scenario: Forced refresh followed by a shell

- **WHEN** build and shell modes are selected together with `-c "echo ok"`
- **THEN** successful preflights precede a build and an attached Bash session using the caller identity and normal filesystem policy
- **AND** Bash runs `-c` and `echo ok` as two arguments and prints `ok`

### Requirement: Explicit worktree exposure

`--container-git-worktree` SHALL expose exactly the physical workspace's immediate parent at the same absolute path and keep the original physical workspace as workdir. Default sessions SHALL expose only the workspace through their workspace bind. Parent exposure SHALL require the explicit option and remain subject to the sensitive-directory guard.

#### Scenario: Worktree operations

- **WHEN** the caller explicitly selects worktree mode inside a project
- **THEN** Git can create a sibling worktree within the exposed parent while the shell starts inside the original workspace and no higher ancestor is mounted by that option.

### Requirement: Image absence differs from operational failure

Automatic image creation SHALL occur only for image-existence status 1, and every build, automatic or explicit, SHALL require exact `PI_CONTAINER_MAINTENANCE=1`. Other image-existence errors and failed staleness-label inspection SHALL stop startup with actionable diagnostics. A successful inspection with an absent or mismatched hash SHALL stop with status 1 and a message naming `--container-build`, without building or creating a session. Failed builds SHALL prevent session creation.

#### Scenario: Engine or inspection failure

- **WHEN** image existence returns an error other than 1, or label inspection fails
- **THEN** startup fails without attempting an automatic build or session creation.

#### Scenario: Absent or stale image

- **WHEN** the image is absent, or successful label inspection finds a hash that differs from the current build inputs
- **THEN** an absent image is built from the recorded inputs before reserving a session
- **AND** a stale image makes the wrapper exit with status 1 naming `--container-build`, without building or creating a session

#### Scenario: Build without maintenance authorization
- **WHEN** the image is absent or `--container-build` is requested and `PI_CONTAINER_MAINTENANCE` differs from exactly `1`
- **THEN** the wrapper exits nonzero naming the variable, without building, pulling or creating a session

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

### Requirement: Retained runtime and secret controls
The wrapper SHALL retain resource-limit overrides, read-only state, the opt-in read-only gitconfig, the bounded npm cache, and extra variable forwarding by name through `PI_CONTAINER_ENV_VARS`. `EDITOR` and `VISUAL` SHALL be `nano` in every session. Secret values SHALL NOT appear in wrapper-generated argv or diagnostics. Offline and provider modes SHALL forward no host proxy or CA variable. Provider mode SHALL forward only the selected profile's credential, offline none, and unrestricted mode only credentials listed in `PI_CONTAINER_ENV_VARS`.

#### Scenario: Existing options and secret values
- **WHEN** a caller selects custom limits and cache settings in unrestricted mode and forwards a dummy secret using `PI_CONTAINER_ENV_VARS`
- **THEN** the session receives the intended settings and the secret by name, while recorded argv and diagnostics contain the variable name without its secret value and cannot override the selected session connection

#### Scenario: Removed network selection
- **WHEN** the earlier `PI_NETWORK` is set to `none`, `host` or any other value, in any mode
- **THEN** it has no effect and produces no notice; the mode comes from `PI_CONTAINER_NETWORK` or the provider default

#### Scenario: Host editors are not kept
- **WHEN** the host sets `EDITOR=vim` and `VISUAL=code`
- **THEN** the session has `EDITOR=nano` and `VISUAL=nano`

#### Scenario: Restricted forwarding
- **WHEN** offline or provider mode runs with `HTTPS_PROXY`, `no_proxy`, `SSL_CERT_FILE` and the four provider keys set on the host, and the same names listed in `PI_CONTAINER_ENV_VARS`
- **THEN** none of the host proxy or CA values reaches the session, offline forwards no provider key, and provider forwards only the selected profile's key

#### Scenario: Unrestricted credentials need the forwarding list
- **WHEN** an unrestricted session starts with `ANTHROPIC_API_KEY` and `OPENAI_API_KEY` set and only `ANTHROPIC_API_KEY` listed in `PI_CONTAINER_ENV_VARS`
- **THEN** the session receives `ANTHROPIC_API_KEY` by name and no `OPENAI_API_KEY`

### Requirement: Verifiable operational documentation

README, SECURITY.md, CONTRIBUTING.md, and wrapper help SHALL describe identity, strict launch-engine checks, session container engine boundaries, state repair, temporary mounts, parent exposure, lifecycle deadlines, and residual-resource limitations consistently. Validation evidence SHALL distinguish synthetic tests, real rootless checks, and unperformed authenticated workflows.

#### Scenario: Validation handoff

- **WHEN** the implementation is declared complete
- **THEN** documentation and test guidance describe the implemented contract, record actual results and unavailable checks, and close `todo.md` items only with corresponding verification evidence.

### Requirement: Pi has no approval layer to bypass
`PI_CONTAINER_YOLO` SHALL be a validated boolean (`0`, `1`, `true`, `false`, `yes`, `no`, any case, or empty), checked before engine queries as in the other wrappers. Pi runs its tools without approval prompts, so an enabled value SHALL print one stderr notice in a Pi session that it has no effect, a disabled value SHALL be silent, and neither SHALL change the engine arguments. Shell mode and the qualification probe SHALL ignore the variable. Help, README and `AGENTS.md` SHALL state that the container is the only boundary around Pi's tools.

#### Scenario: YOLO variable set
- **WHEN** `PI_CONTAINER_YOLO=1` (or `true` or `YES`) is set for a Pi session
- **THEN** one notice states that Pi has no tool-approval layer and the setting has no effect, and the engine arguments equal those of the same launch without the variable

#### Scenario: YOLO disabled by the managed launcher
- **WHEN** a managed launch exports `PI_CONTAINER_YOLO=0`
- **THEN** no YOLO notice is printed and the engine arguments are unchanged

#### Scenario: Invalid YOLO value
- **WHEN** `PI_CONTAINER_YOLO` is set to another value, such as `2` or `on`
- **THEN** the wrapper exits with status 1 naming the variable and its accepted values, before engine queries or state creation

#### Scenario: Project-file trust is separate
- **WHEN** a reader looks up Pi's `--approve` option in the help or README
- **THEN** it is described as trust in project-local files, not as tool approval or YOLO

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

## ADDED Requirements

### Requirement: Common variable names
Wrapper settings SHALL use the `PI_CONTAINER_` prefix, including `PI_CONTAINER_IMAGE`, `PI_CONTAINER_PODMAN`, `PI_CONTAINER_PODMAN_SOCKET`, `PI_CONTAINER_MEMORY_LIMIT`, `PI_CONTAINER_CPU_LIMIT`, `PI_CONTAINER_PIDS_LIMIT`, `PI_CONTAINER_RUN_TIMEOUT`, `PI_CONTAINER_ALLOW_UNSAFE_WORKSPACE`, `PI_CONTAINER_ENV_VARS`, `PI_CONTAINER_READONLY_STATE` and `PI_CONTAINER_GITCONFIG`. Earlier names SHALL have no effect and SHALL produce no notice.

#### Scenario: Earlier name alone
- **WHEN** only `PI_MEMORY_LIMIT=2g`, `PI_ENABLE_PODMAN=1`, `PI_NETWORK=host` or `PI_PULL_ALWAYS=1` is set
- **THEN** the launch behaves as if the variable were unset, with no deprecation or migration notice

#### Scenario: Earlier forwarding name
- **WHEN** `PI_ENV_VARS="CUSTOM"` is set and `PI_CONTAINER_ENV_VARS` is not
- **THEN** `CUSTOM` is not forwarded

## REMOVED Requirements

### Requirement: Common variable names with deprecated aliases
**Reason**: The project has no release, so the shared core removes legacy names without compatibility hooks (launcher contract U2).
**Migration**: Use the `PI_CONTAINER_*` names in "Common variable names".

### Requirement: Ignored image variables
**Reason**: `PI_PULL_ALWAYS` is a legacy name removed with the aliases (U2); the shared core prints no notice for it.
**Migration**: None; image inputs stay pinned in the recipe.

## MODIFIED Requirements

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
`--container-build` with application arguments SHALL rebuild the image, using the layer cache, before starting the requested session. `--container-shell` SHALL start Bash instead of Pi and pass it the remaining arguments in every network mode, without the approval bypass. Build, shell, and ordinary sessions SHALL use the same applicable engine, state, delegation, and mount checks; shell mode SHALL retain session cleanup guarantees.

#### Scenario: Forced refresh followed by a shell
- **WHEN** build and shell modes are selected together with `-c "echo ok"`
- **THEN** successful preflights precede a build and an attached Bash session using the caller identity and normal filesystem policy
- **AND** Bash runs `-c` and `echo ok` as two arguments and prints `ok`

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
`--container-build` without application arguments SHALL validate every launch setting, build the runtime image and exit without creating a container. `--container-git-worktree` and `--container-shell` SHALL NOT count as application arguments. It SHALL validate the network mode, maintenance, budgets, lifetime, image name, state and configuration paths, delegation settings and socket, host tools, the launch engine and the CA selection, and SHALL skip the workspace refusal, state creation, toolchains, cgroup checks and restricted preparation. It SHALL require the exact `PI_CONTAINER_MAINTENANCE=1` and SHALL use the same build arguments and `build-inputs-hash` label as a launch that builds, with no build timeout. With host CA trust enabled, it SHALL pass the selected bundle as the `build-ca` secret, as a launch that builds does.

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

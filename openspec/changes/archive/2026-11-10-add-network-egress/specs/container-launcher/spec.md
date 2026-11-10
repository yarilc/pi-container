## MODIFIED Requirements

### Requirement: Side-effect-free wrapper help and native arguments

The wrapper SHALL consume `--container-build`, `--container-shell`, `--container-git-worktree`, `--container-qualify`, the internal `--container-qualify-probe` and `--container-help` without forwarding them to Pi. `--wrapper-help` SHALL remain an alias. Wrapper help SHALL work without Podman, valid state, or `.version`, SHALL cause no builds or state creation, and SHALL use the layout shared with the other wrappers. Native `--help` and all other arguments SHALL retain their values and order.

#### Scenario: Help without runtime prerequisites

- **WHEN** either wrapper help option is requested with no Podman and a missing version file
- **THEN** help exits successfully, documents modes, variables and boundaries, and does not inspect engines, create state, or build images.
- **AND** it shows usage, `Container options:`, a lifecycle summary and `Environment:` listing every `PI_CONTAINER_*` variable with its default and the deprecated names.

#### Scenario: Native Pi invocation

- **WHEN** Pi `--help`, prompts containing spaces, or other native arguments accompany wrapper options
- **THEN** a Pi session receives only the original native argument vector in its original order.

#### Scenario: Help describes the network contract
- **WHEN** wrapper help is requested
- **THEN** it names `PI_CONTAINER_NETWORK` with its three values, `PI_CONTAINER_MAINTENANCE`, the CA variables, `--container-qualify` and the removal of `PI_NETWORK`
- **AND** it states the residual exfiltration limit of provider mode

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

### Requirement: Retained runtime and secret controls

The wrapper SHALL retain resource-limit overrides, read-only configuration, the opt-in read-only gitconfig, editor preferences, bounded npm cache, and API/proxy/extra variable forwarding by name. Secret values SHALL not appear in wrapper-generated argv or debug output. A set `PI_NETWORK` SHALL stop the wrapper before engine queries with migration guidance. Offline and provider modes SHALL forward no host proxy or CA variable and only the profile's credential.

#### Scenario: Existing options and secret values

- **WHEN** a caller selects custom limits/cache/editor settings in unrestricted mode and forwards a dummy secret using `PI_ENV_VARS`
- **THEN** the session receives the intended settings and secret, while recorded argv/debug output contain the variable name without its secret value and cannot override the selected session connection.

#### Scenario: Removed network selection
- **WHEN** `PI_NETWORK` is set to `none`, `host` or any other nonempty value, in any mode
- **THEN** the wrapper exits with status 1 before engine queries, naming `PI_CONTAINER_NETWORK` and the matching mode (`offline` for `none`, otherwise `unrestricted`)

#### Scenario: Restricted forwarding
- **WHEN** offline or provider mode runs with `HTTPS_PROXY`, `no_proxy`, `SSL_CERT_FILE` and the four provider keys set on the host, and the same names listed in `PI_ENV_VARS`
- **THEN** none of the host proxy or CA values reaches the session, offline forwards no provider key, and provider forwards only the selected profile's key

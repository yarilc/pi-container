# container-launcher Specification

## Purpose

Expose container-specific controls while retaining native Pi arguments, image freshness, and the project's established optional tooling.

## Requirements

### Requirement: Side-effect-free wrapper help and native arguments

The wrapper SHALL consume `--container-build`, `--container-shell`, `--container-git-worktree`, and `--container-help` without forwarding them to Pi. `--wrapper-help` SHALL remain an alias. Wrapper help SHALL work without Podman, valid state, or `.version`, SHALL cause no builds or state creation, and SHALL use the layout shared with the other wrappers. Native `--help` and all other arguments SHALL retain their values and order.

#### Scenario: Help without runtime prerequisites

- **WHEN** either wrapper help option is requested with no Podman and a missing version file
- **THEN** help exits successfully, documents modes, variables and boundaries, and does not inspect engines, create state, or build images.
- **AND** it shows usage, `Container options:`, a lifecycle summary and `Environment:` listing every `PI_CONTAINER_*` variable with its default and the deprecated names.

#### Scenario: Native Pi invocation

- **WHEN** Pi `--help`, prompts containing spaces, or other native arguments accompany wrapper options
- **THEN** a Pi session receives only the original native argument vector in its original order.

### Requirement: Build and shell session modes

`--container-build` SHALL force image refresh before starting the requested session. `--container-shell` SHALL start Bash instead of Pi and discard native Pi arguments. Build, shell, and ordinary sessions SHALL use the same applicable engine, state, delegation, and mount checks; shell mode SHALL retain session cleanup guarantees.

#### Scenario: Forced refresh followed by a shell

- **WHEN** build and shell modes are selected together
- **THEN** successful preflights precede a forced build and an attached Bash session using the caller identity and normal filesystem policy.

### Requirement: Explicit worktree exposure

`--container-git-worktree` SHALL expose exactly the physical workspace's immediate parent at the same absolute path and keep the original physical workspace as workdir. Default sessions SHALL expose only the workspace through their workspace bind. Parent exposure SHALL require the explicit option and remain subject to the sensitive-directory guard.

#### Scenario: Worktree operations

- **WHEN** the caller explicitly selects worktree mode inside a project
- **THEN** Git can create a sibling worktree within the exposed parent while the shell starts inside the original workspace and no higher ancestor is mounted by that option.

### Requirement: Image absence differs from operational failure

Automatic image creation SHALL occur only for image-existence status 1. Other image-existence errors and failed staleness-label inspection SHALL stop startup with actionable diagnostics. A successful inspection with an absent or mismatched hash SHALL stop with status 1 and a message naming `--container-build`, without building or creating a session. Failed builds SHALL prevent session creation.

#### Scenario: Engine or inspection failure

- **WHEN** image existence returns an error other than 1, or label inspection fails
- **THEN** startup fails without attempting an automatic build or session creation.

#### Scenario: Absent or stale image

- **WHEN** the image is absent, or successful label inspection finds a hash that differs from the current build inputs
- **THEN** an absent image is built from the recorded inputs before reserving a session
- **AND** a stale image makes the wrapper exit with status 1 naming `--container-build`, without building or creating a session

### Requirement: Versioned optional tooling remains coherent

Image freshness SHALL account for `Containerfile`, `.containerignore`, `.version` and Bun selection. `.version` SHALL remain Pi's version source. The Podman client SHALL be part of every image, independent of delegation. Optional Bun SHALL be selected by a nonempty `PI_ENABLE_BUN`, installed at the version recorded in the recipe, and remain independent of Podman delegation.

#### Scenario: Bun version changes

- **WHEN** Bun is enabled and `PI_BUN_VERSION` is set to a different version
- **THEN** the variable is ignored with a warning and the image keeps the Bun version recorded in the recipe

#### Scenario: Bun selection changes

- **WHEN** an image built without Bun exists and `PI_ENABLE_BUN=1` is set
- **THEN** the wrapper reports a stale image and names `--container-build`, and after that build `bun --version` reports the recorded version

#### Scenario: No delegated authority with Bun

- **WHEN** Bun is enabled with Podman delegation disabled
- **THEN** Bun is available without a host socket mount or additional runtime privileges.

### Requirement: Retained runtime and secret controls

The wrapper SHALL retain resource-limit overrides, network selection, read-only configuration, the opt-in read-only gitconfig, editor preferences, bounded npm cache, and API/proxy/extra variable forwarding by name. Secret values SHALL not appear in wrapper-generated argv or debug output. Connection variables SHALL remain governed by the engine specification rather than extra-variable forwarding.

#### Scenario: Existing options and secret values

- **WHEN** a caller selects custom limits/network/cache/editor settings and forwards a dummy secret using `PI_ENV_VARS`
- **THEN** the session receives the intended settings and secret, while recorded argv/debug output contain the variable name without its secret value and cannot override the selected session connection.

### Requirement: Verifiable operational documentation

README, SECURITY.md, CONTRIBUTING.md, and wrapper help SHALL describe identity, strict engine/delegation checks, state repair, temporary mounts, parent exposure, lifecycle deadlines, and residual-resource limitations consistently. Validation evidence SHALL distinguish synthetic tests, real rootless checks, and unperformed authenticated workflows.

#### Scenario: Validation handoff

- **WHEN** the implementation is declared complete
- **THEN** documentation and test guidance describe the implemented contract, record actual results and unavailable checks, and close `todo.md` items only with corresponding verification evidence.

### Requirement: Common variable names with deprecated aliases

Wrapper settings SHALL use the `PI_CONTAINER_` prefix: `PI_CONTAINER_IMAGE`, `PI_CONTAINER_PODMAN`, `PI_CONTAINER_PODMAN_SOCKET`, `PI_CONTAINER_MEMORY_LIMIT`, `PI_CONTAINER_CPU_LIMIT`, `PI_CONTAINER_PIDS_LIMIT`, `PI_CONTAINER_RUN_TIMEOUT` and `PI_CONTAINER_ALLOW_UNSAFE_WORKSPACE`. Each earlier name SHALL remain a deprecated alias that prints one stderr warning naming its replacement and is used only when the new name is unset. Conflicting old and new values SHALL stop before engine queries.

#### Scenario: Alias table

- **WHEN** an earlier name is set
- **THEN** `PI_IMAGE_NAME`, `PI_ENABLE_PODMAN`, `PI_PODMAN_SOCKET`, `PI_MEMORY_LIMIT`, `PI_CPU_LIMIT`, `PI_PIDS_LIMIT`, `PI_RUN_TIMEOUT` and `PI_ALLOW_UNSAFE_PWD` map respectively to the new names above

#### Scenario: Old name alone

- **WHEN** only `PI_MEMORY_LIMIT=2g` is set
- **THEN** stderr contains one deprecation warning naming `PI_CONTAINER_MEMORY_LIMIT` and the session uses 2 GiB

#### Scenario: Conflicting names

- **WHEN** `PI_ENABLE_PODMAN=1` and `PI_CONTAINER_PODMAN=0` are set, or `PI_IMAGE_NAME` and `PI_CONTAINER_IMAGE` differ
- **THEN** the wrapper exits with status 1 naming both variables before any engine query or state creation

#### Scenario: Same value under both names

- **WHEN** an old and a new name are set to equal values, or to values with the same meaning for an exact-`1` switch
- **THEN** the session starts with that value and one deprecation warning

### Requirement: Pi has no approval layer to bypass

The wrapper SHALL NOT offer a YOLO switch, because the pinned Pi runs its tools without approval prompts. Help, README and `AGENTS.md` SHALL state that the container is the only boundary around Pi's tools and that Pi's `--approve` controls trust in project-local files, not tool approval. When `PI_CONTAINER_YOLO` is set, the wrapper SHALL print one stderr warning that it has no effect, and SHALL change nothing else.

#### Scenario: YOLO variable set

- **WHEN** `PI_CONTAINER_YOLO=1` is set
- **THEN** a warning states that Pi has no approval layer, and the engine arguments equal those of the same launch without the variable

### Requirement: Ignored image variables

When `PI_BUN_VERSION` or `PI_PULL_ALWAYS` is set, the wrapper SHALL print one stderr warning that the variable is ignored, because image inputs are pinned in the recipe, and SHALL continue unchanged.

#### Scenario: Ignored variables set

- **WHEN** `PI_BUN_VERSION=bun-v1.2.0` and `PI_PULL_ALWAYS=1` are set
- **THEN** stderr names both variables as ignored and no build argument or pull option depends on them

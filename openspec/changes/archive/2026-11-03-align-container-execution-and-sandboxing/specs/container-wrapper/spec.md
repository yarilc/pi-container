# Spec Delta

## Purpose

Expose container-specific controls while retaining native Pi arguments, image freshness, and the project's established optional tooling.

## ADDED Requirements

### Requirement: Side-effect-free wrapper help and native arguments

The wrapper SHALL consume `--container-build`, `--container-shell`, `--container-git-worktree`, and `--container-help` without forwarding them to Pi. `--wrapper-help` SHALL remain an alias. Wrapper help SHALL work without Podman, valid state, or `.version` and SHALL cause no builds or state creation. Native `--help` and all other arguments SHALL retain their values and order.

#### Scenario: Help without runtime prerequisites

- **WHEN** either wrapper help option is requested with no Podman and a missing version file
- **THEN** help exits successfully, documents modes and boundaries, and does not inspect engines, create state, or build images.

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

Automatic image creation SHALL occur only for image-existence status 1. Other image-existence errors and failed staleness-label inspection SHALL stop startup with actionable diagnostics. A successful inspection with an absent or mismatched hash SHALL trigger rebuilding. Failed builds SHALL prevent session creation.

#### Scenario: Engine or inspection failure

- **WHEN** image existence returns an error other than 1, or label inspection fails
- **THEN** startup fails without attempting an automatic build or session creation.

#### Scenario: Absent or stale image

- **WHEN** the image is absent or successful label inspection finds outdated build inputs
- **THEN** the wrapper builds using the selected Pi version and tooling inputs before reserving a session.

### Requirement: Versioned optional tooling remains coherent

Image freshness SHALL account for Containerfile, build-context policy, `.version`, exact Podman opt-in, Bun selection, and the selected Bun version. `.version` SHALL remain Pi's version source. Optional Bun behavior SHALL remain independent of Podman delegation. The build context SHALL remain default-deny and exclude credentials and workspace content.

#### Scenario: Bun version changes

- **WHEN** Bun is enabled and `PI_BUN_VERSION` changes while other build inputs remain unchanged
- **THEN** stale-image detection triggers a build with the selected Bun version rather than reusing the previous image.

#### Scenario: No delegated authority with Bun

- **WHEN** Bun is enabled with Podman delegation disabled
- **THEN** Bun is available without a host socket mount or additional runtime privileges.

### Requirement: Retained runtime and secret controls

The wrapper SHALL retain resource-limit overrides, network selection, read-only configuration, optional read-only gitconfig, editor preferences, bounded npm cache, and API/proxy/extra variable forwarding by name. Secret values SHALL not appear in wrapper-generated argv or debug output. Connection variables SHALL remain governed by the engine specification rather than extra-variable forwarding.

#### Scenario: Existing options and secret values

- **WHEN** a caller selects custom limits/network/cache/editor settings and forwards a dummy secret using `PI_ENV_VARS`
- **THEN** the session receives the intended settings and secret, while recorded argv/debug output contain the variable name without its secret value and cannot override the selected session connection.

### Requirement: Verifiable operational documentation

README, SECURITY.md, CONTRIBUTING.md, and wrapper help SHALL describe identity, strict engine/delegation checks, state repair, temporary mounts, parent exposure, lifecycle deadlines, and residual-resource limitations consistently. Validation evidence SHALL distinguish synthetic tests, real rootless checks, and unperformed authenticated workflows.

#### Scenario: Validation handoff

- **WHEN** the implementation is declared complete
- **THEN** documentation and test guidance describe the implemented contract, record actual results and unavailable checks, and close `todo.md` items only with corresponding verification evidence.

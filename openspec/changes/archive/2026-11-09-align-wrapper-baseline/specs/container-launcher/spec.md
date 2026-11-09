# Spec Delta

## ADDED Requirements

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

## MODIFIED Requirements

### Requirement: Side-effect-free wrapper help and native arguments

The wrapper SHALL consume `--container-build`, `--container-shell`, `--container-git-worktree`, and `--container-help` without forwarding them to Pi. `--wrapper-help` SHALL remain an alias. Wrapper help SHALL work without Podman, valid state, or `.version`, SHALL cause no builds or state creation, and SHALL use the layout shared with the other wrappers. Native `--help` and all other arguments SHALL retain their values and order.

#### Scenario: Help without runtime prerequisites

- **WHEN** either wrapper help option is requested with no Podman and a missing version file
- **THEN** help exits successfully, documents modes, variables and boundaries, and does not inspect engines, create state, or build images.
- **AND** it shows usage, `Container options:`, a lifecycle summary and `Environment:` listing every `PI_CONTAINER_*` variable with its default and the deprecated names.

#### Scenario: Native Pi invocation

- **WHEN** Pi `--help`, prompts containing spaces, or other native arguments accompany wrapper options
- **THEN** a Pi session receives only the original native argument vector in its original order.

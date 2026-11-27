# Spec Delta

## ADDED Requirements

### Requirement: Separate runtime and session engine images

Pi's runtime image (`localhost/pi-container:latest`, built from `Containerfile`) and its session container engine image (`localhost/pi-container-engine:latest`, built from `launcher/engine/Containerfile` by guided setup) SHALL remain separate images with distinct inputs and lifecycles. Runtime builds (`--container-build`) SHALL remain independent of the session engine image.

#### Scenario: Derived engine image name

- **WHEN** guided setup prepares the session container engine for Pi's profile (`images.agent = localhost/pi-container`)
- **THEN** setup builds and records `localhost/pi-container-engine:latest` without modifying `localhost/pi-container:latest`

## MODIFIED Requirements

### Requirement: Image with the common toolset

The image SHALL be built on `docker.io/library/node:22-bookworm-slim` referenced by digest and SHALL provide Pi, OpenSpec, the Podman client and the common toolset shared with the other wrappers, without a caller identity. Its entrypoint SHALL run Pi.

#### Scenario: Common toolset

- **WHEN** the recipe is inspected
- **THEN** it installs `bash`, `bubblewrap`, `bzip2`, `ca-certificates`, `coreutils`, `curl`, `diffutils`, `file`, `findutils`, `gawk`, `git`, `grep`, `jq`, `less`, `nano`, `patch`, `podman`, `procps`, `python3`, `ripgrep`, `sed`, `tar`, `unzip`, `util-linux`, `xz-utils` and `zip`

#### Scenario: Tool inventory in a session

- **WHEN** a session runs as the mapped non-root user
- **THEN** each listed tool, `pi`, `openspec` and `podman` are available, with or without a session container engine

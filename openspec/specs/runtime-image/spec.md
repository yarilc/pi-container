# runtime-image Specification

## Purpose

Provide a reproducible Pi runtime image with the common toolset, pinned inputs, an explicit update procedure and a default-deny build context.

## Requirements

### Requirement: Image with the common toolset

The image SHALL be built on `docker.io/library/node:22-bookworm-slim` referenced by digest and SHALL provide Pi, OpenSpec, the Podman client and the common toolset shared with the other wrappers, without a caller identity. Its entrypoint SHALL run Pi.

#### Scenario: Common toolset

- **WHEN** the recipe is inspected
- **THEN** it installs `bash`, `bubblewrap`, `bzip2`, `ca-certificates`, `coreutils`, `curl`, `diffutils`, `file`, `findutils`, `gawk`, `git`, `grep`, `jq`, `less`, `nano`, `patch`, `podman`, `procps`, `python3`, `ripgrep`, `sed`, `tar`, `unzip`, `util-linux`, `xz-utils` and `zip`

#### Scenario: Tool inventory in a session

- **WHEN** a session runs as the mapped non-root user
- **THEN** each listed tool, `pi`, `openspec` and `podman` are available, with or without a session container engine

### Requirement: Runtime image inputs are pinned

The recipe SHALL install the exact Pi version recorded in `.version` and an exact `@fission-ai/openspec` version, both recorded in the repository and installed from the npm registry. It SHALL reference the base image by digest. No floating tag, `latest` specifier, version range or remote install script SHALL select an image input. Sessions SHALL NOT change installed versions.

#### Scenario: Build uses recorded versions

- **WHEN** the image is built with `--container-build`
- **THEN** `pi --version` and `openspec --version` report exactly the recorded versions
- **AND** `bun` is not installed

#### Scenario: Unpinned input is rejected by tests

- **WHEN** the recipe uses a base without digest, an npm package without exact version or with `@latest`, a remote install script piped to a shell, or misses a toolset package
- **THEN** the credential-free unit suite fails

### Requirement: Version updates follow explicit maintenance

Documentation SHALL describe the update procedure:

- record the new Pi version in `.version`, or the new OpenSpec version or base digest in the recipe;
- rebuild explicitly with `--container-build`;
- rerun the credential-free and real-engine checks;
- record the tested versions with the date in the validation record.

#### Scenario: Maintainer updates Pi

- **WHEN** a maintainer follows the documented procedure to move to a new Pi release
- **THEN** the procedure requires the recorded version, an explicit rebuild, a rerun of the checks and a dated validation entry

### Requirement: Default-deny build context

The effective Podman build context MUST allow only the root `Containerfile`, `.containerignore` and `.version`, plus `network/relay.py` and `network/mux.py`, which the image copies to `/opt/sandbox-egress/`. The image SHALL NOT contain the guard. Unknown files, nested lookalikes, repository metadata, local state and credentials MUST be excluded.

#### Scenario: Probe context contents

- **WHEN** a disposable build context includes unknown root files, nested recipe names and synthetic credentials
- **THEN** a build that copies the whole context sees only the five allowed files

### Requirement: Pinned CLI matches the tested policy version
The Pi version recorded in `.version` SHALL equal the CLI version recorded in the protected network policy's tested metadata. A version change SHALL update both in the same change and record the tested version in the validation record.

#### Scenario: Versions diverge
- **WHEN** the pinned Pi version differs from the policy's tested CLI field
- **THEN** the credential-free unit suite fails and names both versions

### Requirement: Restricted sessions use an immutable runtime image identity
Offline and provider launches SHALL resolve the selected runtime image to its immutable image ID before preparation and SHALL create the agent container from that ID. An unresolvable or malformed identity SHALL stop startup. Unrestricted launches MAY keep using the image name.

#### Scenario: Image tag moves during a launch
- **WHEN** the selected tag is rebuilt after a restricted launch has resolved its identity
- **THEN** the session and its qualification check use the resolved ID, not the moved tag

#### Scenario: Identity cannot be resolved
- **WHEN** image inspection fails or returns a malformed ID in a restricted mode
- **THEN** startup fails before agent execution

### Requirement: Proxy image acquisition requires maintenance and a digest
Provider mode SHALL use the immutable egress proxy image named by `PI_CONTAINER_EGRESS_IMAGE`. An absent proxy image SHALL be pulled only with exact `PI_CONTAINER_MAINTENANCE=1` and only when the reference is pinned by digest. Otherwise startup SHALL fail with maintenance guidance before agent execution.

#### Scenario: Proxy image absent without authorization
- **WHEN** the proxy image is absent and maintenance is not authorized or the reference has no digest
- **THEN** startup fails without pulling and names the required operator action

### Requirement: Image package sources use verified HTTPS
The runtime image recipe SHALL fetch Debian packages only from `https://` sources, with TLS peer verification enabled for every fetch. The build SHALL NOT require outbound port 80 and SHALL NOT fall back to plain HTTP. The built image SHALL keep HTTPS Debian sources.

#### Scenario: Host blocks outbound port 80
- **WHEN** the runtime image is built under maintenance authorization on a host where outbound TCP 80 is blocked and HTTPS to the Debian, npm and container registries is reachable
- **THEN** the build completes and the image reports the recorded Pi and OpenSpec versions

#### Scenario: Built image keeps HTTPS sources
- **WHEN** a user inspects the Debian source configuration inside a container started from the runtime image
- **THEN** every Debian source URI uses `https://`

#### Scenario: Insecure transport is rejected by tests
- **WHEN** the recipe uses a plain-HTTP Debian source or disables apt TLS peer or host verification
- **THEN** the credential-free unit suite fails and names the violation

### Requirement: Package-source trust bootstrap uses pinned inputs and opt-in host CA
Before Debian `ca-certificates` is installed, the recipe SHALL verify HTTPS package fetches with roots from the digest-pinned base image, plus the operator's selected CA bundle only when host CA trust is enabled. It SHALL add no image, digest or download input. It SHALL remove the bootstrap bundle in the same build step, and the built image SHALL contain Debian `ca-certificates`.

#### Scenario: No bootstrap residue
- **WHEN** a user lists the bootstrap bundle path inside a container started from the runtime image
- **THEN** the file does not exist
- **AND** the Debian `ca-certificates` package is installed

#### Scenario: Host CA trust disabled
- **WHEN** setup or `--container-build` builds the runtime image with host CA trust disabled
- **THEN** the build receives no host CA bundle and verifies only against the base image's roots

#### Scenario: TLS-intercepting network with host CA trust
- **WHEN** setup or `--container-build` builds the runtime image with host CA trust enabled and a CA bundle that includes the network's interception CA
- **THEN** the build receives that bundle only as a build secret, the HTTPS package fetches verify against it, and the build completes

#### Scenario: Host CA bundle is not persisted
- **WHEN** a user searches a container started from an image built with host CA trust enabled
- **THEN** neither the bootstrap bundle nor the build secret is present in the image

### Requirement: Image working directory needs no engine creation
The runtime image SHALL either declare no `WORKDIR` or declare one that an earlier build step creates in an image layer, so that a container started without `--workdir` never makes the engine create or chown a working directory at start.

#### Scenario: Recipe without a working directory
- **WHEN** a qualification gate container starts from the runtime image without `--workdir`
- **THEN** it uses `/` and the engine performs no working-directory creation or ownership change

#### Scenario: Recipe regression is rejected by tests
- **WHEN** the recipe declares a `WORKDIR` that no earlier build step creates
- **THEN** the credential-free unit suite fails

### Requirement: Separate runtime and session engine images

Pi's runtime image (`localhost/pi-container:latest`, built from `Containerfile`) and its session container engine image (`localhost/pi-container-engine:latest`, built from `launcher/engine/Containerfile` by guided setup) SHALL remain separate images with distinct inputs and lifecycles. Runtime builds (`--container-build`) SHALL remain independent of the session engine image.

#### Scenario: Derived engine image name

- **WHEN** guided setup prepares the session container engine for Pi's profile (`images.agent = localhost/pi-container`)
- **THEN** setup builds and records `localhost/pi-container-engine:latest` without modifying `localhost/pi-container:latest`

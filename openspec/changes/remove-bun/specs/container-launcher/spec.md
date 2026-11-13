## ADDED Requirements

### Requirement: Single image variant with coherent freshness
The runtime image SHALL have a single variant without optional image inputs. Image freshness SHALL account for `Containerfile`, `.containerignore`, `.version`, `network/relay.py` and `network/mux.py`, and for no environment selection. `.version` SHALL remain Pi's version source. The Podman client SHALL be part of every image, independent of delegation. The image SHALL NOT contain Bun.

#### Scenario: Recipe input changes
- **WHEN** an image exists and `Containerfile` or `.version` changes
- **THEN** the wrapper reports a stale image and names `--container-build`

#### Scenario: Former Bun variables have no effect
- **WHEN** a current image exists and `PI_ENABLE_BUN=1` and `PI_BUN_VERSION=bun-v1.2.0` are set
- **THEN** the launch starts without a stale-image stop, a build or a warning about either variable
- **AND** `bun` is not found in the session

#### Scenario: Podman client without delegation
- **WHEN** a session starts with Podman delegation disabled
- **THEN** the `podman` client is present in the image and no host socket is mounted

## MODIFIED Requirements

### Requirement: Ignored image variables

When `PI_PULL_ALWAYS` is set, the wrapper SHALL print one stderr warning that the variable is ignored, because image inputs are pinned in the recipe, and SHALL continue unchanged.

#### Scenario: Ignored variables set

- **WHEN** `PI_PULL_ALWAYS=1` is set
- **THEN** stderr names the variable as ignored and no pull option depends on it

### Requirement: Build-only image refresh
`--container-build` used alone SHALL build the runtime image and exit without creating a container. It SHALL require the exact `PI_CONTAINER_MAINTENANCE=1`, an explicit network mode, a verified engine and the selected image name, and SHALL use the same build arguments and `build-inputs-hash` label as a launch that builds. With host CA trust enabled, the build-only refresh SHALL resolve the selected bundle before building and pass it as the `build-ca` secret, as a launch that builds does. Combined with a launch, it SHALL keep refreshing the image before starting the session.

#### Scenario: Build-only refresh
- **WHEN** `PI_CONTAINER_NETWORK=unrestricted PI_CONTAINER_MAINTENANCE=1 PI_CONTAINER_IMAGE=localhost/pi-container:setup-x pi-container.sh --container-build` runs
- **THEN** the image is built with Pi from `.version` and a matching staleness label, and the wrapper exits 0 without creating a container

#### Scenario: Build-only without maintenance
- **WHEN** `--container-build` is used alone without `PI_CONTAINER_MAINTENANCE=1`
- **THEN** the wrapper exits with status 1 naming the maintenance variable, without image operations

#### Scenario: Build-only refresh with host CA trust
- **WHEN** the build-only refresh runs with `PI_CONTAINER_TRUST_HOST_CA=1` and a selected bundle
- **THEN** the build receives `--secret id=build-ca,src=<bundle>` and the staleness label is unchanged by the secret
- **AND** an invalid bundle selection fails before any image operation

#### Scenario: Build-only refresh without host CA trust
- **WHEN** the build-only refresh runs with host CA trust disabled
- **THEN** the build receives no secret

## REMOVED Requirements

### Requirement: Versioned optional tooling remains coherent
**Reason**: Bun, its only optional input, is removed. Setup never selected it, and qualification could not accept an image built with it.
**Migration**: Replaced by "Single image variant with coherent freshness". Unset `PI_ENABLE_BUN` and `PI_BUN_VERSION`, and rerun `--container-setup`. Projects that need Bun run it outside the sandbox.

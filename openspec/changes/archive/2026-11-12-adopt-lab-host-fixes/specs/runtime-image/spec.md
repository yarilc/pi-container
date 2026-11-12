# Spec Delta

## ADDED Requirements

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

# Spec Delta

## MODIFIED Requirements

### Requirement: Build-only image refresh
`--container-build` used alone SHALL build the runtime image and exit without creating a container. It SHALL require the exact `PI_CONTAINER_MAINTENANCE=1`, an explicit network mode, a verified engine and the selected image name, and SHALL use the same build arguments, Bun selection and `build-inputs-hash` label as a launch that builds. With host CA trust enabled, the build-only refresh SHALL resolve the selected bundle before building and pass it as the `build-ca` secret, as a launch that builds does. Combined with a launch, it SHALL keep refreshing the image before starting the session.

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

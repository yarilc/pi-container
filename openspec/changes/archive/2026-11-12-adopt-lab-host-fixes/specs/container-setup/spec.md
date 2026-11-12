# Spec Delta

## MODIFIED Requirements

### Requirement: Saved budgets govern managed launches and verification
The managed launcher SHALL supply the saved budgets and lifetime through `PI_CONTAINER_MEMORY_LIMIT`, `PI_CONTAINER_CPU_LIMIT`, `PI_CONTAINER_PIDS_LIMIT` and `PI_CONTAINER_RUN_TIMEOUT` when these are absent from the launch environment. An explicitly present variable SHALL take precedence. Setup smoke and qualification SHALL use the saved values for every budget the engine can enforce.

#### Scenario: Managed launch uses saved budgets
- **WHEN** the user launches through the managed command with no budget variables exported
- **THEN** the agent container receives the saved budgets and lifetime
- **AND** a restricted launch matches the qualification report produced by setup

#### Scenario: Explicit override differs from qualified values
- **WHEN** the user exports `PI_CONTAINER_MEMORY_LIMIT=16g` for a restricted managed launch qualified with `4g`
- **THEN** the override is used and the qualification check stops the launch with requalification guidance

#### Scenario: Smoke verifies saved values
- **WHEN** setup runs its installed smoke check
- **THEN** the smoke compares the effective cgroup limits of every enforced budget with the saved budgets, not with ambient environment values
- **AND** it requires every unenforced budget to be absent

#### Scenario: Setup plan names unenforced budgets
- **WHEN** setup runs on an engine that does not report the `cpu` controller
- **THEN** the setup plan lists the CPU budget as not enforced, with the missing controller, and setup continues without an extra question

### Requirement: Runtime image built through the Pi wrapper
Because the profile declares `install.runtime_build: "wrapper"`, setup SHALL build a new runtime image by running the installed release's `pi-container.sh --container-build` alone, under maintenance authorization and with the candidate image tag, then inspect the candidate's immutable identity. The build SHALL use the same build arguments and `build-inputs-hash` label as a launch, without Bun, and start no session. A reused runtime image SHALL keep its labels. When host CA trust is enabled, setup SHALL pass the trust selection and the selected bundle to that build, and the wrapper SHALL give the bundle to its runtime build only as the non-persisted `build-ca` secret.

#### Scenario: Fresh runtime build
- **WHEN** approved setup has no reusable runtime image
- **THEN** the wrapper builds the candidate tag with Pi from `.version` and a `build-inputs-hash` label that matches the installed inputs
- **AND** the managed launcher and the smoke check accept the image without a staleness stop

#### Scenario: Build failure
- **WHEN** the wrapper build fails or the candidate tag cannot be inspected afterwards
- **THEN** setup reports the runtime build stage and leaves the last working installation selected

#### Scenario: Stale reusable image
- **WHEN** the reusable runtime image carries a staleness label that does not match the installed inputs
- **THEN** the smoke check stops with the stale-image message instead of declaring the sandbox ready, and a rerun with refresh rebuilds it through the wrapper

#### Scenario: Bun is not selected by setup
- **WHEN** a managed launch sets `PI_ENABLE_BUN`
- **THEN** the setup-built image is stale for that selection and the launch stops until an explicit maintenance rebuild

#### Scenario: Wrapper-built runtime with host CA trust
- **WHEN** setup prepares the runtime image with host CA trust enabled
- **THEN** the wrapper's build receives the selected bundle as the `build-ca` secret, and the built image contains neither the bundle nor its temporary copy

#### Scenario: Wrapper-built runtime without host CA trust
- **WHEN** setup prepares the runtime image with host CA trust disabled
- **THEN** the wrapper's build receives no build secret and no host CA bundle

## ADDED Requirements

### Requirement: Host CA trust covers setup package fetches
When host CA trust is enabled, setup SHALL give the selected CA bundle to the runtime image and guard toolchain builds only as a non-persisted build secret, so their HTTPS package fetches verify on TLS-intercepting networks. Without host CA trust, setup SHALL pass no host CA to any build. The proxy build SHALL never receive it.

#### Scenario: Toolchain build on a TLS-intercepting network
- **WHEN** setup prepares the guard toolchain with host CA trust enabled and a bundle containing the interception CA
- **THEN** the toolchain package fetches verify against that bundle and the build completes
- **AND** the toolchain image contains neither the bundle nor its temporary copy

#### Scenario: Host CA trust disabled
- **WHEN** setup prepares images with host CA trust disabled
- **THEN** no build receives a host CA bundle, and the toolchain build verifies only against the base image's certificates

## MODIFIED Requirements

### Requirement: Runtime image built through the Pi wrapper
Because the profile declares `install.runtime_build: "wrapper"`, setup SHALL build a new runtime image by running the installed release's `pi-container.sh --container-build` alone, under maintenance authorization and with the candidate image tag, then inspect the candidate's immutable identity. The build SHALL use the same build arguments and `build-inputs-hash` label as a launch and start no session. A reused runtime image SHALL keep its labels. When host CA trust is enabled, setup SHALL pass the trust selection and the selected bundle to that build, and the wrapper SHALL give the bundle to its runtime build only as the non-persisted `build-ca` secret.

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
- **WHEN** setup runs, or a managed launch starts, with `PI_ENABLE_BUN` set in the operator's environment
- **THEN** the setup-built image matches the launch's inputs, so neither setup nor the launch stops as stale
- **AND** the image contains no Bun

#### Scenario: Wrapper-built runtime with host CA trust
- **WHEN** setup prepares the runtime image with host CA trust enabled
- **THEN** the wrapper's build receives the selected bundle as the `build-ca` secret, and the built image contains neither the bundle nor its temporary copy

#### Scenario: Wrapper-built runtime without host CA trust
- **WHEN** setup prepares the runtime image with host CA trust disabled
- **THEN** the wrapper's build receives no build secret and no host CA bundle

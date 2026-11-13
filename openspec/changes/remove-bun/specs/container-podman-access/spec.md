## MODIFIED Requirements

### Requirement: Exact delegation opt-in

Host service delegation and conditional Podman client installation SHALL be enabled only by exact `PI_CONTAINER_PODMAN=1`, or by the deprecated `PI_ENABLE_PODMAN=1` when the new name is unset. Disabled delegation SHALL omit the socket bind and explicitly remove session `CONTAINER_HOST`, including requests through `PI_ENV_VARS`. Native Pi permissions SHALL remain independent.

#### Scenario: Non-enabling values

- **WHEN** `PI_CONTAINER_PODMAN` is unset, empty, `0`, `false`, `true`, `yes`, or any value other than `1`, and no enabling alias applies
- **THEN** no delegated-service query or socket mount occurs, `INSTALL_PODMAN=0`, and session `CONTAINER_HOST` is absent even if forwarded by name.

#### Scenario: Enabled authority cannot be verified

- **WHEN** delegation is enabled and selected socket verification fails
- **THEN** startup fails before image operations without silently degrading to an undelegated session or starting a host service.

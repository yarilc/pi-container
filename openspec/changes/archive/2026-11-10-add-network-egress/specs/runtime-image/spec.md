## ADDED Requirements

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

## MODIFIED Requirements

### Requirement: Default-deny build context

The effective Podman build context MUST allow only the root `Containerfile`, `.containerignore` and `.version`, plus `network/relay.py` and `network/mux.py`, which the image copies to `/opt/sandbox-egress/`. The image SHALL NOT contain the guard. Unknown files, nested lookalikes, repository metadata, local state and credentials MUST be excluded.

#### Scenario: Probe context contents

- **WHEN** a disposable build context includes unknown root files, nested recipe names and synthetic credentials
- **THEN** a build that copies the whole context sees only the five allowed files

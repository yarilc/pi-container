# Spec Delta

## MODIFIED Requirements

### Requirement: Agent-neutral shared sandbox components
The shared `network/` and `setup/` components and shared tests, including the compiled guard, SHALL contain no agent identifiers and SHALL stay byte-identical to the reference copies in `sandbox-container`, checked by the unchanged `tests/test_alignment.py` and the per-agent SHA-256 manifest. In-container paths, the guard name and the multiplex protocol marker SHALL be agent-neutral. Host-visible images, labels, variables and installation paths SHALL come from the profile.

#### Scenario: Shared component contains an agent identifier
- **WHEN** a shared network or setup file contains an identifier declared by the profile outside the documented allow-list
- **THEN** the credential-free alignment check fails

#### Scenario: Shared component differs from the reference
- **WHEN** a copied shared file differs from its SHA-256 recorded for the reference tag, or `diff -r` against a sibling `sandbox-container` checkout at that tag reports a difference
- **THEN** the credential-free alignment check fails

#### Scenario: Two wrappers on the same host
- **WHEN** Pi and another wrapper run restricted sessions or qualification concurrently
- **THEN** each creates, inspects and cleans up only resources carrying its own labels and image names

### Requirement: Evidence and common contract documentation
Documentation SHALL map N01–N14 and C01–C14 to implementation and acceptance, publish the mode and profile contract and the five-wrapper parity table, and date and version the endpoint inventories. `docs/validation.md` SHALL separate synthetic enforcement, real-rootless bypass checks and operator-run authenticated checks. Untested checks SHALL be recorded as unavailable, and automated tests SHALL NOT use real credentials.

#### Scenario: Provider profile readiness
- **WHEN** a profile is declared verified for an Pi version
- **THEN** operator-run evidence covers authenticated model requests, streaming, long-lived requests, supported WebSockets, the interactive TUI, CA behavior and shell mode
- **AND** credential-free tests separately cover DNS/UDP/IPv6, direct IPs and ports, deceptive hosts, redirects, host/LAN/metadata, administration, concurrency, delegation rejection, failure closure and cleanup

#### Scenario: Authenticated check unavailable
- **WHEN** a real API key or account check has not been run by the operator
- **THEN** it is recorded as unavailable and no provider verification is claimed, while mandatory enforcement tests are not waived

#### Scenario: User reviews limits
- **WHEN** a user reads the network documentation
- **THEN** it explains that allowed services can receive session data, provider-hosted tools are outside local filtering, and runtime filtering does not constrain host-side image pulls or builds

#### Scenario: Parity table
- **WHEN** a reader compares the five wrappers
- **THEN** `docs/network-contract.md` here, in `sandbox-container`, `codex-container` and `opencode-container` show the same Pi row, with authenticated compatibility recorded as pending until the operator checks run

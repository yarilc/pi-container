# Spec Delta

## ADDED Requirements

### Requirement: Ignored image variables

When `PI_BUN_VERSION` or `PI_PULL_ALWAYS` is set, the wrapper SHALL print one stderr warning that the variable is ignored, because image inputs are pinned in the recipe, and SHALL continue unchanged.

#### Scenario: Ignored variables set

- **WHEN** `PI_BUN_VERSION=bun-v1.2.0` and `PI_PULL_ALWAYS=1` are set
- **THEN** stderr names both variables as ignored and no build argument or pull option depends on them

## MODIFIED Requirements

### Requirement: Image absence differs from operational failure

Automatic image creation SHALL occur only for image-existence status 1. Other image-existence errors and failed staleness-label inspection SHALL stop startup with actionable diagnostics. A successful inspection with an absent or mismatched hash SHALL stop with status 1 and a message naming `--container-build`, without building or creating a session. Failed builds SHALL prevent session creation.

#### Scenario: Engine or inspection failure

- **WHEN** image existence returns an error other than 1, or label inspection fails
- **THEN** startup fails without attempting an automatic build or session creation.

#### Scenario: Absent or stale image

- **WHEN** the image is absent, or successful label inspection finds a hash that differs from the current build inputs
- **THEN** an absent image is built from the recorded inputs before reserving a session
- **AND** a stale image makes the wrapper exit with status 1 naming `--container-build`, without building or creating a session

### Requirement: Versioned optional tooling remains coherent

Image freshness SHALL account for `Containerfile`, `.containerignore`, `.version` and Bun selection. `.version` SHALL remain Pi's version source. The Podman client SHALL be part of every image, independent of delegation. Optional Bun SHALL be selected by a nonempty `PI_ENABLE_BUN`, installed at the version recorded in the recipe, and remain independent of Podman delegation.

#### Scenario: Bun version changes

- **WHEN** Bun is enabled and `PI_BUN_VERSION` is set to a different version
- **THEN** the variable is ignored with a warning and the image keeps the Bun version recorded in the recipe

#### Scenario: Bun selection changes

- **WHEN** an image built without Bun exists and `PI_ENABLE_BUN=1` is set
- **THEN** the wrapper reports a stale image and names `--container-build`, and after that build `bun --version` reports the recorded version

#### Scenario: No delegated authority with Bun

- **WHEN** Bun is enabled with Podman delegation disabled
- **THEN** Bun is available without a host socket mount or additional runtime privileges.

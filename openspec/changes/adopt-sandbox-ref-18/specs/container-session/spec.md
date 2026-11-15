# Spec Delta

## ADDED Requirements

### Requirement: Name collisions are confirmed by ownership
When container creation fails without returning an ID and a container with the candidate name exists, the wrapper SHALL treat it as another session's container only when its session ownership label differs from this session's token. A container carrying this session's label SHALL be reconciled and removed as this session's own, never skipped.

#### Scenario: Another session holds the name
- **WHEN** creation fails, no ID was returned, and the existing container with that name carries another session's label
- **THEN** the wrapper retries the next numeric name without touching that container

#### Scenario: The engine created this session's container
- **WHEN** creation fails without returning an ID, and the container with that name carries this session's label
- **THEN** the wrapper reports the original creation failure, does not retry, and removes that container during bounded cleanup

### Requirement: Interrupted creation is recovered by ownership label
When creation is interrupted or fails and no valid ID was published, cleanup SHALL look up containers carrying this session's ownership label, within the shutdown budget, and remove the one it confirms as owned. It SHALL report unresolved creation only when that lookup fails or finds no confirmed owned container.

#### Scenario: Engine created the container before the client was cancelled
- **WHEN** a handled signal interrupts creation, the client publishes no ID, and the engine has created this session's container
- **THEN** cleanup finds it by the session label, confirms the label, removes it, and the wrapper returns the interruption status

#### Scenario: Nothing was created
- **WHEN** creation is interrupted and no container carries this session's label
- **THEN** the wrapper removes nothing and returns the interruption status

#### Scenario: Lookup unavailable
- **WHEN** the label lookup fails or times out
- **THEN** the wrapper reports that creation is unresolved and that engine inspection is required, without removing any container

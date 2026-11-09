# Spec Delta

## MODIFIED Requirements

### Requirement: Retained runtime and secret controls

The wrapper SHALL retain resource-limit overrides, network selection, read-only configuration, the opt-in read-only gitconfig, editor preferences, bounded npm cache, and API/proxy/extra variable forwarding by name. Secret values SHALL not appear in wrapper-generated argv or debug output. Connection variables SHALL remain governed by the engine specification rather than extra-variable forwarding.

#### Scenario: Existing options and secret values

- **WHEN** a caller selects custom limits/network/cache/editor settings and forwards a dummy secret using `PI_ENV_VARS`
- **THEN** the session receives the intended settings and secret, while recorded argv/debug output contain the variable name without its secret value and cannot override the selected session connection.

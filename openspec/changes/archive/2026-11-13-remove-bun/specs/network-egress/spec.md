## MODIFIED Requirements

### Requirement: Pi tools and extensions under the outer boundary
Pi's interactive TUI, its tools, extensions and skills SHALL run under the guard. Their communication SHALL be limited to own-loopback TCP, pipes and connected socket pairs. A component needing a named Unix socket, a host service or an unapproved endpoint SHALL fail with documented guidance; the guard SHALL NOT be weakened for it. Pi has no tool-approval layer, so guard and proxy are the only enforcement.

#### Scenario: Interactive session in a restricted mode
- **WHEN** the Pi TUI starts in a PTY in offline or provider mode and quits
- **THEN** the interface renders and exits cleanly

#### Scenario: Component needs an unavailable transport
- **WHEN** an extension, a runtime package install, or a tool requires a named Unix socket, a host service or an unapproved remote host
- **THEN** that component fails while the session and its outer restrictions stay unchanged
- **AND** the README and the validation record name the affected workflows

### Requirement: Optional traffic remains opt-in
Provider sessions SHALL disable Pi's version check and telemetry where the tested version supports it, using protected environment values, set after forwarding, that writable Pi settings and forwarded variables cannot override. Runtime package installs from package registries SHALL stay denied; packages are preinstalled during maintenance. A missing disable control SHALL NOT broaden the allowlist. Shell mode SHALL keep the same outer restrictions.

#### Scenario: Optional feature attempts outbound access
- **WHEN** a disabled feature, an extension or a writable setting attempts an update, telemetry, package or share request to an unapproved host
- **THEN** the proxy denies it without adding vendor or CDN wildcards

#### Scenario: Protected values cannot be overridden
- **WHEN** the operator lists an optional-traffic variable in `PI_ENV_VARS` or the host sets it to another value
- **THEN** the session receives the protected value

#### Scenario: Provider-hosted tools
- **WHEN** Pi uses a provider-hosted tool such as remote web search
- **THEN** documentation states that this network activity happens at the provider, outside the local boundary

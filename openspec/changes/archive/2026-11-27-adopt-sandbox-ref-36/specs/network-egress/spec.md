# Spec Delta

## MODIFIED Requirements

### Requirement: Operator-selected runtime modes

The wrapper SHALL accept `PI_CONTAINER_NETWORK=offline|provider|unrestricted` from explicit operator configuration or the validated managed launcher. An unset or empty mode SHALL select `provider`, and SHALL stop with setup guidance before engine calls, state creation or image operations when the provider settings are missing. Other values SHALL fail before image operations. Only explicit `unrestricted` SHALL remove the runtime destination boundary. Agent-writable configuration SHALL NOT select or broaden the outer policy.

#### Scenario: Missing and invalid selection

- **WHEN** an ordinary invocation leaves the mode unset or empty without provider settings
- **THEN** it exits nonzero with setup-required guidance naming `--container-setup` and `PI_CONTAINER_NETWORK`, before any engine call or state creation
- **AND** an unknown nonempty mode fails with an invalid-mode diagnostic without image operations or agent startup

#### Scenario: Provider by default

- **WHEN** the mode is unset and the provider settings select a protected installation, policy and proxy image
- **THEN** the session runs in provider mode with all provider requirements

#### Scenario: Policy cannot escalate itself

- **WHEN** workspace settings, `~/.pi` settings, models and auth files, extensions, application state or commands request a broader policy or remove proxy variables
- **THEN** the running session keeps its operator-selected outer boundary

#### Scenario: Explicit offline operation

- **WHEN** an operator selects offline mode
- **THEN** all restricted platform, protected-installation, guard and qualification requirements apply
- **AND** the session cannot reach external services, including every model provider

#### Scenario: Explicit provider or unrestricted operation

- **WHEN** an operator selects provider or unrestricted mode
- **THEN** the mode keeps its policy, authority, prerequisite and separate maintenance requirements
- **AND** failed restricted preparation never falls back to unrestricted networking

#### Scenario: Unrestricted keeps current behavior

- **WHEN** an operator selects `unrestricted`
- **THEN** the session has direct networking with the common launcher hardening, refuses exact `PI_CONTAINER_PODMAN=1`, starts a private session engine only when the library holds images, and needs no host Python, guard or qualification report

#### Scenario: Qualification is not an ordinary session

- **WHEN** `--container-qualify` runs with no effective mode
- **THEN** it qualifies the default mode, `provider`, with its protected fixtures, as the launcher and every Python helper resolve it
- **AND** neither the operation nor its internal probe admits an arbitrary application command or bypasses enforcement

### Requirement: Evidence and common contract documentation

Documentation SHALL map N01–N14 and C01–C14 to implementation and acceptance, publish the mode and profile contract and the five-wrapper parity table, and date and version the endpoint inventories. `docs/validation.md` SHALL separate synthetic enforcement, real-rootless bypass checks and operator-run authenticated checks. Untested checks SHALL be recorded as unavailable, and automated tests SHALL NOT use real credentials.

#### Scenario: Provider profile readiness

- **WHEN** a profile is declared verified for a Pi version
- **THEN** operator-run evidence covers authenticated model requests, streaming, long-lived requests, supported WebSockets, the interactive TUI, CA behavior and shell mode
- **AND** credential-free tests separately cover DNS/UDP/IPv6, direct IPs and ports, deceptive hosts, redirects, host/LAN/metadata, administration, concurrency, leftover delegation refusal, session engine containment, failure closure and cleanup

#### Scenario: Authenticated check unavailable

- **WHEN** a real API key or account check has not been run by the operator
- **THEN** it is recorded as unavailable and no provider verification is claimed, while mandatory enforcement tests are not waived

#### Scenario: User reviews limits

- **WHEN** a user reads the network documentation
- **THEN** it explains that allowed services can receive session data, provider-hosted tools are outside local filtering, and runtime filtering does not constrain host-side image pulls or builds

#### Scenario: Parity table

- **WHEN** a reader compares the five wrappers
- **THEN** `docs/network-contract.md` here and in `sandbox-container` show the same Pi row after parity synchronization, with authenticated compatibility recorded as pending until the operator checks run

### Requirement: Proxy process budget falls back to the process rlimit

When the verified engine does not delegate the `pids` controller and the engine host counts the process rlimit per container, each session proxy's first process SHALL set its soft and hard process rlimit to 128 before the proxy program runs, and the engine SHALL apply no process rlimit for the budget. The created proxy and its effective limit SHALL be verified before agent execution. Otherwise the proxy process budget SHALL stay unenforced with a notice. The proxy memory budget SHALL have no fallback.

#### Scenario: Proxy on the process rlimit fallback

- **WHEN** a restricted session prepares its proxy on an engine that delegates `memory` but not `pids`, on a host that counts the process rlimit per container
- **THEN** the proxy's first process sets a soft and hard process rlimit of 128, and the proxy is created without a cgroup process limit and without a process rlimit requested from the engine
- **AND** the effective process rlimit inside the proxy is verified before the agent starts
- **AND** the session prints a notice that the proxy process budget is enforced through the process rlimit

#### Scenario: Proxy fallback is not effective

- **WHEN** the proxy reports no process rlimit, or a value other than 128, while the fallback applies
- **THEN** preparation fails before agent execution and cleans up only owned resources
- **AND** it never substitutes an unrestricted connection

#### Scenario: Proxy fallback not applied

- **WHEN** the engine does not delegate `pids` and per-container counting is not established
- **THEN** the session requests neither a cgroup process limit nor a process rlimit for the proxy
- **AND** the session prints a notice naming the unenforced proxy process budget and why the fallback was not applied

#### Scenario: Other containers do not consume the proxy's budget

- **WHEN** other containers of the same user, such as other sessions, their proxies and engines, together hold more than 128 processes
- **THEN** the proxy starts, passes its effective-limit check, and serves the session

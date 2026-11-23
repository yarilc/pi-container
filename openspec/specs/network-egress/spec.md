# network-egress Specification

## Purpose

Let the operator select offline, provider-restricted or explicitly unrestricted networking for Pi sessions, enforce the restricted modes outside the agent with the shared native guard and exact-destination egress proxy, and document what that enforcement does not cover.

## Requirements

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
- **THEN** the session has direct networking and optional delegation with the common launcher hardening, and needs no host Python, guard or qualification report

#### Scenario: Qualification is not an ordinary session
- **WHEN** `--container-qualify` runs with no effective mode
- **THEN** it qualifies the default mode, `provider`, with its protected fixtures, as the launcher and every Python helper resolve it
- **AND** neither the operation nor its internal probe admits an arbitrary application command or bypasses enforcement

### Requirement: Restricted sessions have no direct external path
Offline sessions SHALL have only their own loopback services. Provider sessions SHALL additionally reach only the trusted proxy frontend. Restricted sessions SHALL have no direct Internet route or secondary unrestricted attachment and SHALL deny host, LAN, metadata, other sessions and proxy administration. Unsupported enforcement SHALL stop startup before the agent runs.

#### Scenario: Direct connection attempts
- **WHEN** a restricted session tries direct IPv4/IPv6 sockets, host aliases, the host gateway, private destinations or a second session
- **THEN** those connections fail independently of client proxy settings

#### Scenario: Host or shared namespace defaults
- **WHEN** engine defaults would share host PID/IPC namespaces or those of another container
- **THEN** the restricted launch selects private namespaces and exposes no host process or IPC handles
- **AND** the proxy remains outside the agent's PID/IPC domains

#### Scenario: Backend cannot enforce isolation
- **WHEN** the rootless backend, its version or resource setup cannot establish the boundary
- **THEN** startup fails with a diagnostic and cleans up owned resources without starting the agent

### Requirement: Mandatory inherited IPC enforcement
Restricted sessions SHALL admit native Linux and WSL2 x86_64 installations with usable Landlock ABI >= 3, using filesystem confinement plus an additional in-process seccomp filter installed before agent code. Restrictions SHALL survive descendants. The standard OCI seccomp profile and any active SELinux/AppArmor policy SHALL stay active; their enabled status alone SHALL NOT reject preparation, and compatibility with them SHALL NOT be guaranteed.

#### Scenario: Unsupported or blocked kernel features
- **WHEN** the ABI is below 3, the Landlock rules or the additional filter cannot install, or the syscall architecture is unsupported
- **THEN** startup fails before Pi, Bash, the relay or application initialization
- **AND** no privilege addition, weakened OCI profile, kernel change or unrestricted retry occurs

#### Scenario: Native approvals cannot remove confinement
- **WHEN** a session forks, execs, creates threads, or runs Pi tools, which have no approval prompts
- **THEN** all agent-controlled descendants keep both enforcement layers and cannot acquire unfiltered external peers

#### Scenario: Active security modules
- **WHEN** native Linux reports SELinux or AppArmor enabled
- **THEN** preparation evaluates actual enforcement and local qualification without rejecting the enabled status alone
- **AND** a policy denial stops preparation without disabling modules, relabeling or adding privileges

### Requirement: Pi tools and extensions under the outer boundary
Pi's interactive TUI, its tools, extensions and skills SHALL run under the guard. Their communication SHALL be limited to own-loopback TCP, pipes and connected socket pairs. A component needing a named Unix socket, a host service or an unapproved endpoint SHALL fail with documented guidance; the guard SHALL NOT be weakened for it. Pi has no tool-approval layer, so guard and proxy are the only enforcement.

#### Scenario: Interactive session in a restricted mode
- **WHEN** the Pi TUI starts in a PTY in offline or provider mode and quits
- **THEN** the interface renders and exits cleanly

#### Scenario: Component needs an unavailable transport
- **WHEN** an extension, a runtime package install, or a tool requires a named Unix socket, a host service or an unapproved remote host
- **THEN** that component fails while the session and its outer restrictions stay unchanged
- **AND** the README and the validation record name the affected workflows

### Requirement: External Unix endpoints are denied
Restricted processes SHALL be unable to connect or explicitly send to unapproved external Unix endpoints through mounts or aliases, including sockets created after startup. Provider mode SHALL keep only one bootstrap-verified preconnected proxy data channel as an external Unix exception; offline SHALL keep none. A socket's presence in a permitted mount SHALL NOT authorize its use.

#### Scenario: Host socket in a shared tree
- **WHEN** a host service exposes a stream, datagram or seqpacket Unix socket in the workspace, worktree parent, Pi state directories (`~/.pi`, `~/.agents`) or isolated home, before or after startup
- **THEN** agent connection and explicit-recipient sends to it fail
- **AND** renaming, symlinking, hard-linking or alternate pathnames do not authorize it

#### Scenario: Proxy exception is a preconnected channel
- **WHEN** provider preparation connects to the verified session frontend before confinement
- **THEN** only that connected policy-filtered channel survives into the confined relay
- **AND** new connections, socket replacement and channel death cannot broaden access or trigger unfiltered reconnection

#### Scenario: External abstract socket
- **WHEN** an agent attempts to create a Unix socket for an external abstract endpoint
- **THEN** creation is denied independently of pathname permissions or writable settings

### Requirement: Restricted local IPC compatibility
Restricted sessions SHALL deny new Unix listeners and unconnected Unix sockets, even in private temporary directories. Own-loopback services, pipes and connected AF_UNIX stream/seqpacket pairs SHALL remain usable. Retargetable datagram/raw pairs SHALL be denied. Socket publication on host binds SHALL fail, while ordinary file persistence and baseline-permitted rename/link operations SHALL remain available.

#### Scenario: Named socket placement and aliases
- **WHEN** a process attempts a named or abstract Unix listener, an unconnected socket, or socket placement into host file state
- **THEN** the operation fails, including in private temporary directories or through aliases
- **AND** binds overlapping reserved private runtime hierarchies are rejected

#### Scenario: Fixed-peer local communication
- **WHEN** descendants use permitted connected pairs, pipes or own-loopback services
- **THEN** local communication works without authorizing any external Unix endpoint
- **AND** reconnect, disconnect, explicit-recipient sends and descriptor transfer cannot retarget permitted pairs

#### Scenario: Ordinary files and incompatible daemons
- **WHEN** the session uses ordinary file, Git or worktree operations, or a tool requiring a named Unix daemon
- **THEN** file operations preserve caller ownership and persistence
- **AND** the named daemon fails with documented compatibility guidance rather than a policy bypass

### Requirement: Trusted bootstrap and descriptor hygiene
Restricted startup SHALL use a protected native bootstrap that confines the session before untrusted loaders, interpreters, environment hooks or settings execute. It SHALL close unrelated inherited descriptors and leave no unconfined agent-side supervisor. Only validated standard I/O and the provider relay's verified preconnected channel SHALL survive preparation.

#### Scenario: Early execution or descriptor injection
- **WHEN** image, workspace or state settings attempt pre-policy execution, an unexpected descriptor is inherited, or the bootstrap identity or rule installation is invalid
- **THEN** startup rejects the condition or closes the descriptor before any agent-controlled code executes
- **AND** connected host sockets cannot bypass the policy through inherited handles, descriptor transfer or asynchronous I/O

### Requirement: Full platform support requires transport evidence
Installing both enforcement layers SHALL be necessary but insufficient for restricted startup. A protected installation gate SHALL verify IP, Unix IPC and enabled alternate host-facing transports under the actual kernel, bootstrap, engine, backend and security policy. An uncontained or unassessable path SHALL keep startup unavailable. Socket creation or a missing listener SHALL NOT prove containment.

#### Scenario: Alternate host transport or incomplete evidence
- **WHEN** a platform exposes a non-IP transport such as AF_VSOCK or lacks controlled evidence for a required boundary
- **THEN** local qualification fails until denial is established with syscall tests and positive controls

#### Scenario: New combination qualifies locally
- **WHEN** an eligible installation passes every local check but has no release acceptance entry for its combination
- **THEN** restricted startup proceeds with a visible locally-qualified, not-release-measured notice
- **AND** no distribution matrix, authenticated-provider verification or SELinux/AppArmor compatibility is claimed

### Requirement: Bounded multiplexed proxy data transport
Provider mode SHALL carry concurrent, independently authorized tunnels over its sole preconnected channel using a protected versioned protocol with bounded streams, frames, queues and flow control. Invalid protocol state or channel failure SHALL fail closed without policy changes or descriptor transfer. Idle channels SHALL NOT expire; incomplete frames and operations SHALL have finite deadlines. Stream failures SHALL preserve unrelated tunnels.

#### Scenario: Repeated and concurrent tunnels
- **WHEN** clients open concurrent tunnels or more sequential tunnels than the concurrency limit
- **THEN** each connection independently passes authority, DNS and address checks
- **AND** TLS, streaming, supported WebSockets and backpressure operate within bounded resources

#### Scenario: Malformed transport and channel death
- **WHEN** clients send invalid versions, lengths, stream IDs, state transitions or credits, or the channel dies
- **THEN** affected operations fail closed with sanitized diagnostics and no unfiltered reconnection

#### Scenario: Resume after an idle prompt
- **WHEN** a healthy provider session receives no transport frames for longer than 300 seconds
- **THEN** a subsequent approved TLS request succeeds through the original channel without restarting the session

#### Scenario: A partial frame stalls
- **WHEN** a peer starts a frame but does not complete it within the finite frame deadline
- **THEN** the channel closes and pending operations terminate, and partial progress does not extend the deadline

#### Scenario: One stream fails while another carries traffic
- **WHEN** a tunnel is cancelled, fails an operation or exceeds its close-acknowledgement deadline on a healthy transport
- **THEN** its operations terminate within finite bounds
- **AND** other tunnels continue and a new authorized tunnel succeeds on the same channel

### Requirement: Bounded stream closing state
Provider transport SHALL bound the state kept for closing tunnels and validate legal late frames without delivering them to another tunnel. A missing close acknowledgement SHALL NOT alone close the shared channel. Exhausted closing-state capacity SHALL prevent further local admission without disrupting established healthy tunnels.

#### Scenario: Late acknowledgement and crossing frames
- **WHEN** a delayed acknowledgement, in-flight data, credit or half-close arrives for a locally closed tunnel
- **THEN** the frame is validated against that tunnel's state, closing state is released exactly once, and discarded data reaches no other tunnel
- **AND** an invalid transition or credit violation still fails closed

#### Scenario: Repeated missing acknowledgements exhaust capacity
- **WHEN** unacknowledged closing tunnels reach the retention limit
- **THEN** further local admission fails within a finite bound without closing healthy tunnels, and retained state stays bounded

#### Scenario: Retired or unknown identifiers receive frames
- **WHEN** a frame references a retired or never-issued tunnel identifier
- **THEN** only permitted idempotent terminal frames for known retired identifiers are tolerated, and identifiers are never reused

### Requirement: Recoverable transport control pressure
Provider transport SHALL handle temporary control-queue saturation within fixed queue and task bounds without treating saturation alone as a protocol violation. Required closure controls SHALL NOT be dropped. A shared write that cannot complete within its finite deadline SHALL fail the channel closed.

#### Scenario: Closure burst
- **WHEN** valid stream closures temporarily fill the control queue and writes resume within the deadline
- **THEN** required controls drain within fixed bounds and unrelated traffic and new tunnels resume on the original channel

#### Scenario: Shared writer remains blocked
- **WHEN** required writes cannot complete within the transport deadline
- **THEN** the channel closes and wakes affected operations without policy relaxation or reconnection

#### Scenario: Cancellation during control pressure
- **WHEN** stream or session cancellation races with a full control queue or writer shutdown
- **THEN** owned tasks and buffers are released without deadlock or unbounded background work
- **AND** stream cancellation preserves a healthy channel while session cancellation closes it

### Requirement: Exact destination enforcement outside the agent
A trusted proxy outside agent control SHALL allow only normalized exact policy hostnames and approved ports, normally CONNECT on 443. It SHALL reject unapproved IP literals, wildcard or suffix matches, ambiguous authorities, unsafe ports and unsupported methods. TLS SHALL stay end-to-end without decryption or disabled certificate verification.

#### Scenario: Authority validation
- **WHEN** a client requests an approved exact hostname on its approved port
- **THEN** the proxy evaluates it for connection
- **AND** deceptive suffixes, userinfo, malformed authorities, unapproved ports, literals and wildcards are rejected

#### Scenario: Redirect or tunnel target changes
- **WHEN** an approved HTTPS response redirects the client to an unapproved hostname
- **THEN** a new connection to that hostname is denied
- **AND** documentation makes no claim to inspect encrypted paths, payloads, HTTP Host or authority, domain fronting with matching SNI, or provider-side forwarding

### Requirement: Trusted DNS and connection-time address validation
Only trusted infrastructure SHALL resolve approved upstream names. Each connection SHALL use an address validated against denied IPv4/IPv6 special, private, loopback, link-local and metadata ranges without a second unchecked resolution. Restricted agents SHALL have no external DNS, UDP/QUIC or alternate direct transport.

#### Scenario: Rebinding and mixed address records
- **WHEN** an approved name resolves to a forbidden IPv4/IPv6 address, including mapped IPv4 or a mixed public/private answer
- **THEN** the proxy refuses the connection without connecting to the forbidden address

#### Scenario: Arbitrary DNS and alternate transports
- **WHEN** a tool sends DNS queries, UDP, QUIC or traffic to a resolver or unapproved destination
- **THEN** the traffic cannot leave the restricted session, and local name handling forwards no agent-selected names upstream

### Requirement: Protected and versioned policy inputs
Policy, agent profile and proxy configuration SHALL be outside all agent-writable mounts, with validated ownership, access, syntax, schema revision, profile and required hosts. Only read-only policy inputs SHALL be exposed where needed. The agent SHALL have no proxy administration or policy-write authority. The policy revision and tested CLI and authentication versions SHALL be recorded.

#### Scenario: Unsafe policy or mount overlap
- **WHEN** policy input is malformed, untrusted, missing required hosts, or reachable through a writable workspace or state mount or an escaped symlink
- **THEN** startup rejects it before the agent runs, without repairing permissions or importing credentials

### Requirement: Narrow explicit exceptions
Any local-provider, gateway or optional-service exception SHALL be operator-approved and versioned in a separately named profile with an exact destination and port. Local exceptions SHALL identify their approved address scope and SHALL NOT exempt unrelated private ranges. Exceptions SHALL NOT appear automatically after failures.

#### Scenario: Unapproved endpoint requested
- **WHEN** an agent requests a LAN provider, a custom `base_url` or a feature endpoint absent from the selected policy
- **THEN** access is denied with an actionable policy diagnostic and the policy remains unchanged

### Requirement: Client compatibility does not establish enforcement
Provider mode SHALL set consistent uppercase and lowercase HTTP/HTTPS proxy values pointing at the loopback relay, with a narrow loopback `NO_PROXY`, and SHALL clear conflicting inherited and image proxy variables. Unsetting or ignoring them SHALL NOT create a direct route. TLS trust SHALL follow the opt-in host CA contract.

#### Scenario: Client bypass and incompatible transport
- **WHEN** a command clears proxy variables, uses a wildcard bypass or requires an unsupported transport
- **THEN** direct egress still fails and no direct fallback or TLS relaxation occurs

#### Scenario: Pi client through the relay
- **WHEN** Pi, running on Node, sends HTTPS requests, server-sent event streams or WebSocket traffic in provider mode
- **THEN** the traffic uses CONNECT through the relay with certificate verification enabled, or the incompatible transport fails closed and is documented

#### Scenario: Host CA off and on
- **WHEN** provider mode runs with host CA trust unset and then enabled with `1`
- **THEN** the first run has no host CA mount or wrapper CA variables
- **AND** the second has only the read-only bundle at `/pi-home/ca/bundle.pem` and the four CA variables pointing there

### Requirement: Separate Pi provider profiles
Provider mode SHALL require a named protected profile that describes the upstream service rather than the model brand. The base profiles SHALL be:
- `anthropic-api`, allowing `api.anthropic.com:443`;
- `openai-api`, allowing `api.openai.com:443`;
- `gemini-api`, allowing `generativelanguage.googleapis.com:443`;
- `openrouter-api`, allowing `openrouter.ai:443`.

Hosts SHALL be confirmed on the pinned Pi version. Wildcards SHALL NOT be used.

#### Scenario: API profile
- **WHEN** `anthropic-api` is selected
- **THEN** only `api.anthropic.com:443` is reachable, and other providers, update checks and unrelated feature hosts are denied

#### Scenario: Profile inventory is dated
- **WHEN** a profile is shipped
- **THEN** the policy records the Pi version, the source documentation date and the measured hosts

#### Scenario: Credential follows the profile
- **WHEN** a provider session uses `openrouter-api` and the host sets `OPENROUTER_API_KEY`, `ANTHROPIC_API_KEY` and `GOOGLE_API_KEY`
- **THEN** only `OPENROUTER_API_KEY` among them is passed to the container, by name
- **AND** offline sessions receive no provider credential from the wrapper

### Requirement: Other upstreams need named profiles
Subscription and OAuth logins (Claude Pro/Max, ChatGPT, GitHub Copilot and similar), cloud providers, custom base URLs, other gateways and local model servers SHALL need separately named, operator-approved profiles. Writable `~/.pi` settings, models and auth files, available keys and extensions SHALL NOT add hosts.

#### Scenario: Configuration names another upstream
- **WHEN** `~/.pi` models or settings, or an extension, configure a provider or base URL outside the selected profile
- **THEN** requests to it are denied and no host is added to the session policy

#### Scenario: Browser-callback login remains unsupported
- **WHEN** a user starts a Pi login that needs a host browser to reach a callback port in the container
- **THEN** no port is published and no host-network exception is added
- **AND** documentation names API keys as the supported method

### Requirement: Optional traffic remains opt-in
Restricted sessions SHALL disable Pi's version check and telemetry where the tested version supports it, using protected environment values (`PI_OFFLINE=1`, `PI_SKIP_VERSION_CHECK=1`, `PI_TELEMETRY=0`), set after forwarding, that writable Pi settings and forwarded variables cannot override. Runtime package installs from package registries SHALL stay denied; packages are preinstalled during maintenance. A missing disable control SHALL NOT broaden the allowlist. Shell mode SHALL keep the same outer restrictions.

#### Scenario: Optional feature attempts outbound access
- **WHEN** a disabled feature, an extension or a writable setting attempts an update, telemetry, package or share request to an unapproved host
- **THEN** the proxy denies it without adding vendor or CDN wildcards

#### Scenario: Protected values cannot be overridden
- **WHEN** the operator lists an optional-traffic variable in `PI_CONTAINER_ENV_VARS` or the host sets it to another value
- **THEN** the session receives the protected value, and the forwarding list skips the name with a notice

#### Scenario: Provider-hosted tools
- **WHEN** Pi uses a provider-hosted tool such as remote web search
- **THEN** documentation states that this network activity happens at the provider, outside the local boundary

### Requirement: Session-owned egress resource lifecycle
Proxy resources, setup channels, transport endpoints, configuration and local clients SHALL have unique recoverable session ownership under `io.pi-container.*` labels. Setup failure SHALL stop launch and remove only owned resources. Cleanup SHALL share the launcher's bounded shutdown budget and preserve the primary exit status. Proxy failure SHALL leave outbound attempts closed without changing mode.

#### Scenario: Concurrent sessions and setup interruption
- **WHEN** sessions with different policies start concurrently or setup is interrupted after resource creation
- **THEN** identities remain distinct and cleanup removes only the interrupted session's resources

#### Scenario: Bootstrap fails after proxy setup
- **WHEN** confinement or descriptor validation fails after the session proxy exists
- **THEN** no agent code runs, the failure status is preserved, and only owned resources are removed within the shutdown budget

#### Scenario: Proxy failure
- **WHEN** the proxy becomes unavailable during a provider session
- **THEN** later outbound attempts fail and the agent receives no alternate network attachment

### Requirement: Redacted actionable diagnostics
Startup SHALL report the mode, selected profile and policy revision. Protected logs SHALL distinguish proxy unavailability, DNS failure, destination rejection and provider authentication failure when observable. Denial records SHALL contain only the bounded sanitized destination and port, session identity and reason, never credentials, token URLs, headers, bodies or prompts.

#### Scenario: Malicious diagnostic input
- **WHEN** a rejected request includes userinfo, control characters, authorization data or a token-bearing URL
- **THEN** logs omit secrets and raw request content and report a bounded reason without log injection

### Requirement: Mandatory TLS server-name binding
Every provider tunnel SHALL validate the complete initial TLS 1.2/1.3 ClientHello in the trusted proxy before forwarding client bytes. Exactly one unambiguous DNS server name SHALL normalize to the authorized CONNECT hostname. After a TLS 1.3 HelloRetryRequest the second ClientHello SHALL be bound the same way, with client bytes held until the upstream's first handshake message is classified.

#### Scenario: Matching names with certificate verification
- **WHEN** a valid ClientHello names the authorized hostname, including case and terminal-dot normalization
- **THEN** the original bytes are forwarded once and the client still validates the upstream certificate

#### Scenario: Shared-address server-name mismatch
- **WHEN** CONNECT authorizes one hostname but the ClientHello names another hostname served at the same address
- **THEN** the proxy rejects the tunnel before forwarding any client bytes

#### Scenario: Missing, ambiguous or unverifiable identity
- **WHEN** the ClientHello has missing, duplicate, conflicting, malformed, non-DNS or mismatched names, is non-TLS, offers only unsupported versions, or carries ECH including GREASE ECH
- **THEN** the proxy rejects the tunnel with no unchecked fallback

#### Scenario: Retried ClientHello
- **WHEN** the upstream sends a HelloRetryRequest and the second ClientHello names a different host, lacks a name, carries ECH or is malformed
- **THEN** the proxy rejects the tunnel before any byte of the second ClientHello reaches the upstream
- **AND** without a retry, held bytes are forwarded unchanged and the tunnel continues opaquely

#### Scenario: Agent bypasses the loopback relay
- **WHEN** agent code sends OPEN and DATA directly over the inherited multiplex channel
- **THEN** the proxy applies the same inspection and policy binding

### Requirement: Bounded TLS inspection across transport boundaries
TLS inspection SHALL reassemble ClientHellos across arbitrary TLS record and multiplex frame boundaries, and SHALL enforce finite limits on wire bytes, decoded size, record count, elapsed time and per-stream and per-session memory independently of untrusted lengths. Failure SHALL release resources without unchecked forwarding or reconnection.

#### Scenario: Fragmented and coalesced input
- **WHEN** a valid ClientHello is fragmented across records or frames, or shares a chunk with later TLS bytes
- **THEN** acceptance depends on the reconstructed ClientHello and forwarded bytes keep their order and contents

#### Scenario: Inspection exhaustion or premature end
- **WHEN** declared lengths are invalid, limits are exceeded, input ends early or the absolute deadline expires
- **THEN** the tunnel is rejected, buffered data is discarded and unrelated streams continue

### Requirement: Verified proxy destination-binding revision
Provider startup SHALL verify the protected destination-binding revision `tls-clienthello-sni-v2`, together with the policy, bootstrap and multiplex identities. An old or incompatible proxy SHALL fail readiness before agent startup. The revision SHALL apply to bundled and operator-defined profiles, and writable settings SHALL NOT disable it.

#### Scenario: Old proxy image or mismatched readiness
- **WHEN** the immutable proxy image lacks the required revision, reports another one, or receives an incompatible manifest
- **THEN** provider preparation fails before agent execution, cleans up only owned resources, and substitutes no unchecked proxy

### Requirement: Single-source enforcement revisions
The guard revision, the required Landlock ABI and the destination-binding revision SHALL each be defined once for the protected Python components that write, validate or report them. Tests SHALL fail when the compiled guard's declared revision or version output differs from that definition.

#### Scenario: Revision drift
- **WHEN** the guard source, the manifest writer, the proxy validator or the readiness check would use different revision values
- **THEN** the test suites fail before release

### Requirement: Redacted TLS binding rejection diagnostics
Protected denial logs SHALL distinguish TLS identity rejection, malformed or unsupported negotiation, ECH rejection, inspection overflow and inspection timeout with bounded reason codes and the authorized destination. They SHALL NOT record raw ClientHello data, rejected raw SNI, headers, credentials, URLs, payloads or prompts.

#### Scenario: Sensitive ClientHello contents
- **WHEN** rejected TLS input contains secret-like strings, control characters or excessive lengths
- **THEN** logs contain only the normalized authorized host and port, session identity, timestamp and bounded reason

### Requirement: Capability-based restricted platform prerequisites
Restricted preparation SHALL require Linux x86_64, a rootless Podman server >= 4.9 with Netavark over a verified same-host Unix service, host Python 3, usable Landlock ABI >= 3 and standard OCI seccomp. Exact kernel or server pins and upper version bounds SHALL NOT decide admission. Effective enforcement, protected assets and local qualification SHALL remain mandatory.

#### Scenario: Different kernel and Podman versions
- **WHEN** an installation meets the prerequisites with another kernel or a stable Podman server at or above 4.9
- **THEN** preparation does not reject it for differing from the recorded target, and guard installation and qualification decide readiness

#### Scenario: Missing or unverifiable prerequisite
- **WHEN** architecture, rootless status, service identity, version, backend, ABI or seccomp is unsupported, missing or malformed
- **THEN** preparation fails before agent execution, names the failed prerequisite, and uses no local-engine, rootful, other-backend or unrestricted fallback

### Requirement: Credential-free local enforcement qualification
`--container-qualify` SHALL run a bounded credential-free gate through the production launch and guard path and SHALL write a protected report. The qualified code identity SHALL include the shared launcher core and the agent launcher part. Required denial checks SHALL have positive controls or show enforcing syscall rejection. Missing fixtures, unrelated connectivity failure, skipped checks and unavailable transport evidence SHALL fail qualification.

#### Scenario: Mandatory IP and IPC controls
- **WHEN** offline or provider mode is qualified
- **THEN** the gate verifies direct IPv4/IPv6 denial, no external DNS/UDP path, denial of existing and late external Unix endpoints, host-bind socket publication, alternate socket families and pair retargeting
- **AND** loopback and connected-pair exchange, descendant enforcement and caller-owned file persistence succeed

#### Scenario: Provider boundary qualification
- **WHEN** provider mode is qualified
- **THEN** controlled TLS endpoints exercise matching CONNECT/SNI with certificate verification, zero-byte rejection of mismatched SNI, denied authority and fail-closed channel or proxy loss
- **AND** fixture policies and certificates never modify production inventories or CA defaults

#### Scenario: Probe or smoke check is insufficient
- **WHEN** only an ABI query, socket creation, version query or a smoke check succeeds
- **THEN** no successful report is issued and restricted startup stays blocked

#### Scenario: Documented requalification triggers
- **WHEN** the host reboots, or the active SELinux/AppArmor policy cannot be identified
- **THEN** a reboot requires `--container-qualify` again, and an unidentifiable policy forces full qualification on every launch
- **AND** the shipped release acceptance inventory is empty and the gate cannot add entries, so no installation reports release-measured

#### Scenario: Host kernel without IPv6
- **WHEN** the engine host has no IPv6 support, observed as a missing `/proc/sys/net/ipv6` and `EAFNOSUPPORT` on `AF_INET6` socket creation
- **THEN** the gate uses an IPv4-only positive-control network and peer
- **AND** the IPv6 denial is evidenced by `EAFNOSUPPORT` on `AF_INET6` socket creation in both the unconfined control and the guarded probe
- **AND** every other required check runs unchanged

#### Scenario: Inconsistent IPv6 evidence
- **WHEN** the detected IPv6 state is neither clearly present nor clearly absent, or the fixture network, peer addresses, control or guarded probe contradict it
- **THEN** qualification fails without a report and without falling back to the other path

#### Scenario: IPv6 state is bound to the report
- **WHEN** a report was issued for one IPv6 state and the host later runs with the other state
- **THEN** the report is stale and restricted startup requires requalification

### Requirement: Session proxies have enforced resource budgets

Each session proxy SHALL drop all capabilities, set no-new-privileges and have limits of 128 processes and 256 MiB memory, enforced by the engine and host cgroups, for each budget whose cgroup v2 controller (`pids`, `memory`) the verified rootless engine delegates. Startup SHALL fail before agent execution if a setting or an enforced limit is not effective, or if an unenforced limit is unexpectedly present.

#### Scenario: Proxy readiness with applied limits

- **WHEN** a provider session prepares its proxy on an engine delegating the `pids` and `memory` controllers
- **THEN** budgets, zero capabilities, no-new-privileges and seccomp are verified as effective before the agent starts

#### Scenario: Rootless resource control unavailable

- **WHEN** the engine rejects or silently ignores a limit whose controller it delegates, or cannot report it
- **THEN** provider preparation fails, cleans up only owned resources and never connects unrestricted

#### Scenario: Controller not delegated for the proxy

- **WHEN** the verified engine does not delegate the `memory` controller
- **THEN** the proxy is created without a memory limit, and its process limit is still applied and verified when `pids` is delegated
- **AND** the session prints a notice naming the unenforced proxy budget

#### Scenario: Proxy exceeds a resource budget

- **WHEN** a proxy reaches its process or memory budget
- **THEN** affected outbound operations fail closed and cleanup preserves the primary exit status

### Requirement: Single protected agent profile
All Pi-specific values used by the shared network, launcher and setup components SHALL come from one data-only `agent/profile.json` and its provider policy file. The agent launcher part SHALL mirror them for the launcher and SHALL be checked against them. They include wrapper and variable names, images, labels, installation files and state names, native home, command, application path (the default `native.exec`, `/usr/local/bin/pi`), temporary storage without execution (the default `native.exec_tmp`, false), configuration variables, authentication methods and policy profiles. The profile SHALL be schema-validated, trusted-path checked and outside agent-writable mounts.

#### Scenario: Invalid or unprotected profile
- **WHEN** the profile is missing, malformed, has duplicate or unknown keys, fails validation, or is reachable through a writable mount or escaped symlink
- **THEN** qualification and restricted startup fail before the agent runs, name the profile and use no built-in defaults

#### Scenario: Profile not taken from the workspace
- **WHEN** the workspace contains a file with the profile's name or layout
- **THEN** the wrapper uses only the profile in its protected checkout

#### Scenario: Profile changed after qualification
- **WHEN** the installed profile or policy differs from the one recorded in the current report
- **THEN** ordinary restricted launches are refused with requalification guidance

#### Scenario: Obsolete or mistyped launcher fields
- **WHEN** the profile declares `install.runtime_build`, a relative `native.exec` or a non-boolean `native.exec_tmp`
- **THEN** profile validation fails naming the field

### Requirement: Agent-neutral shared sandbox components
The shared `launcher/`, `network/` and `setup/` components and shared tests, including the compiled guard, `tests/test_launcher.py` and `tests/fake_podman.py`, SHALL contain no agent identifiers and SHALL stay byte-identical to the reference copies in `sandbox-container`, checked by the unchanged `tests/test_alignment.py` and the per-agent SHA-256 manifest. In-container paths, the guard name and the multiplex protocol marker SHALL be agent-neutral. Host-visible images, labels, variables and installation paths SHALL come from the profile.

#### Scenario: Shared component contains an agent identifier
- **WHEN** a shared launcher, network or setup file contains an identifier declared by the profile outside the documented allow-list
- **THEN** the credential-free alignment check fails

#### Scenario: Shared component differs from the reference
- **WHEN** a copied shared file differs from its SHA-256 recorded for the reference tag, or `diff -r` against a sibling `sandbox-container` checkout at that tag reports a difference
- **THEN** the credential-free alignment check fails

#### Scenario: Unlisted file in a shared directory
- **WHEN** `launcher/` contains a file that the manifest does not list
- **THEN** the reference-copy check fails naming the file

#### Scenario: Two wrappers on the same host
- **WHEN** Pi and another wrapper run restricted sessions or qualification concurrently
- **THEN** each creates, inspects and cleans up only resources carrying its own labels and image names

### Requirement: Shared restricted session interface
Restricted preparation, proxy lifecycle, restricted container arguments and proxy cleanup SHALL come from the shared profile-driven helper through fixed operations with explicit inputs and outputs. The wrapper SHALL NOT re-implement them. Helper cleanup SHALL use only the remaining shutdown budget and SHALL NOT change the primary exit status.

#### Scenario: Wrapper integration
- **WHEN** the wrapper starts an offline or provider session
- **THEN** preflight, the guard probe, proxy creation, readiness, hardening verification, guard and relay arguments and proxy cleanup come from the helper
- **AND** the wrapper adds only Pi command, environment, state and credential options

#### Scenario: Interrupted proxy start
- **WHEN** a signal arrives while the helper creates or verifies the proxy
- **THEN** the wrapper terminates that operation and removes only this session's proxy within the remaining budget, creates no agent container and returns the signal status

#### Scenario: Arguments with special characters
- **WHEN** the Pi command or its arguments contain spaces, quotes or newlines
- **THEN** the helper returns them unchanged as separate arguments

### Requirement: Actionable host guard probe diagnostics
Host-side guard probes run by preparation and qualification SHALL NOT depend on the caller's standard output or error being a terminal, file, pipe or null device. A failed probe SHALL report a message naming the probe, its exit status and the Landlock ABI or standard I/O requirement.

#### Scenario: Caller output is a socket
- **WHEN** preparation or qualification runs with standard output or error attached to a socket
- **THEN** the probe result is captured and relayed, and preparation proceeds as from a terminal

### Requirement: Residual exfiltration disclosure
Provider help, README and the network contract SHALL state that destination and SNI binding cannot distinguish the operator's credentials from attacker-supplied ones, so each allowed host can receive workspace data sent with a foreign API key or account. Help SHALL print the hosts of each base profile from the default policy; the README and the network contract SHALL name them too. They SHALL state that only offline mode removes the channel, and SHALL NOT present host reduction as preventing it.

#### Scenario: Operator reads the provider limits
- **WHEN** an operator reads the provider help, README or network contract
- **THEN** the foreign-credential channel is described for every allowed host of the selected profile, including `api.anthropic.com`, `api.openai.com`, `generativelanguage.googleapis.com` and `openrouter.ai`

### Requirement: Accurate provider identity documentation
Provider help and the network contract SHALL distinguish CONNECT authorization, SNI binding of the initial and retried ClientHellos, and encrypted application routing. They SHALL state that matching SNI does not prove exclusive communication with the operator's provider account, and SHALL name uninspected TLS 1.2 renegotiation as an accepted limitation. Credential-injecting interception SHALL be described as unimplemented.

#### Scenario: Operator reviews provider guarantees
- **WHEN** an operator reads about provider mode
- **THEN** the ClientHello guarantee, the remaining application-level limits, the renegotiation limitation and the unimplemented interception option are visible

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

### Requirement: Private runtime hierarchies admit only verified read-only masks
Before agent code runs, the restricted bootstrap SHALL reject every nested mount below `/tmp`, `/run` and `/var/tmp`, except the engine metadata file `/run/.containerenv`, the provider runtime `/run/sandbox-egress` and `/run/secrets` when it is a `tmpfs` whose per-mount options are read-only. Provider proxies and qualification gate containers SHALL also receive the read-only `/run/secrets` mask.

#### Scenario: Read-only secrets mask
- **WHEN** a restricted session starts with the read-only tmpfs mask at `/run/secrets`
- **THEN** the bootstrap accepts the layout and Pi starts

#### Scenario: Writable secrets mount
- **WHEN** `/run/secrets` is a writable mount, for example the engine default without the mask
- **THEN** startup stops with the nested private IPC mount diagnostic before agent code runs

#### Scenario: Other nested mount
- **WHEN** any other host or tmpfs mount appears below `/tmp`, `/run` or `/var/tmp`, read-only or not
- **THEN** startup stops before agent code runs

### Requirement: Provider upstream connection tolerates unsupported address families
When an approved name resolves to several validated addresses, the provider proxy SHALL skip any address whose family the kernel does not support and try the next one. It SHALL never connect to an unvalidated address or resolve the name a second time. When no address yields a connection, it SHALL reject the tunnel.

#### Scenario: AAAA records on a kernel without IPv6
- **WHEN** an approved host resolves to IPv6 and IPv4 public addresses and the proxy runs on a kernel without IPv6
- **THEN** the proxy connects through a validated IPv4 address
- **AND** the IPv6 addresses do not abort the tunnel

#### Scenario: Only unsupported families
- **WHEN** every validated address has a family the kernel does not support
- **THEN** the tunnel is rejected as upstream-unavailable before any client bytes are forwarded

### Requirement: Qualification containers do not depend on the image working directory
Every container that local enforcement qualification starts from the runtime image SHALL set its working directory to `/` explicitly. This covers the gate's certificate, control and peer containers and the security-identity probe. The engine SHALL therefore never create or change the ownership of an image working directory for these containers, whatever `WORKDIR` the runtime image declares.

#### Scenario: Runtime image with a WORKDIR missing from its layers
- **WHEN** a wrapper's runtime image declares `WORKDIR /workspace` without creating it in a build step, and qualification runs
- **THEN** the qualification containers start in `/` and the engine does not create `/workspace` in them

#### Scenario: Host with a domain UID under keep-id
- **WHEN** qualification runs as a caller whose UID cannot be used for an engine-side chown under `--userns=keep-id`
- **THEN** no qualification container fails on a working-directory chown

#### Scenario: Probe behavior unchanged
- **WHEN** the control probe, peer and security probe run in `/`
- **THEN** they reach their fixtures by absolute paths and produce the same evidence as before

### Requirement: Guard runtime test uses the wrapper's native home
The shared guard runtime test SHALL run the real Pi image with the wrapper's own native home mounted writable, as the launcher does, so that an agent command that writes to its home at startup runs under the production guard.

#### Scenario: Agent command writes to its home
- **WHEN** `bash tests/run-runtime.sh --guard` runs the production guard with the Pi image and its command creates directories under its native home
- **THEN** the guarded production-container test passes without a read-only file system error

### Requirement: Launcher files are protected restricted inputs
The shared launcher core and the agent launcher part SHALL be part of the protected code identity recorded in local qualification reports. Restricted preflight SHALL require each of them to be a protected file. Any change to either SHALL invalidate matching qualification evidence.

#### Scenario: Writable launcher core
- **WHEN** `launcher/core.sh` or `agent/launcher.sh` in the installation is writable by others or reachable through a writable mount
- **THEN** restricted preflight fails naming the file

#### Scenario: Launcher core changed after qualification
- **WHEN** `launcher/core.sh` or `agent/launcher.sh` differs from the one recorded in the report
- **THEN** ordinary restricted startup requires requalification

### Requirement: Proxy process budget falls back to the process rlimit

When the verified engine does not delegate the `pids` controller and the engine host counts the process rlimit per container, each session proxy SHALL be created with a soft and hard process rlimit of 128. The configured and effective limit SHALL be verified before agent execution. Otherwise the proxy process budget SHALL stay unenforced with a notice. The proxy memory budget SHALL have no fallback.

#### Scenario: Proxy on the process rlimit fallback

- **WHEN** a restricted session prepares its proxy on an engine that delegates `memory` but not `pids`, on a host that counts the process rlimit per container
- **THEN** the proxy is created with a soft and hard process rlimit of 128 and without a cgroup process limit
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

### Requirement: Restricted sessions run the application under a confined init

After confinement, the guard SHALL run the application as its child in a new process group that becomes the controlling terminal's foreground group, forward the termination and user signals it receives to the application, reap orphaned processes, and exit with the application's status, or 128 plus the signal number when a signal ended it. The waiting guard SHALL keep no proxy channel and no standard input or output.

#### Scenario: Interrupt from the terminal

- **WHEN** the user presses Ctrl+C during a restricted session whose command, such as `sleep 60`, installs no SIGINT handler
- **THEN** the command ends at once and the session's status is 130, as in an unrestricted session

#### Scenario: One interrupt

- **WHEN** the application handles SIGINT and the user presses Ctrl+C once
- **THEN** the application receives exactly one SIGINT

#### Scenario: Shutdown signal

- **WHEN** the launcher's bounded shutdown sends TERM to a restricted container
- **THEN** the application receives TERM before the forced removal

#### Scenario: Exit status and orphans

- **WHEN** the application starts a background process and exits with status 37
- **THEN** the session's status is 37 and the guard exits without waiting for the background process

#### Scenario: Confined supervisor

- **WHEN** the application runs
- **THEN** the waiting guard runs under the same Landlock and seccomp restrictions and holds neither the provider's proxy channel nor standard input and output

# Spec Delta

## MODIFIED Requirements

### Requirement: Session proxies have enforced resource budgets
Each session proxy SHALL drop all capabilities, set no-new-privileges and have limits of 128 processes and 256 MiB memory, enforced by the engine and host cgroups, for each budget whose cgroup v2 controller (`pids`, `memory`) the verified rootless engine reports as available. Startup SHALL fail before agent execution if a setting or an enforced limit is not effective, or if an unenforced limit is unexpectedly present.

#### Scenario: Proxy readiness with applied limits
- **WHEN** a provider session prepares its proxy on an engine reporting the `pids` and `memory` controllers
- **THEN** budgets, zero capabilities, no-new-privileges and seccomp are verified as effective before the agent starts

#### Scenario: Rootless resource control unavailable
- **WHEN** the engine rejects or silently ignores a limit whose controller it reports as available, or cannot report it
- **THEN** provider preparation fails, cleans up only owned resources and never connects unrestricted

#### Scenario: Controller not delegated for the proxy
- **WHEN** the verified engine does not report the `memory` controller
- **THEN** the proxy is created without a memory limit, and its process limit is still applied and verified when `pids` is reported
- **AND** the session prints a notice naming the unenforced proxy budget

#### Scenario: Proxy exceeds a resource budget
- **WHEN** a proxy reaches its process or memory budget
- **THEN** affected outbound operations fail closed and cleanup preserves the primary exit status

### Requirement: Credential-free local enforcement qualification
`--container-qualify` SHALL run a bounded credential-free gate through the production launch and guard path and SHALL write a protected report. Required denial checks SHALL have positive controls or show enforcing syscall rejection. Missing fixtures, unrelated connectivity failure, skipped checks and unavailable transport evidence SHALL fail qualification.

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

## ADDED Requirements

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

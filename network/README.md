# Native IPC bootstrap

`guard.c` implements the mandatory native bootstrap for restricted wrapper
sessions in `add-enforced-network-egress`. The superseded IP-only startup hold
is replaced by mandatory protected-asset, platform and in-container enforcement
checks plus the credential-free installation gate. An ABI number or mock pass alone
does not establish support.

Shared files in `network/` and `setup/` contain no agent identifiers. Agent-specific
names (wrapper, variables, images, labels, native home/command and provider
host requirements) come from the protected `agent/profile.json`; provider
policies live in `agent/policies/`. In-container paths are neutral:
`/opt/sandbox-egress`, `/run/sandbox-egress`, `/tmp/sandbox-runtime` and the
`sandbox-egress-guard` binary.

The guard accepts only:

```text
sandbox-egress-guard --version
sandbox-egress-guard --probe
sandbox-egress-guard --offline -- /absolute/program [args...]
sandbox-egress-guard --provider -- /absolute/program [args...]
```

`--probe` queries Landlock ABI >= 3 only; it does not attest enforcement.
Like every guard mode, it exits 78 without writing when stdout or stderr is not a
terminal, regular file, pipe or `/dev/null` (for example a journald socket).
`session.py prepare` and qualification therefore run it through pipes and relay
its output; a failed probe reports `sandbox egress guard probe failed (status N)`.
The guard revision and required ABI are defined once for Python code in
`network/revisions.py`; `tests/test_guard.py` checks that the C defines match.
Native Linux and WSL2 x86_64 are eligible with usable ABI >= 3, standard OCI
seccomp and rootless same-host Unix Netavark/Podman >= 4.9. Kernel releases are
not pinned and stable server versions have no upper bound. SELinux/AppArmor
enabled status alone is not rejection; compatibility is not guaranteed and
actual policy denials stop startup. See the versioned validation record for actual
IP/IPC/proxy checks and remaining authenticated-provider gaps.

Restricted agents and session proxies use `--cap-drop=all` and
`--security-opt=no-new-privileges` at container creation. The guard also retains
its own no-new-privileges check. Keep caller UID/GID, `--userns=keep-id`, standard
OCI seccomp, SELinux policy and mount restrictions; failures never cause a
privileged or unrestricted retry. Unrestricted agent launches retain their
existing arguments.

## Restricted session helper

Wrappers do not implement the restricted lifecycle themselves. They call
`network/session.py` as a separate process (`python3 -I`) with four fixed
operations, in this order:

| Operation | Does | Output |
| --- | --- | --- |
| `prepare --mode M --installation I --writable … --mount-target … [provider inputs] --server-version … --backend … --endpoint … --engine …` (platform JSON on stdin) | control preflight, platform check, guard `--probe`; with `--probe --qualification-input F --workspace W`, validates the fixed qualification input | one line: `guard_digest` or `guard_digest token tls` |
| `start [network inputs] [probe inputs] --session S --guard-digest D` | snapshot, proxy create and start, readiness identity, bounded inspect/exec hardening checks; runs in its own process group | `policy_identity` |
| `agent-args --installation I --mode M --session S --guard-digest D [probe inputs] -- command…` | restricted options, provider relay mounts and proxy variables, guard entrypoint | NUL-terminated records: option count, options, entrypoint arguments |
| `stop --session S --deadline SECONDS [--container ID]` | ownership-confirmed proxy recovery (`proxy.id`, or `proxy.pending` with cid, stdout or label) and removal within the remaining shutdown budget; sanitized diagnostics tail | none; warnings on stderr |

The wrapper keeps everything agent-specific and adds it itself:
- the agent command and approval-bypass arguments;
- optional-traffic variables and credential forwarding;
- the state layout and the agent container lifecycle.

On shutdown it terminates an in-flight `start` by process group, removes the agent
container and then calls `stop` with the seconds left of its 20-second budget.
`start` never cleans up; its `proxy.pending`/`proxy.id` markers let `stop`
recover ownership. Failures keep the exact statuses and messages of the
underlying checks.

Each session proxy has `--pids-limit=128 --memory=256m`. After readiness, the
session helper performs bounded inspect and exec checks of its actual cgroup v2
`pids.max=128` and `memory.max=268435456`, zero capability sets, NoNewPrivs and
standard seccomp before any agent runs. `network/proxy_hardening.py` is protected
installed code; its fixed probe runs inside the proxy without extra mounts or
an administration endpoint. Missing controllers, unknown cgroup layouts or
ignored limits fail closed. Inspect rootless memory/pids controller delegation
and the selected image when this diagnostic appears; do not add privileges or
disable host policy. Proxy exhaustion never creates an unbounded replacement.

The static single-threaded bootstrap validates terminal/pipe/file stdio (rejecting
namespace/process/anonymous-inode handles and O_PATH capabilities) and closes
all unrelated descriptors, queries ABI, validates private tmpfs roots, sets/checks
no_new_privs, installs MAKE_SOCK/REFER filesystem rules and an additional native
x86_64 seccomp filter, then execs the absolute application. It does not load shell,
interpreter, NSS or dynamic library hooks before confinement. Failure exits 78;
usage errors exit 64. Diagnostics go to stderr and arguments/stdin remain intact.

`guard_landlock.h` contains minimal Linux v6.6 UAPI declarations (MAKE_SOCK is bit
9; bit 7 is MAKE_DIR). REFER is granted at the root to retain ordinary file
rename/link operations. MAKE_SOCK is granted only on verified private tmpfs
/tmp, /run and /var/tmp; publication/link/rename into workspace/state stays denied.
`guard_seccomp.h` contains the independently auditable classic BPF filter and
minimal Linux v6.6 filter/seccomp layouts, avoiding an unpinned header dependency.

The added filter stacks on, and never replaces or weakens, the standard OCI
profile. New sockets are limited to AF_INET/AF_INET6 inside network=none.
New AF_UNIX, VSOCK and all other socket families are denied. AF_UNIX socketpair
permits only connected stream/seqpacket with protocol zero and CLOEXEC/NONBLOCK
flags; datagram/raw pairs are denied. Compat/i386, x32, io_uring setup/enter/register
and pidfd_getfd are denied. Descendants inherit both layers.

Provider preparation verifies a private caller-owned read-only transport mount
and socket inode, connects once through a held directory FD, rechecks identity,
and retains that nonblocking connected data channel as FD 3. Offline retains no
external channel. No unconnected Unix socket, namespace handle, ring or unconfined
agent supervisor survives. The confined relay must close FD 3 in its application
exec branch. The proxy never transfers descriptors and exposes no administration.
Handshake, policy/session readiness and relay integration remain separately tested.

New Unix listeners and unconnected Unix sockets are unavailable even in tmpfs.
Existing connected pairs may bind/autobind private pathname or abstract names;
they must remain fixed to their original peer and cannot listen or publish into
host binds. This narrow naming allowance was approved after the real WSL probe.
Pipes, pairs and own loopback remain supported. Keep HOME/configuration unchanged;
XDG_RUNTIME_DIR becomes private /tmp/sandbox-runtime for ordinary runtime files.
Host-agent, named-cache and external supervisor workflows remain incompatible.

The launcher still must validate immutable guard hash/ownership, effective binds,
private PID/IPC namespaces, protected policy/frontend readiness and the full local
IP/IPC/transport gate plus matching evidence. No environment variable can bypass guard rules,
choose an inherited FD or enable a reduced policy. Other architectures require
an independently audited filter. Keep mandatory per-session refusal on failed enforcement; do not add fallback.

## Local installation qualification

After preparing protected code, guard, images and provider inputs, run the
installed wrapper's `--container-qualify` alone. Guided setup does this before
activating its candidate. No credential, public provider endpoint, image pull or
build is required by the gate; necessary images must already be prepared under
separate maintenance authorization. Direct environment-based invocation remains
supported after a matching qualification report exists.

The gate uses bounded disposable resources and fixed protected programs. An
isolated dual-stack bridge hosts controlled TCP/UDP peers; unconfined positive
controls prove reachability before network=none guard probes deny it. Existing
and late Unix endpoints, aliases, pair retargeting/publication, descendants,
alternate families, compat/x32 and asynchronous syscalls are checked alongside
working loopback, connected pairs and ordinary persistence in both state modes.
No missing peer, skipped check or unrelated connection error counts as denial.

Provider qualification additionally exercises the selected production proxy code
with a separate exact fixture policy and certificate, matching TLS/SNI, mismatched
SNI with zero upstream bytes, denied authority and owned proxy loss. The fixed
fixture entrypoint exists only in the dedicated internal probe operation; it
does not add a production DNS/address/SNI bypass or change the selected policy.
The agent always enters through the production guard/relay and N18 hardening.
The probe exception accepts no application command or writable program input.

`qualification/<fingerprint>.json` is a private strict report published atomically
only after all controls pass, cleanup succeeds and before/after identities match.
It binds current kernel/boot, ABI, server/endpoint, backend and OCI/security
artifacts, protected code, inspected immutable images, policy/profile, CA trust
and hardening. The shared validator is `platform_check.py`. Fixed host-side
read-only file probes identify the server's seccomp/Netavark artifacts even when
the Podman client itself runs in a container. A bounded read-only info request to
the verified Unix API preserves server metadata omitted by older clients; backend
binary paths are reported by the server rather than guessed from default locations.
Report paths cannot escape via
symlinks, become application-writable or be repaired recursively.

Ordinary launches require matching evidence and still run all engine/path,
bootstrap and readiness checks. Reboots and relevant updates require another
gate; unidentifiable active LSM policy forces one each launch. Failures stay
closed with `ineligible` or `qualification-required` status. A local pass reports
`locally-qualified`, with a visible notice that the combination is not
release-measured. Only an exact protected entry in `release_acceptance.json`
permits `release-measured`; the shipped inventory is empty and the gate cannot
grow it. Neither status proves real-provider authentication or all native/LSM
combinations. Roll back by restoring the previous complete protected release.

Run `bash tests/run-runtime.sh --qualification` on disposable native storage for
contract and installed gate tests; run the existing guard/network/setup suites
separately. See `docs/validation.md` for actual environments and unavailable checks.

## Operator build inputs

The [interactive setup](../docs/setup.md) can orchestrate these existing recipes,
image inspection and guard packaging after explicit maintenance consent. It
reuses valid artifacts and resolves the provider proxy to an immutable ID. No
host compiler/package installation is performed; compilation remains network
free inside the pinned toolchain. Host pulls and build RUN traffic are outside
session network filtering, including when preparing offline mode. Preparation
authorization is not persisted in managed launch defaults. Missing pinned inputs
remain a maintenance error rather than triggering automatic version changes.

The host sandbox has no C compiler. `guard-build.Containerfile` supplies one in a
rootless container from a digest-pinned Alpine image and explicitly pinned GCC,
musl development headers and binutils. Building that toolchain is operator
maintenance outside runtime egress enforcement. It installs no host packages and
needs no credentials or delegated agent socket.

```bash
tag=$(python3 -I network/agent_profile.py image toolchain development)
podman build --pull=never --tag "$tag" --file network/guard-build.Containerfile network
toolchain=$(podman image inspect --format '{{.Id}}' "$tag")
SANDBOX_GUARD_TOOLCHAIN="$toolchain" bash tests/run-runtime.sh --guard
```

The test runner resolves a prepared toolchain to its immutable image ID before
using it. Source and output binds retain true absolute host paths; outputs use a
disposable native Linux volume. The compiler has no network during compilation.
Use these same inputs/flags for a production artifact, in a protected host-visible
native output directory, using the operator packaging script:

```text
-std=c11 -O2 -static -Wall -Wextra -Werror -D_FORTIFY_SOURCE=2
-fstack-protector-strong -fno-ident -Wl,--build-id=none
LC_ALL=C SOURCE_DATE_EPOCH=0
```

The measured toolchain image ID is
`0b69ba43c894c4599fcfc0fa7b5e3c150ec26fcf7a2690e3c83708688ff9402c`,
with GCC 13.2.1, musl 1.2.5-r4 and binutils 2.42-r1. The exact image ID pins its
transitive packages. Rebuilding the toolchain image against a later package index
is a new input and needs revalidation; do not infer cross-image reproducibility.
Record executable SHA-256 and guard revision separately from policy revision.
No compiled binary is committed or installed outside disposable test storage by the tests.

Create a private native `network/bin` directory inside the protected installation,
then run `<PREFIX>_MAINTENANCE=1 bash network/build-guard.sh /absolute/installed/network/bin`, where
`<PREFIX>` is the profile's `env_prefix` (`python3 -I network/agent_profile.py env MAINTENANCE`
prints the exact name).
The script uses the prepared immutable toolchain without network, atomically
installs the static executable and writes its SHA-256 manifest. Startup validates
trusted ownership/ancestors, digest, executable mode and static x86_64 ELF layout.
Builds remain operator maintenance; no compiler or socket is delegated to the agent.

## Component tests and enforcement evidence

`tests/test_guard.py` builds both the production executable and a separately named
test executable linked with `tests/guard_syscall_mock.c`. The test-only link
wrappers simulate ABI/syscall and filesystem metadata results so ordering,
failure handling, exact rights, descriptor closure, argument/stdin forwarding and
status preservation can be tested on ABI 3. They are not linked into the production
artifact and provide no confinement. Never install the mock executable or count
its success as a real kernel enforcement pass.

The suite checks the production ELF has no dynamic/interpreter segment or mock
configuration, repeat builds are byte-identical, injected loader hooks cannot run
before rejection, and setup failures never execute a sentinel. Real rootless tests
on the target WSL ABI-3 kernel cover new-socket denial, compat/x32 and async syscall
denial, pair retargeting/explicit sends/naming/FD transfer, ordinary file REFER,
Node/Python subprocesses, the agent's `--version` and the sole provider preconnection.
These are component results, not complete IP/IPC/lifecycle or authenticated agent
acceptance. See docs/validation.md and tasks 1.6–1.8 and 4–7.

## Multiplex data protocol v1

The only outside channel is the bootstrap's connected AF_UNIX stream FD 3. Both
peers send and verify `SANDBOX-EGRESS\x00\x01` within 10 seconds. This is an
identity/version check inside the operator-protected session transport, not a
replacement for launcher policy/session readiness verification. A proxy accepts
one channel for its lifetime. Lost channels require a new session.

Each frame is a network-byte-order unsigned byte type, unsigned 32-bit stream ID,
unsigned 32-bit payload length, then exactly that many bytes (`!BII`). IDs start
at 1, increment without gaps and never repeat. Exhaustion requires a new session.
Only the relay initiates OPEN; the proxy independently parses/normalizes and
checks every exact authority and port, resolves it through trusted DNS, rejects
unsafe/mixed addresses, and connects numerically without a second lookup.

| Type | Value | Payload and transition |
| --- | --- | --- |
| OPEN | 1 | 1–8192 bytes of exact ASCII authority; one upstream per stream |
| OPEN_OK | 2 | Empty; proxy authorization/connect completed |
| OPEN_ERR | 3 | Only `denied` or `unavailable`; no raw request data |
| DATA | 4 | 1–16384 bytes; established stream, before remote HALF_CLOSE |
| HALF_CLOSE | 5 | Empty; EOF in one direction, exactly once |
| CLOSE | 6 | Empty; cancel/complete stream, peer acknowledges with CLOSE |
| WINDOW_UPDATE | 7 | Unsigned 32-bit nonzero consumed-byte credit |

At most 64 streams are active. Each direction begins with 256 KiB of credit per
stream; returned credit cannot exceed that window. Received bytes cannot exceed
outstanding credit, 256 KiB per-stream buffers, or the 16 MiB session buffer cap.
Writer buffering is bounded with backpressure; control acknowledgments have a
separate queue of at most 64 entries and one sender. Temporary saturation applies
bounded backpressure outside stream locks; receiver dispatch can pause until
space is available. Queue admission, writer-lock acquisition and drain share an
absolute 30-second control-write budget. A sustained shared-write stall closes
the channel; temporary pressure does not create a protocol error or drop CLOSE.
The loopback relay accepts at most 64 active client handlers. Handshake/payload
reads take at most 10 seconds; stream idle operations 300 seconds, writes 30 seconds,
OPEN replies 15 seconds, CLOSE acknowledgments 10 seconds and tunnels 12 hours.
Async timeouts preserve cancellation without spawning detached operations.
An established channel can wait indefinitely for the first byte of a new frame,
including when no tunnels are open. Once a frame starts, its remaining header
and validated payload share one absolute 10-second completion deadline; partial
progress does not reset it. Quiet sessions require no heartbeat or reconnect.
Local cancellation, operation expiry and a missing CLOSE acknowledgement preserve
healthy unrelated tunnels. After the ten-second acknowledgement wait, the caller
finishes and only compact validation state remains until remote CLOSE or channel
teardown. Closing records count against the 64 outstanding-stream slots: repeated
missing acknowledgements can exhaust admission, which rejects new local opens
while established healthy tunnels continue. Valid crossing frames are checked;
discarded DATA consumes remaining receive credit without granting fresh credit.
Concurrent callers share one channel-owned close task per stream, at most 64;
caller cancellation cannot drop required closure work. Payload buffers and tunnel
workers are released, and delayed acknowledgement restores the occupied slot.
Fully retired IDs still accept only idempotent CLOSE and WINDOW_UPDATE.
EOF, malformed/incomplete frames, transport failure and cancellation still close
it safely (cancellation here means the session/channel, not one tunnel).
Actual channel loss requires a new session.

Run `bash tests/run-runtime.sh --guard-idle` with the prepared runtime and immutable
guard toolchain images for opt-in idle acceptance. It runs controlled verified
TLS requests and the existing TLS rejection controls through the production
guard, relay and proxy, pauses for 305 seconds without application requests,
then opens a fresh tunnel in the same session. Production timeout constants stay
unchanged; only this test's application watchdog is extended to 420 seconds.
Ordinary qualification and `--guard` do not include the long wait. No real
credentials or model calls are used. Component tests use shortened deadlines
and are separate evidence from this real-duration check.

Unknown types, versions, IDs, reused OPEN IDs, oversized lengths, credit overflow,
zero credit, data before authorization/after EOF and invalid transitions close
the channel. CLOSE and returned credits for retired IDs are idempotent because
those frames may cross during cancellation; no data or new stream can use a
retired ID. Closing one stream must preserve others and more than 64 sequential
requests must work. Socket replacement, handshake failure and proxy/channel death
never enable a reconnect or unconfined broker.

The relay exposes HTTP CONNECT only on agent loopback. The proxy's Unix frontend
accepts only multiplex data frames. Neither exposes policy-changing operations,
administration or descriptor transfer. Error logs use bounded normalized
host/port/session/reason fields; framing errors never log raw payloads. Log
retention remains capped at 1 MiB. TLS stays end-to-end with certificate validation;
the initial and retried ClientHello SNI is bound to CONNECT before client bytes are forwarded.
There is no TLS interception, application-content filtering, domain-fronting
protection for matching SNI or control over provider-hosted remote tools and shared services.

Run `python3 -m unittest discover -s tests -p test_mux.py -v` or
`bash tests/run-runtime.sh --mux` for framing/state/credit/cancellation and
concurrency checks. The real `--guard` suite also runs 80 sequential controlled
TLS requests, concurrent streaming, WebSocket and certificate/destination-denial
checks through the production static guard and confined relay. These are
credential-free transport tests, not authenticated agent compatibility.

## TLS ClientHello inspection

The destination-binding parser in `tls_client_hello.py` supports TLS 1.2 legacy
ClientHello and TLS 1.3 ClientHello with `supported_versions`. It reconstructs
the first handshake across TLS records and multiplex DATA boundaries. Exactly
one ASCII DNS SNI must match the normalized CONNECT hostname, using the same
case and optional terminal-dot normalization as the policy. Missing, duplicate,
conflicting, malformed, non-DNS or mismatched names fail closed. Unknown ordinary
extensions and GREASE version values do not by themselves invalidate a supported
hello; duplicate extensions, non-TLS, unsupported-only versions and ECH (including
GREASE ECH) are rejected. No extension is stripped and no unchecked retry occurs.

Inspection retains at most 64 KiB of handshake bytes and 96 KiB of original wire
bytes, consumes at most 128 records with 16 KiB plaintext payloads, and never
allocates from a peer-declared length. A fixed 8 KiB extension-presence bitmap
bounds duplicate detection metadata. The ClientHello must end at a record
boundary; later records are surplus and stay held. Original wire bytes remain
ordered and unchanged. Parser rejection exposes only a
fixed reason code, never raw SNI or handshake data. Tests:
`python3 -m unittest discover -s tests -p test_tls_client_hello.py -v`.

This parser verifies the initial plaintext ClientHello name. It cannot establish
exclusive provider application identity, inspect encrypted HTTP Host/authority,
prevent shared-service routing or provider forwarding, or prevent data transfer
to allowed services. Certificate verification remains the client's responsibility
and stays end-to-end. The deployment acceptance status is recorded separately in
`docs/validation.md`; parser tests alone do not establish production enforcement.

The trusted proxy sends OPEN_OK after authority, DNS and address authorization;
the relay then returns HTTP 200. This allows an ordinary client to submit its
ClientHello, but does not authorize unchecked forwarding. During inspection the
upstream can observe a TCP connection with zero client application bytes. A
10-second absolute deadline starts after OPEN_OK and is not refreshed by input.
The proxy reserves 160 KiB of handshake/wire storage per inspecting stream,
at most 10 MiB per 64-stream session, in addition to existing mux credit bounds
and fixed parser metadata. EOF, timeout, rejection and cancellation release the
reservation and close the upstream. Valid streams remain independent.

After validation, the ClientHello records are flushed once. The proxy then
holds any further client bytes, within the same reservation and a new 10-second
deadline, until it classifies the upstream's first handshake message
(`ServerHello` in `tls_client_hello.py`, fixed storage). Upstream bytes are
classified before they are relayed, so the client cannot answer a retry the
proxy has not seen. Without a TLS 1.3 HelloRetryRequest, the held bytes are
forwarded unchanged. After one, the held and following client bytes must form
optional ChangeCipherSpec/early-data records and a retried ClientHello that
passes the same validation and names the same host; only then are they
forwarded. OpenSSL 3.0 servers answer a retried ClientHello that names another
host, so this binding is required, not defensive only. Afterwards the existing
bounded bridge carries opaque traffic.

TLS 1.2 renegotiation is an accepted limitation. Its ClientHello is encrypted
under the established session; the proxy does not decrypt TLS and cannot
inspect it. TLS 1.3 has no renegotiation, and RFC 8446 forbids a second
HelloRetryRequest, so no later ClientHello is inspected. Rejections after OPEN_OK use stream CLOSE, never
a second OPEN response. Direct use of the inherited mux channel receives the
same trusted-proxy inspection. Denial reasons are `tls-identity`, `tls-retry-identity`,
`tls-malformed`, `tls-unsupported`, `tls-ech`, `tls-overflow`, and `tls-timeout`; only the authorized
normalized destination is logged, with existing bounded/redacted audit fields.
Run `python3 -m unittest discover -s tests -p test_tls_proxy.py -v` for proxy/relay
zero-byte rejection, concurrent inspection, deadline and channel-death checks.

Provider manifests and readiness require `tls-clienthello-sni-v2` in addition to
policy, guard digest and mux v1 identities. Rebuild and select the immutable proxy
image together with the matching protected release; an old proxy fails before
agent startup. Setup packages the parser and smoke-checks the candidate before
activation. Rollback to historical code/images removes the new guarantee; use
offline mode if matching, verified code/images cannot be deployed. No ECH/GREASE
compatibility failure may automatically relax policy or enable interception.

Known retired encrypted-name extensions are rejected with `tls-ech` as well:
ESNI `0xffce` ([draft-ietf-tls-esni-05](https://datatracker.ietf.org/doc/html/draft-ietf-tls-esni-05))
and early ECH `0xff02`, `0xff03`, `0xff04`
([draft-ietf-tls-esni-07](https://datatracker.ietf.org/doc/html/draft-ietf-tls-esni-07)).
These cannot be treated as ordinary unknown extensions when validating visible
server-name identity. New name-hiding mechanisms require explicit reassessment;
ClientHello inspection does not establish later application identity.

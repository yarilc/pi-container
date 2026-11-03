# Design

## Context

See `proposal.md` for motivation and the four capability deltas for acceptance criteria. Read-only review on 2026-11-03 covered `todo.md`, `pi-container.sh`, `Containerfile`, `.containerignore`, both test scripts, CI, README, SECURITY.md, CONTRIBUTING.md, and the three sibling launchers and their lifecycle/runtime tests.

All 21 existing synthetic wrapper tests pass. This establishes the starting behavior, not acceptance of the proposed boundary: tests currently require the rootful escape hatch, lowest-free naming, and the old `podman run` argv. `test.sh` builds real images but duplicates root-based runtime flags rather than exercising the wrapper's lifecycle. No image builds, real runtime checks, or authenticated Pi requests were run for this proposal. No existing main specs or other active Pi changes exist.

The checklist matches the inspected implementation. Additional detail: README says Bun version participates in freshness detection, but the hash contains `INSTALL_BUN` without `PI_BUN_VERSION`. Include the selected version to make that stated behavior true. The modified `.version` and other pre-existing workspace changes are unrelated and must be preserved.

The references share a policy rather than identical code. Codex's active `bound-interrupted-container-creation` change is already reflected in its current launcher: pending creation has finite completion/cancellation phases and strict private-CID parsing. Claude additionally uses ownership labels and engine discovery. Antigravity uses private-CID recovery. Adopt the smaller CID-based protocol with the strongest bounded-creation and response-validation cases, rather than copying one launcher wholesale.

## Goals / Non-Goals

**Goals:** Make all non-help entry points share one ordered preflight and runtime policy; preserve Pi's existing state destinations and optional tools; expose lifecycle phases explicitly enough for deterministic tests; use the same contract from shell and Pi modes.

**Non-Goals:** Modifying sibling repositories, adding Pi approval/YOLO flags, changing provider configuration or dependency versions, general startup timeouts, automatic service activation, automatic permission/SELinux repair, recovery after SIGKILL, and guaranteeing cleanup when the engine never publishes an owned identity.

## Decisions

### 1. Parse modes before prerequisites and share ordered preflight

Parse reserved wrapper flags first, preserve all other native arguments as an array, and make either help alias terminate before version/tool/state checks. `--container-build` forces the normal build path before a session, matching Codex's build-then-run semantics; it need not invalidate every cached layer. Shell mode overrides the entrypoint with Bash and clears native Pi arguments. Worktree mode changes only the workspace bind source/destination to the immediate physical parent and retains the physical original workdir. Apply the sensitive-directory guard to the actual exposed directory so worktree mode does not accidentally bypass it.

For all remaining modes, validate required host tools and version inputs, verify the launch engine, verify optional delegation, and validate both persistent-state sources before any image operation. Only then inspect/build images, prepare runtime arguments, reserve, and attach. This ordering makes invalid authority or state observable without building or inspecting images. Keep the current bounded preflight query/build behavior and require GNU timeout for finite control calls; do not broaden the claim into a total startup deadline.

Alternative: separate shell/build launch paths. Rejected because duplicated preflights drift and a shell is still an equally privileged session.

### 2. Use one strict response-capture protocol

Retain all response bytes representable in Bash using a success-only sentinel, remove the sentinel and at most one final LF, and preserve query failures. Launch queries use one record with exactly rootless/OS/remote fields. Delegation queries use two records, `Host.Security.Rootless` then `Host.RemoteSocket.Path`, as Codex does, preserving spaces in the complete path. Reject CR and any extra/missing records. Do not reuse ordinary command substitution followed by `read`, which hides trailing blank records. Validate context selection independently from reported rootless state; rootless alone does not establish same-host Linux execution.

Introduce `PI_PODMAN_SOCKET` as the absolute socket override. Selection precedence follows the engine spec. Resolve and query the accessible endpoint explicitly with `--remote --url`, then bind the service-reported host path to `/run/podman/podman.sock`. This distinguishes paths visible to a containerized wrapper from sources resolved by the host engine. The user remains responsible for same-host service selection and preserving absolute workspace/state paths across container boundaries; a Unix URI is not proof of host identity.

Only exact `PI_ENABLE_PODMAN=1` selects delegation and `INSTALL_PODMAN=1`. Exclude `CONTAINER_HOST` from extra-variable forwarding in both states and emit the final authoritative environment setting or unset instruction. Bun retains its current separate switch semantics. No automatic fallback or service start is permitted when explicitly requested delegation fails.

Alternative: install Podman unconditionally or reuse the launch socket without querying it. Rejected to retain the optional image feature and verify the actual delegated authority.

### 3. Keep state destinations and provide caller-owned writable surfaces

Retain session `HOME=$HOME`, state destinations `$HOME/.pi` and `$HOME/.agents`, and optional read-only `$HOME/.gitconfig`. Canonicalize host sources separately. For writable state, create only genuinely missing directories with a scoped umask; reject dangling links, non-directories, wrong ownership, inaccessible paths, and group/other mode bits. Follow valid directory symlinks to their physical target and validate that target. Never silently repair existing state. Read-only mode requires existing readable/traversable sources, does not create them, and does not apply writable-state ownership/privacy requirements; document that confidentiality is then the caller's responsibility.

Set `--userns=keep-id --user <uid>:<gid>`, retain `--cap-drop=ALL`, and remove all capability additions. Image tooling under `/usr/local` must be executable by arbitrary numeric users; use runtime home/cache setup and tmpfs ownership rather than chowning host binds. Keep the root filesystem read-only without mounting all HOME writable or persisting another credential store. Verify Pi version/help, user/project npm extension installation, disposable Git commits/worktrees, and enabled Bun as this mapped identity. Use a local disposable npm extension fixture for credential-free acceptance; any network smoke package remains explicitly a network-dependent check.

Alternative: retain root with selected capabilities. Rejected because the existing claim that Pi requires it is not backed by mapped-user workflow checks and conflicts with the desired common boundary.

### 4. Declare temporary storage completely

Set `--read-only-tmpfs=false`. Provide `/tmp` and `/var/tmp` at 256 MiB each and `/run` at 32 MiB, explicitly rw/noexec/nosuid/nodev/mode=1777. Preserve a separate HOME/.npm mount with `PI_NPM_CACHE_SIZE` default 256 MiB, rw/noexec/nosuid/nodev, and caller UID/GID with mode 0700. If the current delegated-client storage mounts remain necessary, configure `/var/lib/containers` at 256 MiB and `/run/containers` at 64 MiB with the same hardening and caller ownership. Use the Podman `U` option only on private tmpfs mounts to assign the configured session UID/GID; raw `uid=`/`gid=` tmpfs options are rejected by the tested engine. Never apply `U` to host binds. Test every retained temporary mount rather than assuming automatic Podman provisioning.

Retaining Pi's existing noexec policy is intentional; extension fixtures must confirm compatibility. Installation or execution requiring executable temporary storage is an acceptance failure to resolve explicitly, not grounds to silently drop the policy. Capacity and exhaustion checks belong in real-runtime tests. No automatic `:Z`, `:z`, privileged mode, or security-label disabling is added on access failure.

### 5. Separate name reservation, creation ownership, and attachment

Normalize invalid prefix runs to hyphens, strip invalid leading dot/hyphen characters and trailing punctuation, retain the existing length bound, and fall back to `pi`. Enumerate all containers, accept numeric suffixes of 1–9 decimal digits (explicit base 10 handles `08`), and select max+1. Use at most 20 `podman create` attempts. Retry only when no owned CID exists and a successful existence check confirms collision; a non-collision or lookup error remains a failure. Set CONTAINER_NAME per attempt and never use replacement flags.

Create a mode-0700 bookkeeping directory and use a private `--cidfile` per attempt. Require the whole record to match 64 lowercase hexadecimal characters, optionally one final LF; reject NUL, CR, and extra records. Keep creation PID and pending-creation state until final reconciliation. Attach by full ID with stdin explicitly redirected from fd 0, interactive mode, and `--sig-proxy=false`; allocate TTY only with terminal stdin and stdout. Retain init as defense in depth rather than treating it as lifecycle management.

Alternative: labels plus engine discovery. Rejected as unnecessary for the checklist's ownership guarantee; unknown identities produce diagnostics instead of broader deletion queries. Private CID provenance authorizes cleanup; name availability never does.

### 6. Use fixed shutdown phases and preserve primary status

Record only the first TERM/INT/HUP and corresponding 143/130/129. Honor signals racing with PID assignment before attachment or another create attempt. During shutdown ignore subsequent signals so they cannot restart deadlines. Attached sessions forward once, allow at most 5s application grace, force removal, then reap local clients. Signal/removal controls each use a 5s timeout plus a 1s kill-after. Client reaping uses TERM for at most 5s then KILL with at most 1s observation; never unconditionally wait on a live child or signal a recycled PID.

Pending creation gets at most 5s completion, 5s TERM cancellation, and 1s KILL observation. Re-read the entire CID after cancellation, including a CID published by a TERM handler; attempt removal with the existing 5s+1s bound. Creation shutdown therefore has at most 17s of phase budgets, and attached shutdown at most 23s when every control/grace/reaping phase is consumed, excluding scheduling overhead. No valid CID means an explicit unresolved-outcome diagnostic and no deletion by name. Local cancellation cannot prove server cancellation; even a late server result may remain for manual inspection. Retain private files until recovery is finished, then release them.

Preserve application and attach statuses including 125 and the first interruption status regardless of cleanup failure. Keep `PI_RUN_TIMEOUT` as a native Podman container lifetime option before the image in create argv, not an outer client timeout or shutdown budget; test its actual supported-engine semantics separately and document that timed-out application status is engine-defined.

### 7. Retain image freshness and distinguish operational errors

Build automatically only when image-existence status is 1. Preserve other errors and failed label inspection; successful absent/mismatched labels mean stale images. Keep the `.version` source, build-inputs label, 300s build bound, build arguments, pull control, conditional client/Bun installation, and default-deny context. Add selected `PI_BUN_VERSION` to the hash alongside its enable state. Force-build mode shares this exact path and does not bypass preflight. No dependency upgrades are needed.

### 8. Verify policy through both synthetic and real-wrapper checks

Extend the existing shell test entrypoint with a fake engine that records every operation and supports create/CID/start/kill/rm, complete protocol responses, error statuses, controlled barriers, and indefinite stalls. Keep deterministic readiness markers, full-ID assertions, and failure process-group teardown. A delayed success fixture does not prove bounded cancellation. Exercise repeated signals, CID publication on TERM, and cleanup failures without releasing permanent stalls.

Add opt-in real-rootless runtime support, invoked from a documented test runner, using disposable HOME and workspace on native Linux storage, no provider keys, and explicit time bounds. A runner container can use the host rootless service when needed, preserving host absolute paths. Ensure runner tools are available without requiring unnecessary new production dependencies. Test shell paths and actual Pi help/version/install flows; the shell harness alone does not validate Pi. Adjust `test.sh` so smoke assertions use the new identity/mount policy and wrapper acceptance is not inferred from duplicated flags. CI keeps wrapper/smoke entrypoints and gains runtime coverage where its prerequisites can be provisioned explicitly.

## Risks / Trade-offs

- Existing state on filesystems that ignore Unix permissions will fail writable preflight → document private native Linux storage and explicit caller-directed migration, never silently relax privacy.
- Arbitrary UID tooling or noexec cache behavior may expose Pi/npm/Bun assumptions → run actual workflows before accepting capability removal; record failures without claiming completion.
- Removing automatic relabeling may expose SELinux denials → report policy/permission guidance without changing labels or confinement.
- Worktree parent and Podman delegation intentionally expand authority → document exactly what each explicit opt-in exposes; keep them independent.
- Lost or delayed engine outcomes may leave residual resources → bounded CID recovery and actionable owned-ID/unresolved diagnostics; do not claim guaranteed cleanup under SIGKILL or engine loss.
- Timing tests may fluctuate → synchronize with readiness markers, assert production phases, and use conservative outer limits (25s creation, 35s attachment) without extending production budgets.

## Migration Plan

Implement and verify through a subsequent apply workflow. Users must replace truthy delegation values with exact `1`, remove reliance on `PI_ALLOW_ROOTFUL`, and explicitly repair or relocate insecure writable state. Preserve existing state contents and all unrelated workspace edits. Update README, SECURITY.md, CONTRIBUTING.md, and help together, including `PI_PODMAN_SOCKET`, fixed storage policy, timeout semantics, and residual-resource limitations. Record actual commands, results, and missing prerequisites in a validation document; close checklist items only when corresponding acceptance evidence exists.

Rollback restores the previous launcher/image/tests/documentation together; no state-format conversion is required. Users retain responsibility for any engine resources whose ownership was unresolved. Main-spec synchronization and archive are separate follow-up workflows after implementation acceptance.

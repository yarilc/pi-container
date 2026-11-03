# Tasks

## 1. Shared entry modes and acceptance harness

- [x] 1.1 Extend the fake Podman behind `test-wrapper.sh` to record ordered engine/image/create/start/control operations, exact argv, full CID files, configurable failures, and synchronized stalls; verify fixtures fail on unexpected subcommands and keep secret values out of captured wrapper argv.
- [x] 1.2 Parse reserved container flags before prerequisites, retain `--wrapper-help`, and implement build/shell/worktree mode selection with unchanged native argv; verify both help aliases work without Podman or `.version` and cause no state/image operations, native `--help` is forwarded, and shell mode clears Pi arguments.
- [x] 1.3 Add an opt-in real-rootless test runner using disposable HOME/workspace on native Linux storage, preserving absolute bind sources for service-backed runs; verify prerequisite failures are actionable, credentials are absent, and fixture cleanup removes only resources it created.
- [x] 1.4 Document mode semantics and test entrypoints in README, wrapper help, and CONTRIBUTING.md; verify examples match parsing and forced build starts the selected session rather than acting as build-only.

## 2. Verified engine and delegated authority

- [x] 2.1 Replace the rootless-only query and remove `PI_ALLOW_ROOTFUL`; verify local/explicit Unix Linux-rootless engines succeed and named, implicit remote, TCP/SSH, slash-only Unix, rootful, and non-Linux cases fail before image operations in normal/build/shell modes, including former override values `1` and `0`.
- [x] 2.2 Implement complete response capture for launch and two-record delegation queries; verify optional single final LF, path spaces, failed queries with valid-looking output, missing/extra fields, unexpected booleans, CR, and additional blank/nonblank records produce the specified outcomes.
- [x] 2.3 Make delegation/client installation depend on exact `PI_ENABLE_PODMAN=1`, introduce `PI_PODMAN_SOCKET` precedence/canonicalization, and verify the exact selected accessible service; test override/Unix/XDG/fallback selection, missing/inaccessible/non-socket/relative paths, rootful responses, and failure before image operations without service auto-start or fallback.
- [x] 2.4 Bind the reported host-side socket to `/run/podman/podman.sock`, reserve connection-variable handling against `PI_ENV_VARS`, and explicitly unset disabled session `CONTAINER_HOST`; verify remapped host paths, exact disabled-value cases, and a real delegated child container using a disposable absolute workspace bind.
- [x] 2.5 Update README, SECURITY.md, and help with removed bypasses, exact opt-in migration, socket selection/remapping, and expanded host authority; verify documented values and precedence match synthetic tests and record real service-check results separately from simulations.

## 3. Private state and physical mount boundaries

- [x] 3.1 Validate physical writable Pi/shared-agent state before image operations and create only missing directories under scoped umask 077; verify private caller-owned directories pass while wrong owner/modes, inaccessible paths, files, and dangling links fail without chmod/chown/replacement or credential imports, using native Linux fixtures.
- [x] 3.2 Preserve read-only configuration with existing readable/traversable physical sources and no creation/write requirement; verify writes fail, missing sources fail before image operations, and read-only mode does not silently modify state.
- [x] 3.3 Use `pwd -P`, same-path absolute workspace binds, physical state sources, and no automatic relabeling; verify symlinks/spaces, default sibling inaccessibility, explicit immediate-parent worktree access with unchanged workdir, and the sensitive-directory guard applied to the exposed parent.
- [x] 3.4 Update README and SECURITY.md with private-state repair/migration, read-only confidentiality limits, parent exposure, and SELinux failure guidance; verify no documented workaround implies automatic labels, permission repair, or weakened confinement.

## 4. Mapped-user workflows and explicit temporary storage

- [x] 4.1 Run sessions with keep-id and explicit caller UID/GID, remove all capability additions, and adapt image/tool/home ownership without changing host state; verify synthetic create flags and real process/file identity, no-new-privileges, dropped capabilities, configured resource limits, and failed rootfs writes.
- [x] 4.2 Disable implicit read-only tmpfs provisioning and explicitly configure `/tmp`, `/var/tmp`, `/run`, and caller-owned npm cache with the spec's capacities/access/flags; apply bounded hardened policy to retained delegated-client stores and verify real mount flags, mapped-user writes, capacity/exhaustion, noexec behavior, and cleanup between sessions.
- [x] 4.3 Update `test.sh` to the new identity/mount policy and add credential-free real wrapper checks for Pi help/version, user/project npm extension installation from a disposable fixture, Git commits/worktrees, and optional Bun; verify persisted extension locations and host ownership without restoring capabilities or broad HOME writes.
- [x] 4.4 Update Containerfile comments, README mount/identity diagrams, SECURITY.md privilege claims, help, and CONTRIBUTING.md workflow guidance; verify capacities and writable surfaces match runtime assertions and record any unavailable real checks explicitly.

## 5. Image errors and coherent optional builds

- [x] 5.1 Distinguish image-existence status 1 from operational errors and preserve staleness-inspection failures; verify absence and successful missing/mismatched labels rebuild, failed queries/builds stop without session creation, and unchanged labels reuse the image.
- [x] 5.2 Preserve version/build-input labels, optional Podman/Bun build arguments, pull control, default-deny context, and build timeout; include selected Bun version in hashing and verify changing it triggers rebuild independently of delegation, while dummy credentials/unknown files remain excluded from build context.
- [x] 5.3 Connect `--container-build` to the shared forced-refresh path after all preflights; verify normal and shell combinations, failure ordering, and retained `PI_IMAGE_NAME`, `.version`, and pull behavior, then update README/help stale-image descriptions and correct the Bun hash discrepancy.

## 6. Atomic reservation and transparent attachment

- [x] 6.1 Replace lowest-free lookup plus run with sanitized-prefix max+1 reservation through create; verify stopped containers, `08`, malformed/overlong suffixes, empty/invalid prefixes, concurrent collisions, 20-attempt exhaustion, listing/lookup errors, no replacement, and per-attempt CONTAINER_NAME consistency.
- [x] 6.2 Add private session bookkeeping/CID records and complete full-ID validation; verify mode/privacy, optional one final LF, short IDs/NUL/CR/extra records, create failure with a valid owned CID, and absence of destructive operations by name or prefix.
- [x] 6.3 Attach by full ID with preserved fd 0 and explicit signal-proxy handling; verify redirected/piped input and EOF, TTY only for terminal stdin/stdout, ordinary application statuses including 125, and real concurrent sessions without input loss.
- [x] 6.4 Place configured `PI_RUN_TIMEOUT` before the image as a native create option; verify it never enters Pi argv, run a bounded real-engine lifetime check, and document observed supported-engine timeout semantics separately from shutdown deadlines.
- [x] 6.5 Update README/help naming, stream, and timeout descriptions and extend CONTRIBUTING.md lifecycle guidance; verify examples and expected codes match synthetic and real-wrapper checks.

## 7. Bounded interruption and owned cleanup

- [x] 7.1 Implement first-signal TERM/INT/HUP recording, PID-assignment race handling, and bounded attached shutdown/control/client-reaping phases; verify 143/130/129, one forwarded signal, repeated mixed signals without deadline renewal, stubborn applications, failed/stalled controls, primary status preservation, and diagnostics within a conservative 35s test bound.
- [x] 7.2 Implement finite interrupted-creation completion/cancellation/reaping and final CID reconciliation; verify permanent stalls before/after publication, CID-on-TERM, successful completion during grace, malformed/missing CID, and failed/stalled removal finish within a conservative 25s test bound without starting/retrying an interrupted session.
- [x] 7.3 Assert private bookkeeping lifetime, full-ID-only removal, and local-client cleanup using readiness/PID markers and unreleased permanent-stall fixtures; verify unrelated concurrent sessions survive, unknown ownership never triggers name deletion, and cleanup failure cannot replace application exit 125 or first interruption status.
- [x] 7.4 Add real-rootless signal/concurrency/owned-cleanup regressions and update README, SECURITY.md, help, and CONTRIBUTING.md with phase budgets, cancellation limits, residual resources, and manual inspection guidance; verify real results are recorded separately from injected synthetic hangs.

## 8. Integration acceptance and evidence

- [x] 8.1 Run the completed wrapper suite, `bash -n pi-container.sh test-wrapper.sh test.sh`, ShellCheck, applicable image/Markdown lint, `git diff --check`, and `openspec validate align-container-execution-and-sandboxing --strict`; verify CI includes the new test support while preserving existing smoke/scan entrypoints.
- [x] 8.2 Run real rootless wrapper acceptance and image smoke checks with disposable native Linux state and no provider credentials, including delegation disabled/enabled and optional Bun; record exact commands/results, prerequisites, synthetic stall evidence, and unperformed authenticated operations in `docs/validation.md` without counting skipped checks as passes.
- [x] 8.3 Reconcile every `todo.md` item against the capability scenarios and validation evidence, confirm README/SECURITY/help/CONTRIBUTING agree, and mark only demonstrated implementation tasks complete; verify unrelated `.version` and pre-existing workspace changes remain untouched.

## Workflow follow-up

- Synchronize the four capability deltas into main specs after implementation acceptance.
- Archive this change with the archive workflow and validate the resulting main specifications.

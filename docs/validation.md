# Validation evidence

Change: `align-container-execution-and-sandboxing`, 2026-11-03.

## Environment and boundaries

- Linux rootless Podman through an explicit same-host Unix service.
- Podman client 4.3.1 and service 4.9.3.
- Caller UID/GID 1000:1000; state/workspaces in a disposable native Linux volume.
- Pi version comes from the pre-existing `.version` value, 0.80.8; it was not changed by this implementation.
- Production image remains Node-based. A separate disposable Python/Podman runner provides test tooling.
- No provider credentials or authenticated model requests are used.

## Synthetic evidence

Final `bash test-wrapper.sh` passed all **47 tests in 269.733s**. An earlier
complete run passed 42 tests in 282.204s; the final suite also includes prefix
fallback/full CID records, forced-build input preservation, missing successful
CID diagnostics, runtime-runner prerequisite/image guards, and retained
editor/gitconfig/secret controls. Coverage includes complete engine records,
failure-before-image ordering, exact opt-in/socket remapping, native Linux
permission checks, TTY/input/EOF, image errors/hashes, naming, exit 125, all
handled signals, permanent creation stalls, CID-on-TERM, repeated mixed signals,
failed/stalled controls, client reaping, owned cleanup, and private bookkeeping
release. No synthetic tests were skipped in the final run.

Wrong-owner/non-enforcing metadata and unkillable-client branches use controlled
fixtures; they do not claim actual filesystem emulation or uninterruptible kernel
processes. Creation stalls are injected synthetic clients, not real engine hangs.

## Real rootless acceptance

The initial disposable-image `bash test.sh --image localhost/pi-acceptance-20261103`
run passed build-context exclusion, concurrent reservation with a stopped `08`
container, private/read-only state, native container lifetime timeout, and real
signal forwarding/owned cleanup. Pi help/version, local-tarball npm extension
installation in user/project scopes, Git commits, and worktree creation completed
before the combined optional-Bun check failed.

That run was not an acceptance pass: two interactive build checks hit the test
harness deadline, the mount-check JavaScript fixture contained an incorrectly
escaped newline, and one subsequent preflight timed out. Corrective changes:
private tmpfs ownership uses Podman's `U` option (raw uid/gid options are rejected
by the tested engine); builds receive `/dev/null` so they cannot consume session
input; tests allow the existing 300s build budget when optional variants change;
the JavaScript escape was fixed. The production shutdown budgets were unchanged.

The corrected run `bash test.sh --image localhost/pi-acceptance-20261103-r2`
passed all 9 runtime tests in 60.228s. A final run with direct runtime-limit
inspection and delegated-storage lifetime checks,
`bash test.sh --image localhost/pi-acceptance-20261103-final`, passed all 10
runtime tests in 62.916s, including optional Bun 1.3.14. The runner and selected
image tags were removed by their owned cleanup paths.

Real checks verified UID/GID and resulting file ownership; no-new-privileges,
zero effective capabilities, read-only rootfs; 4 GiB memory, 2 CPUs, and 512 PIDs;
explicit tmpfs flags, access, capacity/exhaustion, noexec, private npm/delegated
storage, and ephemeral lifetime; extension persistence in both scopes; physical
workspace/parent boundaries and Git worktrees; delegated children and a nested
caller with a remapped Unix socket; TTY and redirected stdin/EOF; application
exit 125; concurrent name reservation; signals and owned cleanup while an
unrelated stopped container survives. Native one-second container lifetime
returned 255 on this service. This is observed behavior, not a portable exit-code
guarantee, and is separate from shutdown budgets.

## Static checks

- `bash -n pi-container.sh test-wrapper.sh test.sh tests/run-runtime.sh` passed.
- ShellCheck (containerized `docker.io/koalaman/shellcheck:stable`) passed for all four scripts.
- Hadolint (`docker.io/hadolint/hadolint:latest-alpine`) passed for production and runner Containerfiles.
- Markdownlint (`docker.io/davidanson/markdownlint-cli2:latest`) passed README, SECURITY, CONTRIBUTING, CHANGELOG, validation evidence, and all change Markdown.
- `openspec validate align-container-execution-and-sandboxing --strict` passed.
- `git diff --check` passed.

Tool containers used same-path read-only workspace binds with keep-id; missing
host lint binaries were not treated as unavailable checks. GitHub-hosted CI was
updated to start its own rootless service for the same smoke/runtime entrypoint;
this session did not execute a remote CI job.

No missing or skipped check is counted as a pass. No guarantee is claimed for
SIGKILL, lost engine ownership, delayed server outcomes, or authenticated Pi
operations. Actual SELinux denial injection and an actual unresponsive engine
were not performed; synthetic contracts verify no relabel/security override and
bounded failure handling.

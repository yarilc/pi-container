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

## Common specification names: 2026-11-09

The OpenSpec capabilities were renamed to the scheme shared by the five wrappers (Wave 1, `sandbox-ref-2`). Requirements and scenarios are unchanged; only directory names and spec titles changed. Earlier sections and archived changes keep the names that were current at the time.

| Previous name | Current name |
| --- | --- |
| `container-wrapper` | `container-launcher` |
| `container-engine` | `container-podman-access` |
| `container-filesystem` | `container-isolation` |

`openspec validate --specs` passed: 4 specs, 0 failures.

## Narrowed exposed state (A07, A09): 2026-11-09

Change `narrow-exposed-state` (Wave 2). Host: rootless Podman 4.9.3 server.
Image `pi-container` (`d2c47c167ea5`), unchanged by this change. No credentials,
Pi login or model requests were used.

Behavior changes:

- `~/.gitconfig` is no longer mounted by default. Exact
  `PI_CONTAINER_GITCONFIG=1` mounts it read-only at `$HOME/.gitconfig` from its
  physical file. The opt-in fails before any engine query when the path is not
  a regular file.
- `PI_MOUNT_GITCONFIG` is a deprecated alias that prints a warning: `1` mounts
  and `0` does not. Other values, and conflicts with `PI_CONTAINER_GITCONFIG`,
  are errors.
- While `~/.gitconfig` exists and neither variable is set, one notice explains
  the change; `PI_CONTAINER_GITCONFIG=0` silences it.
- The three `.wrapper-test-*` directories from 2026-07-02 were removed. They
  held only a fake `podman` and empty `home` and `project` directories from the
  shell suite replaced in `651c9bc`. `.test-state/` is now ignored.

| Check | Result |
| --- | --- |
| Unit discovery in a runner container (wrapper tests; runtime tests skipped without opt-in) | 62 tests, OK (11 skipped) |
| New wrapper cases | default without mount and with notice; exact opt-in from a symlink's physical target; non-exact values; missing and directory paths; alias in both directions; conflicts; invalid alias values; help; no scratch directories |
| `bash tests/run-runtime.sh` (real rootless engine) | 11 tests, OK |
| New real-engine case | `~/.gitconfig` absent by default; with the opt-in, readable through `git config --global` and not writable; host file unchanged |
| `bash -n`, ShellCheck (`pi-container.sh`, `test.sh`, `test-wrapper.sh`, `tests/run-runtime.sh`), `git diff --check` | Passed |
| Markdownlint (README, SECURITY, CHANGELOG, validation evidence, change Markdown) | 0 errors |

Initial failures and reruns: the change Markdown first failed markdownlint
(missing blank lines and no top-level heading in the delta specs). It was
reformatted to the repository's `# Spec Delta` convention and rerun. The two
pre-existing `project-with-spaces-0/1` containers from 2026-11-03 were present
before and after the runs and were left untouched.

## Common wrapper baseline (A01, A02, A08, A11): 2026-11-09

Change `align-wrapper-baseline` (Wave 2). Host: rootless Podman 4.9.3 server.
Image `pi-container` (`d2c47c167ea5`, Pi 0.80.8), unchanged by this change. No
credentials, Pi login or model requests were used.

Pi approval facts, from `pi --help` on that image: Pi exposes no tool-approval
option and runs its tools without prompts. `--approve`/`-a` means "Trust
project-local files for this run". The wrapper therefore has no YOLO switch;
`PI_CONTAINER_YOLO` only prints a warning that it has no effect.

Behavior changes:

- **Common names.** Wrapper settings use `PI_CONTAINER_IMAGE`,
  `PI_CONTAINER_PODMAN`, `PI_CONTAINER_PODMAN_SOCKET`,
  `PI_CONTAINER_MEMORY_LIMIT`, `PI_CONTAINER_CPU_LIMIT`,
  `PI_CONTAINER_PIDS_LIMIT`, `PI_CONTAINER_RUN_TIMEOUT` and
  `PI_CONTAINER_ALLOW_UNSAFE_WORKSPACE`. The earlier names warn, and
  conflicting old and new values fail before engine queries.
- **Budgets and lifetime.** They are validated with the `sandbox-ref-2` rules;
  only an unset variable selects a default. The created container is inspected
  and started only when the configured budgets match. A lifetime stop prints a
  notice and keeps the client status.
- **Sensitive workspaces.** The guard uses the reference refused set on
  physical paths, which adds `/tmp` and `/mnt/<letter>`, and only exact `1`
  overrides it.

| Check | Result |
| --- | --- |
| Unit discovery in a runner container (wrapper tests; runtime tests skipped without opt-in) | 71 tests, OK (14 skipped) |
| New wrapper cases | alias table (old alone, new alone, equal, conflicting, switch meaning); every rejected budget and lifetime form with no engine call or state; inspection mismatch and failure removing only the owned container without start; lifetime notice and early exit; refused roots including `/tmp`, `/mnt/d` and a symlink to `/etc`, worktree parent, exact and non-exact override and the old alias; YOLO warning with unchanged arguments; help |
| `bash tests/run-runtime.sh` (real rootless engine) | 14 tests, OK |
| Effective hardening | Zero capability sets, `NoNewPrivs: 1`; `memory.max=4294967296`, `pids.max=512`, `cpu.max=200000 100000` by default and `1610612736`/`256`/`150000 100000` overridden, with and without delegation |
| Process limit 32 | Process creation refused inside the session |
| Lifetime (`PI_CONTAINER_RUN_TIMEOUT=3`, `sleep 30`) | Stopped; client status 255; notice printed. Early exit kept status 4 without notice |
| Refused home workspace | Exit 1 before engine use |
| `bash -n`, ShellCheck, hadolint with `.hadolint.yaml` (production and runner Containerfiles), `git diff --check` | Passed |
| Markdownlint (README, SECURITY, CONTRIBUTING, CHANGELOG, AGENTS, validation evidence, change Markdown) | 0 errors |

The README was reordered into the common section order: requirements, quick
start, optional Podman API access, usage, environment, mounts and security,
included tools, troubleshooting, verification, migration, security and
license. A sentence-level comparison with the previous file found only renamed
variables and the intentionally rewritten guard, budget and table rows.

Initial failures and reruns:

- **Wrapper tests, first run.** Two existing assertions expected the old help
  text and unconverted budget flags. After that, the new rejection cases
  failed because a state directory created earlier in the same test was
  checked. The rejected cases now use a fresh home.
- **README reorder.** The first attempt missed four trailing sections and
  demoted the Podman subsections one level too far, which markdownlint caught.
- **hadolint.** Run from stdin, it ignored `.hadolint.yaml` and reported DL3008.
  The documented command now passes the configuration, as CI does.

Containers present on the host before and after the runs (`project-with-spaces-0/1`
from 2026-11-03, `project-0`, `strange_allen` and the agent's own session) were
not created by these tests and were left untouched.

## Runtime image and container home (A03, A04, A05, A06): 2026-11-09

Change `align-runtime-image` (Wave 2). Host: rootless Podman 4.9.3 server. No
credentials, Pi login or model requests were used.

Pinned inputs:

- base `docker.io/library/node:22-bookworm-slim@sha256:4b150b48b4116e2a22f2c39cc27025fbf4f153e2078fd3b14d159fdb5c7279da`;
- `@earendil-works/pi-coding-agent@0.80.8` (from `.version`);
- `@fission-ai/openspec@1.16.0`;
- optional `bun@1.3.14`.

npm channel facts: `npm view` reports a registry SHA-512 integrity for Pi
0.80.8 and `bun@1.3.14`. Bun's platform binaries (`@oven/bun-linux-x64` and
others) are exact-version optional dependencies selected by its postinstall.
The build fails unless `pi --version`, `openspec --version` and, with Bun,
`bun --version` report the recorded versions. A build with a nonexistent
`PI_VERSION` failed as expected.

Baseline before the change: the previous `pi-container` image (`d2c47c167ea5`,
floating base) had `HOME=/home/node` in the image. It lacked `openspec`,
`podman` (without the delegation variant), `bwrap`, `bzip2`, `curl`, `file`,
`gawk`, `jq`, `less`, `patch`, `ps`, `python3`, `unzip`, `xz` and `zip`.

After the change, in real sessions:

- every toolset command, `pi`, `openspec` and `podman` are present;
- `HOME=/pi-home` is a tmpfs, and the host `~/.pi` and `~/.agents` are seen at
  `/pi-home/.pi` and `/pi-home/.agents`;
- a scratch file in the home disappears after the session, while state writes
  persist;
- `PI_CONTAINER_STATE_DIR` persists its whole home across sessions with mode
  700 and leaves `~/.pi` untouched;
- the explicit Bun build reports `bun --version` 1.3.14 and runs a script;
- the same image launched without `PI_ENABLE_BUN` stops as stale and names
  `--container-build`.

| Check | Result |
| --- | --- |
| Unit discovery in a runner container (wrapper and pin tests; runtime tests skipped without opt-in) | 76 tests, OK (15 skipped) |
| New wrapper cases | stale image stops without build or create; missing image builds; explicit build passes only `PI_VERSION` and `INSTALL_BUN`; Bun selection changes the hash; one warning each for `PI_BUN_VERSION` and `PI_PULL_ALWAYS`; dedicated home destinations; isolated state in writable and read-only modes with invalid, foreign and overlapping values; help |
| `tests/test_image_pins.py` | Passes; mutated recipes (tag-only base, `@latest`, unversioned package, version range, missing package, `curl \| bash` installer, missing toolset package) fail |
| `./test.sh` (disposable image build plus `tests/run-runtime.sh` with Bun) | 15 tests, OK, run twice (before and after the last wrapper edit) |
| Build context | Only `Containerfile`, `.containerignore` and `.version` reach the build |
| Lifetime | Status 255 with the notice, unchanged |
| `bash -n`, ShellCheck, hadolint with `.hadolint.yaml`, `git diff --check` | Passed |
| Markdownlint (README, SECURITY, CONTRIBUTING, CHANGELOG, AGENTS, validation evidence, change Markdown) | 0 errors |

Initial failures and reruns:

- **Wrapper suite.** After the code change, seven existing assertions failed
  as expected because they named host-path destinations, the old build
  arguments or the automatic stale rebuild. They now expect the new layout and
  policy.
- **Pin test parser.** The parser copied from Codex read the `if` clause
  around the Bun install as package names. It now reads only the text after
  `npm install`.
- **Runtime Bun check.** It relied on the automatic stale rebuild. It now builds
  a disposable Bun image explicitly with `--container-build`, checks that the
  stale stop happens, and removes the image.
- **ShellCheck.** It reported SC2015 on the new private-mode check. The line is
  annotated, because `die` must also run when the second test fails.

The agent sandbox has a read-only home, so the image was built through
`./test.sh` and the wrapper's `--container-build` inside the runtime suite. The
operator's existing `pi-container` image (`d2c47c167ea5`) was not rebuilt, so
its next launch reports it as stale and asks for `--container-build`. The
`localhost/pi-align-test:bun` image built during the investigation was
removed. Containers present before the runs were left untouched.

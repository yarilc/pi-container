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

## Network egress port (`add-network-egress`): 2026-11-10

Target: WSL2 kernel 6.6.87.2, Podman client 4.3.1 and server 4.9.3, Netavark.
The runtime image `localhost/pi-container:latest` was rebuilt from the current
recipe: ID `39082eebb4b7…`, Pi 0.80.8, Python 3.11.2, OpenSSL 3.0.22. The
previous tag predated Wave 2 and had no `python3`.

### Measured Pi endpoints and controls

Method: a static scan of the installed `@earendil-works/pi-coding-agent` 0.80.8
package, plus credential-free `pi -p` runs in `--network=none` containers.
`HTTPS_PROXY` pointed at a loopback proxy that logged every request and
answered 403. Every run used dummy keys.

| Use | Host | Key variable read by Pi |
| --- | --- | --- |
| Anthropic | `api.anthropic.com` | `ANTHROPIC_API_KEY` |
| OpenAI | `api.openai.com` | `OPENAI_API_KEY` |
| Gemini (`--provider google`) | `generativelanguage.googleapis.com` | `GEMINI_API_KEY`. `GOOGLE_API_KEY`, which the wrapper used to forward, is not read: with only that variable Pi reports a missing key |
| OpenRouter | `openrouter.ai` | `OPENROUTER_API_KEY` |
| Version check and install telemetry | `pi.dev` (`/api/latest-version`; share viewer `pi.dev/session/`) | — |

Optional-traffic controls:

- **Version check and telemetry flags alone.** With `PI_SKIP_VERSION_CHECK=1`
  and `PI_TELEMETRY=0`, a startup request to `pi.dev` remains.
- **`PI_OFFLINE=1`** ("disable startup network operations") removes it and
  still lets the model request through.
- **Writable settings.** With `PI_OFFLINE=1`, a writable
  `~/.pi/agent/settings.json` that enables install telemetry and update checks
  causes no `pi.dev` request.
- **Protected values.** Restricted sessions set `PI_OFFLINE=1`,
  `PI_SKIP_VERSION_CHECK=1` and `PI_TELEMETRY=0`.

Subscription and OAuth logins (`/login`) were not measured. They have no
profile and remain unsupported in restricted modes.

### Node client behavior

Pi on Node 22 sends its HTTPS requests as CONNECT through `HTTPS_PROXY`.
A fixture CA was tested with a `CA:FALSE`, `serverAuth` leaf certificate for
`api.anthropic.com`, behind a CONNECT proxy:

| CA setting | Result |
| --- | --- |
| No CA variable | Refused: the TLS handshake was closed by the client |
| `NODE_EXTRA_CA_CERTS` | `POST /v1/messages` reached the fixture |
| `SSL_CERT_FILE` alone | Refused; Node does not read it |

The host CA contract sets all four variables, so `NODE_EXTRA_CA_CERTS` covers Pi.

### Pi under the guard (offline)

The guard was packaged from toolchain `localhost/pi-guard-toolchain:development`
(`0b69ba43c894…`, the reference toolchain). Its SHA-256 is
`0c647dfea75667a46a8cd4cc4dfea4ee3d10363752ea7ce5957162bacd6d7ec9`, identical
to Claude, Codex and OpenCode. The proxy image `localhost/pi-egress:local` is
`13adbfafd7bd…`, the same agent-neutral image. The runs used Pi's layout:

- `--network=none`, private PID and IPC namespaces, a read-only root, no
  capabilities and no-new-privileges;
- noexec tmpfs mounts for `/tmp`, `/var/tmp`, `/run` and `/pi-home`;
- the npm cache tmpfs, and `.pi` and `.agents` bind-mounted below the home.

| Check | Result |
| --- | --- |
| Layout | The guard reported `enforced revision=abi3-seccomp-mux-v1 abi=3` with the noexec home, the npm cache tmpfs and the state binds |
| `pi -p` against a loopback OpenAI-compatible stub (a `models.json` provider with `openai-completions` and base URL `http://127.0.0.1:18080/v1`) | The stub returned a `bash` tool call. The tool wrote the sentinel to the workspace, owned by the caller UID 1000, and the second turn returned `fixture-done` |
| Pi TUI in a PTY | Rendered, then exited with status 0 after `/quit` or two Ctrl+C (about 13 seconds including startup). A first attempt hung only because the test harness sent no Enter and had no timeout |
| `pi --version` | `0.80.8` |
| `npm install` at runtime | Fails (exit status 1): no registry is reachable. Extensions must be preinstalled during maintenance |
| Named Unix socket | Denied (`PermissionError`); `pi -p`, its tools and the TUI need none |
| Bun 1.3.14 (image built with `INSTALL_BUN=1`) | `bun -e` ran under the guard and wrote a workspace file; listening on a Unix socket failed |
| `bwrap` | Only the example extension `examples/extensions/sandbox` references it; Pi itself does not use it |

Runtime images rebuilt from the updated recipe, which copies
`network/relay.py` and `network/mux.py` to `/opt/sandbox-egress/` (both match
by SHA-256):

| Image | ID | Contents |
| --- | --- | --- |
| `localhost/pi-container:latest`, without Bun | `099873e2a000…` | Pi 0.80.8 |
| Disposable Bun variant, removed after the check | `9ec891bf59a4…` | Pi 0.80.8, Bun 1.3.14 |

### Final verification: 2026-11-10

Target as above (WSL2 kernel 6.6.87.2, Landlock ABI 3, Podman client 4.3.1 and
server 4.9.3, Netavark). Shared files at `claude-container` `sandbox-ref-6`
(commit `3150bfe`). Images: `localhost/pi-container:latest` `099873e2a000…`,
`localhost/pi-egress:local` `13adbfafd7bd…`, toolchain `0b69ba43c894…`; guard
SHA-256 `0c647dfe…6d7ec9`.

`sandbox-ref-6` was found during this apply. The wrapper reads `.version`, which
the shared installation manifest of `sandbox-ref-5` did not include, so five
shared qualification tests failed. The reference added the optional profile
field `install.files`; Pi declares `.version`.

| Check | Result |
| --- | --- |
| `bash -n`, ShellCheck | Passed, no findings |
| `--wrapper` | Passed: 71 tests. One run had a `test_lifetime_notice` failure (the known whole-second timing granularity); two reruns of that test passed |
| `--shared` (includes `test_reference_copy.py`) | Passed: 134 tests, 27 skipped (run by the modes) |
| `--qualification` | Passed: 18 tests (before `sandbox-ref-6`: five failures from the missing `.version`) |
| `--network-feasibility`, `--network-policy`, `--mux` | Passed: 1, 14 and 26 tests |
| `--guard`, `--guard-idle` | Passed: 19 tests (1 skipped) and 1 test |
| `--network` (offline, provider, TLS fixture, concurrency, cleanup, `pi -p` with a streamed tool call, TUI) | Passed: 21 tests |
| default (unrestricted runtime suite) | Passed: 15 tests. One run had a `test_native_lifetime_timeout` failure (same timing granularity); two reruns passed |
| `test.sh` | Passed: 15 tests |
| `test-wrapper.sh` | Not runnable on this host: `/tmp` is noexec and `/mnt/d` cannot hold Unix sockets. It runs the same `test_wrapper.py` that `--wrapper` runs in the runner |
| `openspec validate add-network-egress --strict`, `git diff --check` | Valid, clean |

No container, volume or network labeled for `io.pi-container` remained after
the runs; the pre-existing containers were untouched.

Operator-run authenticated checks (real keys for `anthropic-api`,
`openai-api`, `gemini-api` and `openrouter-api`) are unavailable here and
remain pending.

## Guided setup (`add-container-setup`): 2026-11-10

Target as in the network egress port (WSL2 kernel 6.6.87.2, Landlock ABI 3,
Podman client 4.3.1 and server 4.9.3, Netavark). Shared files at
`claude-container` `sandbox-ref-8` (commit `12cffab`). Images:
`localhost/pi-container:latest` `099873e2a000…`, `localhost/pi-egress:local`
`13adbfafd7bd…`, toolchain `0b69ba43c894…`.

Two reference tags were created during this change:

- `sandbox-ref-7` adds the optional profile field `install.runtime_build`. Pi
  declares `wrapper`, so setup builds the runtime image through
  `pi-container.sh --container-build` with the `PI_VERSION` and `INSTALL_BUN`
  build arguments and the `build-inputs-hash` label. A plain `podman build`
  would produce an image the staleness check refuses.
- `sandbox-ref-8` fixes the shared `tests/test_setup.py`: one test patched
  `build_image`, which `prepare_artifacts` reaches only on the default `recipe`
  path. It now patches `build_runtime`. No setup code changed.

Codex and OpenCode adopted both tags before this copy, with `--shared`,
`--setup` and `--qualification` passing.

### Guided setup in provider mode with the `gemini` method

Recorded by `tests/test_setup_runtime.py`
(`test_provider_gemini_transcript`) under a pseudo-terminal, with a disposable
`HOME`, no API key set and no systemd changes:

- The residual exfiltration notice listed `api.anthropic.com`,
  `api.openai.com`, `generativelanguage.googleapis.com` and `openrouter.ai`,
  and required an explicit acknowledgement.
- The method `gemini` saved the protected profile `gemini-api`.
- The maintenance review asked for authorization before any image or guard
  preparation.
- The guard reported `abi3-seccomp-mux-v1`, followed by
  `Sandbox qualification: locally-qualified` and `Sandbox: ready`.
- Setup ended with `Authentication pending. Supply GEMINI_API_KEY`.
- The managed `--version` launch printed `0.80.8` with no
  `PI_CONTAINER_YOLO` warning (the saved value was `0`).

### Final verification

| Check | Result |
| --- | --- |
| `bash -n`, ShellCheck | Passed, no findings |
| `--wrapper` | Passed: 74 tests |
| `--shared` (includes `test_reference_copy.py` and `test_alignment.py`) | Passed: 144 tests, 27 skipped (run by the modes) |
| `--setup` (shared `test_setup.py`, unchanged) | Passed: 64 tests |
| `--setup-runtime` (offline, provider, unrestricted, wrapper-built runtime image, Gemini transcript) | Passed: 4 tests |
| `--qualification` | Passed: 18 tests |
| `--network` | Passed: 21 tests |
| default (unrestricted runtime suite) | Passed: 15 tests |
| `test.sh` | Passed: 15 tests |
| `test-wrapper.sh` | Not runnable on this host, as before; `--wrapper` runs the same `test_wrapper.py` |
| `openspec validate add-container-setup --strict`, `git diff --check` | Valid, clean |

No container, volume or network for `io.pi-container` remained after the runs.
Pre-existing containers and images were untouched.

Operator-run authenticated checks for the four profiles remain pending.

## Adoption of `sandbox-ref-9`: 2026-11-10

`claude-container` tag `sandbox-ref-9` (commit `8b191e5`) lets an account method
declare empty `login_args`, so setup can offer sign-in inside the interactive
agent (needed by Antigravity, whose CLI has no login command). The changed
shared files `network/agent_profile.py`, `setup/setup.py`,
`tests/test_agent_profile.py` and `tests/test_setup.py` were copied unchanged;
the `tests/test_reference_copy.py` manifest moved to the tag. Pi's API-key
methods keep their current setup behavior.

| Check | Result |
| --- | --- |
| `bash tests/run-runtime.sh --shared` | Passed: 145 tests, 27 skipped (run by the modes) |
| `bash tests/run-runtime.sh --setup` | Passed: 65 tests |
| `bash tests/run-runtime.sh --setup-runtime` | Passed: 4 tests |

## Adoption of `sandbox-ref-10`: 2026-11-11

Copied from `claude-container` tag `sandbox-ref-10` (commit `0f6585f`):

- `network/agent_profile.py`, `setup/common.py`, `setup/setup.py`;
- `tests/test_agent_profile.py`, `tests/test_setup.py`.

The `tests/test_reference_copy.py` manifest moved to the tag.
`agent/profile.json` sets `native.private_shared_dirs: true`. The cause was an
operator setup that failed with only `Setup command failed (exit 1)`: the
wrapper refused a non-private `~/.agents` in the smoke launch, while setup had
checked only `~/.pi`. Setup now refuses that directory before image work and
shows the smoke stderr on failure.

| Check | Result |
| --- | --- |
| `bash tests/run-runtime.sh --shared` | Passed: 146 tests, 27 skipped (run by the modes) |
| `bash tests/run-runtime.sh --setup` | Passed: 68 tests |
| `bash tests/run-runtime.sh --setup-runtime` | Passed: 4 tests, after a rerun (see below) |
| `bash tests/run-runtime.sh --wrapper` | 74 tests; 72 passed. `test_permanently_stalled_creation_signal_matrix` failed in 2 subtests on `elapsed > 3` (2.6 to 2.9 s), also when run alone. The same timing failure occurs on `main` in `codex-container`, and this adoption changes neither the wrapper nor `test_wrapper.py`. It is recorded as an environment timing issue after the host crash, not a regression |

A first run of all wrappers' suites was interrupted by a host crash. The crash
left a test-runner image (`pi-runtime-runner-1000-124363`) whose cached package
layer had an empty `libsubid.so.4.0.0`, so the next `--setup-runtime` run failed
with `podman: error while loading shared libraries`. After that image was
removed, the rerun built a fresh layer and passed.

## Operator authenticated session: 2026-11-11

The operator ran an authenticated Pi session in provider mode with the
setup-default profile `anthropic-api`. In the TUI, they asked the model to confirm
that it could use the harness tools and to report the sandbox's access limits.
The model did both, and the operator found the result correct.

Setup succeeded after `PI_ENABLE_BUN` was unset and `~/.agents` was made
private. `sandbox-ref-10` now refuses a non-private `~/.agents` before image
work. A Bun image still fails qualification, which is an open decision.

This covers an authenticated model request with tool use through the sandbox.
The `openai-api`, `gemini-api` and `openrouter-api` profiles remain pending. Full profile verification under the readiness checklist is not
claimed. The checklist also covers streaming and long-lived requests,
WebSockets, sign-in, token reuse and refresh, CA behavior and shell mode.

## Adoption of `sandbox-ref-12` and lab-host fixes (`adopt-lab-host-fixes`): 2026-11-12

Copied from `claude-container` tag `sandbox-ref-12` (commit `fd196c9`),
adopted directly from `sandbox-ref-10`:

- `network/.containerignore`, `network/README.md`, `network/agent_budgets.py`;
- `network/control.py`, `network/guard-build.Containerfile`, `network/guard.c`;
- `network/proxy.py`, `network/proxy_hardening.py`;
- `network/qualification_peer.py`, `network/qualification_probe.py`,
  `network/qualification_records.py`, `network/qualification_runtime.py`;
- `network/qualify.py`, `network/session.py`;
- `setup/setup.py`, `setup/smoke.py`;
- `tests/test_guard.py`, `tests/test_network_policy.py`,
  `tests/test_qualification.py`, `tests/test_session.py`, `tests/test_setup.py`.

The `tests/test_reference_copy.py` manifest moved to the tag.

A first adoption of `sandbox-ref-11` was discarded, as `docs/propagation.md`
requires. The shared
`test_runtime_build_receives_host_ca_only_when_trusted` assumed
`runtime_build: recipe` and failed for Pi's wrapper-built runtime.
`sandbox-ref-12` fixes that test and also runs every qualification container
in `/`.

Pi adaptations, equivalent to the Codex and OpenCode ports:

- the Podman 5 `unix://` socket report is reduced to its pathname;
- each budget is requested only when its cgroup controller is delegated,
  with notices, and the inspection requires enforced budgets and no
  unenforced one;
- the `/run/secrets` mask;
- a `noexec` `/dev`, `devpts` and an empty read-only `/dev/shm` instead of
  `--read-only-tmpfs=false`. The `noexec` `/tmp`, `/var/tmp`, `/run`, the
  home, the npm cache and the delegated Podman storage tmpfs are unchanged;
- the host CA selection moved into `select_ca_bundle()`, before any build,
  so the build-only refresh that setup uses also passes the `build-ca`
  secret. The secret does not enter `build-inputs-hash`;
- `.containerignore` admits `podman-build-secret*`;
- Debian packages are fetched over verified HTTPS in the first `RUN`.

The pin tests also reject a future `WORKDIR` that no build step creates. Pi
declares none.

| Check | Result |
| --- | --- |
| `python3 -m unittest discover -s tests` (disposable container, private executable tmpfs) | Passed: 358 tests, 68 skipped |
| `python3 -m unittest discover -s tests -p test_wrapper.py` | Passed: 81 tests. New cases: socket URL and invalid `unix://` values; every subset of controllers; unverifiable lists; unenforced budget present or enforced budget missing; device and secrets mounts in every unrestricted mode, offline and provider; proxy secrets mask and budgets; build secret for build-only and launch builds with and without trust, with an unchanged staleness label; an invalid bundle stops build-only before image operations |
| `python3 -m unittest tests.test_image_pins` | Passed: 7 tests. Transport, toolchain and workdir checks with mutations adapted to Pi's two-step recipe; the toolset check accepts `apt-get -o ... install` |
| `bash tests/run-runtime.sh --shared` | Passed: 159 tests, 28 skipped |
| `bash tests/run-runtime.sh --setup` | Passed: 71 tests |
| `bash tests/run-runtime.sh --setup-runtime` | Passed: 4 tests, including the wrapper-built runtime |
| `bash tests/run-runtime.sh --qualification` | Passed: 27 tests, with `localhost/pi-guard-toolchain:development` (`215f5ffc1023`) |
| `bash tests/run-runtime.sh --guard` | Passed: 20 tests, 1 skipped (the 305-second idle check) |
| `bash tests/run-runtime.sh --network` | Passed: 21 tests |
| `bash tests/run-runtime.sh` (`test_runtime.py`) | Passed: 15 tests |
| `./test.sh` (disposable image with Bun, real wrapper checks) | Passed: 15 tests; the test image was removed |
| Runtime image via `PI_CONTAINER_NETWORK=unrestricted PI_CONTAINER_MAINTENANCE=1 PI_CONTAINER_IMAGE=localhost/pi-container:adopt-ref-11 ./pi-container.sh --container-build` | Image `9d90d493f905`. Debian sources `https://`, no `/tmp/apt-bootstrap-ca.pem`, `ca-certificates` installed, Pi `0.80.8` (`.version`), OpenSpec `1.16.0`, no `WORKDIR` (`/`). The `build-inputs-hash` label equals the launcher's current hash (`d37f2c98…`) |
| `bash -n pi-container.sh test-wrapper.sh test.sh tests/run-runtime.sh`, `git diff --check`, `openspec validate adopt-lab-host-fixes --strict` | Passed, clean, valid |
| Parity table | SHA-256 `4079aef2ddc9883bf8208deb0c0906cc825f9228a2a6198b901b9b523d1eb376`, identical to claude-container. Codex and OpenCode will match after adopting `sandbox-ref-12` |
| Operator `--container-setup` on this host | First run failed: the qualification security-probe container was created but never started within the 30-second probe timeout (engine stall). The same invocation completed in under a second right after. The leftover created container was removed. Second run passed (operator-reported, 2026-11-12) |
| Operator `--container-setup` on the Rocky Linux 9 lab host | Passed (operator-reported, 2026-11-12): runtime, toolchain and proxy images rebuilt (tag suffix `setup-c46d9009767b4c8084aeb29378e5e168`); `Sandbox qualification: locally-qualified`; `Sandbox: ready`; both state directories private. Authentication pending (`anthropic-api` key supplied at launch); no authenticated model request |
| Operator `--container-setup` on the newer WSL host | First run failed: the setup's build-only refresh inherited `PI_ENABLE_BUN=1` from the operator's shell (image label = Bun inputs), while qualification keeps only `PATH`, `CONTAINER_HOST` and budgets, so the launcher computed the non-Bun hash and reported the image as stale. After removing `PI_ENABLE_BUN` from the environment, the second run passed (operator-reported, 2026-11-12): images rebuilt (tag suffix `setup-b747721ff2304ba89dfcef90bab26e06`), `locally-qualified`, `Sandbox: ready`; authentication pending (`OPENROUTER_API_KEY` supplied at launch). Bun selection for setup and restricted modes remains an open decision |

Every Pi image is stale until rebuilt (the `Containerfile` and
`.containerignore` change), and restricted installations rerun setup.

## Engine-provided `/dev` for pseudo-terminals: 2026-11-12

Change `use-engine-dev-for-pseudo-terminals`, launcher only, as in the Claude
reference (claude-container `docs/validation.md`, same title), Codex and
OpenCode. No shared file changes.

Pi and shell containers no longer mount their own `/dev` tmpfs or `devpts`.
The explicit `devpts` from `sandbox-ref-11` took the kernel defaults
`mode=600,ptmxmode=000`, so no process in a session could open a
pseudo-terminal ("out of pty devices"). The terminal itself attached,
because the engine allocates the console outside that `devpts`. The engine's
`devpts` is `mode=620,ptmxmode=666`.

On Podman 5, `/dev` is now the engine's writable tmpfs without `noexec`.
Pi's own temporary mounts are all `noexec`, so this is a policy change. The
workspace bind mount was already writable and executable. The requirement
"Terminal-compatible device mounts" is replaced by "Engine-provided device
mounts allow pseudo-terminals".

| Check | Result |
| --- | --- |
| Image `5428725d0274` (`localhost/pi-container:setup-7c06…`, from the operator's setup on this host) with the previous `/dev` arguments | `pty.openpty()`: "out of pty devices" |
| `test_pseudo_terminals_and_device_masks` (new) with the previous launcher | Failed: "out of pty devices" |
| `test_pseudo_terminals_and_device_masks` with the fix | Passed |
| `tests/test_wrapper.py` | Passed: 81 tests. With the previous launcher, the updated assertions fail (12 failures) |
| `python3 -m unittest discover -s tests` (disposable container, private executable tmpfs) | Passed: 359 tests, 69 skipped (the runtime tests are opt-in) |
| `bash tests/run-runtime.sh` (`test_runtime.py`, same image) | Passed: 16 tests, including `test_identity_storage_hardening_and_ephemeral_lifetime` and `test_pseudo_terminals_and_device_masks` (`PI_ENABLE_BUN` unset) |
| Operator `--container-setup` on this host, the Rocky Linux 9 lab host and the newer WSL host | Passed (operator-reported, 2026-11-13) on all three hosts, with `PI_ENABLE_BUN` unset |

Qualification digests the launcher, so restricted installations rerun
`--container-setup`. The runtime image is unchanged.

## Bun removal: 2026-11-13

Change `remove-bun`, Pi-specific files only. No shared file changes.

The image no longer offers the optional Bun runtime. Setup always built the
runtime image without Bun, and qualification could not accept an image built
with it, so a `PI_ENABLE_BUN` left in the operator's shell made the setup
fail as stale (see "Operator `--container-setup` on the newer WSL host"
above). This closes the open Bun decision recorded there.

- `Containerfile` has no `INSTALL_BUN` or `BUN_VERSION`; the image has a
  single variant.
- `pi-container.sh` no longer reads `PI_ENABLE_BUN`. `PI_BUN_VERSION` is no
  longer warned about, while `PI_PULL_ALWAYS` still is. The build passes only
  `PI_VERSION`.
- The `build-inputs-hash` covers exactly the five build-context files, so
  every existing runtime image is stale once.

| Check | Result |
| --- | --- |
| `tests/test_image_pins.py` with the previous recipe | Failed as intended: `unexpected package is installed: bun@1.3.14`. New cases: unexpected package; the unversioned-package and remote-installer mutations now use OpenSpec |
| Updated `tests/test_wrapper.py` cases with the previous launcher | Failed as intended (build arguments, inert `PI_ENABLE_BUN`/`PI_BUN_VERSION`, help text) |
| `tests/test_image_pins.py` with the change | Passed: 7 tests |
| `tests/test_wrapper.py` | Passed: 81 tests |
| `python3 -m unittest discover -s tests` (disposable container, private executable tmpfs) | Passed: 359 tests, 69 skipped (the runtime tests are opt-in) |
| `./test.sh` (disposable image built without Bun, then `tests/run-runtime.sh`) | Passed: 16 tests, including `test_native_pi_help_version_npm_git_and_no_bun` (`bun` absent) and `test_pseudo_terminals_and_device_masks`; the test image was removed |
| `grep -rni bun` over live files | Remaining hits: existing dated records, existing changelog entries, the removal notes in `README.md` and `CHANGELOG.md`, and test assertions that Bun is absent or inert |
| Operator `--container-setup` on this host, the Rocky Linux 9 lab host and the newer WSL host | Passed (operator-reported, 2026-11-13) on all three hosts, provider mode with the `openrouter-api` profile |

Qualification digests the launcher and the runtime image changes, so every
installation reruns `--container-setup`.

## Adoption of `sandbox-ref-16` and the toolchain library (`adopt-sandbox-ref-16`): 2026-11-14

Copied from `claude-container` tag `sandbox-ref-16` (commit `1fa091e`),
adopted directly from `sandbox-ref-12`:
`network/agent_profile.py`, `network/control.py`,
`network/qualification_records.py`, `setup/common.py`,
`tests/test_alignment.py`, `tests/test_qualification.py`,
`setup/toolchains.py`, `tests/test_toolchains.py`.
The `tests/test_reference_copy.py` manifest moved to the tag.

Wrapper port of the reference toolchain library (claude-container
`add-toolchain-library`; Codex `adopt-sandbox-ref-14`, OpenCode
`adopt-sandbox-ref-16`):

- `--container-toolchain add|list|remove|verify`, dispatched before the
  network mode and accepted only as the first argument;
- `PI_CONTAINER_TOOLCHAINS`, parsed like the other boolean settings, and
  `PI_CONTAINER_TOOLCHAINS_DIR`;
- the library checked against the workspace and every writable state
  directory (`~/.pi` and `~/.agents`, or the isolated
  `PI_CONTAINER_STATE_DIR`) before any image or container operation;
- the read-only `/toolchains` mount (`ro,nosuid,nodev`), with
  `--mount-target /toolchains` in restricted modes;
- default toolchain `PATH` entries appended after the image `PATH`, read from
  the session image's `.Config.Env`;
- the toolchain environment placed before the launcher's own `--env` values,
  so `PI_OFFLINE=1`, `PI_SKIP_VERSION_CHECK=1` and `PI_TELEMETRY=0` win over a
  toolchain that names them. Since `sandbox-ref-15`, toolchains cannot set
  `LD_`, `XDG_`, `PI_CONTAINER_` or `SANDBOX_` variables.

The README has a "Toolchains" section with the `AGENTS.md` instruction line;
the example recipes are linked in claude-container.

`tests/run-runtime.sh` mounts a private executable tmpfs at
`/sandbox-test-tmp` as `SANDBOX_TEST_TMPDIR`, and `tests/test_wrapper.py`
creates its fixtures there. `./test-wrapper.sh` creates a private
`SANDBOX_TEST_TMPDIR` below `XDG_RUNTIME_DIR` (or `~/.cache`) when it is
unset, and removes it on exit, because the library refuses a world-writable
ancestor such as `/tmp`.

Fixture adaptations required by the new mount:

- `tests/test_wrapper.py`:
  - a workspace that contains the library (sensitive-workspace cases) runs
    with the library moved outside it;
  - the bare wrapper copy without the diagnostics filter runs with
    `PI_CONTAINER_TOOLCHAINS=0`, since it has no `setup/`;
  - the restricted fixture installs `setup/common.py`, `setup/toolchains.py`
    and `Containerfile`;
- `tests/fake_podman.py` answers the image `.Config.Env` inspection;
- `tests/test_runtime.py`: the home moved outside the worktree base, which
  otherwise overlaps the library, and the nested-caller check also mounts
  that home;
- `tests/test_network_runtime.py`: the synthetic installation gains
  `setup/common.py`, `setup/toolchains.py` and `Containerfile`.

| Check | Result |
| --- | --- |
| New `tests/test_wrapper.py` cases with the previous launcher | Failed as intended (dispatch, mount, private creation, unsafe library including state overlap, disabled mount, appended `PATH`, restricted `--mount-target` and Pi settings order) |
| `python3 -m unittest tests.test_reference_copy tests.test_toolchains` (private tmpfs), including the agent-identifier scans | Passed |
| `python3 -m unittest discover -s tests` (disposable container, private executable tmpfs) | Passed: 391 tests, 72 skipped (the runtime tests are opt-in) |
| `./test-wrapper.sh` | Passed: 87 tests |
| `bash tests/run-runtime.sh --shared` | Passed: 160 tests, 28 skipped |
| `bash tests/run-runtime.sh --setup` | Passed: 71 tests |
| `bash tests/run-runtime.sh --setup-runtime` | Passed: 4 tests |
| `bash tests/run-runtime.sh --qualification` | Passed: 28 tests |
| `bash tests/run-runtime.sh --guard` | Passed: 20 tests, 1 skipped (the 305-second idle check) |
| `bash tests/run-runtime.sh --network` | Passed: 22 tests, including a toolchain added on the host during an offline session, usable without direct network |
| `bash tests/run-runtime.sh --wrapper` | 87 tests. An earlier run passed. In the full sequence, `test_lifetime_notice` failed once: exit status 255 without the lifetime notice. The test and the timing code are unchanged. It is timing-sensitive: the fake engine sleeps 2.2 s against a 2-second limit, measured in whole `SECONDS`. Three isolated reruns passed |
| `bash tests/run-runtime.sh` (`test_runtime.py`) | Passed: 18 tests, including archive and image sources, a failing check, the read-only mount, the image's `node` and `python3` kept first, and the omitted mount |
| `./test.sh` (disposable image, then `tests/run-runtime.sh`) | Passed: 18 tests; the test image was removed |
| Five-wrapper parity table | Identical to claude-container's (`sandbox-ref-16`) |
| Operator `--container-setup` on this host, the Rocky Linux 9 lab host and the newer WSL host, `java -version` with the Temurin 21 toolchain, and `--container-toolchain verify java21` | Passed (operator-reported, 2026-11-14): `main` pushed; `java -version` reports Temurin `21.0.13+9` LTS |

Runtime image: `localhost/pi-container:setup-c027176512b2430e8df55d80e3ea170a`
as `PI_CONTAINER_IMAGE`, with `PI_ENABLE_BUN` unset. Qualification digests
the launcher and `setup/toolchains.py`, so restricted installations rerun
`--container-setup`.

## Adoption of `sandbox-ref-17`: 2026-11-14

Copied from `claude-container` tag `sandbox-ref-17` (commit `a23f155`):
`setup/toolchains.py`, `tests/test_toolchains.py`.
The `tests/test_reference_copy.py` manifest moved to the tag.

`sandbox-ref-17` splits the protected toolchain variables into two groups:

- **Neutral:** the same in every wrapper, now including
  `DBUS_SESSION_BUS_ADDRESS`. `add` rejects them, and `launch-env` fails on
  them.
- **Profile:** Pi's own variables, `PI_CONTAINER_*` and the four credential
  variables. `add` rejects them. When another wrapper's toolchain in the
  shared index sets one, `launch-env` leaves it out of the session and prints
  one warning naming the toolchain.

The README "Protected variables" bullet describes both groups and keeps the
note on Pi's session settings. The launcher reads only the standard output
of `launch-env`, and the warnings go to standard error. The launcher and the
wrapper tests are therefore unchanged.

| Check | Result |
| --- | --- |
| `python3 -m unittest tests.test_reference_copy tests.test_alignment tests.test_toolchains` (private tmpfs) | Passed: 38 tests, 1 skipped |
| `python3 -m unittest discover -s tests` (disposable container, private executable tmpfs) | Passed: 393 tests, 72 skipped |
| `bash tests/run-runtime.sh --shared` | Passed: 160 tests, 28 skipped |
| `bash tests/run-runtime.sh --setup` | Passed: 71 tests |
| `bash tests/run-runtime.sh --setup-runtime` | Passed: 4 tests |
| `bash tests/run-runtime.sh --qualification` | Passed: 28 tests |
| `bash tests/run-runtime.sh --wrapper` | Passed: 87 tests |
| `bash tests/run-runtime.sh` (`test_runtime.py`) | Passed: 18 tests |
| Five-wrapper parity table | Identical to claude-container's (`sandbox-ref-17`) |
| Operator `--container-setup` on this host, the Rocky Linux 9 lab host and the newer WSL host | Passed (operator-reported, 2026-11-14); `main` pushed |

Runtime image: `localhost/pi-container:setup-c027176512b2430e8df55d80e3ea170a`
as `PI_CONTAINER_IMAGE`, with `PI_ENABLE_BUN` unset. `setup/toolchains.py`
is qualified code, so restricted installations rerun `--container-setup`.

## Adoption of `sandbox-ref-18`: 2026-11-15

Copied from `claude-container` tag `sandbox-ref-18` (commit `958465b`):
`network/agent_profile.py`, `setup/common.py`, `setup/toolchains.py`,
`tests/test_agent_profile.py`, `tests/test_alignment.py`, `tests/test_setup.py`,
`tests/test_toolchains.py`.
The `tests/test_reference_copy.py` manifest moved to the tag.

`sandbox-ref-18` adds the optional profile field `native.protected_env`, runs
the toolchain check in `/`, refuses an isolated state directory that overlaps
the workspace on managed launches, and makes the alignment test check the
launcher's code and its help text separately. The shared tests passed
without adapting a Pi fixture.

Pi changes, from the cross-wrapper review of 2026-11-14:

- **Agent variables:** `agent/profile.json` declares `PI_`, `ANTHROPIC_`,
  `OPENAI_`, `GEMINI_`, `OPENROUTER_` and `GOOGLE_API_KEY`. A default
  toolchain could previously set `ANTHROPIC_BASE_URL` in Pi sessions;
  `launch-env` now leaves it out with a warning. Pi's own settings
  (`PI_OFFLINE`, `PI_SKIP_VERSION_CHECK`, `PI_TELEMETRY`) are now dropped from
  the toolchain environment instead of only being overridden later, so
  `test_restricted_sessions_declare_the_toolchain_mount_and_keep_pi_settings`
  now expects the toolchain values to be absent and one warning each.
- **Name collisions (M2):** after a failed create without an ID, an existing
  container with the candidate name is a collision only when its session
  label differs. This session's own container is reported as the creation
  failure and removed in cleanup, instead of being left behind while the
  wrapper tried the next name.
- **Label recovery (M2):** when creation was interrupted or failed without a
  published ID, cleanup looks up the session label (`ps --all --no-trunc
  --filter label=…`), confirms exactly one ID by inspecting its label, and
  removes it. A failed lookup, several IDs or an unconfirmed label keep the
  "Creation outcome unresolved" report.

`tests/fake_podman.py` now answers the session-label lookup and label
inspection. The new tests (`test_toolchain_cannot_set_agent_variables`,
`test_owned_name_is_not_a_collision`,
`test_interrupted_creation_is_recovered_by_label`) fail on `main` and pass on
the branch.

| Check | Result |
| --- | --- |
| `shellcheck pi-container.sh` | Same warning as on `main` (SC2054) |
| `python3 -m unittest discover -s tests` (disposable container, private executable tmpfs) | Passed: 400 tests, 74 skipped |
| `bash tests/run-runtime.sh --shared` | Passed: 161 tests, 28 skipped |
| `bash tests/run-runtime.sh --setup` | Passed: 72 tests |
| `bash tests/run-runtime.sh --setup-runtime` | Passed: 4 tests |
| `bash tests/run-runtime.sh --qualification` (not in the tool's checklist; shared `setup/` modules are qualified code) | Passed: 28 tests |
| `bash tests/run-runtime.sh --wrapper` | Passed: 90 tests |
| `bash tests/run-runtime.sh` (`test_runtime.py`) | Passed: 18 tests |
| Five-wrapper parity table | Identical to claude-container's (`sandbox-ref-18`) |
| Operator `--container-setup` on this host, the Rocky Linux 9 lab host and the newer WSL host | Passed (2026-11-15, reported by the operator after the push) |

Runtime image: setup image `2fe240ad73ed`
(`localhost/pi-container:setup-c0271765…`), tagged
`localhost/pi-container:latest` only for the runs and untagged by name
afterwards. Shared qualified code changes, so restricted installations rerun
`--container-setup`.

## Adoption of `sandbox-ref-20`: 2026-11-16

`sandbox-container` is now the reference (it replaced `claude-container`).
Copied from `sandbox-container` tag `sandbox-ref-20` (commit `d4fd4ca`) with
`tools/propagate.py`: `network/README.md`, `network/agent_profile.py`,
`network/policy.py`, `network/qualification_records.py`, `network/qualify.py`,
`network/session.py`, `setup/common.py`, `setup/setup.py`, `setup/toolchains.py`,
`tests/sandbox_profile.py`, `tests/test_agent_profile.py`, `tests/test_alignment.py`,
`tests/test_guard.py`, `tests/test_qualification.py`, `tests/test_session.py`,
`tests/test_setup.py` and the fixture profiles in `tests/fixtures/`. The
`tests/test_reference_copy.py` manifest moved to the tag and names
`sandbox-container` as its sibling. Per-agent: `tests/test_setup_wrapper.py`
(copied from Claude), the lifetime notice measured with a monotonic clock
(`/proc/uptime`, since WSL2 steps the wall clock backwards) from just before
container creation plus a boundary test (failed with the old launcher),
documents pointing at `sandbox-container`, parity table fixed by hand.

Runtime image: setup image `2fe240ad73ed`
(`localhost/pi-container:setup-3705f13b…`), tagged `localhost/pi-container:latest`
only for the runs and untagged by name afterwards; `PI_ENABLE_BUN` unset; WSL2
6.6.87.2, Podman 4.9.3.

| Check | Result |
| --- | --- |
| `python3 -m unittest discover -s tests` (disposable container, private executable tmpfs) | Passed: 418 tests, 72 skipped |
| `bash tests/run-runtime.sh --setup` | Passed: 66 tests |
| `bash tests/run-runtime.sh --setup-runtime` | Passed: 4 tests |
| `bash tests/run-runtime.sh --qualification` | Passed: 28 tests |
| `bash tests/run-runtime.sh --guard` | Passed: 20 tests, 1 skipped |
| `bash tests/run-runtime.sh --network` | Passed: 22 tests |
| `bash tests/run-runtime.sh --network-policy` | Passed: 15 tests |
| `bash tests/run-runtime.sh --network-feasibility` | Passed: 1 test |
| `bash tests/run-runtime.sh --wrapper` | Passed: 91 tests |
| `bash tests/run-runtime.sh` (`test_runtime.py`) | Passed: 18 tests |
| `./test.sh` | Passed |
| `git diff --check`, `bash -n pi-container.sh` | Passed |
| Operator `--container-setup` on the three hosts (`sandbox-ref-21`) | Passed (operator, 2026-11-16) |

## Adoption of `sandbox-ref-21`: 2026-11-16

Copied from `sandbox-container` tag `sandbox-ref-21` (commit `4b25eae`) with
`tools/propagate.py`: `tests/sandbox_profile.py`, `tests/test_guard.py`. The
`tests/test_reference_copy.py` manifest moved to the tag; parity table fixed by
hand. The shared guard runtime test now mounts the image's own native home
(`AGENT_HOME`) instead of the fixture profile's home.

Runtime image: `localhost/pi-container:setup-3705f13b91c1402ab8f7f184e1f6e886`; WSL2 6.6.87.2, Podman 4.9.3.

| Check | Result |
| --- | --- |
| `python3 -m unittest discover -s tests` (disposable container, private executable tmpfs) | Passed: 418 tests, 72 skipped |
| `bash tests/run-runtime.sh --guard` | Passed: 20 tests, 1 skipped |
| `git diff --check` | Passed |
| Operator `--container-setup` on the three hosts (`sandbox-ref-21`) | Passed (operator, 2026-11-16) |

Only shared test files changed: installations need no new setup for this tag.

## Adoption of `sandbox-ref-25`: 2026-11-18

Change `adopt-sandbox-ref-25`: full adoption of the shared launcher core, from
`sandbox-ref-21` straight to `sandbox-ref-25` (commit `6bed770`). Copied from
`sandbox-container` with `tools/propagate.py`: `network/README.md`,
`network/agent_profile.py`, `network/control.py`, `network/qualification_records.py`,
`network/qualify.py`, `setup/common.py`, `setup/launch.py`, `setup/setup.py`,
`tests/fixtures/agent/profile.json`, `tests/sandbox_profile.py`,
`tests/test_agent_profile.py`, `tests/test_alignment.py`, `tests/test_network_policy.py`,
`tests/test_qualification.py`, `tests/test_setup.py`, `launcher/core.sh`,
`tests/fake_podman.py`, `tests/fixtures/agent/launcher.sh`,
`tests/fixtures/shell-agent/launcher.sh`, `tests/test_launcher.py`. The
`tests/test_reference_copy.py` manifest moved to the tag and lists `launcher` as
a closed directory; the parity rows were copied from their repositories.

- **Launcher:** `pi-container.sh` is the reference entry script with the wrapper
  name replaced. `agent/launcher.sh` holds Pi's profile values,
  `AGENT_EXEC=/usr/local/bin/pi`, `AGENT_EXEC_TMP=0`, `AGENT_INSTALL_FILES=(.version)`,
  one credential per policy profile, `PI_OFFLINE=1`, `PI_SKIP_VERSION_CHECK=1` and
  `PI_TELEMETRY=0` for restricted sessions, and five hooks: `agent_validate`,
  `agent_mounts`, `agent_build_args`, `agent_approval_bypass` and `agent_help`.
  `agent/profile.json` drops `install.runtime_build`.
- **State (U4, U6, M4):** shared `~/.pi` and `~/.agents` stay the default;
  `PI_CONTAINER_READONLY_STATE` replaces `PI_READONLY_CONFIG`.
- **Temporary storage (U7, L7):** `/tmp`, `/var/tmp` and the shared-state home are
  512 MiB `noexec` tmpfs mounts; `/run` (32 MiB) is not writable by the session
  user; the `~/.npm` tmpfs keeps its 256 MiB default.
- **Gitconfig:** the migration notice is dropped with the aliases (design
  decision 2).

Old tests gate (design decision 4): the `sandbox-ref-21` `tests/test_wrapper.py`
(91 cases) ran with its saved fake engine against the new entry script and core,
with only its harness adapted (the fake answers the core's `build-inputs-hash`
label and its one-line socket query; synthetic installations copy the core and
the agent part). 43 cases failed, each classified below. No lost behavior: one
candidate (`test_missing_successful_cid_reports_unresolved`) was classified as
a visible change by the user (2026-11-18). A diagnostic rerun with the new
variable names (`PI_CONTAINER_READONLY_STATE`, `PI_CONTAINER_ENV_VARS`) and the
new YOLO notice passed `test_physical_state_both_directories_and_readonly`,
`test_exact_delegation_and_connection_forwarding` and `test_yolo_has_no_effect`;
an invalid CID record is refused and the created container removed.

| Old case | Outcome | Maps to |
| --- | --- | --- |
| `test_all_names_decimal_bounds_and_listing_error` | visible change | wording ("cannot list Podman containers") |
| `test_application_status_and_cleanup_failure` | visible change | wording; status preserved (U9 cleanup report "cleanup rm failed or timed out") |
| `test_budget_inspection` | visible change | wording ("agent not started"); start still refused |
| `test_budget_validation` | visible change | `--cap-drop=all` spelling; the budget checks passed |
| `test_build_cannot_consume_session_input` | visible change | U3/U16: `--container-build --container-shell` is the build-only operation; the build still gets no session input |
| `test_build_only_refresh` | visible change | U8: the build-only operation checks and pulls the exact bases; wording and status of a failed build |
| `test_common_names_and_deprecated_aliases` | visible change | U2: aliases removed without notice |
| `test_creation_and_collision_query_failures` (exists=125) | visible change | phase 6: collisions confirmed by ownership label, not `container exists`; create diagnostics kept |
| `test_dedicated_home_layout` | visible change | U7 512 MiB home; U11 environment order |
| `test_device_and_secret_mounts_in_every_unrestricted_mode` | visible change | U7 tmpfs sizes and option order |
| `test_exact_delegation_and_connection_forwarding` | visible change | U6 `PI_CONTAINER_ENV_VARS`; passed with the new name |
| `test_gitconfig_deprecated_alias` | visible change | U2: `PI_MOUNT_GITCONFIG` removed |
| `test_gitconfig_opt_in_without_regular_file` | visible change | design decision 2: no migration notice; the refusals passed |
| `test_gitconfig_requires_exact_opt_in` | visible change | design decision 2: no migration notice |
| `test_hash_inspection_build_inputs_and_failures` | visible change | U8 core hash; wording of the stale-image message |
| `test_help_documents_modes_migration_and_provider_limits` | visible change | U1: no migration text; hosts printed from the policy |
| `test_help_missing_version_and_runtime` | visible change | U2 `--wrapper-help`; the copied entry script needs the core; help without `.version` is a hook case in the reduced tests |
| `test_help_without_engine_or_state` | visible change | help text from the core (U2: no deprecated names) |
| `test_image_and_build_status_matrix` | visible change | a failed image inspection exits 1 with a diagnostic instead of the engine status (user, 2026-11-17, Codex) |
| `test_interrupted_creation_invalid_identity_and_control_failures` | visible change | wording of the core's cleanup reports (validated CID record, U9) |
| `test_interrupted_creation_is_recovered_by_label` | visible change | wording of the core's cleanup reports |
| `test_isolated_state_directory` | visible change | U6 `PI_CONTAINER_READONLY_STATE`; the privacy refusal names the directory |
| `test_maintenance_gates_every_build` | visible change | wording of the stale-image message |
| `test_missing_mode_and_removed_network_stop_before_engine` | visible change | U1 provider default and its setup message; U2 `PI_NETWORK` |
| `test_missing_successful_cid_reports_unresolved` | visible change (user, 2026-11-18) | a successful create with a valid stdout ID and an empty CID record starts the session; the record is a cross-check when present |
| `test_mode_and_delegation_rejections_precede_engine` | visible change | phase 1-2 union: setup guidance before mode-specific settings |
| `test_modes_image_override_and_native_help` | visible change | U14: shell receives its arguments |
| `test_non_enforcing_modes_controlled_fixture` | visible change | wording ("use native Linux storage if permissions are not enforced") |
| `test_offline_order_arguments_and_forwarding` | visible change | the qualification check follows the name listing, before create |
| `test_permanently_stalled_creation_signal_matrix` | visible change | U9 immediate shutdown |
| `test_physical_state_both_directories_and_readonly` | visible change | U6 `PI_CONTAINER_READONLY_STATE`; passed with the new name |
| `test_prefix_fallback_identity_records_and_attempt_environment` | visible change | low findings: fallback name `AGENT_NAME`; an invalid CID record is refused and the created container removed |
| `test_provider_order_and_profile_credentials` | visible change | U7 tmpfs sizes |
| `test_restricted_credentials_match_the_agent_profile` | visible change | source inspection of the old launcher; `AGENT_CREDENTIALS` (U10) |
| `test_retained_editors_gitconfig_and_secrets` | visible change | U15 `EDITOR`/`VISUAL` nano; U10 |
| `test_sensitive_workspaces` | visible change | U2 `PI_ALLOW_UNSAFE_PWD`; wording |
| `test_setup_entry_point_is_dedicated_and_help_takes_precedence` | visible change | help text from the core |
| `test_socket_fallbacks_and_symlink` (default path) | visible change | fixture limit: the core checks the default socket before resolving it; shared case covers `/run/user/<uid>/podman/podman.sock` |
| `test_stubborn_application_and_stalled_cleanup_are_bounded` | visible change | U9 rewrite; wording |
| `test_unreapable_client_reports_without_waiting` | visible change | source inspection of the old helper (U9) |
| `test_unrestricted_keeps_forwarding` | visible change | U10: unrestricted sessions forward no key unless listed |
| `test_workspace_parent_identity_tmpfs_and_controls` | visible change | `--cap-drop=all` spelling; U7 |
| `test_yolo_has_no_effect` | Pi-only behavior | notice from `agent_approval_bypass` with new wording; passed with it; kept in the reduced tests |

The other "to verify at adoption" cases passed against the core. The hook cases
are rewritten in the reduced `tests/test_wrapper.py` (13 tests).

Environment: WSL2 6.6.87.2, Podman server 4.9.3; image rebuilt through the
build-only path: `localhost/pi-container:latest` `21762a3dcf25`, Pi 0.80.8,
`build-inputs-hash` `7797baa9d001aece6d7f01bb8cac91425d699f326b548fbb275e23d8b210916c`;
guard toolchain tagged from the setup image of this host.

| Check | Result |
| --- | --- |
| `--container-build` alone (real engine, maintenance) | Passed: built, labeled, no session container |
| `python3 -m unittest tests.test_alignment tests.test_agent_profile tests.test_launcher` (disposable container) | Passed: 145 tests, 1 skipped |
| `python3 -m unittest discover -s tests` (disposable container, private executable tmpfs) | Passed: 453 tests, 73 skipped |
| `bash tests/run-runtime.sh --wrapper` | Passed: 120 tests (`test_launcher.py`, `test_wrapper.py`) |
| `bash tests/run-runtime.sh --shared` | Passed: 288 tests, 29 skipped |
| `bash tests/run-runtime.sh --setup` | Passed: 67 tests |
| `bash tests/run-runtime.sh --setup-runtime` | Passed: 4 tests |
| `bash tests/run-runtime.sh --qualification` | Passed: 29 tests |
| `bash tests/run-runtime.sh --network` | Passed: 22 tests |
| `bash tests/run-runtime.sh --guard` | Passed: 20 tests, 1 skipped |
| `bash tests/run-runtime.sh` (`test_runtime.py`) | Passed: 18 tests |
| `./test.sh` (image built through `--container-build`) | Passed: 18 tests |
| `git diff --check`, `bash -n` on the entry script and the agent part | Passed |
| ShellCheck (warning) on `pi-container.sh`, `agent/launcher.sh`, `test.sh`, `test-wrapper.sh`, `tests/run-runtime.sh` | Passed. Standalone, `launcher/core.sh` and the launcher fixtures report warnings (unknown shell, variables assigned by `capture_response`); this is the same in every wrapper and is reported to the reference |
| Operator `--container-setup` on this host, the Rocky Linux 9 lab host and the newer WSL host, then a Pi session in provider mode | Passed (operator, 2026-11-18) |

The installed and qualified code changes (entry script, core, agent part,
profile): installations rerun `--container-setup`.

## Pi 1.5.2 and OpenSpec 2.0.0 image pins (2026-11-18)

`pin-pi-1-5-2` selects the newest stable releases at least 72 hours old at the
2026-11-18 freeze. Pi 1.5.2 was released on November 10 and OpenSpec 2.0.0 on
November 11. The base image is
`node:22-bookworm-slim@sha256:4b150b48b4116e2a22f2c39cc27025fbf4f153e2078fd3b14d159fdb5c7279da`.

| Image | Image ID | Reported Pi | Reported OpenSpec |
| --- | --- | --- | --- |
| Baseline | `21762a3dcf255a82042d7d33935d79a7f2c17ad970750ba5bd89e6ff2a537ede` | 0.80.8 | 1.16.0 |
| Updated | `f2097164a9e3a3cdc2d14be40bceec76f67b3251be597e954cb1dc40bd8ef89c` | 1.5.2 | 2.0.0 |

The maintenance build used HTTPS Debian sources and recorded build-inputs hash
`c6fd471da71276109eac82f7fdd3e4867c0a0be16fa975d74c78603a68b664c0`.
The updated image reports Node 22.23.4 and Python 3.11.2. Validation used
WSL2 6.6.87.2 x86_64, Podman client 4.3.1, rootless server 4.9.3 and Netavark.

### Provider inventory and startup controls

The offline inventory scanned literal URLs in the installed JavaScript and
JSON of `pi-coding-agent` and `pi-ai` for both versions, plus `pi-mcp` and
`pi-codemode` for 1.5.2. The four provider hosts remain in the installed
provider code or catalog. The logging proxy received one CONNECT to each
profile's host in a separate dummy-key `pi -p` run per profile. These containers
had `--network=none` and the proxy returned HTTP 403 to every request.

| Profile | Model | Key supplied | Destination in both versions and both control settings |
| --- | --- | --- | --- |
| `anthropic-api` | `claude-sonnet-4-6` | `ANTHROPIC_API_KEY` | `api.anthropic.com:443` |
| `openai-api` | `gpt-4o` | `OPENAI_API_KEY` | `api.openai.com:443` |
| `gemini-api` | `gemini-2.5-flash` | `GEMINI_API_KEY` | `generativelanguage.googleapis.com:443` |
| `openrouter-api` | `anthropic/claude-sonnet-4.6` | `OPENROUTER_API_KEY` | `openrouter.ai:443` |

| Probe | Additional CONNECT attempts on 0.80.8 | Additional CONNECT attempts on 1.5.2 |
| --- | --- | --- |
| Print mode, all controls unset | `pi.dev:443` once per provider | None |
| Print mode, version check and telemetry flags only (Anthropic) | `pi.dev:443` once | None |
| Print mode, all restricted controls | None | None |
| Interactive startup, all controls unset | `api.github.com:443` (1), `pi.dev:443` (2) | `github.com:443` (3), `pi.dev:443` (2) |
| Interactive startup, `PI_SKIP_VERSION_CHECK=1` | `api.github.com:443` (1), `pi.dev:443` (1) | `github.com:443` (3), `pi.dev:443` (1) |
| Interactive startup, `PI_TELEMETRY=0` | `api.github.com:443` (1), `pi.dev:443` (1) | `github.com:443` (3), `pi.dev:443` (1) |
| Interactive startup, all restricted controls | None | None |

Each startup run used new settings with update checks and install telemetry
enabled. The protected combination `PI_OFFLINE=1`,
`PI_SKIP_VERSION_CHECK=1`, `PI_TELEMETRY=0` suppressed the startup traffic and
still permitted model requests to reach the logging proxy. The four required
destinations match policy revision `pi-2026-11-10-v1`.

#### Additional hostname literals in 1.5.2

- `a.co`, `accounts.google.com`, `ae.api.openai.com`,
  `aiplatform.googleapis.com`, `api.meta.ai`, `api.typesafe.ai`,
  `auth.kimi.com`, `auth.meta.com`, `aws.amazon.com`,
  `cloudresourcemanager.googleapis.com`, `codeload.github.com`.
- `developers.openai.com`, `docs.anthropic.com`, `docs.cloud.google.com`,
  `docs.expo.dev`, `dummy.com`, `eu.api.openai.com`, `example.com`,
  `gist.githubusercontent.com`, `help.openai.com`, `huggingface.co`,
  `inference.baseten.co`.
- `json-schema.invalid`, `learn.microsoft.com`, `mcp.sentry.dev`,
  `mtls.api.openai.com`, `oauth2.googleapis.com`, `react-native.canny.io`,
  `redacted.invalid`, `signin-fips.amazonaws-us-gov.com`, `sts.amazonaws.com`.
- `token-plan.ap-southeast-1.maas.aliyuncs.com`,
  `token-plan.cn-beijing.maas.aliyuncs.com`, `us.api.openai.com`,
  `us.openrouter.ai`, `vercel.com`, `workers-binding.ai`,
  `www.googleapis.com`, `www.gstatic.com`.

Only 0.80.8 contained literals for `api.github.com`, `gist.github.com`,
`mistral.ai` and `raw.githubusercontent.com`. The interactive startup
comparison measures which GitHub host the CLI attempted. The provider runs
above exercised the four default API routes.

### Guard, MCP and state

The packaged codemode worker ran a QuickJS script and called a synthetic
tool under guard `abi3-seccomp-mux-v1`. A user-level `mcp.json` pointed at
`mcp.example.invalid`. The proxy logged `policy-denied` and `pi mcp list`
reported `failed` with exit 1. Pi's MCP OAuth callback server bound and
accepted a synthetic callback on the session's private loopback.

The 0.80.8 SDK serialized a session in isolated state with settings, a user
skill and a separate project skill. Pi 1.5.2 read the copy and continued the
session against the synthetic API. The session header stayed at format 3 and
the settings matched byte for byte. The model request contained the old reply
and the user skill. The default print run skipped the project skill and
`--approve` loaded it for a single invocation.

The ordinary TUI executed a synthetic Bash tool call without a tool-approval
prompt. The interactive `/trust` command saved the canonical project path
in the persistent `~/.pi/agent/trust.json`. A subsequent print run loaded the
project skill using the saved decision. The TUI also reported that `fd` was
absent and skipped its download under `PI_OFFLINE=1`.

### Offline OpenSpec round trip

OpenSpec 2.0.0 read the 1.16.0 settings in a qualified offline shell. It
initialized a temporary project with `--tools none`, created a change with
`skip_specs: true`, validated it strictly, and listed it. The names and
checksums of the legacy configuration files matched before and after.

### Generated OpenSpec skills

`openspec update` ran on the checkout from the qualified offline shell in the
updated image. The dry run identified the six tracked skill files and a global
configuration file in the disposable home. The update regenerated all six
`.agents/skills/openspec-*/SKILL.md` files with `generatedBy: "2.0.0"`.

### Acceptance checks

Runtime acceptance ran on November 18–19, 2026 UTC. Both versions passed
all 13 checks in `./test-wrapper.sh` and seven image-pin tests. Unit discovery
on the updated image ran 453 cases with 73 skips and
passed the reference-copy comparison against the sibling `sandbox-ref-25`
checkout.

| Check | Result |
| --- | --- |
| `./test.sh` | Built a disposable image through the wrapper and passed all 18 default runtime tests. |
| `bash tests/run-runtime.sh --wrapper` | 119 passed in the full run. The synthetic lifetime-boundary case passed on a targeted rerun. |
| `bash tests/run-runtime.sh --shared` | Ran 288 cases with 29 skips. All other cases passed. |
| `bash tests/run-runtime.sh --setup` | Passed all 67 tests. |
| `bash tests/run-runtime.sh --setup-runtime` | Passed all four tests. |
| `bash tests/run-runtime.sh --qualification` | Passed all 29 tests. |
| `bash tests/run-runtime.sh --network` | Passed all 22 tests, including the TUI, the native Bash tool through a synthetic API and TLS destination binding. |
| `bash tests/run-runtime.sh --guard` | Ran 20 cases with the opt-in idle check skipped. All other cases passed. |
| `bash tests/run-runtime.sh --guard-idle` | Passed. The guarded provider channel resumed after 305 seconds of inactivity. |
| `bash tests/run-runtime.sh --network-feasibility` | Passed on rerun. The topology harness reproduced its expected unguarded Unix socket control. |
| `bash tests/run-runtime.sh --network-policy` | Passed all 15 tests. |
| `bash tests/run-runtime.sh --mux` | Passed all 26 tests. |

In the full wrapper run, one iteration of the shared lifetime test printed
the one-second expiry notice with the expected exit status 3. The same case
passed in unit discovery, the targeted `--wrapper` rerun, and `--shared`.

The first topology run stopped before a probe started. The OCI runtime
reported a missing UID 0 mapping for one of the concurrently created
containers. The same test passed on an isolated rerun.

The guard tests used the prepared toolchain image
`a33a4e7a708555af127d04f788dc341decf4402077064deb64bb345720365654`.

`bash ../sandbox-container/tools/shellcheck.sh .` produced the same 71 findings
before and after. The shared core accounted for 14 and the two launcher
fixtures for 32 and 25. `git diff --check` and strict change validation passed.
The local OpenSpec 1.16.0 and the image's OpenSpec 2.0.0 both validated the change.

## Adoption of `sandbox-ref-28`: 2026-11-23

Change `adopt-sandbox-ref-28`, from `sandbox-ref-25` directly. It takes in
`sandbox-ref-26`, `sandbox-ref-27` and `sandbox-ref-28`:

- the process rlimit fallback and systemd-only cgroup delegation;
- the shared launcher files passing ShellCheck;
- Windows support on a Podman machine;
- the Windows setup guidance for agent wrappers.

Copied from `sandbox-container` tag `sandbox-ref-28` (commit `ba1ef14`):

- updated: `launcher/core.sh`, `network/README.md`, `network/agent_budgets.py`,
  `network/control.py`, `network/guard.c`, `network/proxy_hardening.py`,
  `network/qualification_probe.py`, `network/qualification_records.py`,
  `network/session.py`, `setup/common.py`, `setup/launch.py`, `setup/setup.py`,
  `setup/smoke.py`, `tests/fake_podman.py`, both fixture `launcher.sh`,
  `tests/test_alignment.py`, `tests/test_guard.py`, `tests/test_launcher.py`,
  `tests/test_qualification.py`, `tests/test_session.py` and
  `tests/test_setup.py`;
- added: the five `launcher/windows/` files, `tests/test_windows_bootstrap.py`,
  `tests/test_windows_enter.py` and `tests/windows/shim_tests.ps1`.

The `tests/test_reference_copy.py` manifest moved to the tag, and
`CONTRIBUTING.md` names it. Pi was the last wrapper on `sandbox-ref-25`, so
no parity row needed restoring: every other row already matched
`sandbox-container`.

By hand, as `docs/propagation.md` says:

- `pi-container.ps1` is a byte-for-byte copy of `sandbox-container.ps1`;
- `.gitattributes` was copied. The LF rewrite changed nothing: every tracked
  file was already LF in the index and the working tree;
- `agent/launcher.sh` already had the ShellCheck header of the reference agent
  part, so it did not change.

Pi's own tests changed where the shared behavior did, as in the other
wrappers:

- `tests/test_setup_wrapper.py` is the shared adapted file, byte for byte: the
  files were identical before. It adds a failing `systemctl`, the budget plan
  with the rlimit fallback and `cgroupfs`, and the case for setup without a
  launch service;
- `tests/test_runtime.py`: `engine_budgets()` reads the delegated controllers
  and the process mechanism with the rule of `network/agent_budgets.py`.
  `test_effective_hardening_and_budgets` follows them, reads a missing
  controller file as unlimited and checks the process rlimit and the launch
  notices. `test_process_limit_enforced` uses a budget of 128 with 200
  children, and is skipped when the engine enforces no process budget.

The README, `docs/setup.md`, `AGENTS.md`, `SECURITY.md` and `CHANGELOG.md`
cover:

- the Windows entry for Pi, with the four API key methods through
  `$env:<KEY>`;
- `PI_NPM_CACHE_SIZE`, which reaches a session from Windows only through
  `PI_CONTAINER_ENV_VARS`, and `PI_CONTAINER_GITCONFIG`;
- the installer;
- host CA trust on Windows;
- the Windows limits, including Bitdefender, and the Windows sensitive
  folders;
- the `cgroupfs` budgets, the rlimit fallback and the guard as init;
- the setup changes.

The change's OpenSpec files, the README, `docs/setup.md`, `AGENTS.md`,
`SECURITY.md`, `CHANGELOG.md` and this file pass markdownlint
(`markdownlint-cli2` v0.18.1, MD013 and MD033 off), as this repository
requires: the delta specs, `design.md` and `docs/setup.md` gained the missing
blank lines around headings, lists and code fences.

**This runner.** WSL2 `6.18.58.1-microsoft-standard-WSL2`, Podman server
4.9.3, the `systemd` cgroup manager and controllers `[cpu memory pids]`.

- The engine had no `localhost/pi-container:latest`. Its
  `localhost/pi-container:setup-b4718cbdce044a7b9d2d6ea52f01ce06`
  (`9ed2a78259d9`) predates the Pi 1.5.2 pin (`build-inputs-hash`
  `7797baa9...`, Pi 0.80.8). The adoption changes no build input.
- `localhost/pi-container:latest` `70c03c7e3703` was rebuilt with
  `--container-build`, `build-inputs-hash` `c6fd471d...`, Pi 1.5.2 and
  OpenSpec 2.0.0. The runner's network intercepts TLS, so the build used host
  CA trust with the session's CA bundle as the build secret.
- For the guard toolchain,
  `localhost/pi-guard-toolchain:setup-b4718cbdce044a7b9d2d6ea52f01ce06`
  (`101d7cadcd1c`) was also tagged `localhost/pi-guard-toolchain:development`,
  the name that `--guard`, `--qualification` and `--network` use.

| Check | Result |
| --- | --- |
| `python3 -m unittest tests.test_reference_copy tests.test_alignment` (host Python, siblings present) | Passed: 26 tests, no skips |
| `bash tools/shellcheck.sh ../pi-container`, `bash tools/powershell.sh ../pi-container` (from `sandbox-container`) | Passed: no finding, 62 shim cases |
| `python3 -m unittest discover -s tests` (disposable container, private executable tmpfs) | Passed: 508 tests, 81 skipped |
| `bash tests/run-runtime.sh --wrapper` | Passed: 124 tests, 1 skipped (no drive root under `/mnt`). A first run, while the operator's first Windows setup and a file transfer also loaded the computer, took 1540 s and failed the timing-sensitive shared tests `test_lifetime_notice_preserves_status` (seven boundary attempts), `test_int_and_hup_forwarding` and `test_term_forwarding`; the rerun on its own passed |
| `bash tests/run-runtime.sh --shared` | Passed: 303 tests, 35 skipped. A first run failed the shared signal test `test_int_and_hup_forwarding`, which passed in `--wrapper`; the rerun on its own passed |
| `bash tests/run-runtime.sh --setup` | Passed: 88 tests |
| `bash tests/run-runtime.sh --setup-runtime` | Passed: 4 tests |
| `bash tests/run-runtime.sh --qualification` | Passed: 31 tests |
| `bash tests/run-runtime.sh --guard` | Passed: 25 tests, 1 skipped (`--guard-idle`) |
| `bash tests/run-runtime.sh --network` | Passed: 22 tests |
| `bash tests/run-runtime.sh` (`test_runtime.py`) | Passed: 18 tests, including the budget checks above |
| `git diff --check` | Passed |

**Windows** (operator, 2026-11-23). Windows WSL 3.0.5.0, kernel 6.18.58.1-1,
Landlock ABI 7. The Podman Desktop machine `podman-machine-default` uses the
`cgroupfs` manager, with Ubuntu running. The checkouts were snapshots of this
branch and of `sandbox-container` in `C:\Work`.

| Step | Result |
| --- | --- |
| Setup from `pi-container.ps1`: provider networking with the `openrouter` method, shared state, host CA trust with `/etc/ssl/certs/ca-certificates.crt`, permission bypass on | The plan printed `enforced agent budgets: none`, the `cgroupfs` notices and the process rlimit for the agent (512) and the proxy (128). Images built in the machine, `Sandbox qualification: locally-qualified`, `Sandbox: ready`. Setup said `Set $env:OPENROUTER_API_KEY = '...' in PowerShell before pi-container.ps1`, with no distribution path. A first attempt failed; see the notes |
| A Pi session with `$env:OPENROUTER_API_KEY` | Provider session with `openrouter-api`, Pi 1.5.2, model Flint (free) through OpenRouter. Pi wrote `hello.txt` in the project with its tools. `$LASTEXITCODE` was 0 after `/quit` and after two quick Ctrl+C presses (two sessions), as on Linux; once it was 130, see the notes. `podman ps -a` then listed no container of the sessions (operator) |
| `$env:PI_NPM_CACHE_SIZE = '1g'`, then `--container-shell -c 'df -h /pi-home/.npm'` | The tmpfs was 256M; with `$env:PI_CONTAINER_ENV_VARS = 'PI_NPM_CACHE_SIZE'` it was 1.0G |
| `windows-validate.ps1 -Checkout C:\Work\pi-container -Install -StopMachine`, Windows PowerShell 5.1 | 55 passed, 0 failed, 1 skipped (restricted mode without a prepared installation, because setup saved provider). Installer, user `PATH`, uninstall, stopped machine, a distribution started by WSL alone, the restart with Podman, the Windows folders, "Offline qualification", "Offline session", "Redirected input" and "One engine for sessions and the machine" passed |
| The same without `-Install -StopMachine`, PowerShell 7.7.0 | 43 passed, 0 failed, 3 skipped |

Notes:

- **The first setup attempt failed under load.** The computer also ran the
  runner's `--wrapper` suite and an operator file transfer. After the image
  builds, the qualification's security probe timed out (30 s), so setup
  stopped with `run --container-qualify or rerun --container-setup`. Its
  cleanup of the candidate tags then timed out on `podman image exists`
  (20 s) and ended in a `subprocess.TimeoutExpired` traceback, which left the
  candidate tags `setup-f9a1801e...` in the machine; they were removed before
  the rerun. A timed-out probe can also leave its container in `Created`
  state. The rerun, with the runner idle, passed. Both defects are in shared
  setup and qualification code, so `sandbox-container` fixes them in a
  dedicated change; the next tag brings the fix.
- **One session ended with 130.** Pi had written the file, then two Ctrl+C
  presses ended the session with 130, the status the launcher selects for an
  INT signal. Two later sessions ended with 0 after two quick Ctrl+C presses.
  The cause of the single 130 is not established.
- **`fd not found. Offline mode enabled`.** Pi prints it at startup because
  restricted sessions set `PI_OFFLINE=1`, as on Linux.
- **The `transport-closed` diagnostic.** At session end, the
  `recent protected egress diagnostics` line with `transport-closed` is the
  behavior already recorded on Linux.
- **The machine keeps the method of the last setup** (`openrouter`).

The installed launcher core, setup and guard change, so installations rerun
`--container-setup`.

## Adoption of `sandbox-ref-36`: 2026-11-27

Change `adopt-sandbox-ref-36`, from `sandbox-ref-28` (`ba1ef14`) directly to
`sandbox-ref-36` (`ce2c9d2`). It takes in `sandbox-ref-29` through
`sandbox-ref-36` and explicitly excludes `add-read-only-dependency-mirror`
(whose code landed on `sandbox-container/main` after `sandbox-ref-36`):

- host Podman delegation is removed in every mode (`PI_CONTAINER_PODMAN=1`
  stops startup before engine queries with migration guidance) and replaced by
  a private, session-owned rootless Podman engine
  (`localhost/pi-container-engine:latest`) whenever the enabled toolchain
  library holds image toolchains;
- toolchains are provisioned from the shipped release catalog
  (`setup/toolchain-catalog/`) and host-side HTTPS archive downloads without
  maintenance consent, with read-only `.images` storage, idle-engine checks on
  image removal, Windows drive-path translation, and automatic re-verification
  during `--container-setup`;
- the process rlimit fallback is set inside each container by its first process
  (never `--ulimit nproc`), verified per container across agent, proxy and
  engine containers;
- nested systemd containers and explicit nested limits on eligible engines, and
  `io.containers.capabilities` (`SETUID,SETGID,SYS_CHROOT,CHOWN`) declared on
  the engine image;
- guarded terminal availability probing (`tests/guard_terminal_probe.py`) and
  runtime-test portability updates.

Copied from `sandbox-container` tag `sandbox-ref-36` (commit `ce2c9d2`):

- updated (29): `launcher/core.sh`, `launcher/windows/bootstrap.sh`,
  `launcher/windows/core.ps1`, `network/README.md`, `network/agent_budgets.py`,
  `network/agent_profile.py`, `network/proxy_hardening.py`,
  `network/qualification_probe.py`, `network/qualification_records.py`,
  `network/qualify.py`, `network/session.py`, `setup/common.py`,
  `setup/launch.py`, `setup/setup.py`, `setup/smoke.py`, `setup/toolchains.py`,
  `tests/fake_podman.py`, `tests/guard_runtime_fixture.py`,
  `tests/network_fixture.py`, `tests/test_alignment.py`, `tests/test_guard.py`,
  `tests/test_launcher.py`, `tests/test_network_feasibility.py`,
  `tests/test_qualification.py`, `tests/test_session.py`, `tests/test_setup.py`,
  `tests/test_toolchains.py`, `tests/test_windows_bootstrap.py`,
  `tests/windows/shim_tests.ps1`;
- added (17): the eight `launcher/engine/` files, `setup/engine.py`, the six
  `setup/toolchain-catalog/` files, `tests/guard_terminal_probe.py` and
  `tests/test_engine.py`;
- removed: none.

The `tests/test_reference_copy.py` manifest moved to `sandbox-ref-36`
(`ce2c9d28873838a4ac541da34edaf7d8b5264be4`, 92 entries). `pi-container.ps1`,
`.gitattributes`, `Containerfile` (Pi `1.5.2` from `.version`, OpenSpec
`2.0.0`), `.containerignore`, `agent/profile.json`, `agent/launcher.sh` and
`agent/policies/default.json` are unchanged.

Pi-specific updates:

- `tests/run-runtime.sh` and `test.sh`: removed `PI_CONTAINER_PODMAN_SOCKET`,
  selecting the Unix socket from `CONTAINER_HOST` or the runtime directory and
  stripping an optional `unix://` prefix from `Host.RemoteSocket.Path`; aligned
  `--shared` with `tests/test_alignment.py` by adding `test_engine`,
  `test_toolchains`, `test_windows_bootstrap`, `test_windows_enter` and
  `test_image_pins`; forwarded optional `PI_CONTAINER_ENGINE_IMAGE`,
  `SANDBOX_TEST_ENGINE_SAMPLE` and `SANDBOX_TEST_SYSTEMD_SAMPLE`; replaced the
  stale delegated-children comment in `test.sh`;
- `tests/test_wrapper.py`: removed the synthetic
  `PI_CONTAINER_PODMAN_SOCKET` fixture, stale `PI_CONTAINER_PODMAN` entry, and
  duplicate `qualification-input` stub (now provided by `synthetic_install`),
  keeping Pi's help, `PI_CONTAINER_YOLO` notice-only rules,
  `PI_CONTAINER_GITCONFIG`, `PI_NPM_CACHE_SIZE`, `.version` (`PI_VERSION`),
  four provider profiles, restricted `PI_OFFLINE=1` / `PI_SKIP_VERSION_CHECK=1`
  / `PI_TELEMETRY=0` controls, and qualification probe checks;
- `tests/test_setup_wrapper.py` and `tests/test_setup_runtime.py`: removed host
  Podman delegation prompts and summary assertions, isolated `XDG_RUNTIME_DIR`
  in synthetic setup tests, asserted schema 3 preferences (`schema_version == 3`,
  `engine_image`, absent `podman` / `delegation_socket`) and saved-delegation
  refusal, copied the CA fixture into native storage, routed prepared
  `localhost/pi-container-engine:latest` lookups without mutating operator
  images, and tracked disposable `setup-<release>` runtime, engine, toolchain
  and proxy tags while preserving Pi's `1.5.2` version,
  `test_wrapper_built_runtime_passes_the_staleness_check`, rollback, and
  `test_provider_gemini_transcript`;
- `tests/test_runtime.py`: removed
  `test_delegated_child_and_remapped_containerized_caller` and legacy
  `PI_CONTAINER_PODMAN=1` / `PI_CONTAINER_PODMAN_SOCKET` branches, replaced
  with `test_containerized_caller_and_leftover_delegation_refusal`, updated
  `test_identity_storage_hardening_and_ephemeral_lifetime` to check both
  `CONTAINER_HOST` and `DOCKER_HOST` unset, made
  `test_declared_runtime_limits_and_owned_id` respect delegated controllers and
  the rlimit fallback, added `test_process_rlimit_counts_per_container`, and
  ported `SessionEngineTests` (6 cases using
  `localhost/pi-container-engine:latest`: workspace binds with caller-owned
  files, read-only store, build/load, per-container rlimit, no-engine mode,
  concurrent isolation, cgroup delegation, and nested systemd containers) while
  keeping Pi's `1.5.2` / OpenSpec `2.0.0` / npm / worktree / `/pi-home` /
  gitconfig / toolchain checks;
- `tests/test_network_runtime.py`: installed `setup/engine.py`, `engine.INPUTS`,
  `setup/toolchain-catalog/` and the derived engine seccomp profile; replaced
  restricted-only delegation checks with exact `PI_CONTAINER_PODMAN=1` refusal
  across `offline`, `provider` and `unrestricted` modes plus ignored
  non-enabling values; added `test_offline_session_engine_has_no_external_path`,
  `test_image_recipe_check_runs_without_network`, controller-aware agent/proxy
  budget checks, `test_proxy_starts_beside_containers_holding_more_than_its_budget`,
  bounded cleanup for interrupted fixtures, and `guard_terminal_probe.py`
  gating for guarded terminal cases (keeping pipe cases independently runnable
  and preserving Pi's four provider TLS binding checks, credential controls,
  and `test_actual_pi_bash_tool_with_synthetic_chat_api`);
- `README.md`, `AGENTS.md`, `SECURITY.md`, `CONTRIBUTING.md`, `CHANGELOG.md`,
  `docs/setup.md`, `docs/network-contract.md` and
  `openspec/specs/toolchain-library/spec.md` (`## Purpose`): replaced host
  Podman delegation docs with the private session container engine, container
  tests workflow, shipped catalog, host-side HTTPS fetching, image recipes,
  Windows drive-path translation, schema 3 migration, and in-container process
  rlimit fallback.

### Working-session checks (2026-11-27)

Environment: guarded sandbox session (`CONTAINER_HOST=tcp://127.0.0.1:2375`,
rootless Linux `cgroupfs`, controllers `[cpu io memory pids]`, kernel
`6.6.87.2-microsoft-standard-WSL2`), checkout on DrvFS (`/mnt/d/`, mode `777`).
Synthetic suites requiring private executable `0700` storage ran in a
disposable offline `localhost/docgen:1.0.0` container with private executable
`tmpfs` (`SANDBOX_TEST_TMPDIR=/sandbox-test-tmp`). Real Pi images
(`localhost/pi-container:latest`, `localhost/pi-container-engine:latest`,
`localhost/pi-guard-toolchain:development`), `shellcheck`, `pwsh`,
`markdownlint-cli2` and a same-host Unix Podman service (`AF_UNIX` blocked with
`EPERM` by the session guard) are unavailable in this session.

| Check | Result |
| --- | --- |
| `python3 -B -m unittest tests.test_reference_copy tests.test_alignment -v` (host Python, git and sibling checkouts present) | Passed: 26 tests, 0 skips |
| `python3 -B -m unittest tests.test_wrapper -v` (disposable container, private executable `tmpfs`) | Passed: 13 tests |
| `python3 -B -m unittest tests.test_setup_wrapper -v` (disposable container, private executable `tmpfs`) | Passed: 9 tests |
| `python3 -B -m unittest tests.test_engine tests.test_toolchains tests.test_qualification tests.test_session tests.test_network_policy -v` (disposable container, private executable `tmpfs`) | Passed: 156 tests, 7 opt-in real-engine skips (`test_qualification`) |
| Full non-alignment unit run across all 22 remaining `tests/test_*.py` modules (disposable `localhost/docgen:1.0.0` container, private executable `tmpfs`) | Passed: 562 tests (475 passed, 87 opt-in skips: `test_runtime` 25, `test_network_runtime` 25, `test_guard` 24, `test_qualification` 7, `test_setup_runtime` 4, `test_network_feasibility` 1, `test_launcher` 1; 0 failures, 0 errors); combined with the 26 host `test_reference_copy` + `test_alignment` cases, all 24 test modules (588 tests) verified cleanly |
| `bash -n` on all 11 tracked `*.sh` files | Passed |
| `python3 -B -m py_compile` on updated Python test modules | Passed |
| `git diff --check` | Passed |
| `openspec validate adopt-sandbox-ref-36 --strict` | Passed (0 errors, 0 warnings) |
| Disposable OpenSpec archive/spec-merge preview (`openspec archive --yes` + `openspec validate --specs` in temp copy) | Passed: `container-podman-access` retired, `session-container-engine` created with 20 requirements (valid under `--strict`), launch-engine verification moved to `container-launcher`, Pi contracts preserved (`PI_NPM_CACHE_SIZE`, `PI_CONTAINER_GITCONFIG`, `PI_CONTAINER_YOLO`, four provider profiles), 13/13 specs passed (`+35, ~29, -5`) |
| `python3 -I ../sandbox-container/tools/propagate.py ../pi-container sandbox-ref-28 sandbox-ref-36 --checklist` | Generated 13-entry checklist (`runtime`/`toolchain` images, engine build, 9 runner modes, Windows manual step) |
| `bash tests/run-runtime.sh` (preflight in guarded session) | Failed closed at image preflight (exit 1, `localhost/pi-container:latest` absent in session engine); with `PI_CONTAINER_IMAGE=localhost/docgen:1.0.0`, failed closed at Unix-service preflight (exit 125, `socket: operation not permitted` under session guard) without mutating engine or host state |
| `shellcheck`, `pwsh`, `markdownlint-cli2` | Unavailable in session (not installed; no offline tool images in session engine) |
| Real-engine runner modes (`--shared`, `--setup`, `--setup-runtime`, `--qualification`, `--wrapper`, default, `--network-feasibility`, `--guard`, `--network`) | Unavailable in session (no `localhost/pi-container:latest`, `localhost/pi-container-engine:latest`, `localhost/pi-guard-toolchain:development`, or host Unix Podman service) |
| Authenticated provider checks (`anthropic-api`, `openai-api`, `gemini-api`, `openrouter-api`) | Not run in session (operator-only; prior `sandbox-ref-28` results remain in history) |
| Windows PowerShell 5.1 validation | Not run in session (Linux session; post-closure follow-up) |

### Follow-up after closure

- On WSL or the native Linux host, from `sandbox-container`:
  `bash tools/adoption-run.sh /mnt/d/Workspace/sandboxes/pi-container sandbox-ref-28 sandbox-ref-36`: pending
  (prepare `localhost/pi-container-engine:latest` and record runtime/engine
  image IDs, `io.containers.capabilities`, runner suites, and any host-specific
  skips).
- On a Windows host, rerun `--container-setup` from PowerShell and run from
  `sandbox-container`:
  `.\tools\windows-validate.ps1 -Checkout <the Windows checkout>` on Windows
  PowerShell 5.1 (and PowerShell 7): pending (verify saved-delegation refusal,
  library-image session with private engine, `PI_NPM_CACHE_SIZE`, and
  interactive Pi).
- Static ShellCheck, Markdownlint and PSScriptAnalyzer/shim checks
  (`tools/shellcheck.sh` and `tools/powershell.sh` from `sandbox-container`):
  pending on host with tool images/binaries.
- Cross-repository parity table synchronization (`sandbox-container` and
  sibling wrappers): pending as a separate parity step after closure.

The installed launcher core, setup, guard and engine recipe change, and setup
builds `localhost/pi-container-engine:latest` and migrates schema 1/2
preferences to schema 3, so existing installations must rerun
`--container-setup`.

## Removal of the GitHub pipelines (`remove-github-pipelines`): 2026-11-28

Environment: claude-container session started from Windows (Podman machine,
WSL2 backend), checkout on DrvFS (`/mnt/d/`). The session engine
(`CONTAINER_HOST=tcp://127.0.0.1:2375`) holds only toolchain library images,
and the session has no network.

| Check | Result |
| --- | --- |
| `git ls-files .github .trivyignore`; `test -e .github` | Nothing tracked; `.github` absent |
| `git grep -n -i -e '\.github' -e dependabot -e trivy -e '\bCI\b' -- ':!openspec/changes'` | Matches only the new and historical `CHANGELOG.md` entries, earlier sections of this file (lines 76, 78 and 188, and the Pi endpoint tables from line 1021), and the README heading "Non-interactive use (piped input, CI/CD)" |
| `python3 -B -m unittest tests.test_reference_copy tests.test_alignment -v` (host Python, sibling checkouts present) | Passed: 26 tests, 0 skips |
| `git diff --check` | Passed |
| `openspec validate remove-github-pipelines --strict` | Passed (`skip_specs: true`, no spec deltas) |
| `markdownlint-cli2` on the edited Markdown and the change Markdown | Unavailable in session (not installed; no tool image in the session engine and no network to pull `docker.io/davidanson/markdownlint-cli2:latest`) |

### Follow-up after closure

- Markdownlint with the `AGENTS.md` container command on `README.md`,
  `SECURITY.md`, `CONTRIBUTING.md`, `CHANGELOG.md`, `AGENTS.md`, this file and
  the archived change: pending.
- After the push, GitHub starts no workflow run for the new commit: pending.
- Open Dependabot pull requests closed, and Dependabot alerts and security
  updates kept or turned off in the repository settings: pending (operator).

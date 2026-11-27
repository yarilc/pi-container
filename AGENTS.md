# Repository Guidelines

Write all documentation, comments, help, specifications and commit messages in
English. Communicate with the user in the language and style the user asks for.

## Project Structure & Module Organization

- `pi-container.sh` is the thin entry script shared by every wrapper: it only
  sources `launcher/core.sh` with `agent/launcher.sh`. The shared launcher core
  owns runtime policy: setting resolution, launch-engine verification,
  session container engine lifecycle, state validation, mounts, hardening and
  budgets, environment forwarding, naming and owned cleanup. `agent/launcher.sh`
  holds Pi's profile data for the core (checked against `agent/profile.json` by
  `tests/test_alignment.py`) and five hooks: `agent_validate` (gitconfig opt-in,
  `PI_NPM_CACHE_SIZE`), `agent_mounts` (the `~/.npm` tmpfs, the read-only
  gitconfig), `agent_build_args` (`PI_VERSION` from `.version`),
  `agent_approval_bypass` (the `PI_CONTAINER_YOLO` notice) and `agent_help`.
- `pi-container.ps1` is the thin Windows entry, identical in every wrapper
  under the wrapper's name: it runs the shared shim `launcher/windows/core.ps1`,
  which starts the managed installation inside a Podman machine's WSL
  distribution through `launcher/windows/bootstrap.sh`, and runs sessions and
  setup in the machine's systemd namespaces through `launcher/windows/enter.sh`.
  Windows supports every network mode that setup prepared and the private
  session container engine for image toolchains; see the README's Windows
  section. `launcher/windows/` is shared like `launcher/core.sh`. The shim
  forwards only `PI_CONTAINER_*`, the four method keys and the names in
  `PI_CONTAINER_ENV_VARS`, so `PI_NPM_CACHE_SIZE` needs that list from Windows;
  document this, and never work around it here.
- `Containerfile` and `.containerignore` define the Pi image (digest-pinned
  base, common toolset with the Podman client, Pi from `.version`, pinned
  OpenSpec) and its five-file build context
  (including `network/relay.py` and `network/mux.py`).
- `tests/test_image_pins.py` rejects floating image inputs and a `.version`
  that differs from the policy's `tested.cli`.
- `agent/profile.json` and `agent/policies/default.json` hold every Pi-specific
  value used by the shared network code (identity, images, state layout and the
  four provider profiles). Restricted preparation, proxy lifecycle and restricted
  container arguments come from `network/session.py` (`prepare`, `start`,
  `agent-args`, `stop`); never re-implement them inline.
- `launcher/` (including `launcher/engine/` and `launcher/windows/`),
  `network/`, `setup/` (including `setup/engine.py` and
  `setup/toolchain-catalog/`) and the shared tests (`sandbox_profile.py`,
  `test_alignment.py`, `test_launcher.py`, `fake_podman.py`, `test_setup.py`,
  `test_agent_profile.py`, `test_network_policy.py`, `test_mux.py`,
  `test_tls_client_hello.py`, `test_tls_proxy.py`, `test_platform.py`,
  `test_qualification.py`, `test_guard.py`, `test_session.py`,
  `test_network_feasibility.py`, `test_toolchains.py`, `test_engine.py`,
  `test_windows_bootstrap.py`, `test_windows_enter.py`, `guard_terminal_probe.py`,
  `windows/shim_tests.ps1` and their fixtures) are copied unchanged from
  `sandbox-container` at tag `sandbox-ref-36`. Never edit them here, and never
  add a profile identifier (`pi-container`, `anthropic`, `openai`, `gemini`,
  `openrouter`) to them; fix a defect in `sandbox-container` first, then copy the
  files again and update `tests/test_reference_copy.py`.
- The shared `setup/toolchains.py` and `setup/engine.py` manage the operator
  toolchain library (including the release catalog and `.images` store), mounted
  read-only at `/toolchains`, and the private session container engine
  (`localhost/pi-container-engine:latest`) started for sessions when the library
  holds at least one image toolchain; the launcher owns only its dispatch, mount,
  engine lifecycle and environment.
- `README.md` documents setup, usage and security; `SECURITY.md`,
  `CONTRIBUTING.md` and `CHANGELOG.md` complement it.
- `openspec/specs/` contains current behavior contracts; `openspec/changes/`
  holds active proposals and dated archives.
- `tests/` contains the synthetic wrapper suite (`test_wrapper.py` with
  `fake_podman.py`) and the opt-in real-engine suite (`test_runtime.py`,
  `run-runtime.sh`, `Containerfile.runner`).
- `docs/validation.md` records verification results and limitations.

## Build, Test, and Development Commands

Run from the repository root:

```bash
bash ./pi-container.sh --container-setup       # guided setup (interactive, alone)
export PI_CONTAINER_NETWORK=unrestricted        # direct launches from a checkout
PI_CONTAINER_MAINTENANCE=1 ./pi-container.sh --container-build   # build the image and exit
./test-wrapper.sh                               # synthetic wrapper suite
bash tests/run-runtime.sh                       # real rootless checks with native Linux state
bash tests/run-runtime.sh --network             # restricted modes (also --wrapper, --shared, --setup, ...)
./test.sh                                       # disposable image build plus real checks
bash -n pi-container.sh agent/launcher.sh test-wrapper.sh test.sh tests/run-runtime.sh
bash ../sandbox-container/tools/shellcheck.sh .   # ShellCheck at warning level
bash ../sandbox-container/tools/powershell.sh .   # PSScriptAnalyzer and shim tests
```

Every tracked `*.sh` file, the shared `launcher/core.sh` and launcher fixtures
included, passes `tools/shellcheck.sh` of `sandbox-container` (pinned
ShellCheck, warning level). Pi's agent part `agent/launcher.sh` starts with
`# shellcheck shell=bash disable=SC2034,SC2154`, because the core reads its data
and defines the state its hooks read.

Every tracked `*.ps1` file passes `tools/powershell.sh` of `sandbox-container`
(pinned PSScriptAnalyzer, warning level), which also runs the shared shim tests
`tests/windows/shim_tests.ps1` against a fake `wsl.exe`. The thin entry and the
shim stay ASCII and run on Windows PowerShell 5.1 and PowerShell 7; Windows
PowerShell 5.1 itself is validated on a Windows host, as follow-up after
closure. Scripts keep LF line endings through `.gitattributes`.

Lint through containers when the tools are not installed:

```bash
podman run --rm -v "$PWD:$PWD:ro" -w "$PWD" docker.io/koalaman/shellcheck:stable \
  pi-container.sh agent/launcher.sh test.sh test-wrapper.sh tests/run-runtime.sh
podman run --rm -v "$PWD:$PWD:ro" -w "$PWD" docker.io/hadolint/hadolint:latest-alpine \
  hadolint --config .hadolint.yaml Containerfile tests/Containerfile.runner \
  network/Containerfile network/guard-build.Containerfile
podman run --rm -v "$PWD:$PWD:ro" -w "$PWD" docker.io/davidanson/markdownlint-cli2:latest \
  README.md SECURITY.md CONTRIBUTING.md CHANGELOG.md AGENTS.md docs/validation.md
```

## Coding Style & Naming Conventions

Use Bash with quoted variables and command arrays for user-controlled
arguments. Follow the four-space indentation, keep hooks small, and prefix
diagnostics with `pi-container:` (`$AGENT_NAME`). Wrapper settings use the
`PI_CONTAINER_` prefix; earlier names have no effect and print no notice.
Launcher behavior belongs in the shared core: change it in `sandbox-container`
and adopt the new tag, never here.
Forward secrets by name only (`--env NAME`), never as `NAME=value`.

## Change workflow and validation environments

A change is validated and closed in the environment where it is developed:
the session the work runs in. Once a change is applied, no task waits for
another environment or for the operator: not the WSL host outside the
session, a native Linux host, a Windows host, nor a real installation.

- **Before the change starts:** while exploring, proposing or designing, a
  spike may run on another environment to answer one specific question. The
  design records the question, the environment, the command and the result.
  A spike is never a task.
- **During the change:** run every check the session supports. A check the
  session cannot run, or one that fails because of the session's
  environment, is recorded in `docs/validation.md` as unavailable in the
  session, with its reason. It moves to the follow-up and does not block
  closure. A failure caused by the change is fixed in the change.
- **Test storage in a session:** `$HOME`, `/tmp` and `/var/tmp` are `noexec`
  there. Point `SANDBOX_TEST_TMPDIR` at a new directory on the workspace
  mount, and remove it afterwards, or tests with stubs fail for the
  session's reasons.
- **After closure:** runs on other environments are follow-up verification:
  runner modes on WSL and on the native Linux host, `tools/adoption-run.sh`,
  `tools/windows-validate.ps1` on Windows PowerShell 5.1, sessions opened on
  another host, and operator checks with real accounts. `tasks.md` lists
  them as plain bullets under "Follow-up after closure", never as
  checkboxes. `docs/validation.md` lists them as pending, then their
  results. A defect they find opens a new change.

`CLAUDE.md` imports this file for Claude Code and holds nothing else: edit
only `AGENTS.md`.

## Testing Guidelines

Tests use Python's standard-library `unittest`; there is no coverage threshold.
The synthetic suite uses a fake Podman and must not contact an engine or use
real credentials; every rejected input must be shown to stop before engine
queries and state creation. The real-engine suite runs only through
`tests/run-runtime.sh`, which provides private native Linux state and the host
socket; use a pseudo-terminal for interactive checks and pipes for
nonterminal ones. Cover budgets as effective cgroup v2 values, lifetime expiry,
refused workspaces, session container engine containment and owned cleanup. Record results and
limitations in `docs/validation.md`, keeping synthetic and real evidence apart,
and never count a skipped check as a pass.

## OpenSpec Workflow

Keep proposal, delta specs, design and tasks coherent. Proposal work changes
planning artifacts only; implement through the apply workflow, mark tasks after
verification, synchronize delta specs into main specs and archive completed
changes under dated directories. Delta specs start with `# Spec Delta`, and all
OpenSpec Markdown must pass markdownlint (blank lines around headings and lists).

## Commit & Pull Request Guidelines

Use concise imperative subjects. Keep commits focused. Pull requests explain
behavior changes, list verification, identify security, mount and naming
changes, and update `README.md`, `SECURITY.md` and `CHANGELOG.md` when usage
changes.

## Security & Configuration

- Pi runs its tools without approval prompts: the container is the only
  boundary. `PI_CONTAINER_YOLO` is a validated boolean for setup and future Pi
  releases; an enabled value only prints a notice and must never change engine
  arguments. `--approve` only trusts project-local files.
- Keep `--cap-drop=ALL`, `no-new-privileges`, the read-only root filesystem,
  noexec temporary storage, the pinned Pi version, and CI with hadolint and
  Trivy. Never add capabilities, `--privileged` or SELinux relabeling.
- Validate `PI_CONTAINER_MEMORY_LIMIT` (4g), `PI_CONTAINER_CPU_LIMIT` (2),
  `PI_CONTAINER_PIDS_LIMIT` (512) and `PI_CONTAINER_RUN_TIMEOUT` before engine
  queries with the claude-container `sandbox-ref-5` rules; request each budget
  only when the engine delegates its cgroup v2 controller
  (`Host.CgroupControllers`), announce unenforced ones, never require host
  changes to delegate them, and start a session only when enforced budgets
  match and unenforced ones are absent. Reported controllers count as delegated
  only with the `systemd` cgroup manager (`Host.CgroupManager`): a rootless
  `cgroupfs` engine reports controllers but applies no limits, so it delegates
  none (`delegated()` in `network/agent_budgets.py`, mirrored in
  `launcher/core.sh`). The process budget alone falls back to a soft and hard
  process rlimit set by the container's first process (never `--ulimit nproc`)
  when the engine kernel (`Host.Kernel`) is Linux 5.14 or later, which counts it
  per container; the mechanism (`cgroup`, `rlimit` or `none`) is one rule in
  `network/agent_budgets.py` and `launcher/core.sh`, verified and qualified like
  a cgroup budget.
- Keep automatic read-only tmpfs provisioning and leave `/dev` and its `devpts`
  to the engine (an explicit `devpts` gets `ptmxmode=000`, so no
  pseudo-terminal can be opened). Mount empty read-only `/dev/shm` and
  `/run/secrets`; never reintroduce `--read-only-tmpfs=false` or a writable
  `/dev/shm`.
- Debian packages are fetched over verified HTTPS only. The host CA reaches
  builds only as the `build-ca` secret, selected before any build including the
  build-only refresh, and never enters `build-inputs-hash`.
- Refuse a workspace or worktree parent that physically is `/`, a system
  directory, `/tmp`, the physical home, a `/mnt/<letter>` drive root or a
  Windows system or profile folder on such a drive, unless exactly
  `PI_CONTAINER_ALLOW_UNSAFE_WORKSPACE=1`.
- An unset or empty `PI_CONTAINER_NETWORK` selects `provider`, which needs the
  provider settings or stops with setup guidance; never fall
  back to unrestricted networking after a restricted failure. Restricted modes
  forward no host proxy or CA variables, only the network profile's key, and set
  `PI_OFFLINE=1`, `PI_SKIP_VERSION_CHECK=1` and `PI_TELEMETRY=0` after
  forwarding.
- Host Podman delegation is removed in every mode: exact `PI_CONTAINER_PODMAN=1`
  stops startup before engine queries with migration guidance pointing to image
  toolchains (`--container-toolchain add`), and other values (plus
  `PI_CONTAINER_PODMAN_SOCKET`) are ignored. Sessions with image toolchains get
  a private rootless container engine (`localhost/pi-container-engine:latest`)
  on `tcp://127.0.0.1:2375` inside the session network namespace with fixed
  hardening exceptions (`SETUID`, `SETGID`, `SYS_CHROOT`, `CHOWN` declared in
  `io.containers.capabilities`).
- Keep every image input pinned and the build policy explicit: build a
  missing image only under exact `PI_CONTAINER_MAINTENANCE=1`, stop on a stale
  `build-inputs-hash` until `--container-build` under maintenance, and never pipe
  remote install scripts to a shell.
- Sessions use `HOME=/pi-home` (ephemeral noexec tmpfs, or the private
  `PI_CONTAINER_STATE_DIR` in writable mode) with `.pi`, `.agents`, the npm
  cache and the opted-in gitconfig below it; the workspace keeps its host path.
- Mount `~/.gitconfig` only with exact `PI_CONTAINER_GITCONFIG=1`; keep `~/.pi`
  and `~/.agents` private and never repair or import state.

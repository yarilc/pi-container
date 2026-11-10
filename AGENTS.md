# Repository Guidelines

Write all documentation, comments, help, specifications and commit messages in
English. Communicate with the user in the language and style the user asks for.

## Project Structure & Module Organization

- `pi-container.sh` owns runtime policy: setting resolution and deprecated
  aliases, engine and delegation verification, state validation, mounts,
  hardening and budgets, environment forwarding, naming and owned cleanup.
- `Containerfile` and `.containerignore` define the Pi image (digest-pinned
  base, common toolset with the Podman client, Pi from `.version`, pinned
  OpenSpec and optional pinned Bun) and its five-file build context
  (including `network/relay.py` and `network/mux.py`).
- `tests/test_image_pins.py` rejects floating image inputs and a `.version`
  that differs from the policy's `tested.cli`.
- `agent/profile.json` and `agent/policies/default.json` hold every Pi-specific
  value used by the shared network code (identity, images, state layout and the
  four provider profiles). Restricted preparation, proxy lifecycle and restricted
  container arguments come from `network/session.py` (`prepare`, `start`,
  `agent-args`, `stop`); never re-implement them inline.
- `network/`, `setup/diagnostics.py` and the shared tests (`sandbox_profile.py`,
  `test_agent_profile.py`, `test_network_policy.py`, `test_mux.py`,
  `test_tls_client_hello.py`, `test_tls_proxy.py`, `test_platform.py`,
  `test_qualification.py`, `test_guard.py`, `test_session.py`,
  `test_network_feasibility.py` and their fixtures) are copied unchanged from
  `claude-container` at tag `sandbox-ref-6`. Never edit them here, and never
  add a profile identifier (`pi-container`, `anthropic`, `openai`, `gemini`,
  `openrouter`) to them; fix a defect in `claude-container` first, then copy the
  files again and update `tests/test_reference_copy.py`.
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
export PI_CONTAINER_NETWORK=unrestricted        # every launch needs a mode
PI_CONTAINER_MAINTENANCE=1 ./pi-container.sh --container-build --version   # build, then print Pi's version
./test-wrapper.sh                               # synthetic wrapper suite
bash tests/run-runtime.sh                       # real rootless checks with native Linux state
bash tests/run-runtime.sh --network             # restricted modes (also --wrapper, --shared, --guard, ...)
./test.sh                                       # disposable image build plus real checks
bash -n pi-container.sh test-wrapper.sh test.sh tests/run-runtime.sh
```

Lint through containers when the tools are not installed:

```bash
podman run --rm -v "$PWD:$PWD:ro" -w "$PWD" docker.io/koalaman/shellcheck:stable \
  pi-container.sh test.sh test-wrapper.sh tests/run-runtime.sh
podman run --rm -v "$PWD:$PWD:ro" -w "$PWD" docker.io/hadolint/hadolint:latest-alpine \
  hadolint --config .hadolint.yaml Containerfile tests/Containerfile.runner \
  network/Containerfile network/guard-build.Containerfile
podman run --rm -v "$PWD:$PWD:ro" -w "$PWD" docker.io/davidanson/markdownlint-cli2:latest \
  README.md SECURITY.md CONTRIBUTING.md CHANGELOG.md AGENTS.md docs/validation.md
```

## Coding Style & Naming Conventions

Use Bash with `set -Eeuo pipefail`, quoted variables and command arrays for
user-controlled arguments. Follow the script's four-space indentation, prefer
small functions, and prefix diagnostics with `pi-container:`. Wrapper settings
use the `PI_CONTAINER_` prefix; earlier names stay deprecated aliases resolved
by `select_setting`, which warns and rejects conflicting old and new values.
Forward secrets by name only (`--env NAME`), never as `NAME=value`.

## Testing Guidelines

Tests use Python's standard-library `unittest`; there is no coverage threshold.
The synthetic suite uses a fake Podman and must not contact an engine or use
real credentials; every rejected input must be shown to stop before engine
queries and state creation. The real-engine suite runs only through
`tests/run-runtime.sh`, which provides private native Linux state and the host
socket; use a pseudo-terminal for interactive checks and pipes for
nonterminal ones. Cover budgets as effective cgroup v2 values, lifetime expiry,
refused workspaces, delegation and owned cleanup. Record results and
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
  boundary. Do not add a YOLO switch; `--approve` only trusts project-local
  files.
- Keep `--cap-drop=ALL`, `no-new-privileges`, the read-only root filesystem,
  noexec temporary storage, the pinned Pi version, and CI with hadolint and
  Trivy. Never add capabilities, `--privileged` or SELinux relabeling.
- Validate `PI_CONTAINER_MEMORY_LIMIT` (4g), `PI_CONTAINER_CPU_LIMIT` (2),
  `PI_CONTAINER_PIDS_LIMIT` (512) and `PI_CONTAINER_RUN_TIMEOUT` before engine
  queries with the claude-container `sandbox-ref-5` rules; start a session only
  when the created container carries the selected budgets.
- Refuse a workspace or worktree parent that physically is `/`, a system
  directory, `/tmp`, the physical home or a `/mnt/<letter>` drive root, unless
  exactly `PI_CONTAINER_ALLOW_UNSAFE_WORKSPACE=1`.
- Require an explicit `PI_CONTAINER_NETWORK`; reject `PI_NETWORK`; never fall
  back to unrestricted networking after a restricted failure. Restricted modes
  forward no host proxy or CA variables, only the network profile's key, and set
  `PI_OFFLINE=1`, `PI_SKIP_VERSION_CHECK=1` and `PI_TELEMETRY=0` after
  forwarding.
- Delegate the host Podman socket only with exact `PI_CONTAINER_PODMAN=1` in
  unrestricted mode, after verifying the rootless service; never start services
  or fall back silently.
- Keep every image input pinned and the build policy explicit: build a
  missing image only under exact `PI_CONTAINER_MAINTENANCE=1`, stop on a stale
  `build-inputs-hash` until `--container-build` under maintenance, and never pipe
  remote install scripts to a shell.
- Sessions use `HOME=/pi-home` (ephemeral noexec tmpfs, or the private
  `PI_CONTAINER_STATE_DIR` in writable mode) with `.pi`, `.agents`, the npm
  cache and the opted-in gitconfig below it; the workspace keeps its host path.
- Mount `~/.gitconfig` only with exact `PI_CONTAINER_GITCONFIG=1`; keep `~/.pi`
  and `~/.agents` private and never repair or import state.

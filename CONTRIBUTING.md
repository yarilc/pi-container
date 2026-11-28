# Contributing

Thanks for your interest in pi-container!

## Project Scope

pi-container is a thin wrapper that runs the Pi Coding Agent inside a Podman
container. Its primary concerns are:

- **Security:** the wrapper must not weaken the container isolation boundary.
- **Correctness:** file ownership, unchanged SELinux policy, and environment forwarding
  must behave predictably.
- **Reproducibility:** the container image must be deterministic given the
  same `.version` and `Containerfile`.

## Development Workflow

### Prerequisites

- Linux rootless Podman ≥ 4.x, GNU coreutils timeout, Python 3 for synthetic tests
- Native Linux state storage for permission-sensitive checks
- ShellCheck, hadolint, markdownlint-cli2 (optional: `AGENTS.md` runs them
  through containers when they are not installed)

### Testing

```bash
# Unit tests for wrapper logic (uses a fake podman, no build needed)
./test-wrapper.sh

# Integration / smoke tests (builds a real image)
./test.sh

# Real wrapper acceptance from disposable native Linux storage
# Build your selected image first
PI_CONTAINER_IMAGE=localhost/pi-container ./tests/run-runtime.sh

# Restricted-mode and shared sandbox suites
bash tests/run-runtime.sh --wrapper    # shared launcher and Pi wrapper tests
bash tests/run-runtime.sh --shared     # suites copied from sandbox-container
bash tests/run-runtime.sh --network    # restricted modes with real rootless Podman
bash tests/run-runtime.sh --guard      # guard fixtures (toolchain image required)
```

`launcher/`, `network/`, `setup/` and the shared tests are copied unchanged
from `sandbox-container` (tag `sandbox-ref-36`); never edit them here. Fix a
defect in `sandbox-container` first, then copy the files again and update the
manifest in `tests/test_reference_copy.py`.

Run synthetic tests and credential-free real wrapper/image acceptance before a PR.
The runner provisions Python/Podman test tooling in a disposable image and
removes only its own image/volume. It does not forward provider credentials.
Record actual commands/results and missing prerequisites in docs/validation.md;
skips do not count as passes. Do not claim authenticated Pi verification.

Launcher behavior (signals, the 20-second shutdown deadline, naming, owned
cleanup, launch-engine verification, leftover delegation refusal, session
container engine wiring, state and mounts) is tested once, for every
wrapper, by the shared `tests/test_launcher.py` (with `tests/test_engine.py`
and `tests/test_toolchains.py`). A Pi launcher case it does not
cover goes into `sandbox-container` first. `tests/test_wrapper.py` covers only
Pi's agent part: its hooks, its restricted settings and the provider key per
policy profile. Help must work without Podman, state, or `.version`; native
`--help` goes to Pi.
Changes to identity, mounts, optional tools, or state must include real Pi/npm
and Git workflow checks, not only duplicated podman flags.

### Coding Style

- Shell scripts: `set -euo pipefail`, quote all variables, prefer `[[ ]]`.
- Follow ShellCheck recommendations (severity: warning).
- One environment variable per feature; document in help text and README.
- No hardcoded paths; all paths derived from `SCRIPT_DIR` or `$HOME`.

## Security

- No change that weakens the container's capability/read-only/SELinux posture
  will be accepted without a strong documented rationale.
- Environment variables containing secrets (API keys) must never appear on
  the process command line; forward by name only (`-e KEY`).
- New mounts must be documented in SECURITY.md and README.md.
- Wrapper settings use the `PI_CONTAINER_` prefix; earlier names have no
  effect. Launcher behavior lives in the shared `launcher/core.sh`; Pi adds only
  data and hooks in `agent/launcher.sh`. Fix a core defect in
  `sandbox-container` first.

## Versioning

The wrapper version (this repo) is independent of the Pi version (`.version`).
The wrapper follows [SemVer](https://semver.org/). The Pi version is managed
in `.version` and is the single source of truth for what gets installed in the
image.

## Pull Request Process

1. Run `./test-wrapper.sh` and `./test.sh`, plus lint and OpenSpec validation.
2. Update `CHANGELOG.md` with your change under "Unreleased".
3. If adding a new environment variable, update:
   - `agent_help` in `agent/launcher.sh` (a Pi variable) or the core's help in
     `sandbox-container` (a common variable)
   - `README.md` environment variables table
   - `SECURITY.md` if security-relevant
4. Open a PR against `main`.
5. Run the tests and linters in `AGENTS.md` (Build, Test, and Development
   Commands) in your working environment, and list the results in the PR.

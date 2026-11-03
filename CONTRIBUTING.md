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
- ShellCheck, hadolint, markdownlint-cli2 (optional, run in CI)

### Testing

```bash
# Unit tests for wrapper logic (uses a fake podman, no build needed)
./test-wrapper.sh

# Integration / smoke tests (builds a real image)
./test.sh

# Real wrapper acceptance from disposable native Linux storage
# Build your selected image first; optional Bun coverage is enabled by test.sh
PI_IMAGE_NAME=pi-container ./tests/run-runtime.sh
```

Run synthetic tests and credential-free real wrapper/image acceptance before a PR.
The runner provisions Python/Podman test tooling in a disposable image and
removes only its own image/volume. It does not forward provider credentials.
Record actual commands/results and missing prerequisites in docs/validation.md;
skips do not count as passes. Do not claim authenticated Pi verification.

Use readiness barriers for signal tests, full IDs for cleanup assertions, and
permanently stalled fixtures for creation cancellation. Production phases are
5s completion/grace, 5s TERM, 1s KILL observation, with 5s+1s bounded controls.
First interruption wins (143/130/129); exit 125 and redirected stdin/EOF must
remain intact. Check both terminal streams before TTY allocation. Concurrent
sessions must reserve names atomically above the maximum suffix, never replace
other sessions, and remove only verified owned IDs. Unknown ownership is a
diagnostic, not permission to delete by name. The native PI_RUN_TIMEOUT option
is separate from shutdown budgets.

All build/shell/worktree modes share engine/state/socket preflights. Help aliases
must work without Podman, state, or .version; native --help goes to Pi.
Changes to identity, mounts, optional tools, or state must include real Pi/npm,
Git, and enabled Bun workflow checks, not only duplicated podman flags.

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
- Sensitive-PWD guard list must be kept in sync with the case statement.

## Versioning

The wrapper version (this repo) is independent of the Pi version (`.version`).
The wrapper follows [SemVer](https://semver.org/). The Pi version is managed
in `.version` and is the single source of truth for what gets installed in the
image.

## Pull Request Process

1. Run `./test-wrapper.sh` and `./test.sh`, plus lint and OpenSpec validation.
2. Update `CHANGELOG.md` with your change under "Unreleased".
3. If adding a new environment variable, update:
   - `pi-container.sh` help text and env var block
   - `README.md` environment variables table
   - `SECURITY.md` if security-relevant
4. Open a PR against `main`.
5. CI must pass (lint, test, scan).

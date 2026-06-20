# Contributing

Thanks for your interest in pi-container!

## Project Scope

pi-container is a thin wrapper that runs the Pi Coding Agent inside a Podman
container. Its primary concerns are:

- **Security:** the wrapper must not weaken the container isolation boundary.
- **Correctness:** file ownership, SELinux labels, and environment forwarding
  must behave predictably.
- **Reproducibility:** the container image must be deterministic given the
  same `.version` and `Containerfile`.

## Development Workflow

### Prerequisites

- Podman ≥ 4.x (rootless)
- ShellCheck, hadolint, markdownlint-cli2 (optional, run in CI)

### Testing

```bash
# Unit tests for wrapper logic (uses a fake podman, no build needed)
./test-wrapper.sh

# Integration / smoke tests (builds a real image)
./test.sh
```

Always run both test suites before opening a PR.

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

1. Run `./test-wrapper.sh` and `./test.sh`.
2. Update `CHANGELOG.md` with your change under "Unreleased".
3. If adding a new environment variable, update:
   - `pi-container.sh` help text and env var block
   - `README.md` environment variables table
   - `SECURITY.md` if security-relevant
4. Open a PR against `main`.
5. CI must pass (lint, test, scan).

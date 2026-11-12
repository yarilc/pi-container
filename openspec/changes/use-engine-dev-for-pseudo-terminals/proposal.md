# Proposal

## Why

The agent device layout from `sandbox-ref-11` mounts its own `/dev` tmpfs
and an explicit `--mount type=devpts,destination=/dev/pts`. That `devpts`
takes the kernel defaults `mode=600,ptmxmode=000`, so no process in a
session can open a pseudo-terminal: `pty.openpty()` fails with "out of pty
devices". The terminal itself attaches, because the engine allocates the
console outside that `devpts`.

The defect reproduces with the Pi image on this host, Podman 4.9.3.
Antigravity, the Claude reference, Codex and OpenCode already fixed it by
leaving `/dev` to the engine (`use-engine-dev-for-pseudo-terminals`). The
operator's setups passed with that layout on this host, the Rocky Linux 9
lab host and the newer WSL host. Pi tools and interactive shell tools
(`script`, `expect`, `tmux`) that open their own PTY need the same fix. Pi
is the last wrapper with the defect.

## What Changes

- **Launcher (`pi-container.sh`):**
  - remove `--tmpfs "/dev:rw,nosuid,noexec,mode=755,size=65536k"` and
    `--mount type=devpts,destination=/dev/pts`;
  - keep `--read-only` with automatic read-only tmpfs provisioning, the
    empty read-only `/dev/shm` and the `/run/secrets` mask;
  - the engine then provides `/dev` and its `devpts`.
- **Tests:**
  - the wrapper assertions require no explicit `/dev` or `devpts` mount, and
    still require the `/dev/shm` and `/run/secrets` masks and the Pi
    temporary mounts;
  - a new runtime test opens a pseudo-terminal in a session and checks that
    `/dev/shm` and `/run/secrets` are empty and read-only.
- **Documentation:** `README.md`, `AGENTS.md`, and a validation record in
  `docs/validation.md`.
- **BREAKING (policy):**
  - on Podman 5, `/dev` is the engine's writable tmpfs without `noexec`. On
    Podman 4.9 it stays read-only. Unlike Codex and OpenCode, Pi's own
    temporary mounts are all `noexec`, so this adds a writable executable
    path besides the workspace and state mounts;
  - the requirement "Terminal-compatible device mounts", with its scenario
    "Executables cannot run from /dev", is removed and replaced, as in the
    reference.
- **BREAKING (installation):** qualification digests the launcher, so
  restricted installations rerun `--container-setup`. The runtime image is
  unchanged.
- **Unchanged:**
  - the proxy keeps `--read-only-tmpfs=false`;
  - the Pi `/tmp`, `/var/tmp`, `/run`, home and npm cache mounts;
  - shared code;
  - the open Bun decision.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `container-isolation`:
  - removes "Terminal-compatible device mounts";
  - adds "Engine-provided device mounts allow pseudo-terminals".

## Impact

- `pi-container.sh`, `tests/test_wrapper.py`, `tests/test_runtime.py`.
- `README.md`, `AGENTS.md`, `docs/validation.md`.

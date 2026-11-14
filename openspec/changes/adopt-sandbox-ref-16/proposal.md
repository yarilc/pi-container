# Proposal

## Why

claude-container published the operator-managed toolchain library in
`sandbox-ref-13`. It is one host directory shared by all five wrappers and
mounted read-only at `/toolchains`, so a restricted session can use Java, Go
or another relocatable toolchain without Podman access, an unrestricted
network or a rebuilt image. Later tags fixed defects found during the
adoptions:

- `sandbox-ref-14`: the shared qualification fixture installs `setup/`.
- `sandbox-ref-15`: toolchains cannot set `XDG_` variables.
- `sandbox-ref-16`: a shared comment no longer names an agent.

Codex and OpenCode already adopted `sandbox-ref-16` with the library. Pi is on
`sandbox-ref-12`. Without this change, its shared files diverge from the
reference, its parity table falls behind, and its sessions cannot see the
library.

## What Changes

- **Adopt `sandbox-ref-16`** with `tools/propagate.py` (`sandbox-ref-12` →
  `sandbox-ref-16`). The tool copies eight shared files byte for byte:
  - added: `setup/toolchains.py`, `tests/test_toolchains.py`;
  - modified: `network/agent_profile.py`, `network/control.py`,
    `network/qualification_records.py`, `setup/common.py`,
    `tests/test_alignment.py`, `tests/test_qualification.py`.

  It also moves the manifest and the current-state references (`README.md`,
  `AGENTS.md`, `CONTRIBUTING.md`, `docs/setup.md`,
  `docs/network-contract.md`) to the tag.
- **Port the launcher integration to `pi-container.sh`:**
  - `--container-toolchain add|list|remove|verify` as the first argument,
    dispatched before the network mode is read;
  - `PI_CONTAINER_TOOLCHAINS` (`0`/`false`/`no` omits the mount) and
    `PI_CONTAINER_TOOLCHAINS_DIR`;
  - the library checked by `launch-env` against the workspace and every
    state directory: the isolated `PI_CONTAINER_STATE_DIR`, or `~/.pi` (or
    `PI_CONTAINER_CONFIG_DIR`) and `~/.agents`, in writable and read-only
    state modes alike. It is then mounted at `/toolchains` with
    `ro,nosuid,nodev`;
  - `--mount-target /toolchains` for restricted sessions;
  - default toolchain `PATH` entries appended after the image's `PATH`, plus
    their variables;
  - the wrapper's own variables winning over toolchain variables. The
    launcher sets `PI_OFFLINE`, `PI_SKIP_VERSION_CHECK` and `PI_TELEMETRY` in
    restricted sessions, and those names are outside the protected wrapper
    prefix. The toolchain environment is therefore placed before them, and
    Podman keeps the last value;
  - help text for the option and both variables.
- **Tests:**
  - wrapper cases with the synthetic engine;
  - real-engine runtime cases;
  - the live add during an offline session;
  - adaptations of existing fixtures that the new mount affects.
- **Test runner:** `tests/run-runtime.sh` gives the suites a private
  executable tmpfs as `SANDBOX_TEST_TMPDIR`, and `tests/test_wrapper.py`
  creates its fixtures there, as in the other wrappers.
- **Documentation:**
  - a README "Toolchains" section adapted to Pi: the `AGENTS.md` instruction
    line, every tmpfs is `noexec` (the `GOTMPDIR` note applies), read-only
    state mode, and the protected variables;
  - the help-related README parts, `AGENTS.md` and `docs/setup.md`
    (requalification).

  The example recipes stay in claude-container and are linked.
- **BREAKING (installation):** the launcher and the qualified shared code
  change, so restricted installations rerun `--container-setup`.

## Capabilities

### New Capabilities

- `toolchain-library`: the shared library, the `--container-toolchain`
  command, the read-only `/toolchains` mount and default environment in Pi
  sessions, and the protected session variables. A Pi-specific requirement
  covers the wrapper variables that toolchains cannot override.

### Modified Capabilities

None.

## Impact

- The eight shared files, `tests/test_reference_copy.py`, `README.md`,
  `AGENTS.md`, `CONTRIBUTING.md`, `docs/setup.md`, `docs/network-contract.md`,
  `docs/validation.md`.
- `pi-container.sh`, `tests/test_wrapper.py`, `tests/test_runtime.py`,
  `tests/test_network_runtime.py`, `tests/run-runtime.sh`.
- `main` is one commit ahead of `origin/main` (the archive of `remove-bun`);
  that stays as it is.
- Out of scope:
  - registry network access;
  - the example recipes;
  - Antigravity (its own change);
  - an executable temporary directory for Pi.

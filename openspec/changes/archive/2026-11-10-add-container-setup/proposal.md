# Proposal

## Why

`add-network-egress` gave Pi restricted modes, but preparing them is still a manual operator procedure, and a missing mode only names `PI_CONTAINER_NETWORK`. This second Wave 3 change completes the Pi port of the Claude reference sandbox. It adds guided setup with a managed launcher, the unchanged shared setup and alignment tests, and the Pi row of the five-wrapper parity table.

Two gaps in the shared setup block Pi, and the operator decided both on 2026-11-10:
- **Runtime image build.** The shared setup builds the runtime image with a plain `podman build`. The Pi image needs the `PI_VERSION` and `INSTALL_BUN` build arguments and the `build-inputs-hash` label that only the wrapper computes. A setup-built Pi image would therefore stop every launch as stale.
- **YOLO.** Setup asks the YOLO question and exports `PI_CONTAINER_YOLO=0` or `1`. Today the Pi wrapper warns about any nonempty value, so every managed launch would warn, even with `0`.

## What Changes

- **Shared setup fix first (`sandbox-ref-7`).** In `claude-container`, the profile gains an optional field `install.runtime_build`:
  - `recipe` (the default) keeps today's direct `podman build` of `Containerfile`;
  - `wrapper` makes setup build the runtime image through the installed release's own wrapper build entry point, under maintenance and with the candidate image tag, then read its identity.

  Claude, Codex and OpenCode keep the default. Tag `sandbox-ref-7`, then recopy into Codex and OpenCode (manifests and tests) and into this repository.
- **Pi wrapper build entry point.** `--container-build` used alone builds the runtime image and exits without starting a session. It requires the exact `PI_CONTAINER_MAINTENANCE=1`, and it uses the same build arguments and staleness label as an ordinary launch. The profile declares `install.runtime_build: "wrapper"`.
- **YOLO handled as if Pi supported it** (operator decision of 2026-11-10). `PI_CONTAINER_YOLO` becomes a validated boolean, with the same values as the OpenCode wrapper: `0`, `1`, `true`, `false`, `yes` and `no`. Other values fail before engine queries.
  - An enabled value prints one stderr warning that Pi 0.80.8 has no tool-approval layer, so the setting has no effect yet.
  - A disabled value is silent.
  - In every case the engine arguments are unchanged.
  - Setup keeps its YOLO question.
- Copy the rest of `setup/` unchanged from `sandbox-ref-7` (`common.py`, `setup.py`, `launch.py`, `smoke.py`), plus the shared tests `tests/test_setup.py` and `tests/test_alignment.py`.
- Add `--container-setup`, used alone in an interactive terminal. It runs the shared setup, which:
  - asks for the mode, the authentication method (`anthropic`, `openai`, `gemini` or `openrouter`), state, endpoint, delegation, CA trust, YOLO, budgets and lifetime;
  - discloses the residual exfiltration risk of provider mode and requires its acknowledgement;
  - prepares the images and the guard under maintenance consent;
  - installs a protected release, including `.version`, with a managed launcher at `~/.local/bin/pi-container`;
  - runs qualification and a credential-free smoke check;
  - reports authentication as pending, naming the API-key variable of the selected method.
- **BREAKING (message only)**: an ordinary launch with an unset or empty `PI_CONTAINER_NETWORK` now stops with `setup required:` guidance pointing to `--container-setup`, instead of only naming the variable. Explicit operator modes keep working unchanged.
- The wrapper passes the application's stderr through the shared `setup/diagnostics.py` filter, as the other wrappers do. Wrapper messages that the shared tests check literally are aligned to the reference wording.
- Replace the temporary per-agent identifier scan with the unchanged `tests/test_alignment.py`. Keep `tests/test_reference_copy.py` as the byte-identity check, extended to the new shared files.
- Add the per-agent `tests/test_setup_runtime.py` and the `--setup` and `--setup-runtime` runner modes.
- Add `docs/setup.md`, and update the README, help, `AGENTS.md`, `CHANGELOG.md` and `docs/validation.md`.
- Add the five-wrapper parity table to `docs/network-contract.md` with the Pi row. Replace the "Pending" Pi row in `claude-container`, `codex-container` and `opencode-container` with the same row, in documentation-only commits.

## Capabilities

### New Capabilities

- `container-setup`: interactive host-side setup, covering:
  - the questionnaire and its prerequisites;
  - reviewed mutations and maintenance consent;
  - the runtime image built through the Pi wrapper;
  - the protected installation and managed launch preferences;
  - API-key authentication assistance;
  - qualification and smoke readiness;
  - repeatable activation with rollback;
  - the provider acknowledgement;
  - saved budgets.

### Modified Capabilities

- `container-session`: missing-mode admission points to setup; first-user setup and migration guidance is added.
- `container-launcher`:
  - `PI_CONTAINER_YOLO` becomes a validated boolean that warns only when enabled;
  - `--container-build` alone builds the image and exits.
- `network-egress`:
  - the missing-mode scenario directs to setup;
  - the managed launcher can supply the mode;
  - the alignment check uses the shared `test_alignment.py` across `network/` and `setup/`;
  - the contract documentation includes the parity table.

## Impact

- **Code:**
  - `pi-container.sh`: `--container-setup`, the build-only `--container-build`, the YOLO boolean, the setup-required message, the diagnostics filter and the aligned messages;
  - `agent/profile.json`: `install.runtime_build`;
  - new copied files: `setup/common.py`, `setup/setup.py`, `setup/launch.py`, `setup/smoke.py`.
- **Tests:**
  - shared `test_setup.py` and `test_alignment.py`;
  - per-agent `test_setup_runtime.py`;
  - updates to `test_wrapper.py`, `test_reference_copy.py` and `run-runtime.sh`.
- **Users:**
  - new users run `bash ./pi-container.sh --container-setup` once and then use the managed launcher;
  - direct operator launches still work with an explicit mode;
  - an invalid `PI_CONTAINER_YOLO` value now fails instead of warning.
- **Other repositories:**
  - `claude-container`: `install.runtime_build`, tag `sandbox-ref-7`, and the Pi parity row;
  - `codex-container` and `opencode-container`: adoption of `sandbox-ref-7` and the Pi parity row.
- **Out of scope:**
  - authenticated provider verification, which stays operator-run;
  - subscription or OAuth logins for Pi;
  - a Bun choice in setup: setup builds without Bun, and a managed launch that sets `PI_ENABLE_BUN` stops as stale until an explicit rebuild;
  - the Antigravity port.

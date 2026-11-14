# Proposal

## Why

Pi is on `sandbox-ref-16`. claude-container has published
`sandbox-ref-17` (change `share-toolchain-env-across-profiles`), which makes
the toolchain library work the same way in every wrapper:

- **Neutral variables:** `DBUS_SESSION_BUS_ADDRESS` joins the variables that
  every wrapper protects. No session has a bus.
- **Profile variables:** previously, if a toolchain in the shared index set a
  variable that only the current wrapper protects, `launch-env` refused the
  whole library. This happens when another wrapper installed the toolchain,
  for example one that sets `CLAUDE_CONFIG_DIR`. `launch-env` now leaves that
  variable out of the session and prints one warning naming the toolchain.

Without this change, Pi's copy of the shared module differs from the
reference, and a toolchain installed from another wrapper can block every
Pi session that uses the library. claude-container, Antigravity, Codex
and OpenCode already run `sandbox-ref-17`.

The dry run of `tools/propagate.py ../pi-container sandbox-ref-16
sandbox-ref-17` lists:

- two modified files: `setup/toolchains.py` and `tests/test_toolchains.py`;
- nothing added, removed or "not adopted";
- the manifest moving to commit `a23f155`.

## What Changes

- **Adopt `sandbox-ref-17`** with `tools/propagate.py`. The tool copies the
  two shared files byte for byte. It also moves the reference manifest and
  the current-state references to the tag: `README.md`, `AGENTS.md`,
  `CONTRIBUTING.md`, `docs/setup.md` and `docs/network-contract.md`,
  including the parity cells.
- **Rewrite the README "Protected variables" bullet** for the two groups:
  - the neutral variables, including `DBUS_SESSION_BUS_ADDRESS`;
  - Pi's own variables: `PI_CONTAINER_*`, which covers its configuration and
    approval variables, and the four credential variables
    `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, `GEMINI_API_KEY` and
    `OPENROUTER_API_KEY`. `add` rejects them. If another wrapper's toolchain
    sets one, `launch-env` leaves it out of the session with a warning.

  The bullet keeps the note that Pi's session settings (`PI_OFFLINE`,
  `PI_SKIP_VERSION_CHECK`, `PI_TELEMETRY`) come after the toolchain
  environment. The requirement "Pi session settings win over toolchain
  variables" is unchanged.
- **Update the spec:** the protected-variables requirement in
  `toolchain-library` takes the reference's text.
- **No launcher change.** `pi-container.sh` reads only the standard
  output of `launch-env`, and the warnings go to standard error, so they reach
  the user unchanged. `setup/toolchains.py` is qualified code, so restricted
  installations rerun `--container-setup`.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `toolchain-library`: protected variables are now neutral or profile
  variables. The bus variable is protected. A variable that another wrapper's
  toolchain sets in the shared index is left out with a warning, instead of
  failing the session.

## Impact

- `setup/toolchains.py`, `tests/test_toolchains.py`,
  `tests/test_reference_copy.py`, `README.md`, `AGENTS.md`,
  `CONTRIBUTING.md`, `docs/setup.md`, `docs/network-contract.md`,
  `docs/validation.md`.
- After this change, all five wrappers run `sandbox-ref-17`.

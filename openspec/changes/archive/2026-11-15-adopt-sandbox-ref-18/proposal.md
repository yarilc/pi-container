# Proposal

## Why

Pi is on `sandbox-ref-17`. claude-container has published `sandbox-ref-18`
(change `harden-shared-session-boundaries`), from the cross-wrapper review of
2026-11-14:

- **Agent variables:** the optional profile field `native.protected_env`
  lists the variables and `_`-terminated prefixes the agent itself reads.
  Toolchains cannot set them: `add` rejects them and `launch-env` leaves them
  out with a warning. Without a declaration, Pi keeps today's protection.
- **Toolchain check in `/`:** `toolchains.check()` passes `--workdir /`.
- **No state inside the workspace:** the shared `writable_mounts()` refuses
  an isolated state directory that overlaps the workspace, so managed
  launches refuse it.
- **Alignment tests:** the mismatch test runs the real check, which reads the
  launcher's code and its help text separately.

The review also found gaps in Pi's own launcher that the reference does not
have:

- **Interrupted creation (M2):** when creation is interrupted before an ID
  is published, cleanup only prints "creation outcome unresolved"
  (`pi-container.sh:1004`). It never looks the container up by its session
  label. An owned container left behind keeps the forwarded credential in its
  stored configuration until someone removes it.
- **Name collisions (M2):** after a failed create without an ID, any
  existing container with the candidate name counts as a collision
  (`pi-container.sh:1120`), even when it carries this session's label. The wrapper
  then moves to the next name and leaves its own container behind. The
  reference checks the label first.

## What Changes

- **Adopt `sandbox-ref-18`** with `tools/propagate.py`. The dry run lists
  seven modified shared files (`network/agent_profile.py`, `setup/common.py`,
  `setup/toolchains.py` and four shared tests), nothing added, removed or "not
  adopted", and the manifest moving to commit `958465b`.
- **Declare Pi's agent variables** in `agent/profile.json`
  `native.protected_env`: `PI_`, `ANTHROPIC_`, `OPENAI_`, `GEMINI_`, `OPENROUTER_`, `GOOGLE_API_KEY`.
- **Ownership-checked collisions:** a failed create without an ID counts as a
  collision only when the existing container's session label differs from
  this session's token. Otherwise the wrapper reports the failure and removes
  its own container in cleanup.
- **Label recovery in cleanup:** when creation was interrupted or failed
  without a valid ID, cleanup looks up `ps --all --filter label=<session>`
  within its deadline, confirms the label and removes the container. It
  reports unresolved creation only when the lookup fails or finds nothing.
- **Tests and docs:** wrapper tests for each new behavior; the README
  "Protected variables" bullet lists the agent variables.
- **Requalification:** shared qualified code changes, so restricted
  installations rerun `--container-setup`.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `toolchain-library`: the toolchain check starts in `/`; profile variables
  include the agent variables the profile declares.
- `container-session`: name collisions are confirmed by ownership; interrupted creation is recovered by the session label.

## Impact

- Shared copies: `network/agent_profile.py`, `setup/common.py`,
  `setup/toolchains.py`, `tests/test_agent_profile.py`,
  `tests/test_alignment.py`, `tests/test_setup.py`, `tests/test_toolchains.py`,
  `tests/test_reference_copy.py`.
- Pi: `agent/profile.json`, `pi-container.sh`, `tests/test_wrapper.py`, `README.md`,
  `docs/network-contract.md`, `docs/validation.md` and the documents the tool
  updates.
- Out of scope: credential forwarding (M1), the remaining low-severity review
  items.

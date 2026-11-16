# Proposal

## Why

`sandbox-ref-21` fixes a defect of the shared `tests/test_guard.py`: `production_container` ran the real Pi image with the fixture profile's home (`/fixture-home`) as its writable tmpfs instead of the wrapper's native home. Pi passed under `sandbox-ref-20` only because its command does not write to its home at startup. Shared files change only by adopting the reference tag.

## What Changes

- Adopt `sandbox-ref-21` with `tools/propagate.py` from `sandbox-container`: `tests/test_guard.py` and `tests/sandbox_profile.py` (which now exposes `AGENT_HOME`), the manifest in `tests/test_reference_copy.py` and the tag in the current-state documents.
- Fix the parity table by hand after `--apply`.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `network-egress`: the shared guard runtime test runs the real image with the wrapper's own writable native home.

## Impact

- Shared test files only; no launcher, image, profile or qualified code changes, so installations need no new setup for this tag.

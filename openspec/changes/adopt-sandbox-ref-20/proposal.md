# Proposal

## Why

`sandbox-container` is now the reference for the shared sandbox components: `sandbox-ref-19` moved the role away from `claude-container`, and `sandbox-ref-20` fixed two adoption blockers. Claude already adopted `sandbox-ref-20`. Pi still holds `sandbox-ref-18`, and its manifest, documents and spec still name `claude-container` as the reference, so this change brings it to `sandbox-ref-20` like the other wrappers.

## What Changes

- Adopt `sandbox-ref-20` with `tools/propagate.py` run from `sandbox-container`. The run copies the changed shared files, among them:
  - the fixture profiles in `tests/fixtures/` and the shared tests that use them;
  - support for profiles without authentication methods;
  - the wrapper-independent guard test.

  It also points `tests/test_reference_copy.py` at `sandbox-container` (`SIBLING`, docstring and skip message) and moves the tag in the current-state documents.
- Add the per-agent `tests/test_setup_wrapper.py` with the eight setup tests that launch this wrapper. These tests left the shared `tests/test_setup.py`. The file is the same as Claude's, because the tests read only the checkout's profile.
- Fix the session lifetime notice in `pi-container.sh`, as in the reference and in Claude. Bash `SECONDS` counts whole seconds, so a short failing session that crossed a second boundary was reported as a reached lifetime limit. Add a boundary test.
- Documents:
  - README, `AGENTS.md` and `docs/setup.md` name `sandbox-container` as the reference.
  - In the `docs/network-contract.md` parity table, the reference row and the Claude and Pi rows read `sandbox-ref-20`; rows of wrappers that have not adopted yet keep their tag.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `network-egress`: the shared components stay byte-identical to the `sandbox-container` reference copy, and the parity table is shared with `sandbox-container`, instead of `claude-container`.

## Impact

- Shared files from `sandbox-ref-20`. Installed code changes, so installations rerun `--container-setup`.
- Per-agent files: `pi-container.sh` (lifetime notice), `tests/test_setup_wrapper.py`, `tests/test_wrapper.py` (boundary test) and the documents above.
- Operator: push, then run setup on the three hosts. The newer WSL host needs host CA trust because of its TLS-inspecting VPN.

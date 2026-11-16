# Design

## Context

Pi is on `sandbox-ref-20`. `sandbox-ref-21` changes two shared test files and nothing else.

## Decisions

1. **Adopt with the tool, from `sandbox-ref-20`.** The dry run must list only `tests/test_guard.py`, `tests/sandbox_profile.py` and the manifest.
2. **Parity table fixed by hand.** `--apply` rewrites every `sandbox-ref-20` in `docs/network-contract.md`. The reference row is copied from `sandbox-container`, the Pi row reads `Ported from sandbox-ref-21`, and every other wrapper row is copied from that wrapper's repository.
3. **Validation scope.** Only shared tests change, so the unit discovery, `--guard` (which runs the changed test) and `git diff --check` are enough.

## Risks / Trade-offs

- [Rows of wrappers adopted later stay on `sandbox-ref-20` here] → After all five adoptions, the parity tables are made identical again.

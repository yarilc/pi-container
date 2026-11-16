# Design

## Context

Pi adopted `sandbox-ref-18` through `tests/test_reference_copy.py` (58 files, `SIBLING = ROOT.parent / 'claude-container'`). The jump to `sandbox-ref-20` changes the shared test ownership:
- module-level shared tests use fixture profiles;
- the eight setup tests that launch the wrapper become per-agent;
- the qualification runtime gate and the checkout checks read the real profile.

Claude made the same adoption in its change `adopt-sandbox-ref-20`.

## Goals / Non-Goals

**Goals:**
- Pi adopts `sandbox-ref-20` through the normal tool path, and every runner mode passes.

**Non-Goals:**
- Provider policies, profile or authentication behavior.
- The other wrappers' adoptions.

## Decisions

1. **`tests/test_setup_wrapper.py` is copied from `claude-container`.** Its tests and helpers use `REAL_PROFILE`, `REAL_WRAPPER` and `real_env` only, and run the real setup modules in a subprocess. The `sandbox-ref-18` tests they come from were shared, so the behavior they check is the same in every agent wrapper.
   - Alternative considered: re-extracting the tests from `sandbox-ref-18`. Rejected, because it gives the same text and has more room for error.
2. **The parity table is fixed by hand.** The tool replaces every `sandbox-ref-18` in `docs/network-contract.md`. After `--apply`:
   - rows of wrappers still on `sandbox-ref-18` are restored;
   - the `Sandbox (reference)` row is added;
   - the Claude row is copied from `claude-container`;
   - the Pi row reads `Ported from sandbox-ref-20`.
3. **The lifetime notice is measured with a monotonic clock from just before container creation**, as in the reference. Bash `SECONDS` and `EPOCHREALTIME` follow the wall clock, which WSL2 steps backwards by seconds when it resynchronises with the host; `/proc/uptime` does not move. The boundary test runs eight failing sessions of 0.3 s with a 1 s limit; it fails with the old launcher.
4. **The `network-egress` requirements are MODIFIED in place.** The two requirements naming `claude-container` change only that name, so no scenario is renamed.

## Risks / Trade-offs

- [A Pi-specific test relies on the old shared view of the profile] → The full runner set runs before merging. A failure caused by shared code goes back to `sandbox-container` under a new tag, as `docs/propagation.md` there requires.

## Migration Plan

Branch, run the tool's dry run, then `--apply`, then the per-agent adjustments and every runner mode. Merge; the operator pushes and reruns setup on the three hosts; then archive with sync. Rollback: discard the branch.

Wrapper notes: Also run `./test.sh`. `PI_ENABLE_BUN` stays unset.

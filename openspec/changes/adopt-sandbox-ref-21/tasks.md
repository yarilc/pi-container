# Tasks

## 1. Adopt sandbox-ref-21

- [ ] 1.1 Commit this change directory on `main`, create `prepare-adopt-sandbox-ref-21`, then from `sandbox-container` run `python3 -I tools/propagate.py ../pi-container sandbox-ref-20 sandbox-ref-21` (dry run) and `--apply`; verify the plan lists only `tests/test_guard.py`, `tests/sandbox_profile.py` and the manifest, and that the tool switched to `adopt-sandbox-ref-21`.
- [ ] 1.2 Fix the parity table by hand (design decision 2); verify the reference row equals `sandbox-container`'s and the other wrapper rows equal their own repositories'.

## 2. Validation and merge

- [ ] 2.1 Run the unit discovery in the disposable test container, `bash tests/run-runtime.sh --guard` with `localhost/pi-container:setup-3705f13b91c1402ab8f7f184e1f6e886`, and `git diff --check`; verify all pass.
- [ ] 2.2 Add the `sandbox-ref-21` adoption section to `docs/validation.md`, commit, merge into `main`; verify `tests/test_reference_copy.py` passes with host Python next to the `sandbox-container` checkout (sibling check not skipped).

## Workflow follow-up

- The operator pushes `main` and runs `--container-setup` on the three hosts, together with the `sandbox-ref-20` adoption.
- Archive this change with spec sync.

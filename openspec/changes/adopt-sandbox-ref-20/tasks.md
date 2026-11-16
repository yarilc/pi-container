# Tasks

## 1. Adopt `sandbox-ref-20`

- [x] 1.1 Commit this change directory on `main`'s state, then from `sandbox-container` run `python3 -I tools/propagate.py ../pi-container sandbox-ref-18 sandbox-ref-20` (dry run), then `--apply`; verify the plan lists the shared and fixture files and `manifest: names sandbox-container`, and that the tool switched to `adopt-sandbox-ref-20`.
- [x] 1.2 Fix the parity table by hand (design decision 2); verify the reference and Claude rows equal those in `sandbox-container` and `claude-container`, and the rows of wrappers still on `sandbox-ref-18` equal their own repositories'.

## 2. Per-agent adjustments

- [x] 2.1 Copy `claude-container/tests/test_setup_wrapper.py` byte for byte (design decision 1); verify `discover -s tests -p test_setup_wrapper.py` passes in the disposable test container.
- [x] 2.2 Port the lifetime-notice fix to `pi-container.sh` and add the boundary test to `tests/test_wrapper.py` (`PI_CONTAINER_RUN_TIMEOUT='1'`, `FAKE_START_DELAY='0.3'`, `FAKE_EXIT='3'`, eight attempts); verify it fails with the old launcher and `bash tests/run-runtime.sh --wrapper` passes.
- [x] 2.3 Replace `claude-container` as the reference in README, `AGENTS.md` and `docs/setup.md` (history in `docs/validation.md` and archived changes stays); verify `grep -n claude-container README.md AGENTS.md docs/setup.md docs/network-contract.md` shows only the Claude parity row and mentions of Claude as a sibling wrapper.

## 3. Integration

- [x] 3.1 Run the unit discovery in the disposable test container and every runner mode (`--setup`, `--setup-runtime`, `--qualification`, `--guard`, `--network`, `--network-policy`, `--network-feasibility`, `--wrapper`, default) with the Pi setup image, plus `git diff --check`. Wrapper notes: Also run `./test.sh`. `PI_ENABLE_BUN` stays unset. Verify all pass.
- [x] 3.2 Add the `sandbox-ref-20` adoption section to `docs/validation.md` from the tool's template, commit with the tool's message and merge into `main`; verify `tests/test_reference_copy.py` passes with host Python next to the `sandbox-container` checkout (sibling check not skipped).

## Workflow follow-up

- The operator pushes `main` and reruns `--container-setup` on the three hosts (host CA trust on the newer WSL host), then checks a Pi session.
- Archive with spec sync.

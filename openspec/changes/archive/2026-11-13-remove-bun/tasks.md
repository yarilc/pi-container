# Tasks

## 1. Failing tests first

- [x] 1.1 On a branch `remove-bun`, update `tests/test_image_pins.py` (design
  decision 5): remove `bun` from `PACKAGES` and the `BUN_VERSION` assertion,
  move the 'unversioned package' and 'remote installer' mutations to
  OpenSpec, add the 'unexpected package' case (`bun@1.3.14` added to the
  install) and the `violations()` allowlist check. Verify that the new case
  fails on the current recipe (Bun is a conditional install).
- [x] 1.2 Update `tests/test_wrapper.py` and `tests/fake_podman.py` (design
  decisions 1, 2 and 4): build arguments exactly `PI_VERSION`, a hash
  without the `INSTALL_BUN` line, no change from `PI_ENABLE_BUN` or
  `PI_BUN_VERSION`, one `PI_PULL_ALWAYS` warning, and a help text without
  Bun. Verify that the updated cases fail on the current launcher.

## 2. Recipe and launcher

- [x] 2.1 In `Containerfile`, remove `INSTALL_BUN`, `BUN_VERSION`, the
  conditional install and the Bun comments. Verify that
  `grep -ci bun Containerfile` prints `0` and that
  `tests/test_image_pins.py` passes.
- [x] 2.2 In `pi-container.sh`, remove the `PI_ENABLE_BUN` reading, the
  `INSTALL_BUN` build argument and hash line, and `PI_BUN_VERSION` from the
  warning loop. Update the help text and the stale-image message. Verify
  that `bash -n pi-container.sh` passes, that `grep -ci bun pi-container.sh`
  prints `0`, and that `tests/test_wrapper.py` passes.
- [x] 2.3 In `test.sh` and `tests/run-runtime.sh`, remove `INSTALL_BUN` and
  `PI_TEST_BUN`, and update the `test.sh` help text. In
  `tests/test_runtime.py`, remove the `PI_TEST_BUN` block and the
  `PI_ENABLE_BUN` timeout branch, keep the `bun` absence assertion, and
  rename the test without `_and_optional_bun` (design decision 3). Verify
  that `bash -n test.sh tests/run-runtime.sh` passes.

## 3. Documentation

- [x] 3.1 Update `README.md`, `AGENTS.md`, `CONTRIBUTING.md`, `SECURITY.md`,
  `docs/setup.md` and `docs/network-contract.md` (design decision 6). Add
  the `CHANGELOG.md` `[Unreleased]` "Removed" entry. Verify that
  `grep -n -i bun` over these files matches only the changelog's existing
  entries, the new removal entry and statements that the image has no Bun.

## 4. Validation and publication

- [x] 4.1 Run the full unit discovery on executable, private, native
  temporary storage. Verify that there are no failures, apart from known
  timing-sensitive tests that pass on a rerun, which are recorded as such.
- [x] 4.2 Build a disposable image with `./test.sh` (it runs
  `tests/run-runtime.sh`). Verify that it passes, including the `bun`
  absence assertion, and that the test image is removed.
- [x] 4.3 Run `grep -rn -i bun` over the repository, excluding `.git`,
  `openspec/changes/archive` and `openspec/specs`. Verify that every
  remaining hit is an existing dated validation record, an existing
  changelog entry, the new removal entry, an absence assertion or a
  statement that Bun is not in the image.
- [x] 4.4 Add a dated validation record to `docs/validation.md` with the
  results of 1.1–4.3, the closure of the open Bun decision, and the operator
  setups as pending. Verify that `git diff --check` is clean and that
  `openspec validate remove-bun --strict` passes.
- [x] 4.5 Commit on the branch with the co-author trailer, merge it into
  `main` with `--no-ff`, and verify that `git log --oneline -3` shows the
  merge.

## Workflow follow-up

- The operator pushes `main`, then runs `--container-setup` on this host, the
  Rocky Linux 9 lab host and the newer WSL host. The results are added to
  `docs/validation.md`.
- Sync the delta specs and archive this change.

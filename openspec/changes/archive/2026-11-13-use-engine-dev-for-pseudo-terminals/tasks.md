# Tasks

## 1. Failing test first

- [x] 1.1 On a branch `use-engine-dev-for-pseudo-terminals`, add
  `test_pseudo_terminals_and_device_masks` to `tests/test_runtime.py`
  (design decision 3). Run
  `PI_CONTAINER_IMAGE=<image 5428725d0274 tag> bash tests/run-runtime.sh -k test_pseudo_terminals_and_device_masks`
  with the current launcher, and verify that it fails with "out of pty
  devices".

## 2. Launcher

- [x] 2.1 In `pi-container.sh`, remove the `/dev` tmpfs and the `devpts`
  mount, keep the `/dev/shm` and `/run/secrets` masks, and use the
  reference comment (design decision 1). Verify that
  `bash -n pi-container.sh` passes and that
  `grep -c devpts pi-container.sh` prints `0`.
- [x] 2.2 Update the tmpfs check, `DEVICE_MOUNTS` and
  `assert_device_and_secret_mounts` in `tests/test_wrapper.py` (design
  decision 3). Verify that `tests/test_wrapper.py` passes, and that the
  updated assertions fail on the unfixed launcher.
- [x] 2.3 Verify that `test_pseudo_terminals_and_device_masks` now passes.

## 3. Documentation

- [x] 3.1 Update `README.md` and `AGENTS.md` (design decision 4). Verify that
  `grep -n -E "devpts|/dev:rw" README.md AGENTS.md` matches only text that
  explains why no explicit `devpts` is used, or names the engine's `devpts`.

## 4. Validation and publication

- [x] 4.1 Run the full unit discovery on executable, private, native
  temporary storage. Verify that there are no failures, apart from known
  timing-sensitive tests that pass on a rerun, which are recorded as such.
- [x] 4.2 Run `bash tests/run-runtime.sh` (`test_runtime.py`) with the same
  image. Verify that it passes, including
  `test_identity_storage_hardening_and_ephemeral_lifetime` and the new PTY
  test.
- [x] 4.3 Add a validation record to `docs/validation.md` with the results
  of 1.1 and 2.2–4.2, and the operator setups as pending. Verify that
  `git diff --check` is clean and that
  `openspec validate use-engine-dev-for-pseudo-terminals --strict` passes.
- [x] 4.4 Commit on the branch with the co-author trailer, merge it into
  `main` with `--no-ff`, and verify that `git log --oneline -3` shows the
  merge.

## Workflow follow-up

- The operator pushes `main`, then runs `--container-setup` on this host, the
  Rocky Linux 9 lab host and the newer WSL host. The results are added to
  `docs/validation.md`.
- Sync the delta specs and archive this change.

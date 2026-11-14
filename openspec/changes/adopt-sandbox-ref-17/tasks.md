# Tasks

## 1. Adopt sandbox-ref-17

- [x] 1.1 From claude-container, run `python3 -I tools/propagate.py
  ../pi-container sandbox-ref-16 sandbox-ref-17` (dry run). Verify that it
  lists `setup/toolchains.py` and `tests/test_toolchains.py` as modified,
  nothing added, removed or "not adopted", and commit `a23f155`.
- [x] 1.2 Stash the change directory and run `--apply`, which creates the
  branch `adopt-sandbox-ref-17`. Restore the stash on that branch. Verify
  that:
  - the stash list is empty;
  - `git diff --name-only` lists only the two shared files,
    `tests/test_reference_copy.py` and the five documents;
  - `python3 -m unittest tests.test_reference_copy tests.test_alignment
    tests.test_toolchains` passes on private temporary storage.

## 2. Documentation

- [x] 2.1 Rewrite the README "Protected variables" bullet for the two
  groups, following the reference:
  - the neutral variables, including `DBUS_SESSION_BUS_ADDRESS`, the same in
    every wrapper;
  - Pi's own variables (`PI_CONTAINER_*` and the four credential variables),
    which `add` rejects, and which sessions leave out with a warning when
    another wrapper's toolchain sets them.

  Keep the note on Pi's session settings. Verify with
  `grep -n 'DBUS_SESSION_BUS_ADDRESS' README.md`.

## 3. Validation and publication

- [x] 3.1 Run the full unit discovery on private executable temporary
  storage. Then run `bash tests/run-runtime.sh` with:
  - the modes the tool lists: `--shared`, `--setup` and `--setup-runtime`;
  - `--qualification`, because a `SHARED_CODE` file changed;
  - `--wrapper` and the default mode, because the launcher runs `launch-env`.

  Use the current Pi setup image as `PI_CONTAINER_IMAGE`, with
  `PI_ENABLE_BUN` unset. Verify that each mode passes. Record any known
  timing-sensitive test that passes on a rerun as such.
- [x] 3.2 Fill in the tool's validation-record template in
  `docs/validation.md` with the results, the requalification note and the
  operator setups as pending. Verify that:
  - the parity table rows match claude-container's;
  - `git diff --check` is clean;
  - markdownlint passes on `README.md`, `AGENTS.md`, `CONTRIBUTING.md`,
    `docs/validation.md` and the change's Markdown;
  - `openspec validate adopt-sandbox-ref-17 --strict` passes.
- [x] 3.3 Commit on `adopt-sandbox-ref-17` with the tool's message and the
  co-author trailer, merge into `main` with `--no-ff`, and verify that
  `git log --oneline -3` shows the merge.

## Workflow follow-up

- The operator pushes Pi `main` and reruns `--container-setup` on the three
  hosts. The results are added to `docs/validation.md`.
- Sync the delta spec and archive this change.

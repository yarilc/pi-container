# Tasks

## 1. Adopt sandbox-ref-16

- [x] 1.1 Stash the change directory and, from claude-container, run
  `python3 -I tools/propagate.py ../pi-container sandbox-ref-12
  sandbox-ref-16` (dry run). Verify that it lists six modified and two added
  shared files, nothing removed or "not adopted", and commit `1fa091e`.
- [x] 1.2 Run `--apply` and restore the stash on branch
  `adopt-sandbox-ref-16`. Verify that:
  - the stash list is empty;
  - `git diff --name-only` lists only the shared files,
    `tests/test_reference_copy.py` and the five documents;
  - `python3 -m unittest tests.test_reference_copy tests.test_toolchains`
    passes on private temporary storage, including the agent-identifier
    scans.

  `test_alignment` may fail only on the profile variables, until 2.2.

## 2. Launcher, test first

- [x] 2.1 In `tests/test_wrapper.py`, add the cases of design decision 4, and
  install `setup/` and `Containerfile` in its restricted fixtures. Verify that
  the new cases fail on the current launcher.
- [x] 2.2 Port design decisions 2 and 3 to `pi-container.sh`, including the
  help text for `--container-toolchain`, `PI_CONTAINER_TOOLCHAINS` and
  `PI_CONTAINER_TOOLCHAINS_DIR`. Verify that:
  - `bash -n` passes on `pi-container.sh`;
  - `tests/test_wrapper.py` and `tests/test_alignment.py` pass on private
    temporary storage;
  - `./test-wrapper.sh` passes.

  Record each existing fixture that needs an adaptation.
- [x] 2.3 Give `tests/run-runtime.sh` the private tmpfs and
  `SANDBOX_TEST_TMPDIR`, and create the `tests/test_wrapper.py` base there
  (design decision 5). Verify that `bash tests/run-runtime.sh --wrapper`
  passes.

## 3. Real-engine checks

- [x] 3.1 Port the runtime cases to `tests/test_runtime.py` and the live add
  to `tests/test_network_runtime.py`, whose installation gains `setup/` and
  `Containerfile`. With the current Pi setup image as `PI_CONTAINER_IMAGE`,
  verify that `bash tests/run-runtime.sh` and `bash tests/run-runtime.sh
  --network -k toolchain` pass.

## 4. Documentation

- [x] 4.1 Add the README "Toolchains" section (design decision 6) and update
  the help-related README parts, `AGENTS.md` and `docs/setup.md`. Verify that
  every `PI_CONTAINER_TOOLCHAINS*` variable and every `--container-toolchain`
  operation appears in both the help text and the README.

## 5. Validation and publication

- [x] 5.1 Run the full unit discovery on executable, private, native
  temporary storage. Verify that there are no failures, apart from known
  timing-sensitive tests that pass on a rerun, which are recorded as such.
- [x] 5.2 Run `bash tests/run-runtime.sh` with every mode the tool listed and
  the default mode, and `./test.sh`, with `PI_ENABLE_BUN` unset. Verify that
  each passes, or record it as unavailable.
- [x] 5.3 Fill in the tool's validation-record template in
  `docs/validation.md` with the results of 1.2–5.2, the fixture adaptations,
  the requalification note and the operator checks as pending. Verify that:
  - the parity table rows match claude-container's;
  - `git diff --check` is clean;
  - `openspec validate adopt-sandbox-ref-16 --strict` passes.
- [x] 5.4 Commit on `adopt-sandbox-ref-16` with the co-author trailer, merge
  it into `main` with `--no-ff`, and verify that `git log --oneline -3` shows
  the merge.

## Workflow follow-up

- The operator pushes Pi `main` and reruns `--container-setup` on the three
  hosts. They check `java -version` in a Pi session with the Temurin 21
  toolchain and run `--container-toolchain verify java21`. The results are
  added to `docs/validation.md`.
- Sync the delta spec and archive this change.

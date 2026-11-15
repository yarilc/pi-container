# Tasks

## 1. Adopt sandbox-ref-18

- [x] 1.1 From claude-container, run `python3 -I tools/propagate.py
  ../pi-container sandbox-ref-17 sandbox-ref-18` (dry run). Verify that it
  lists the seven modified shared files, nothing added, removed or "not
  adopted", and commit `958465b`.
- [x] 1.2 Stash the change directory, run `--apply`, and restore the stash on
  branch `adopt-sandbox-ref-18`. Verify that the stash list is empty, that
  `git diff --name-only` lists only the shared files,
  `tests/test_reference_copy.py` and the documents the tool names, and that
  `tests.test_reference_copy tests.test_alignment tests.test_agent_profile
  tests.test_toolchains tests.test_setup` pass in a disposable container with
  private executable temporary storage. Adapt and record any Pi fixture the
  new overlap or alignment rule rejects.

## 2. Agent variables

- [x] 2.1 Add `native.protected_env` to `agent/profile.json` with
  `PI_`, `ANTHROPIC_`, `OPENAI_`, `GEMINI_`, `OPENROUTER_`, `GOOGLE_API_KEY`. Verify that `tests.test_agent_profile` passes.
- [x] 2.2 Add a `tests/test_wrapper.py` case in which a default toolchain sets
  two of these variables and `JAVA_HOME`: the session receives only
  `JAVA_HOME`, and `launch-env` warns once per dropped variable. Verify that
  it fails without the profile values and passes with them.
- [x] 2.3 Extend the README "Protected variables" bullet with the agent
  variables and `native.protected_env`. Verify with `grep -n protected_env
  README.md`.

## 3. Container lifecycle

- [x] 3.1 Check the session label before treating an existing name as a
  collision (`pi-container.sh:1120`). Add a `tests/test_wrapper.py` case where the
  fake engine fails the create without an ID and reports this session's label
  for the name: the wrapper returns the create status, does not retry, and
  removes that container. Keep the existing other-session collision test
  passing. Verify that the new case fails before the change.
- [x] 3.2 Add label recovery to `cleanup()`, within the shutdown deadline, as
  in design.md. Add `tests/test_wrapper.py` cases: an interrupted creation
  whose client publishes no ID while the engine reports one container for the
  session label (it is removed and the interruption status is returned), no
  container (nothing removed), and a failed lookup ("unresolved" reported).
  Verify that the first case fails before the change.

## 4. Validation and publication

- [x] 4.1 Run the full unit discovery in a disposable container with private
  executable temporary storage, then `bash tests/run-runtime.sh` with
  `--shared`, `--setup`, `--setup-runtime`, `--qualification` (shared
  `setup/` modules are qualified code, although the tool's checklist omits
  it), `--wrapper` and the default mode, using the current Pi setup image
  tagged `:latest` only for the runs. Verify that each passes; record a known
  timing-sensitive test that passes on a rerun as such.
- [x] 4.2 Fill in the tool's validation-record template in
  `docs/validation.md` with the results, the review findings covered and the
  requalification note, operator setups pending. Verify that the parity table
  rows match claude-container's, `git diff --check` is clean and
  `openspec validate adopt-sandbox-ref-18 --strict` passes.
- [x] 4.3 Commit on `adopt-sandbox-ref-18` with the tool's message, extended
  with the Pi changes, and the co-author trailer. Merge into `main` with
  `--no-ff`, and verify that `git log --oneline -3` shows the merge.

## Workflow follow-up

- The operator pushes Pi `main` and reruns `--container-setup` on the three
  hosts. The results are added to `docs/validation.md`.
- Sync the delta specs and archive this change.

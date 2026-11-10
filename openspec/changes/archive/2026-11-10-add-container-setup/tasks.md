# Tasks

## 1. Shared runtime-build fix and reference `sandbox-ref-7`

- [x] 1.1 In `claude-container`, on a dedicated branch:
  - `network/agent_profile.py` accepts optional `install.runtime_build` (`recipe` or `wrapper`);
  - `setup/setup.py` builds the runtime image through `bash <release>/<wrapper> --container-build` with maintenance, `unrestricted` and the candidate image tag when it is `wrapper`, then inspects the identity;
  - `tests/test_agent_profile.py` adds the invalid values;
  - `tests/test_setup.py` adds the wrapper-build case with a scratch profile and a fake wrapper.

  Verify `test_agent_profile`, `test_alignment`, `--setup`, `--shared` and `--qualification` in Claude: unchanged results for the default. Record in Claude `docs/validation.md`, merge, and create the tag `sandbox-ref-7`.
- [x] 1.2 In `codex-container` and `opencode-container`, each on its own branch, copy the changed shared files from `sandbox-ref-7`. Update the `tests/test_reference_copy.py` manifest, tag and commit, and the current-state references. Verify `--shared`, `--setup` and `--qualification`. Record, commit and merge.
- [x] 1.3 In this repository, create branch `add-container-setup` from `main`. Unpack `network/`, `setup/` and the shared tests (now including `tests/test_setup.py` and `tests/test_alignment.py`) from `sandbox-ref-7`. Verify with `diff -r` against the tag: no differences.
- [x] 1.4 Extend the `tests/test_reference_copy.py` manifest to the new files and move it to `sandbox-ref-7`, using the agent-neutral OpenCode file (its identifier scan stays, next to `test_alignment.py`). Verify that it passes, and that it fails on an injected byte change in `setup/common.py`.

## 2. Pi wrapper: build-only refresh and YOLO

- [x] 2.1 `--container-build` used alone builds the image and exits 0, after mode, budget and engine checks and the maintenance gate. It uses the existing build arguments and staleness label and creates no state or container. Combined use keeps refresh-then-launch. Add `"runtime_build": "wrapper"` to `agent/profile.json`. Verify with `test_wrapper.py` cases:
  - build-only with and without maintenance;
  - restricted and unrestricted modes;
  - the label value;
  - no `create` call.
- [x] 2.2 Parse `PI_CONTAINER_YOLO` as a boolean (`0`, `1`, `true`, `false`, `yes`, `no`, empty) before engine queries. An enabled value prints the "no effect yet" warning, and a disabled value is silent. Invalid values exit 1 naming the accepted values. Update help and README. Verify with `test_wrapper.py`:
  - unchanged engine arguments for `1` and `0`;
  - no warning for `0`;
  - failure for `2`.

## 3. Wrapper setup entry points

- [x] 3.1 Add `--container-setup` to `pi-container.sh`. It must be used alone, needs an interactive terminal and host Python 3, and runs `exec python3 -I setup/setup.py`. Help keeps precedence. Replace the missing-mode message with the `setup required:` form that names the absolute wrapper path. Verify with new `test_wrapper.py` cases and the help text.
- [x] 3.2 Pass the attached client's stderr through `setup/diagnostics.py` over a FIFO in the private session directory, when the filter and host Python exist. Reap the filter after the client within a one-second drain, inside the `shutdown` budget. Verify with `test_wrapper.py` cases:
  - the restart line is reclassified and real errors pass through;
  - the existing signal, TTY, pipe and exit-status cases still pass.
- [x] 3.3 Add `--setup` (shared `test_setup.py`) and `test_alignment` to `tests/run-runtime.sh` and the shared list, and run both. They must pass without edits to shared files. Align any wrapper message the shared tests check literally. If a failure comes from shared code, stop and fix it in `claude-container` first.

## 4. Setup runtime acceptance

- [x] 4.1 Port `tests/test_setup_runtime.py` from OpenCode with Pi names (`PI_CONTAINER_IMAGE`, `localhost/pi-container:latest`, `pi-container`, `--version` printing `0.80.8`), and add the `--setup-runtime` runner mode. Verify with `bash tests/run-runtime.sh --setup-runtime`:
  - offline, provider and unrestricted installations;
  - one installation with no reusable runtime image, built through the wrapper and accepted by the staleness check;
  - the managed launcher from another workspace;
  - qualification and the smoke check;
  - no credentials and no systemd changes.
- [x] 4.2 Run the setup once on the WSL target through a pseudo-terminal, with a disposable `HOME`, in provider mode with the `gemini` method and no key set. Confirm:
  - the residual exfiltration acknowledgement naming the four profile hosts;
  - the maintenance review;
  - `Sandbox: ready`;
  - authentication pending naming `GEMINI_API_KEY`;
  - no YOLO warning on the managed smoke launch.

  Record the transcript summary in `docs/validation.md`.

## 5. Documentation and parity

- [x] 5.1 Add `docs/setup.md`, adapted from OpenCode: guided installation, maintenance consent, the wrapper-built runtime image, the managed launcher, rollback, API-key authentication, YOLO and Bun notes. Update:
  - the README: first-run section, setup-required migration, direct-launch section, verification modes, YOLO;
  - the wrapper help;
  - `AGENTS.md`: the shared-file list with `setup/`, `test_setup.py` and `test_alignment.py`, the setup command and `sandbox-ref-7`;
  - `CHANGELOG.md`, `CONTRIBUTING.md` and `docs/network-contract.md`: references to `sandbox-ref-7`.

  Verify with markdownlint on the changed files and `git diff --check`.
- [x] 5.2 Add the five-wrapper parity table with the Pi row to `docs/network-contract.md`. Replace the Pi row in `claude-container`, `codex-container` and `opencode-container`, documentation only. Verify that the four rows are identical and that the links resolve.
- [x] 5.3 Final verification:
  - `bash -n` and ShellCheck;
  - `bash tests/run-runtime.sh` with `--wrapper`, `--shared`, `--setup`, `--setup-runtime`, `--qualification`, `--network` and the default mode, plus `test.sh`;
  - `openspec validate add-container-setup --strict`;
  - `git diff --check`.

  Record the results in `docs/validation.md`, and update `todo.md` items C11 and C13.

## Workflow follow-up

- `/opsx:archive`, then commit and merge into `main` here. Commit the parity-row edits in the other three repositories. The user pushes, including the tag `sandbox-ref-7`.
- The operator-run authenticated checks remain pending for the four profiles.
- Next Wave 3 port: Antigravity (`add-network-egress`).

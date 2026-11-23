# Tasks

## 1. Adopt `sandbox-ref-28`

- [ ] 1.1 Commit this change directory on `main`. Then, from `sandbox-container`, run `python3 -I tools/propagate.py ../pi-container sandbox-ref-25 sandbox-ref-28` (dry run), then the same command with `--apply`. Verify:
  - the plan lists the files in design "Context";
  - the checklist includes `--guard`;
  - the tool switched to `adopt-sandbox-ref-28`.
- [ ] 1.2 Check the parity rows of `docs/network-contract.md` (design decision 5). Verify: every row other than Pi's equals the one in `sandbox-container`.
- [ ] 1.3 Copy `sandbox-container.ps1` to `pi-container.ps1` byte for byte, and copy `.gitattributes`. Commit both, then rewrite the working files with LF (design decision 2). Verify:
  - `git status` is clean after the renormalization, before the adoption's files are restored;
  - with host Python next to the `sandbox-container` checkout, and the sibling check not skipped, `python3 -m unittest tests.test_reference_copy tests.test_alignment` passes, including the entry, ASCII and line-ending tests.
- [ ] 1.4 Run the reference lint tools (design decision 3). Verify, from `sandbox-container`:
  - `bash tools/shellcheck.sh ../pi-container` reports no finding;
  - `bash tools/powershell.sh ../pi-container` passes the shim cases with no finding.

## 2. Pi's tests and documentation

- [ ] 2.1 Rebuild the runner's stale image with the maintenance build and host CA trust, and tag the guard toolchain as `development` (design decision 7). Verify: `localhost/pi-container:latest` carries the current `build-inputs-hash`, and reports Pi 1.5.2 and OpenSpec 2.0.0.
- [ ] 2.2 Adapt Pi's own tests (design decision 4):
  - copy the shared adapted `tests/test_setup_wrapper.py` byte for byte;
  - in `tests/test_runtime.py`, add `engine_budgets()`, make `test_effective_hardening_and_budgets` follow it, with the notices, and change `test_process_limit_enforced` to a budget of 128 with 200 children, skipped when no mechanism applies.

  Verify: `bash tests/run-runtime.sh --wrapper` passes, and the default `bash tests/run-runtime.sh` passes `test_effective_hardening_and_budgets` and `test_process_limit_enforced`.
- [ ] 2.3 Run the unit discovery in the disposable test container, then `bash tests/run-runtime.sh` in each of these modes, one at a time and not during the Windows validation:
  - `--shared`, `--setup` and `--setup-runtime`;
  - `--qualification`, `--guard` and `--network`;
  - no mode.

  Record the image and the guard toolchain used. Fix in Pi's own tests any failure that a shared behavior change causes. Verify: every mode passes, apart from failures already recorded for this runner. A failure in shared code pauses the change.
- [ ] 2.4 Adapt the documentation (design decision 6):
  - `README.md`:
    - the `## Windows with Podman machine` section, with the API key methods, `PI_NPM_CACHE_SIZE` through `PI_CONTAINER_ENV_VARS`, `PI_CONTAINER_GITCONFIG`, host CA trust on Windows and the install as a command;
    - the Windows limits, including Bitdefender;
    - the rejected-connection sentence, the Podman machine note in `### Host CA trust`, the guard as the confined init and the `PI_NPM_CACHE_SIZE` row;
    - the cgroup managers and the rlimit fallback in `### Session hardening, budgets and lifetime`;
    - the Windows sensitive folders;
  - `docs/setup.md`:
    - the Windows setup and the authentication steps from Windows;
    - setup without a launch service;
    - the carriage-return check;
    - candidate tags;
    - the service endpoint for restricted modes;
    - the budget plan;
  - `AGENTS.md`: `pi-container.ps1`, the Windows files, the ShellCheck and PowerShell checks, the Windows sensitive roots, and the cgroup manager and rlimit rule.

  Verify:
  - the README names `pi-container.ps1`, `$env:ANTHROPIC_API_KEY`, `PI_NPM_CACHE_SIZE` with `PI_CONTAINER_ENV_VARS` in the Windows section, and `podman machine set --import-native-ca`;
  - no `SANDBOX_CONTAINER_`, `CLAUDE_`, `CODEX_`, `ANTIGRAVITY_` or `OPENCODE_` name, and no statement specific to another wrapper, appears in the new text;
  - `git diff --check` passes.

## 3. Validation on Windows

- [ ] 3.1 Prepare the operator bundle: snapshots of `pi-container` and `sandbox-container`, and a README with the steps of design decision 8. Verify:
  - the README lists each step, the summary copies and the data to send back;
  - the checksums match.
- [ ] 3.2 Have the operator run design decision 8. Verify that `docs/validation.md` records:
  - the setup with the API key method and its Windows next step;
  - the Pi session with tool use and its exit status;
  - the npm cache size before and after `PI_CONTAINER_ENV_VARS`;
  - `windows-validate` on both editions, once with `-Install -StopMachine`.

  No case may fail. If one does, the change pauses for a decision between a documented limit in the README's Windows limits and a fix.

## 4. Record, merge and parity

- [ ] 4.1 Add the `sandbox-ref-28` adoption section to `docs/validation.md`, from the tool's template, with every result of tasks 2.1 to 2.3 and 3.2. Set Pi's parity row to "Adopted `sandbox-ref-28`". Commit with the tool's message and merge into `main`. Verify: `tests/test_reference_copy.py` passes on `main`.
- [ ] 4.2 Copy Pi's parity row into `sandbox-container`, `claude-container`, `codex-container`, `antigravity-container` and `opencode-container`, with one commit on `main` in each. Verify: all six rows are identical in the six repositories.

## Workflow follow-up

- The operator pushes `main` in every touched repository. They also push `adopt-sandbox-ref-28` in `pi-container`.
- The operator reruns `--container-setup` for Pi on the Linux hosts and on Windows.
- Archive this change with spec sync.

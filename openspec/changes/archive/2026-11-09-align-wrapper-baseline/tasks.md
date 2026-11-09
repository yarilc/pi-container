# Tasks

## 1. Names and YOLO (A01, A02)

- [x] 1.1 Add the alias resolution helper and apply it to the eight pairs (D1), then replace every use of the old names in the wrapper. Verify with wrapper tests: each old name alone works and warns once; each new name alone works without a warning; equal values warn once; conflicting values, including switch meanings, exit 1 naming both variables with no engine call.
- [x] 1.2 Add the `PI_CONTAINER_YOLO` warning (D4). Verify with a wrapper test that the warning appears and that the engine arguments equal those of a launch without it.

## 2. Session baseline (A11)

- [x] 2.1 Port budget and lifetime validation and normalization (D2), and use the normalized values in `podman_args`. Verify with wrapper tests: default and overridden flags; every rejected memory, CPU, process and lifetime form exits 1 naming the variable with no engine call or state creation.
- [x] 2.2 Add the post-create budget inspection, `started_at` and the lifetime notice (D2), and extend `tests/fake_podman.py`. Verify with wrapper tests: matching, different and missing limits and an inspection failure, each removing only the owned container without start; the notice after a slow non-zero client; no notice on an early exit.
- [x] 2.3 Replace the guard with the reference set and exact override (D3). Verify with wrapper tests:
  - each refused root, including `/tmp`;
  - `/mnt/d` refused while `/mnt/d/project` is accepted;
  - the worktree parent equal to the home;
  - a symlink to `/etc`;
  - exact `1`, non-exact values and the old alias.

  Each refusal must happen with no engine call or state creation.

## 3. Real-engine checks

- [x] 3.1 Move `tests/test_runtime.py` and `tests/run-runtime.sh` to the new names. Add effective hardening and cgroup budget checks (default and overridden, with and without delegation), process-limit enforcement, lifetime expiry and early exit, and a refused home workspace. Verify that `bash tests/run-runtime.sh` passes with no credentials or model requests, and record the observed lifetime status.

## 4. Documentation (A08)

- [x] 4.1 Restructure `--container-help` (D5). Verify that a help test finds every `PI_CONTAINER_*` variable with its default, the deprecated names, the no-approval statement and the refused set, with no engine call or state creation.
- [x] 4.2 Reorder the README into the common sections and add the hardening, permissions and migration content (D5). Update `SECURITY.md`, `CONTRIBUTING.md` and `CHANGELOG.md` for the new names and semantics. Verify:
  - a sentence-level comparison with the previous README shows only renames and moved text;
  - markdownlint reports 0 errors;
  - `git diff --check` passes.
- [x] 4.3 Add `AGENTS.md` (D5). Verify that its commands run as written and that markdownlint passes.

## 5. Evidence

- [x] 5.1 Run the full credential-free unit suite in the runner container, `bash -n`, ShellCheck, hadolint and `bash tests/run-runtime.sh`. Add a dated `docs/validation.md` section covering the Pi approval facts, the results, the initial failures and reruns, the lifetime status and the behavior changes. Verify that `openspec validate align-wrapper-baseline --strict` passes.
- [x] 5.2 Mark A01, A02, A08 and A11 in `todo.md` with an implementation note, leaving the base digest to `align-runtime-image`, and update the A10 note. Verify that the notes name the change and the evidence section.

## Workflow follow-up

- Archive, commit and merge when the user asks; the user pushes.
- Continue Wave 2 with Pi `align-runtime-image` (A03, A04, A05, A06).

# Tasks

## 1. Gitconfig opt-in (A07)

- [x] 1.1 Add the early validation for `PI_CONTAINER_GITCONFIG` and the deprecated `PI_MOUNT_GITCONFIG` (D1), and replace the default mount with the opt-in mount from the physical source. Verify with wrapper tests:
  - no mount by default;
  - the exact `1` mounts read-only at `$HOME/.gitconfig` from the physical target of a symlink;
  - `true`, `yes` and empty do not mount;
  - a missing file and a directory exit 1 with no engine call;
  - the alias alone (`1` mounts, `0` does not, each with one warning);
  - both conflict directions exit 1 naming both variables;
  - `PI_MOUNT_GITCONFIG=2` exits 1.
- [x] 1.2 Add the migration notice (D2). Verify with wrapper tests: one notice when the file exists and no variable is set; none with `PI_CONTAINER_GITCONFIG=0` or `1`, or when the file is absent; the session status is unchanged.
- [x] 1.3 Update wrapper help with the new variable, the opt-in and the deprecated alias. Verify that a help test finds them, with no engine call or state creation.

## 2. Scratch directories (A09)

- [x] 2.1 Confirm that the three `.wrapper-test-*` directories hold only the old fake engine and empty directories, then remove them. Add `.test-state/` to `.gitignore`, and add a wrapper test that checks that a run leaves no new `.wrapper-test-*` in the repository root and no `pi-wrapper-*` scratch directory after cleanup. Verify that `ls -a` shows no `.wrapper-test-*` and that the test passes.

## 3. Real-engine check

- [x] 3.1 Add a runtime case: `~/.gitconfig` is absent in a default session, and present, readable and not writable with `PI_CONTAINER_GITCONFIG=1`. Verify that `bash tests/run-runtime.sh` passes with no credentials or model requests.

## 4. Documentation and evidence

- [x] 4.1 Update README (mount table, environment table, intro note), SECURITY.md ("Host Git Config Exposure"), CHANGELOG.md (Unreleased: Changed and Deprecated) and the opt-in alternatives. Verify that no document still says `~/.gitconfig` is mounted by default and that `git diff --check` passes.
- [x] 4.2 Run the full credential-free wrapper suite in the runner container, `bash -n`, ShellCheck and `bash tests/run-runtime.sh`. Add a dated `docs/validation.md` section covering the results, the initial failures and reruns, and the behavior change. Verify that `openspec validate narrow-exposed-state --strict` passes.
- [x] 4.3 Mark A07 and A09 in `todo.md` with an implementation note naming the change and the evidence section. Verify that the note is present.

## Workflow follow-up

- Archive, commit and merge when the user asks; the user pushes.
- Continue Wave 2 with Pi `align-wrapper-baseline` (A01, A02, A08, A11).

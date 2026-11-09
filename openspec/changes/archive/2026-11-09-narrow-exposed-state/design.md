# Design

## Context

`pi-container.sh` validates its inputs before engine queries:

- `HOME` and its physical path (line ~103);
- the state directories (`validate_state`).

It then builds `podman_args`. The gitconfig mount is a single line:

`[[ ! -f "$HOME/.gitconfig" || "${PI_MOUNT_GITCONFIG:-1}" == 0 ]] || podman_args+=(--volume "$HOME/.gitconfig:$HOME/.gitconfig:ro")`

The source is the lexical path, and only `0` disables the mount. Tests in `tests/test_wrapper.py` use a fake engine (`tests/fake_podman.py`) with scratch space from `tempfile.TemporaryDirectory(prefix='pi-wrapper-')`. Runtime tests use `.test-state/pi-runtime-*` with `addCleanup(shutil.rmtree)`.

The three `.wrapper-test-*` directories date from 2026-07-02. They hold a fake `podman` and empty `home`/`project` directories created by the shell suite that commit `651c9bc` replaced. They are untracked and ignored.

## Goals / Non-Goals

**Goals:**

- No host Git configuration in a session unless the operator asks for it, with the exact-`1` opt-in used by the other wrappers.
- No silent breakage: the deprecated alias, a conflict check and a notice.
- A clean repository root, and suites that never leave scratch directories.

**Non-Goals:**

- Renaming the other `PI_*` variables (A02, `align-wrapper-baseline`).
- The dedicated container home (A04). The opted-in file stays at `$HOME/.gitconfig` until then, and A04 moves it below the new home.
- Mounting `~/.config/git/config` or other Git files.

## Decisions

### D1: Early validation

A block next to the existing `HOME` validation resolves the request:

1. **New name:** `PI_CONTAINER_GITCONFIG`, where exactly `1` means on and anything else means off.
2. **Old name:** `PI_MOUNT_GITCONFIG`, when set.
   - It must be `0` or `1`, otherwise the wrapper dies.
   - The wrapper prints `pi-container: PI_MOUNT_GITCONFIG is deprecated; use PI_CONTAINER_GITCONFIG=1 to mount ~/.gitconfig`.
3. **Conflict:** when both are set and their on/off meanings differ, the wrapper dies naming both.
4. **Mount:** when the result is on, `$HOME/.gitconfig` must be a regular file after symlink resolution, read with `readlink -f` and `-f`. The physical path must contain no colon, CR or LF, the same rule as other binds. Otherwise the wrapper dies.

The mount argument uses the physical source and the destination `$HOME/.gitconfig`, with `:ro`.

- Alternative: keep `PI_MOUNT_GITCONFIG` as the main name with a flipped default. Rejected, because the common scheme uses `PI_CONTAINER_*` (A02).

### D2: Notice

When neither variable is set and `$HOME/.gitconfig` exists, the wrapper prints:

`pi-container: ~/.gitconfig is no longer mounted by default; set PI_CONTAINER_GITCONFIG=1 to mount it read-only (PI_CONTAINER_GITCONFIG=0 silences this notice)`

### D3: Scratch cleanup

The wrapper removes the three directories with `rm -rf` after confirming that they contain only the fake engine and the empty directories. `.gitignore` gains `.test-state/`. A wrapper test runs the suite's normal and failing paths. It asserts that no new `.wrapper-test-*` exists in the repository root and that `pi-wrapper-*` scratch directories are removed after `TemporaryDirectory` cleanup. `.wrapper-test-*` stays in `.gitignore` as a guard.

### D4: Tests

**`tests/test_wrapper.py`:**

- no mount by default;
- the exact opt-in, through a physical symlinked source;
- non-exact values;
- a missing or directory gitconfig with the opt-in;
- the deprecated alias in both directions;
- the conflicts;
- an invalid alias value;
- the notice and its silencing;
- help.

The existing `test_retained_editors_gitconfig_and_secrets` uses the opt-in.

**`tests/test_runtime.py`:** a real session confirms that `~/.gitconfig` is absent by default, and readable but not writable with the opt-in.

The unit suite runs in the host runner container, because the agent sandbox has a `noexec` `/tmp`.

## Risks / Trade-offs

- **Users lose their Git identity inside the container.** The notice, README and CHANGELOG give the opt-in and alternatives: repository-local identity, or `GIT_AUTHOR_NAME`/`GIT_AUTHOR_EMAIL` via `PI_ENV_VARS`.
- **Opting in still exposes credential helpers and tokens.** SECURITY.md keeps the warning and recommends a minimal gitconfig.

## Migration Plan

1. Implement on branch `narrow-exposed-state`. Unit tests run in the runner container; real-engine checks run with `bash tests/run-runtime.sh`.
2. Users who want the file set `PI_CONTAINER_GITCONFIG=1`, and existing `PI_MOUNT_GITCONFIG=0` settings keep working with a warning.
3. Rollback: revert the merge.

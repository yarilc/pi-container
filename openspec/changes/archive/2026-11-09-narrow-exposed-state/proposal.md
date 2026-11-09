# Proposal: Narrow the host state exposed to Pi sessions

## Why

`pi-container.sh` mounts the caller's `~/.gitconfig` read-only into every session whenever the file exists. Users must opt out with `PI_MOUNT_GITCONFIG=0`. Git configuration commonly holds:

- credential helpers;
- URL-embedded tokens;
- `include` paths that point at other host files;
- signing-key references.

No other wrapper exposes it. Three stale `.wrapper-test-*` scratch directories from an earlier shell test suite also remain in the repository root. This change closes todo A07 and A09, the first Pi change of Wave 2.

## What Changes

- **BREAKING:** `~/.gitconfig` is no longer mounted by default. It is mounted read-only at the same path only with exact `PI_CONTAINER_GITCONFIG=1`.
  - Any other value leaves it unmounted.
  - An opt-in without a regular `~/.gitconfig` file stops with status 1 before any engine query.
  - The mount source is the physical file, so a symlinked `~/.gitconfig` is resolved.
- **Deprecated variable:** `PI_MOUNT_GITCONFIG` is kept as a deprecated alias with a warning.
  - `PI_MOUNT_GITCONFIG=1` alone still mounts the file.
  - `PI_MOUNT_GITCONFIG=0` alone keeps it unmounted, which is now the default.
  - Setting both variables to conflicting values, an enabled one and a disabled one, stops with status 1. This follows the A02 rule for deprecated aliases.
  - Any other `PI_MOUNT_GITCONFIG` value is an error.
- **Migration notice:** when neither variable is set and `~/.gitconfig` exists, the wrapper prints one stderr notice saying that it is no longer mounted and how to opt in. `PI_CONTAINER_GITCONFIG=0` silences it.
- **Scratch directories (A09):** the `.wrapper-test-*` directories are removed. The current suites already create their scratch space with automatic cleanup:
  - the wrapper tests in a system temporary directory;
  - the runtime tests under `.test-state`.

  `.test-state/` is added to `.gitignore`, and a wrapper test checks that a run leaves no `.wrapper-test-*` or `pi-wrapper-*` directory behind.
- Help, README, SECURITY.md, CHANGELOG.md, `docs/validation.md` and `todo.md` document the opt-in and the migration.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `container-isolation`: host Git configuration becomes an exact opt-in, with the deprecated alias and the migration notice.
- `container-launcher`: the retained-controls requirement names the opt-in Git configuration instead of the optional default mount.

## Impact

- **Wrapper:** `pi-container.sh` gets early validation of the two variables, the opt-in mount, the notice and the help text.
- **Tests:** `tests/test_wrapper.py` and `tests/test_runtime.py`.
- **Documentation:** `README.md`, `SECURITY.md`, `CHANGELOG.md`, `docs/validation.md`, `todo.md`, `.gitignore`.
- **Users:** Git identity inside the container disappears unless they set `PI_CONTAINER_GITCONFIG=1`. Alternatively they can configure the identity in the repository, or pass `GIT_AUTHOR_*`/`GIT_COMMITTER_*` through `PI_ENV_VARS`.

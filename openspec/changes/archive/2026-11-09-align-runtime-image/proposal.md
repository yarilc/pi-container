# Proposal: Align the Pi runtime image and container home

## Why

The other wrappers share one runtime model:

- a generic image on `node:22-bookworm-slim` pinned by digest;
- the common Debian toolset and OpenSpec, with every input pinned;
- a dedicated container home, plus an option for state kept apart from the host's everyday configuration;
- builds only on explicit `--container-build` or when the image is missing.

Pi differs:

- its base image floats;
- it installs only Bash, CA certificates, Git, nano and ripgrep;
- the Podman client is a build variant selected by `INSTALL_PODMAN`;
- Bun comes from the unverified remote script `curl https://bun.sh/install | bash`, at a version chosen at runtime by `PI_BUN_VERSION`;
- `HOME` is the host home path;
- the wrapper rebuilds silently whenever its `build-inputs-hash` label is stale, and `PI_PULL_ALWAYS` can pull a new base.

This change closes todo A03, A04, A05 and A06, the base-digest part of A11, and the remaining A10 note. It is the last change of Wave 2.

## What Changes

- **Image (A03, A11):** `Containerfile` uses the `sandbox-ref-2` digest of `docker.io/library/node:22-bookworm-slim`. It installs the common toolset and the Podman client unconditionally, then the npm packages at exact versions:
  - Pi from `.version` (`@earendil-works/pi-coding-agent@0.80.8`);
  - `@fission-ai/openspec@1.16.0`.

  The toolset is `bash`, `bubblewrap`, `bzip2`, `ca-certificates`, `coreutils`, `curl`, `diffutils`, `file`, `findutils`, `gawk`, `git`, `grep`, `jq`, `less`, `nano`, `patch`, `podman`, `procps`, `python3`, `ripgrep`, `sed`, `tar`, `unzip`, `util-linux`, `xz-utils` and `zip`. The build fails unless `pi --version` and `openspec --version` report the recorded versions. `INSTALL_PODMAN` is removed; socket delegation stays the exact `PI_CONTAINER_PODMAN=1` opt-in.
- **BREAKING, Bun (A03):** Bun stays optional with `PI_ENABLE_BUN`. It is installed with npm as exactly `bun@1.3.14`, a version recorded in `Containerfile`, so the npm registry verifies its integrity and its platform packages are pinned. `PI_BUN_VERSION` is ignored with a warning.
- **BREAKING, build policy (A06):** the wrapper builds automatically only when the image is missing (exit status 1). When the `build-inputs-hash` label differs from the current inputs, for example after a `Containerfile`, `.version` or `PI_ENABLE_BUN` change, it stops with status 1 and a message naming `--container-build` instead of rebuilding. `PI_PULL_ALWAYS` is ignored with a warning, because the base is pinned. The build context and the hash cover only `Containerfile`, `.containerignore`, `.version` and the Bun selection.
- **BREAKING, dedicated home (A04):** sessions use `HOME=/pi-home`, an ephemeral noexec tmpfs. Mounted beneath it:
  - `~/.pi` at `/pi-home/.pi`;
  - `~/.agents` at `/pi-home/.agents`;
  - the npm cache tmpfs at `/pi-home/.npm`;
  - the opted-in `~/.gitconfig` at `/pi-home/.gitconfig`.

  The workspace keeps its host absolute path. Pi, extensions and Git keep working, and the host state is unchanged.
- **Isolated state (A05):** new `PI_CONTAINER_STATE_DIR` names a private host directory containing `.pi` and `.agents`, used instead of `~/.pi` and `~/.agents`.
  - In writable mode the directory becomes the persistent `/pi-home`.
  - With `PI_READONLY_CONFIG`, its `.pi` and `.agents` are mounted read-only below an ephemeral home.
  - It is created privately when missing and validated like the shared state, with no credential import. It must not overlap the workspace.
  - The shared `~/.pi`/`~/.agents` remain the default.
- **Tests:** a new `tests/test_image_pins.py`. The wrapper and runtime suites cover the image, home, state, build policy and Bun. `test.sh` builds the new image.
- **Documentation:** help, README, `AGENTS.md`, SECURITY.md, CHANGELOG.md, `docs/validation.md` and `todo.md` cover the pinned inputs, the update procedure, the home and state options and the migration.

## Capabilities

### New Capabilities

- `runtime-image`: the pinned image, its toolset, optional pinned Bun, the build context and the update procedure.

### Modified Capabilities

- `container-launcher`:
  - image freshness no longer triggers silent rebuilds;
  - the optional-tooling requirement follows the pinned Bun and the unconditional Podman client;
  - the version-override and pull variables are ignored with warnings.
- `container-isolation`:
  - the dedicated home and destinations;
  - the isolated state option;
  - the read-only mode under the new home;
  - the npm cache location;
  - the gitconfig destination.

## Impact

- **Files:**
  - `Containerfile` is rewritten, and `.containerignore` allows only the three inputs;
  - `pi-container.sh`: build policy, home and state layout, warnings and help.
- **Tests:**
  - `tests/test_wrapper.py`, `tests/fake_podman.py`, `tests/test_runtime.py`, `tests/run-runtime.sh`, `test.sh`;
  - new `tests/test_image_pins.py`.
- **Documentation:** `README.md`, `AGENTS.md`, `SECURITY.md`, `CHANGELOG.md`, `docs/validation.md`, `todo.md`.
- **Users:**
  - one explicit `--container-build` after upgrading, since the hash changes. A missing image still builds automatically;
  - toggling `PI_ENABLE_BUN` now requires `--container-build`;
  - files written to other home paths become ephemeral;
  - `PI_BUN_VERSION` and `PI_PULL_ALWAYS` are ignored with warnings.

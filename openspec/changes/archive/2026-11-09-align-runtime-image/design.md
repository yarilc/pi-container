# Design

## Context

After `align-wrapper-baseline`, the image and home work as follows.

**`Containerfile`:**

- builds on the floating `docker.io/library/node:22-bookworm-slim`;
- installs Bash, CA certificates, Git, nano and ripgrep;
- adds `podman` only when `INSTALL_PODMAN=1`;
- adds Bun only when `INSTALL_BUN=1`, through `curl https://bun.sh/install | bash -s "$BUN_VERSION"`;
- installs `@earendil-works/pi-coding-agent@${PI_VERSION}` from npm, with `PI_VERSION` read from `.version`;
- uses `ENTRYPOINT ["pi"]`.

**Build in `pi-container.sh`:** the wrapper hashes `Containerfile`, `.containerignore`, `.version`, `INSTALL_PODMAN`, `INSTALL_BUN` and `BUN_VERSION`. It rebuilds whenever the image is missing (status 1) or its `build-inputs-hash` label differs, and adds `--pull=always` with `PI_PULL_ALWAYS`.

**Home and state:** sessions use `--env HOME=$HOME`, with these mounts:

- the validated `~/.pi` and `~/.agents` at the same host paths;
- an npm cache tmpfs at `$HOME/.npm`;
- the opted-in gitconfig at `$HOME/.gitconfig`.

`.containerignore` allows `Containerfile`, `.containerignore`, `.gitignore` and `.version`. `test.sh` builds an image with the hash computed independently.

Measured on 2026-11-09 with the pinned base:

- `npm view` reports registry SHA-512 integrity for `@earendil-works/pi-coding-agent@0.80.8` and `bun@1.3.14`;
- `bun@1.3.14` has exact-version optional platform packages (`@oven/bun-linux-x64` and others) and a postinstall step that selects among them.

## Goals / Non-Goals

**Goals:**

- Same image model, pins, toolset, home layout and build policy as the other wrappers, with Pi's existing names (`pi-container` image, `.version`).
- Existing users keep `~/.pi` and `~/.agents` unchanged.

**Non-Goals:**

- Renaming the image or the `PI_ENABLE_BUN`, `PI_NPM_CACHE_SIZE` and `PI_READONLY_CONFIG` variables.
- The maintenance gate and network work of Wave 3 (C01–C03).
- Running runtime tests inside the Pi image instead of the runner.

## Decisions

### D1: Recipe

The recipe follows the Codex structure:

1. digest `FROM` and `SHELL` with pipefail, kept for hadolint DL4006;
2. `ARG PI_VERSION` (required), `ARG OPENSPEC_VERSION=1.16.0`, `ARG INSTALL_BUN=0` and `ARG BUN_VERSION=1.3.14`;
3. one `apt-get install --no-install-recommends` of the common toolset, including `podman`;
4. `npm install --global --omit=dev` of `@earendil-works/pi-coding-agent@${PI_VERSION}` and `@fission-ai/openspec@${OPENSPEC_VERSION}`, plus `bun@${BUN_VERSION}` when `INSTALL_BUN=1`;
5. version checks for `pi`, `openspec` and, conditionally, `bun`;
6. cleanup of the apt lists, `/root/.npm` and `/root/.cache`;
7. `mkdir -m 1777 /pi-home` after removing anything the version checks created;
8. `ENV HOME=/pi-home`;
9. the existing OCI labels;
10. `ENTRYPOINT ["pi"]`.

`INSTALL_PODMAN` is dropped.

Alternative: keep the Bun installer script with a recorded checksum of the downloaded archive. Rejected, because npm already verifies integrity, which keeps one channel for all tools.

### D2: Build policy

Inputs and hash:

- The hash covers `Containerfile`, `.containerignore`, `.version` and `INSTALL_BUN=<0|1>`. `.containerignore` allows only those three files.
- The build passes `PI_VERSION` and `INSTALL_BUN`. `BUN_VERSION` comes from the recipe.

Image check:

- **Missing image (status 1):** the wrapper builds.
- **Label mismatch:** the wrapper dies with `Image <name> is stale for the current inputs (Containerfile, .version or PI_ENABLE_BUN); rebuild explicitly with --container-build`.
- **Explicit `--container-build`:** the wrapper always builds.

Ignored variables: `PI_BUN_VERSION` and `PI_PULL_ALWAYS` each print `pi-container: <NAME> is ignored; image inputs are pinned in Containerfile`.

`test.sh` keeps its independent hash computation, updated to the new inputs, so it still detects a wrapper/test disagreement.

### D3: Home layout

`podman_args` changes:

- `--env HOME=/pi-home`;
- `--tmpfs /pi-home:rw,noexec,nosuid,nodev,mode=1777,size=64M`;
- the npm tmpfs at `/pi-home/.npm`;
- the state binds at `/pi-home/.pi` and `/pi-home/.agents`;
- the gitconfig bind at `/pi-home/.gitconfig`.

The workspace bind and workdir are unchanged. Delegated Podman storage tmpfs mounts are unchanged.

### D4: Isolated state

`PI_CONTAINER_STATE_DIR` is resolved in the early validation block. It must be absolute, contain no colon, CR or LF, and not overlap the physical workspace mount. Its physical path is compared through the parent when the directory is missing.

| Mode | Behavior |
| --- | --- |
| Writable | Create the directory privately if missing, validate it with the same owner/mode checks as `validate_state`, create and validate `.pi` and `.agents` inside it, then bind the directory at `/pi-home` rw instead of the tmpfs home. The npm tmpfs and gitconfig still mount below it. |
| Read-only (`PI_READONLY_CONFIG`) | `validate_state` runs on `<dir>/.pi` and `<dir>/.agents` in read-only mode, under the tmpfs home. Nothing is created. |

Host `~/.pi` and `~/.agents` are not touched in either mode.

### D5: Tests

**`tests/fake_podman.py`:** the hash calculation follows the new inputs.

**`tests/test_wrapper.py`:**

- stale image stops without build;
- a missing image builds;
- `--container-build` builds with no `INSTALL_PODMAN` and no `BUN_VERSION` argument;
- `PI_ENABLE_BUN` changes the hash;
- ignored variables warn;
- the home layout and destinations, and the gitconfig destination;
- isolated state in writable and read-only modes, with invalid and overlapping values;
- help.

**`tests/test_image_pins.py`:** adapted from the OpenCode one. It requires:

- the digest;
- exact npm versions, with `${PI_VERSION}` accepted because `.version` must be an exact version;
- the toolset;
- no remote-script pipe.

**`tests/test_runtime.py` and `test.sh`:**

- the build-context probe expects three files;
- a home-layout test;
- isolated persistence;
- the tool inventory;
- OpenSpec;
- the delegated Podman client;
- Bun at the pinned version in the `test.sh` Bun build.

## Risks / Trade-offs

- **Users of the stale-rebuild convenience must now run `--container-build`.** The message names the command, and the README migration covers it.
- **Programs that write elsewhere in `HOME` lose that data at session end.** This is documented. Isolated mode makes the whole home persistent.
- **The npm postinstall for Bun selects the AVX2 or baseline binary on the build host.** The image is built locally per host, as for OpenCode.
- **The image is larger with the full toolset.** This is accepted for consistency with the other wrappers.

## Migration Plan

1. Implement on branch `align-runtime-image`. Unit suites run in the runner container. Real checks run with `./pi-container.sh --container-build --version`, then `bash tests/run-runtime.sh` and `./test.sh`.
2. Users run `--container-build` once. State stays where it is, and `PI_CONTAINER_STATE_DIR` is optional.
3. Rollback: revert the merge and rebuild.

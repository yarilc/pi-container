# Design

## Context

Pi `main` (`37d3bad`, one commit ahead of `origin/main`) pins
`sandbox-ref-12`. The dry run of `tools/propagate.py ../pi-container
sandbox-ref-12 sandbox-ref-16` (commit `1fa091e`) reports:

- six modified files and two added files, nothing removed or "not adopted";
- five documents (`README.md`, `AGENTS.md`, `CONTRIBUTING.md`,
  `docs/setup.md`, `docs/network-contract.md` with eight references).

The reference launcher change is claude-container commit `e45957f`, ported
by Codex (`adopt-sandbox-ref-14`) and OpenCode (`adopt-sandbox-ref-16`). Pi
differs:

- **State:** an isolated `PI_CONTAINER_STATE_DIR`, mounted as `/pi-home`, or
  `~/.pi` (or `PI_CONTAINER_CONFIG_DIR`) and `~/.agents`, mounted below a tmpfs
  `/pi-home`. `PI_READONLY_CONFIG` selects `state_mode=ro`, which mounts the
  shared state read-only. The validated paths are `isolated_home`,
  `pi_state` and `agents_state` (`pi-container.sh` around line 610).
- **Order:**
  - the runtime image identity (`session_image`) is resolved before
    `podman_args` is built (around line 692);
  - the home and state mounts follow;
  - then the launcher's own `--env` values: `PI_CONTAINER_CONFIG_DIR`, CA
    variables, forwarded names, and in restricted sessions
    `PI_OFFLINE=1 PI_SKIP_VERSION_CHECK=1 PI_TELEMETRY=0`.
- **Helpers:** `capture_engine_info <podman args>` sets `engine_response`.
- **Protected names:** the shared module protects `PI_CONTAINER_*` and the
  profile variables. `PI_OFFLINE`, `PI_SKIP_VERSION_CHECK` and `PI_TELEMETRY`
  are outside that set.
- **Temporary storage:**
  - `/tmp`, `/var/tmp`, `/run`, the `/pi-home` tmpfs and `/pi-home/.npm` are
    all `noexec`;
  - only the workspace (and a writable isolated home) can hold executables;
  - in the reference's examples, Go needs `GOTMPDIR` under the workspace, and
    Maven's jansi prints its warning.
- **Image:**
  - `runtime_build: wrapper`, so the launcher builds and labels the image
    itself;
  - the default image is `localhost/pi-container` (`PI_CONTAINER_IMAGE`);
  - the `Containerfile` has one digest-pinned `FROM`, the same base as the
    reference.
- **Agent instructions:** Pi reads `AGENTS.md` in the project and
  `~/.pi/agent/AGENTS.md`.
- **Tests:**
  - `tests/test_wrapper.py` creates its base with `TemporaryDirectory` and no
    directory argument, and has restricted fixtures that copy an installation
    (around lines 1260 and 1338);
  - `tests/run-runtime.sh` runs the suites in a separate runner image, with a
    world-writable tmpfs `/tmp`;
  - `tests/test_runtime.py` reads `PI_CONTAINER_IMAGE`;
  - `test.sh` and `test-wrapper.sh` are Pi's own acceptance scripts.

## Goals / Non-Goals

**Goals:**

- Pi adopts `sandbox-ref-16` byte for byte, and its parity table matches the
  reference.
- Pi sessions mount the library and get the default environment as reference
  sessions do. Pi's own restricted settings cannot be overridden by a
  toolchain.
- Every runner mode the tool lists passes, `--wrapper` included, and so do
  `./test-wrapper.sh` and `./test.sh`.

**Non-Goals:**

- Any shared-file change.
- An executable temporary directory for Pi. Tools that execute from their
  temporary directory use the workspace, as the README notes.
- The example recipes.

## Decisions

1. **Documented procedure on one branch:**

   - dry run, stash the change directory, `--apply` on
     `adopt-sandbox-ref-16`, restore the stash;
   - commit the wrapper port on the same branch and merge once with
     `--no-ff`.
2. **Port the reference launcher block, renaming only.** Placement:

   - the dispatch next to `--container-setup`;
   - the library check after state validation and before the network inputs,
     so an unsafe library stops before any image or container operation;
   - the `--avoid` list is the workspace plus `isolated_home`, or `pi_state`
     and `agents_state`, in both state modes;
   - the mount and the toolchain environment appended to `podman_args` right
     after the home and state mounts, before any of the launcher's `--env`
     values (decision 3);
   - the image `PATH` read from `session_image` with `capture_engine_info`.

   `PI_CONTAINER_TOOLCHAINS` is parsed like the launcher's other boolean
   settings.
3. **Wrapper variables last.**

   - Podman keeps the last `--env` for a name, so the toolchain environment
     is placed before every value the launcher sets, and the launcher's
     values win.
   - The reference and the other ports append the toolchain environment last.
     There, no launcher-set variable is outside the protected set.
   - Alternative: extend the shared protected set with agent-specific names.
     Rejected for now: the profile has no field for it, and a shared change
     needs a new tag. The ordering gives the same guarantee locally.
4. **Tests mirror the other ports.**

   - `tests/test_wrapper.py`:
     - dispatch;
     - private creation;
     - unsafe library: mode, workspace, installation, `~/.pi`, `~/.agents`
       and the isolated state;
     - disable;
     - appended environment and the stale-base warning;
     - `PI_TELEMETRY` from a toolchain losing to the restricted value;
     - restricted `--mount-target`;
     - the home-workspace overlap.
   - Its restricted fixtures install `setup/common.py`, `setup/toolchains.py`
     and `Containerfile`.
   - `tests/test_runtime.py`: archive and image sources, failing check,
     read-only mount, `node` and `python3` not shadowed, disabled mount.
   - `tests/test_network_runtime.py`: the live add during an offline
     session, with `setup/` in its installation.
   - Existing fixtures that fail because of the mount are adapted and
     recorded.
5. **Runner storage.** `tests/run-runtime.sh` mounts a private executable
   tmpfs at `/sandbox-test-tmp` (`0700`, `U=true`, 1 GiB) as
   `SANDBOX_TEST_TMPDIR`. `tests/test_wrapper.py` creates its base there when
   the variable is set.
6. **Documentation:** the README section states the reference rules for Pi:

   - the `AGENTS.md` line for the project or `~/.pi/agent/AGENTS.md`;
   - every tmpfs is `noexec`, so a tool that runs files from its temporary
     directory uses one under the workspace (for example `GOTMPDIR`);
   - in read-only state mode, caches go to `/tmp`;
   - the protected variables and decision 3.

## Risks / Trade-offs

- [Pi's restricted fixtures copy a fixed file set] → They gain `setup/` and
  `Containerfile`. The suites catch any missing file.
- [Unsafe-workspace launches from the home now stop] → As in the other
  wrappers; documented.
- [`./test.sh` builds a disposable image and runs the real wrapper] → It uses
  the default library under the test's `HOME`. If it fails on the mount, the
  failure is fixed on the same branch and recorded.
- [Qualification reports become stale] → The operator reruns
  `--container-setup`. `PI_ENABLE_BUN` stays unset.

## Migration Plan

1. Merge `adopt-sandbox-ref-16` with `--no-ff`. The operator pushes it.
2. Rerun `--container-setup` on this host, the Rocky Linux 9 lab host and the
   newer WSL host. With the Temurin 21 toolchain in the library, check
   `java -version` in a Pi session and run
   `pi-container --container-toolchain verify java21`.
3. Record the results, then archive with the spec sync.
4. Rollback before the push: reset `main` to `37d3bad`.

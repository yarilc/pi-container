# Design

## Context

Pi `main` (`bc6a309`) pins `sandbox-ref-10`. Running `tools/propagate.py`
from `sandbox-ref-10` to `sandbox-ref-12` (commit `fd196c9`) reports the same
21 modified shared files as Codex and OpenCode saw for `sandbox-ref-11`,
nothing added, removed or "not adopted".

A first apply targeted `sandbox-ref-11`. There
`test_runtime_build_receives_host_ca_only_when_trusted` failed, because it
assumed `runtime_build: recipe`. That is a shared defect, so the adoption
branch was discarded, and claude-container published the fix as
`sandbox-ref-12`. That tag also passes `--workdir /` to every qualification
container. It also reports five documents, including `CONTRIBUTING.md`, and
the runner modes `--shared`, `--setup`, `--setup-runtime`, `--qualification`,
`--guard` and `--network`.

The Codex and OpenCode adoptions (both archived on 2026-11-12) established
the pattern. Pi differs from both in these points:

- **Wrapper-built runtime.** `build_runtime_image()` (around line 469) runs
  before the build-only exit (around line 480). The CA selection (around
  line 549) runs later, after state validation, so `--container-build`
  alone never sees a bundle. A launch that builds (around line 627) does
  have it.
- **The CA selection mixes two concerns.**
  - Bundle choice and path checks: explicit or default bundle, no colon,
    CR or LF. These depend only on the environment.
  - Isolated-home mount preparation, which depends on validated state.
- **Staleness label.** `build_hash` covers `Containerfile`,
  `.containerignore`, `.version`, the relay files and `INSTALL_BUN`. A build
  secret is not a build input, because nothing from it is stored, so it
  must not enter the hash.
- **Launcher idioms:**
  - `capture_engine_info` with a 10-second timeout;
  - the socket check `true\n*`, then an absolute path beyond `/`;
  - one inspection of the exact `memory cpu pids` triple (around line 1011).
- **Mounts:**
  - `noexec` `/tmp` and `/var/tmp` (256 MiB) and `/run` (32 MiB);
  - a 64 MiB home tmpfs or an isolated home;
  - a 256 MiB npm cache tmpfs;
  - with delegation, `/var/lib/containers` and `/run/containers` tmpfs.
- **Recipe:**
  - the first `RUN` checks `PI_VERSION`, then runs `apt-get update`,
    `install` and `clean`;
  - a separate `RUN` installs npm packages, with optional Bun;
  - no `WORKDIR`;
  - `SHELL` is bash with pipefail.
- **Tests:**
  - `tests/fake_podman.py` holds the fake engine, and its inspection returns
    a fixed `FAKE_AGENT_BUDGETS` default;
  - the wrapper fixture (around line 1174 of `tests/test_wrapper.py`) lacks
    `network/agent_budgets.py`;
  - the toolset check in `tests/test_image_pins.py` matches the literal
    `apt-get install`, as OpenCode's did;
  - `test.sh` and `test-wrapper.sh` are the root entry points;
  - `tests/run-runtime.sh` and `test_runtime.py` honor `PI_CONTAINER_IMAGE`.

## Goals / Non-Goals

**Goals:**
- Pi adopts `sandbox-ref-12` byte for byte, with launcher and recipe
  behavior equivalent to the reference, Codex and OpenCode.
- The build-only refresh, which setup uses, verifies HTTPS package fetches
  with the host CA when trust is enabled.

**Non-Goals:**
- Bun in restricted modes. Qualification still drops `PI_ENABLE_BUN`, and
  that remains an open decision.
- Changing the shared files or the guard rule.

## Decisions

1. **Single branch with stash.** As in Codex and OpenCode, `--apply`
   creates `adopt-sandbox-ref-12`. The change directory is stashed around
   it, and one `--no-ff` merge follows.

2. **Split the CA selection.** Move bundle choice and path validation into
   `select_ca_bundle()`, defined and called right after
   `PI_CONTAINER_TRUST_HOST_CA` is parsed, before any build or state
   operation. The isolated-home CA mount preparation stays where it is and
   uses the selected `ca_bundle`. Error messages are unchanged.

   Alternative: move the whole block before the build-only exit. Rejected,
   because the isolated-home part needs the validated state.

3. **Build secret.** `build_runtime_image()` appends
   `--secret id=build-ca,src=$ca_bundle` when a bundle is selected. The
   secret is not added to `build_hash`. `.containerignore` gains
   `!podman-build-secret*`.

4. **Socket URL, budgets and mounts** follow the reference block with
   Pi idioms:
   - strip `unix://` after the `true\n` check and before the path check;
   - query and validate controllers right after the build-only exit. A
     build-only refresh creates no container and needs no budgets. Every
     launch mode queries them before any state work;
   - `budget_args`, with `--pids-limit=-1` when `pids` is missing;
   - notices with the `pi-container:` prefix;
   - an inspection that accepts `0` or `-1` for unenforced pids, with a
     diagnostic naming the reported controllers;
   - the help text;
   - remove `--read-only-tmpfs=false` and add the `/run/secrets`, `/dev`
     (`nosuid,noexec`, 755, 64 MiB), `devpts` and read-only `/dev/shm`
     mounts.

5. **Recipe.** In the first `RUN`, keep the `PI_VERSION` check, then the
   reference prologue:
   - Node.js roots into `/tmp/apt-bootstrap-ca.pem`;
   - the optional `build-ca` append;
   - the `sed` to `https://`;
   - `Acquire::https::CAInfo` on `update` and `install`.

   Remove the bundle after `apt-get install`, before `apt-get clean`, in the
   same step. Node exists in the base image, so this works before
   `ca-certificates` is installed.

6. **Tests.**
   - `tests/fake_podman.py`:
     - answer `{{.Host.CgroupControllers}}` from `FAKE_CONTROLLERS`, by
       default `[cpu memory pids]`;
     - derive the agent inspection from the last agent `create` when
       `FAKE_AGENT_BUDGETS` is unset, with unrequested values as `0`.
   - `tests/test_wrapper.py`:
     - copy `agent_budgets.py` into the fixture;
     - add tests for controller subsets, unverifiable lists, unenforced or
       missing inspection, socket URLs, mounts in every mode, the proxy
       mask, and the build secret for build-only and launch builds with and
       without trust;
     - check that an invalid CA selection fails before a build-only image
       operation;
     - check that the staleness label does not depend on trust.
   - `tests/test_image_pins.py`:
     - gains the transport, toolchain and workdir checks;
     - the mutations are adapted to Pi's two-step recipe (no `WORKDIR`,
       npm in its own `RUN`);
     - the toolset regex accepts `apt-get -o … install`.

## Risks / Trade-offs

- [Moving the CA selection changes the order of validation errors] → Only
  bundle errors move earlier, and they already stop before any session.
  The wrapper tests pin the messages and the absence of image operations.
- [Tools that need POSIX shared memory break with a read-only `/dev/shm`] →
  Covered by `test_runtime.py` and `test.sh`, including Bun when selected.
  A break is recorded and needs a new change.
- [Unenforced budgets let a session exhaust host resources] → Notices,
  qualification binding and README text, as in the reference.
- [Every existing image becomes stale on the label] → This is expected. The
  launcher already prints the rebuild instruction, and setup rebuilds.
- [Rocky-specific failures cannot be reproduced here] → The operator runs
  the final Rocky check.

## Migration Plan

1. Merge `adopt-sandbox-ref-12` with `--no-ff` after validation. The
   operator pushes it, together with the two pending parity commits.
2. On each host: `--container-setup` with refresh approved.
3. Rollback: before the push, reset `main` to `bc6a309`. After the push,
   revert the merge.

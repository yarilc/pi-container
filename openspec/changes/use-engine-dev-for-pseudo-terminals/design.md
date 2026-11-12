# Design

## Context

`pi-container.sh` builds the container arguments around line 700. For every
Pi and shell container it passes, among others:

- `--read-only`, with automatic read-only tmpfs provisioning enabled;
- `--tmpfs "/dev:rw,nosuid,noexec,mode=755,size=65536k"`;
- `--mount type=devpts,destination=/dev/pts`;
- `--mount type=tmpfs,destination=/dev/shm,ro=true`;
- `--mount type=tmpfs,destination=/run/secrets,ro=true`;
- the Pi tmpfs mounts, all `noexec,nosuid,nodev`:
  - `/tmp` and `/var/tmp` (256 MiB);
  - `/run` (32 MiB);
  - the npm cache below `/pi-home`;
  - the ephemeral home when no state directory is used;
- the workspace bind mount, which is writable and not `noexec`.

The same layout was fixed in the Claude reference, Codex and OpenCode. The
reference validation record (claude-container `docs/validation.md`,
"Engine-provided `/dev` for pseudo-terminals") measured:

- the explicit `devpts` is `mode=600,ptmxmode=000`, and allocation fails;
- `--device /dev/ptmx` does not help;
- Podman rejects `ptmxmode` as a mount option;
- the engine's `devpts` is `mode=620,ptmxmode=666` and works.

The defect was rechecked here with the Pi image `5428725d0274` (tags
`setup-7c06…` and `setup-177d…`, built by the operator's setup on this host)
and this launcher's `/dev` arguments: "out of pty devices".

Qualification digests the launcher (`agent/profile.json` `wrapper`).

The existing tests are:

- `tests/test_wrapper.py`:
  - around line 764, a check that expects 6 `--tmpfs` arguments, asserts the
    `/dev` tmpfs, then filters `/dev:` out before checking
    `noexec,nosuid,nodev` on every other tmpfs;
  - `DEVICE_MOUNTS` with `assert_device_and_secret_mounts` (around
    line 1119).
- `tests/test_runtime.py`: `shell()` runs the wrapper through a PTY
  (`terminal_shell`), and `PI_CONTAINER_IMAGE` selects the image.

## Goals / Non-Goals

**Goals:**
- The same launcher, test and documentation behavior as the Claude
  reference, with the Pi temporary mounts unchanged.

**Non-Goals:**
- Shared code. The proxy keeps `--read-only-tmpfs=false`.
- The Bun decision.
- Making `/dev` `noexec` again by other means. There is none that keeps
  usable PTYs (see the reference).

## Decisions

1. **Leave `/dev` to the engine**, as in the reference. Remove the `/dev`
   tmpfs and the `devpts`, keep `--read-only` and both masks, and use the
   reference comment wording.

2. **Spec.** Remove "Terminal-compatible device mounts" and add
   "Engine-provided device mounts allow pseudo-terminals", with the
   reference's scenarios plus the existing scenario "Temporary mounts keep
   their Pi policy".

3. **Tests.**
   - `tests/test_wrapper.py`:
     - at line 764, expect 5 `--tmpfs` arguments, and assert that none
       targets `/dev`. Every tmpfs then keeps `noexec,nosuid,nodev` and a
       size, so the `/dev:` filter goes;
     - `DEVICE_MOUNTS` keeps only the `/dev/shm` and `/run/secrets` masks;
     - `assert_device_and_secret_mounts` also asserts that there is no
       `--tmpfs` for `/dev` and no `devpts` or `/dev` `--mount`.
   - `tests/test_runtime.py`: add `test_pseudo_terminals_and_device_masks`,
     the reference probe run through `self.shell()`. It must fail on the
     current launcher and pass after the fix.

4. **Documentation.**
   - `README.md` hardening table (line 543): "the engine's `/dev` and
     `devpts`, and an empty read-only `/dev/shm`".
   - `README.md` paragraph (around line 593): the engine provides `/dev` and
     a `devpts` that allows pseudo-terminals, and an explicit `devpts` would
     get `ptmxmode=000`. On Podman 5, `/dev` is writable and not `noexec`
     but needs capabilities to create devices; on Podman 4.9 it is
     read-only. The `/dev/shm` and `/run/secrets` sentences stay.
   - `AGENTS.md` (around line 121): keep automatic provisioning, leave
     `/dev` and its `devpts` to the engine, and mask `/dev/shm` and
     `/run/secrets`.
   - `docs/validation.md`: a record with the results and pending operator
     setups.

## Risks / Trade-offs

- [On Podman 5, `/dev` becomes writable and executable, while Pi's own
  temporary mounts are all `noexec`] → The workspace bind mount is already
  writable and executable, so this adds no new capability. `nosuid`
  remains, devices need the dropped capabilities, and `/dev` is ephemeral.
  This is recorded as a policy change.
- [The Bun-enabled image path] → It is not affected: the launcher arguments
  are the same. The Bun runtime test stays optional, as before.
- [The Rocky host cannot be reproduced here] → The operator reruns setup
  there.

## Migration Plan

1. Merge on `main` after validation. The operator pushes it.
2. On each host, run `--container-setup` (the launcher digest changed), with
   `PI_ENABLE_BUN` unset as before.
3. Rollback: revert the merge and rerun setup.

# Proposal

## Why

claude-container tag `sandbox-ref-11` makes the sandbox work on a Rocky Linux 9
lab host (Podman 5, crun 1.27, partial cgroup delegation, `ipv6.disable=1`,
RHEL `/run/secrets` mount, domain UID) and on a newer WSL host. Codex and
OpenCode adopted it in their own changes, and the operator's tests passed on
both hosts. Pi still uses `sandbox-ref-10` with its own launcher and recipe,
and fails on those hosts in the same ways:

- it rejects the `unix://` socket path;
- it requests undelegated budgets;
- the guard refuses the RHEL secrets mount;
- the terminal cannot attach;
- the image build needs outbound port 80.

Pi also builds its setup runtime through `pi-container.sh --container-build`
(`install.runtime_build: wrapper`). That build-only path exits before the
host CA bundle is resolved, so on a TLS-intercepting network the HTTPS
package fetches could not verify.

A first adoption of `sandbox-ref-11` stopped on a shared test that assumed a
recipe-built runtime. Following `docs/propagation.md`, that attempt was
discarded and the test was fixed in claude-container. The fix shipped as
`sandbox-ref-12`, which also makes every qualification container run in
`/`, so qualification never depends on an image `WORKDIR`.

## What Changes

- **Adopt `sandbox-ref-12`** (from `sandbox-ref-10`) with `tools/propagate.py`.
  It contains the `sandbox-ref-11` lab-host fixes, plus `--workdir /` for the
  qualification containers and the runtime-build test pinned to `recipe`. It
  covers the 21 shared files,
  the reference manifest and the current-state documents (`README.md`,
  `AGENTS.md`, `CONTRIBUTING.md`, `docs/setup.md`,
  `docs/network-contract.md`). The shared `setup/setup.py` already passes the
  trust selection and bundle to a wrapper-built runtime.
- **Launcher (`pi-container.sh`)**, ported from the reference, as in Codex
  and OpenCode:
  - reduce a `unix://` host socket report to its pathname;
  - request each budget only when the engine reports its cgroup
    controller. Announce each unenforced budget, and at inspection require
    enforced budgets to match and unenforced ones to be absent;
  - mask `/run/secrets` with an empty read-only tmpfs;
  - stop disabling automatic read-only tmpfs. Mount a `noexec` `/dev`
    tmpfs, `devpts` and an empty read-only `/dev/shm`;
  - select the host CA bundle before any build, including the build-only
    refresh, and pass it to `build_runtime_image` as the `build-ca` secret.
    The secret does not change the `build-inputs-hash` staleness label.
- **Runtime image recipe**:
  - fetch Debian packages only over verified HTTPS, bootstrapped from the
    base image's Node.js roots plus the optional `build-ca` secret;
  - `.containerignore` admits `podman-build-secret*`;
  - the pin tests reject plain-HTTP sources and disabled verification. They
    also reject a `WORKDIR` that no build step creates: Pi declares none
    today, so no recipe change is needed for it.
- **Wrapper tests**:
  - fixtures for the shared-code imports and the controller query;
  - assertions for the new mounts, budgets, socket and build secret,
    including the build-only path.
- **BREAKING (policy):**
  - a budget whose controller is not delegated is not enforced;
  - `/dev` becomes a writable `noexec` tmpfs.
- **BREAKING (installation):** the qualification identity, code digests, the
  runtime image identity and the `build-inputs-hash` (the `Containerfile` and
  `.containerignore` change) all change. Every image is stale until rebuilt,
  and restricted installations rerun setup.
- **Unchanged:**
  - the `noexec` `/tmp`, `/var/tmp` and `/run` sizes;
  - the home, the npm cache and the delegated Podman storage tmpfs;
  - Bun (`PI_ENABLE_BUN`) handling;
  - the provider profiles;
  - the guard's `/run/secrets` rule.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `container-isolation`:
  - explicit bounded ephemeral storage no longer disables automatic
    provisioning;
  - budgets are enforced per delegated controller and verified;
  - the secrets mask;
  - terminal-compatible device mounts.
- `container-podman-access`: accepts a `unix://` host socket report.
- `container-session`:
  - the qualification identity binds the enforced budget sets;
  - unenforced budgets are announced.
- `container-setup`:
  - smoke and plan follow the enforced set;
  - the host CA covers the setup package fetches;
  - the wrapper-built runtime receives the host CA as a build secret.
- `container-launcher`: the build-only refresh resolves and passes the host
  CA.
- `network-egress`:
  - proxy budgets per delegated controller;
  - IPv6-less qualification;
  - the bootstrap admits only the read-only secrets mask;
  - the proxy skips unsupported address families;
  - qualification containers do not depend on the image working directory.
- `runtime-image`:
  - HTTPS package sources and the pinned trust bootstrap;
  - the working directory needs no engine creation.

## Impact

- Shared files through the tool, as listed above.
- Pi-owned files:
  - `pi-container.sh`, `Containerfile`, `.containerignore`;
  - `tests/test_wrapper.py`, `tests/test_image_pins.py`;
  - `README.md`, `AGENTS.md`, `docs/validation.md`.
- `main` is already two commits ahead of `origin/main` (the parity-table
  alignment). That is unrelated and stays as it is.
- Every Pi image becomes stale, and restricted installations must rerun
  setup.

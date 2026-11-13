# Proposal

## Why

Bun is an optional runtime that `PI_ENABLE_BUN` bakes into the Pi image. Pi
itself runs on Node and does not use it. The supported path cannot deliver
it:

- setup always builds the image without Bun;
- qualification keeps only `PATH`, `CONTAINER_HOST` and the budgets, so an
  image built with Bun never qualifies;
- a `PI_ENABLE_BUN` left in the operator's shell makes setup's build-only
  refresh produce a Bun image that the launch then reports as stale. This
  failed the first setup on the newer WSL host (2026-11-12, recorded in
  `docs/validation.md`).

No other wrapper has an optional image input. Bun is the only asymmetry in the
runtime images, and it costs about 90 test references, a disposable Bun image
build in every `./test.sh` run, and Bun requirements in six capabilities. The
validation record lists the Bun selection as an open decision. This change
closes it by removing Bun.

## What Changes

- **Image (`Containerfile`):** remove `ARG INSTALL_BUN`, `ARG BUN_VERSION` and
  the conditional `npm install bun@…`. The image has a single variant.
- **Launcher (`pi-container.sh`):**
  - stop reading `PI_ENABLE_BUN`. Drop `INSTALL_BUN` from the build arguments
    and from the `build-inputs-hash` input;
  - stop warning about `PI_BUN_VERSION`. The `PI_PULL_ALWAYS` warning stays;
  - help text and the stale-image message no longer name Bun.
- **Tests:**
  - remove Bun cases from `tests/test_wrapper.py`, `tests/fake_podman.py`
    and `tests/test_image_pins.py`;
  - remove the disposable Bun image check from `tests/test_runtime.py`, while
    keeping the assertion that `bun` is absent from the image;
  - remove `PI_TEST_BUN` from `test.sh` and `tests/run-runtime.sh`.
- **Documentation:**
  - `README.md` loses the "Bun runtime (opt-in)" section and its other Bun
    mentions;
  - update `AGENTS.md`, `CONTRIBUTING.md`, `SECURITY.md`, `docs/setup.md` and
    `docs/network-contract.md`;
  - add a `CHANGELOG.md` entry and a validation record.
- **BREAKING:**
  - `PI_ENABLE_BUN` and `PI_BUN_VERSION` have no effect, without a warning;
  - an image built with Bun no longer exists as a variant;
  - the staleness hash changes, so every existing runtime image is stale.
    Restricted installations rerun `--container-setup`, which also
    requalifies the changed launcher. Projects that need Bun run it outside
    the sandbox until a toolchain model exists.
- **Unchanged:**
  - shared code (`network/`, `setup/`); no new reference tag;
  - Pi, OpenSpec and the base image versions;
  - the common toolset;
  - runtime package installs, which stay denied in restricted modes.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `container-launcher`:
  - image freshness no longer includes a Bun selection;
  - only `PI_PULL_ALWAYS` is an ignored image variable;
  - the build-only refresh has no Bun selection.
- `runtime-image`: the pinned inputs and the update procedure no longer name
  Bun.
- `container-setup`: the wrapper-built runtime image no longer mentions Bun,
  and the "Bun is not selected by setup" scenario goes.
- `network-egress`:
  - the outer boundary no longer names an optional Bun runtime;
  - runtime installs are denied for every package registry.
- `container-isolation`: caller identity no longer covers enabled Bun.
- `container-podman-access`: delegation is independent of native Pi
  permissions only.

## Impact

- `Containerfile`, `pi-container.sh`, `test.sh`.
- `tests/test_wrapper.py`, `tests/fake_podman.py`, `tests/test_image_pins.py`,
  `tests/test_runtime.py`, `tests/run-runtime.sh`.
- `README.md`, `AGENTS.md`, `CONTRIBUTING.md`, `SECURITY.md`,
  `docs/setup.md`, `docs/network-contract.md`, `docs/validation.md`,
  `CHANGELOG.md`.
- Operators: rerun `--container-setup` on every host.

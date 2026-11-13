# Design

## Context

Bun touches only Pi-specific files. The shared code (`network/`, `setup/`)
never names it, so no reference tag or `tools/propagate.py` run is needed.
See proposal.md (Why) for the motivation.

- **`Containerfile`:**
  - `ARG INSTALL_BUN=0` and `ARG BUN_VERSION=1.3.14`, documented in the
    header comment;
  - an `if [ "${INSTALL_BUN}" = "1" ]` branch inside the single
    `npm install` step;
  - a comment about Bun's platform binaries.
- **`pi-container.sh`:**
  - help text: the `PI_ENABLE_BUN` entry, the deprecated-names paragraph
    ("PI_BUN_VERSION and PI_PULL_ALWAYS are ignored … OpenSpec and Bun") and
    the stale-image paragraph;
  - the ignored-variable loop over `PI_BUN_VERSION PI_PULL_ALWAYS`;
  - `install_bun` from `PI_ENABLE_BUN`, appended to the hash input as
    `INSTALL_BUN=<0|1>\n` and passed as `--build-arg INSTALL_BUN`;
  - the stale-image `die` message, which names `PI_ENABLE_BUN`.
- **`test.sh`:** computes the same hash with a literal `INSTALL_BUN=0`, passes
  `--build-arg INSTALL_BUN=0`, and runs `tests/run-runtime.sh` with
  `PI_TEST_BUN=1`.
- **`tests/run-runtime.sh`:** forwards `PI_TEST_BUN`.
- **Tests:**
  - `tests/fake_podman.py` mirrors the hash, including the `INSTALL_BUN`
    line;
  - `tests/test_wrapper.py`:
    - `test_hash_inspection_bun_build_inputs_and_failures`;
    - `test_exact_delegation_bun_and_connection_forwarding`, which iterates
      over Bun values;
    - `test_build_only_refresh`, which iterates over Bun values;
    - the help-text expectation `'PI_BUN_VERSION and PI_PULL_ALWAYS are
      ignored'`;
  - `tests/test_image_pins.py`:
    - `bun` in `PACKAGES`;
    - the `BUN_VERSION` assertion;
    - two mutation cases built on the Bun install line;
  - `tests/test_runtime.py`:
    - `test_native_pi_help_version_npm_git_and_optional_bun` builds a
      disposable Bun image when `PI_TEST_BUN=1`, and already asserts that
      `bun` is absent from the default image (`exit 9`);
    - `shell()` raises its timeout when `PI_ENABLE_BUN` is set.
- **Qualification** digests the launcher (`agent/profile.json` `wrapper`), so
  any launcher change needs a new `--container-setup`.

## Goals / Non-Goals

**Goals:**
- No Bun in the recipe, launcher, tests or current documentation.
- Keep coverage that does not concern Bun. Re-express it where a test used
  Bun only as a vehicle: the mutation cases in `test_image_pins.py`, the
  delegation matrix, and the build-only refresh.

**Non-Goals:**
- A general toolchain model for the wrappers. That is a separate
  exploration.
- Rewriting history:
  - archived changes and existing dated records in `docs/validation.md` keep
    their Bun text;
  - existing `CHANGELOG.md` entries stay as written;
  - the stale `[Unreleased]` section since `sandbox-ref-10` is not realigned
    here.
- The stale `INSTALL_PODMAN=0` wording in the `container-podman-access`
  scenario. It is unrelated to Bun and left as is.

## Decisions

1. **Drop `PI_ENABLE_BUN` and `PI_BUN_VERSION` silently.**
   - The wrapper no longer reads `PI_ENABLE_BUN`, and `PI_BUN_VERSION` leaves
     the ignored-variable warning loop, which keeps `PI_PULL_ALWAYS`.
   - The project is not distributed, and the operator controls every host.
   - A leftover value in a shell is harmless once it no longer affects the
     hash. Neither the build nor the session reads it, and it is not
     forwarded.
   - Alternative: one-line "ignored" warnings, as for `PI_PULL_ALWAYS`. That
     keeps a compatibility shim and two more help-text lines for no
     operator benefit.

2. **Remove the `INSTALL_BUN` line from the hash input** rather than keep a
   constant `INSTALL_BUN=0`.
   - The hash then covers exactly the five files in the build context,
     like the other wrappers.
   - Every existing image becomes stale once, which setup handles anyway
     because the launcher digest changes.
   - `tests/fake_podman.py` and `test.sh` drop the same line.

3. **Keep the absence assertion.**
   - The runtime test keeps `if command -v bun …; then exit 9`, and the test
     name loses `_and_optional_bun`.
   - It becomes the runtime proof of the new "`bun` is not found"
     scenarios.
   - The `PI_TEST_BUN` block and the `PI_ENABLE_BUN` timeout branch go.

4. **Re-express the wrapper tests on their real subject.**
   - **`test_hash_inspection_…`** (renamed without `bun`):
     - assert that the build arguments are exactly `['PI_VERSION']`;
     - assert that `PI_ENABLE_BUN=1` with `PI_BUN_VERSION=bun-v1.2.0` changes
       neither the label hash nor the build arguments, and prints no
       warning naming them;
     - assert that `PI_PULL_ALWAYS` still warns once.
   - **The delegation matrix** iterates over the access values only, with
     `PI_ENABLE_BUN=1` set once so that a leftover value is shown to be
     inert.
   - **`test_build_only_refresh`** iterates over the modes only, and asserts
     `PI_VERSION` as the only build argument.

5. **Image pins.**
   - `PACKAGES` keeps Pi and OpenSpec, and the `BUN_VERSION` assertion goes.
   - The mutation cases move to OpenSpec:
     - 'unversioned package' installs `@fission-ai/openspec` without a
       version;
     - 'remote installer' adds a `curl … | bash` step to the npm install.
   - A new case adds `bun@1.3.14` to the install. It is pinned, so it must
     be rejected as an unexpected package. This needs a small allowlist
     check in `violations()`: every installed package must be in
     `PACKAGES`.

6. **Documentation.**
   - Remove the README "Bun runtime (opt-in)" section, the `PI_ENABLE_BUN`
     table row, and the Bun steps in the update procedure and
     troubleshooting.
   - Change the mentions that say "Bun" to "package installs" or remove
     them, in the README, `SECURITY.md`, `CONTRIBUTING.md`, `AGENTS.md`,
     `docs/setup.md` and `docs/network-contract.md`.
   - Add a `CHANGELOG.md` `[Unreleased]` "Removed" entry.
   - Add a dated `docs/validation.md` record, which closes the "Bun
     selection remains an open decision" note.

## Risks / Trade-offs

- **A project needs Bun inside the sandbox.**
  - Mitigation: run it outside the sandbox. A future toolchain model can
    reintroduce runtimes through setup, so that they are qualified.
  - The proposal marks this as BREAKING.
- **Every runtime image becomes stale.** This is expected: the operator
  reruns `--container-setup` on each host, as for every launcher change.
  No rollback beyond reverting the commit is needed.
- **Hidden Bun use in the tests.** The tasks end with
  `grep -rni bun` over the live files. Allowed hits are archived changes,
  dated validation records, existing changelog entries and the absence
  assertions.

## Migration Plan

1. Merge to `main`. The operator pushes.
2. On this host, the Rocky Linux 9 lab host and the newer WSL host, run
   `--container-setup`. `PI_ENABLE_BUN` may stay set; it is now inert.
3. Record the results in `docs/validation.md`, then archive with the spec
   sync.

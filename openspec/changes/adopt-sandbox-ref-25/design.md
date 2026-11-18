# Design

## Context

Pi is on `sandbox-ref-21`. Its launcher, `pi-container.sh` (1231 lines), differs from the shared core where the launcher contract (`docs/launcher-contract.md` in `sandbox-container`, column P) records:

- **Names (U2, U5, U6):**
  - `select_setting` maps nine `PI_*` aliases, including `PI_MOUNT_GITCONFIG`;
  - `PI_NETWORK` stops the launch, `PI_PULL_ALWAYS` prints a notice, and `--wrapper-help` is a help alias;
  - `PI_ENV_VARS` and `PI_READONLY_CONFIG` have no `PI_CONTAINER_` prefix;
  - a notice says that `~/.gitconfig` is no longer mounted by default.
- **Temporary storage (U7, L7):** `/tmp` and `/var/tmp` are 256M; the home is a `noexec` 64M tmpfs; `/run` has mode 1777.
- **Signals (U9):** family-B lifecycle with separate creation phases and 5-second control calls.
- **Credentials (U10):** unrestricted sessions forward `ANTHROPIC_API_KEY`, `OPENAI_API_KEY` and `GOOGLE_API_KEY` whenever set.
- **Environment (U11, U15):** `TERM` only with a terminal; `EDITOR` and `VISUAL` keep host values.
- **Build (U8, U12):**
  - `install.runtime_build: "wrapper"`;
  - its own `build-inputs-hash` over the concatenated inputs;
  - a 300-second build timeout.
- **Messages:** `PI_DEBUG` output; a non-absolute `HOME` stops the launch.
- **Pi-only behavior:**
  - `PI_VERSION` from `.version` as a build argument (`agent_build_args`);
  - the `~/.npm` tmpfs sized by `PI_NPM_CACHE_SIZE` (default `256M`) and the exact `PI_CONTAINER_GITCONFIG=1` read-only mount (`agent_validate`, `agent_mounts`);
  - `PI_OFFLINE=1`, `PI_SKIP_VERSION_CHECK=1` and `PI_TELEMETRY=0` in restricted sessions;
  - the `PI_CONTAINER_YOLO` notice, since Pi has no tool-approval layer (`agent_approval_bypass`).

Pi already shares `~/.pi` and `~/.agents` by default (U4), already exits after a build-only `--container-build` (U3), and already adds `--init`, `CONTAINER_NAME`, the delegation tmpfs mounts and `--format docker` (U12).

The test map (`docs/launcher-test-map.md`) sorts Pi's 91 `tests/test_wrapper.py` cases into:

| Destination | Cases |
| --- | --- |
| Shared | 15 |
| Shared (rewrite) | 5 |
| Shared (duplicate) | 59 |
| Hook | 6 |
| Obsolete | 3 |
| Fake engine | 3 |

20 cases are marked "to verify at adoption". The hook cases are:
- `test_help_missing_version_and_runtime`;
- `test_retained_editors_gitconfig_and_secrets`;
- `test_gitconfig_requires_exact_opt_in`;
- `test_gitconfig_opt_in_without_regular_file`;
- `test_yolo_has_no_effect`;
- `test_restricted_sessions_declare_the_toolchain_mount_and_keep_pi_settings`.

The `tools/propagate.py` dry run from `sandbox-ref-21` straight to `sandbox-ref-25` (2026-11-18) gives this plan:

- **Add:** `launcher/core.sh`, `tests/fake_podman.py`, `tests/fixtures/agent/launcher.sh`, `tests/fixtures/shell-agent/launcher.sh`, `tests/test_launcher.py`.
- **Update:** `network/README.md`, `network/agent_profile.py`, `network/control.py`, `network/qualification_records.py`, `network/qualify.py`, `setup/common.py`, `setup/launch.py`, `setup/setup.py`, `tests/fixtures/agent/profile.json`, `tests/sandbox_profile.py`, `tests/test_agent_profile.py`, `tests/test_alignment.py`, `tests/test_network_policy.py`, `tests/test_qualification.py`, `tests/test_setup.py`.
- **Rewrite:** one reference each in `README.md`, `AGENTS.md`, `CONTRIBUTING.md` and `docs/setup.md`, and nine in `docs/network-contract.md`.
- **Move:** the manifest to `sandbox-ref-25` (`6bed770`).

`tests/fake_podman.py` already exists here as Pi's own fake engine, which the old `tests/test_wrapper.py` uses. The tool replaces it with the shared fake.

The Claude, Codex and Antigravity adoptions found what every adoption needs:
- `tests/test_reference_copy.py` lists `launcher` in `CLOSED_DIRECTORIES`.
- The old wrapper tests run against the core only with an adapted harness:
  - the fake answers the `build-inputs-hash` label and the core's one-line socket query;
  - synthetic installations copy the core, the agent part and the build inputs;
  - order-sensitive argument assertions compare options as sets.
- The core prints no help for agent variables, so the agent part defines `agent_help`.
- U10 holds strictly: real network tests that relied on a host key set it inside the session.
- `/run` is not writable by the session user under the core (L7; a visible change for Codex and Antigravity).
- `sandbox-ref-25` covers the Antigravity case that accepted a reported socket path `/`. Pi's spec already requires that refusal.

## Goals / Non-Goals

**Goals:**
- Pi runs entirely on the shared core. Its own launcher code is the entry script and `agent/launcher.sh`.
- No Pi launcher behavior disappears without being either a recorded visible change or a shared test.

**Non-Goals:**
- Adopting the core in OpenCode.
- Changing the Pi image contents, the Pi version, the policy inventories or the authentication methods.
- Changing reference files inside this repository. A defect found here is fixed in `sandbox-container` and arrives by a tag.

## Decisions

1. **Adopt with the tool, straight from `sandbox-ref-21` to `sandbox-ref-25`.**
   - Before running it, save the current `pi-container.sh`, `tests/test_wrapper.py` and `tests/fake_podman.py` outside the repository as the old-test baseline.
   - The dry run must list exactly the plan in "Context". `--apply` switches to the branch `adopt-sandbox-ref-25`.
   - Then add `launcher` to `CLOSED_DIRECTORIES` in `tests/test_reference_copy.py` and fix the parity rows by hand.

2. **Entry script, agent part and profile.**
   - `pi-container.sh` is the reference `sandbox-container.sh`, with only the wrapper name changed.
   - `agent/profile.json` removes `install.runtime_build`. It declares neither `native.exec` (the default `/usr/local/bin/pi` is where the image installs Pi) nor `native.exec_tmp` (Pi's storage was already `noexec`).
   - `agent/launcher.sh` declares:
     - the profile values, with `AGENT_SHARED_DIRS=(.agents)`, `AGENT_PRIVATE_SHARED_DIRS=1`, `AGENT_EXEC=/usr/local/bin/pi` and `AGENT_EXEC_TMP=0`;
     - `AGENT_INSTALL_FILES=(.version)`, which also joins the build-inputs hash;
     - `AGENT_CREDENTIALS=(anthropic-api=ANTHROPIC_API_KEY openai-api=OPENAI_API_KEY gemini-api=GEMINI_API_KEY openrouter-api=OPENROUTER_API_KEY)`;
     - `AGENT_POLICY_HOSTS` for the four base profiles;
     - `AGENT_RESTRICTED_ENV=(PI_OFFLINE=1 PI_SKIP_VERSION_CHECK=1 PI_TELEMETRY=0)`. The core applies these after toolchain and forwarded variables and reserves them in restricted modes.
     - empty session, provider, unset and reserved arrays.
   - Hooks:
     - **`agent_validate`:**
       - with `PI_CONTAINER_GITCONFIG` exactly `1`, it resolves `~/.gitconfig` physically and requires a regular file without colon, CR or LF; otherwise it stops naming the variable and the path;
       - it requires `PI_NPM_CACHE_SIZE`, when set, to match the core's tmpfs size syntax;
       - both checks run before any engine or state operation.
     - **`agent_mounts`:** `tmpfs:<home>/.npm:${PI_NPM_CACHE_SIZE:-256M}` in every session; `ro:<physical gitconfig>:<home>/.gitconfig` with the exact opt-in.
     - **`agent_build_args`:** reads the first line of `.version` in the installation, without whitespace, and stops when it is missing or empty; output `PI_VERSION=<version>`.
     - **`agent_approval_bypass`:** prints one notice that `PI_CONTAINER_YOLO` has no effect, because Pi has no tool-approval layer and the container is the only boundary. Its outputs are empty. The core validates the value as a boolean before any engine operation and never calls the hook in shell mode or the qualification probe.
     - **`agent_help`:**
       - documents `PI_CONTAINER_YOLO`, `PI_CONTAINER_GITCONFIG` and `PI_NPM_CACHE_SIZE`;
       - lists the provider credential of each policy profile, which unrestricted sessions get only through `PI_CONTAINER_ENV_VARS`;
       - names the restricted Pi settings;
       - notes that Pi's `--approve` trusts project-local files and is not tool approval.

   Alternative rejected: keeping the gitconfig migration notice in `agent_validate`. It describes a change from an unreleased version, like the aliases U2 removes, so it goes with them.

3. **State follows the core.**
   - Shared `~/.pi` and `~/.agents` stay the default. `PI_CONTAINER_CONFIG_DIR` replaces `~/.pi`, and a nonempty `PI_CONTAINER_STATE_DIR` selects an isolated home.
   - `PI_CONTAINER_READONLY_STATE` replaces `PI_READONLY_CONFIG`.
   - Isolated-home children must be contained and private (M4).

4. **Old tests gate the deletion.**
   - **Setup:** the saved `tests/test_wrapper.py`, with its saved fake engine, runs against the new entry script and core. The 91 cases stay unchanged; only the harness is adapted, as in the earlier adoptions.
   - **Outcomes:** every failing case is resolved in exactly one way:
     - **(a) Visible change.** The failure matches a row of the contract's "Visible changes" list (U1, U2, U5, U6, U7, U8, U9, U10, U11, U12, U14, U15, U18, M4, the low findings, L7), or the gitconfig migration notice of decision 2. The case is dropped.
     - **(b) Lost behavior.** The work stops. The behavior and a shared case go into `sandbox-container` through a reference change and a new tag, and this change then adopts that tag.
     - **(c) Pi-only behavior.** The case stays in the reduced `tests/test_wrapper.py`.
   - **Record:** passing shared and duplicate cases are dropped. The 20 "to verify at adoption" cases are resolved by name, and the table goes into `docs/validation.md`.

5. **Reduced `tests/test_wrapper.py`.** It uses the shared `tests/fake_podman.py` and the real `agent/launcher.sh`. It covers:
   - help: the provider hosts of the four profiles, `PI_CONTAINER_YOLO`, `PI_CONTAINER_GITCONFIG`, `PI_NPM_CACHE_SIZE` and the credentials, without Podman or `.version`;
   - the YOLO notice for enabled values only, with unchanged engine arguments, no notice in shell mode, and the refusal of invalid values before engine queries;
   - gitconfig: no mount without the exact `1`; the physical file mounted read-only with it; the refusal without a regular file before any engine query or state creation;
   - the `~/.npm` tmpfs with the default and a custom size, and the refusal of an invalid size;
   - `PI_VERSION` from `.version` in the build arguments, and the stop when `.version` is missing;
   - `PI_OFFLINE`, `PI_SKIP_VERSION_CHECK` and `PI_TELEMETRY` winning over a toolchain and `PI_CONTAINER_ENV_VARS` in offline and provider mode, and their absence in unrestricted mode;
   - each policy profile's credential in provider mode, none in offline and unrestricted mode, and an `PI_CONTAINER_ENV_VARS` attempt to forward another profile's key;
   - every outcome (c) from decision 4.

6. **Wrapper-owned tests and scripts follow the Antigravity adoption.**
   - **`tests/run-runtime.sh`:**
     - `--wrapper` runs `test_launcher.py` and `test_wrapper.py`, and `--shared` also runs `test_launcher`;
     - the default image is `localhost/pi-container:latest`;
     - the build hint is the build-only `--container-build`.
   - **`tests/test_runtime.py`:**
     - 512/512/32 MiB for `/tmp`, `/var/tmp` and `/run`, and 512 MiB for the shared-state home, all `noexec`;
     - `/run` not writable by the session user;
     - the `~/.npm` tmpfs;
     - `PI_CONTAINER_READONLY_STATE`.
   - **`tests/test_network_runtime.py`:**
     - it installs `agent/launcher.sh`, `launcher/core.sh`, `.version` and `.containerignore`;
     - it supplies the provider settings to the delegation grid;
     - real network tests that need a provider key under an operator profile set a synthetic key inside the session (U10).
   - **`tests/test_setup_runtime.py`:** its shim answers only the `{{.Id}}` inspection, and the wrapper build no longer depends on `runtime_build`.
   - **`tests/test_setup_wrapper.py`:** covers the provider default.
   - **`test.sh`:** builds its disposable image with `PI_CONTAINER_IMAGE=<image> PI_CONTAINER_NETWORK=unrestricted PI_CONTAINER_MAINTENANCE=1 ./pi-container.sh --container-build` instead of computing its own hash, which no longer matches the core's (M12).
   - **CI:**
     - `.github/workflows/ci.yml` adds `tests.test_launcher` and `tests.test_alignment` to its unit list;
     - its ShellCheck step already scans the whole tree, so it covers `launcher/core.sh` and `agent/launcher.sh` unchanged. A ShellCheck finding in the core is reported to the reference, not fixed here.

7. **Documentation.**
   - **README:**
     - help and first steps without migration history;
     - network modes and the provider default;
     - state, read-only state and the isolated home, and temporary storage;
     - signals and the 20 s deadline;
     - `PI_CONTAINER_ENV_VARS` and credentials;
     - build-only and stale images;
     - the removed names in one sentence;
     - a shared components section naming the core.
   - **Other files:**
     - `SECURITY.md` and `CONTRIBUTING.md` follow the README;
     - `AGENTS.md` describes the entry script and the agent part;
     - `docs/setup.md` follows the provider default;
     - `CHANGELOG.md` gets one entry listing the visible changes.
   - **Parity table:**
     - the reference, Claude, Codex and Antigravity rows are copied from their repositories;
     - the Pi row says it adopted `sandbox-ref-25`;
     - the OpenCode row is copied from its repository.

     After the merge, the Pi row is copied into `sandbox-container`, `claude-container`, `codex-container` and `antigravity-container`.

8. **Validation scope.** The launcher, installation manifest and qualification identity all change, so validation covers the full set:
   - the unit discovery in the disposable test container;
   - `bash tests/run-runtime.sh` with `--wrapper`, `--shared`, `--setup`, `--setup-runtime`, `--qualification`, `--network` and `--guard`;
   - the default runtime run against an image rebuilt with the build-only operation;
   - `bash test.sh`;
   - `git diff --check`;
   - `tests/test_reference_copy.py` with host Python next to the `sandbox-container` checkout.

## Risks / Trade-offs

- **[Decision 4 finds a lost behavior]** → Implementation pauses for a reference change and a new tag. The most likely areas are the isolated-home layout with the `~/.npm` tmpfs below a persistent home, and the read-only state checks.
- **[Scripts using the old names stop working without a notice]** → Intended (U2). The README and `CHANGELOG.md` list the replacements.
- **[Unrestricted users lose implicit API key forwarding]** → Intended (U10). The README gives the `PI_CONTAINER_ENV_VARS` form.
- **[Images built before the adoption carry Pi's own hash and are refused as stale]** → Intended (U8). Test images and installations are rebuilt with `--container-build` or `--container-setup`.
- **[Installed qualification reports no longer match]** → The operator runs `--container-setup` on the three reference hosts after the merge.

## Migration Plan

1. Commit this change directory on `main`, save the old-test baseline, then dry-run and apply the propagation (branch `adopt-sandbox-ref-25`).
2. Write the entry script, the agent part and the profile change. Run the old tests (decision 4) and resolve every failure before touching `tests/test_wrapper.py`.
3. Reduce the wrapper tests, update the runtime tests, scripts and documentation, validate, and merge into `main`.
4. The operator pushes and runs `--container-setup` on the three hosts. The change is archived with spec sync.

Rollback: before the merge, delete the branch. After the merge, revert the merge commit.

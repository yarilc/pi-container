# Proposal

## Why

`sandbox-ref-22` added the shared Bash launcher core (`launcher/core.sh`), and the tags up to `sandbox-ref-25` fixed it while the reference, Claude, Codex and Antigravity adopted it. Pi is still on `sandbox-ref-21` with its own 1231-line `pi-container.sh`. Its aliases, state layout, temporary storage, signal handling, credential forwarding and build path differ from the core's. Until Pi adopts the core, its launcher keeps diverging, and the 20 Pi cases marked "to verify at adoption" in the reference test map stay open.

## What Changes

- Adopt `sandbox-ref-25` directly from `sandbox-ref-21` with `tools/propagate.py`.
  - It adds `launcher/core.sh`, `tests/test_launcher.py`, the shared `tests/fake_podman.py` and the launcher fixtures.
  - It updates the changed shared files (`network/*`, `setup/*`, `tests/test_alignment.py`, `tests/test_setup.py`, ...) and moves the manifest and the current-state references to the tag.
  - `tests/test_reference_copy.py` treats `launcher/` as a closed directory.
- Replace `pi-container.sh` with the thin entry script, identical to the reference's apart from its name.
- Add `agent/launcher.sh` with the Pi profile data and five hooks:
  - `agent_validate` checks `PI_CONTAINER_GITCONFIG=1` (a regular `~/.gitconfig`) and `PI_NPM_CACHE_SIZE` before any engine or state operation;
  - `agent_mounts` adds the `~/.npm` tmpfs (default 256M) and, with the exact opt-in, the read-only `~/.gitconfig`;
  - `agent_build_args` passes `PI_VERSION` from `.version` to every build;
  - `agent_approval_bypass` prints Pi's notice that `PI_CONTAINER_YOLO` has no effect, because Pi has no tool-approval layer;
  - `agent_help` documents those variables, the provider credentials and the boundary.

  The data declares `.version` as an installed file (it joins the build-inputs hash), `PI_OFFLINE=1`, `PI_SKIP_VERSION_CHECK=1` and `PI_TELEMETRY=0` for restricted sessions, and one credential per policy profile (`anthropic-api`, `openai-api`, `gemini-api`, `openrouter-api`).
- `agent/profile.json` drops `install.runtime_build` (U8). Pi keeps the default `native.exec` (`/usr/local/bin/pi`) and `noexec` temporary storage.
- Before the old launcher is deleted, run Pi's current `tests/test_wrapper.py` against the new core. Classify each failing case as one of:
  - a visible change;
  - a lost behavior, fixed in the reference first, with a new tag;
  - Pi-only behavior, kept in the reduced `tests/test_wrapper.py`.
- Reduce `tests/test_wrapper.py` to Pi's hook and data tests. Update the wrapper-owned runtime tests, `test.sh` (it builds through the wrapper's build-only operation) and the CI unit list.
- Visible changes for Pi users, all from the contract's "Visible changes" list. Breaking changes are allowed: the project has no release.
  - **BREAKING**: a missing `PI_CONTAINER_NETWORK` selects `provider`. Without the provider settings, the launch still stops with setup guidance.
  - **BREAKING**: legacy names are removed with no notice (U2):
    - the `PI_*` aliases (`PI_IMAGE_NAME`, `PI_ENABLE_PODMAN`, `PI_PODMAN_SOCKET`, `PI_MEMORY_LIMIT`, `PI_CPU_LIMIT`, `PI_PIDS_LIMIT`, `PI_RUN_TIMEOUT`, `PI_ALLOW_UNSAFE_PWD`, `PI_MOUNT_GITCONFIG`);
    - the `PI_NETWORK` stop and the `PI_PULL_ALWAYS` notice;
    - `--wrapper-help`;
    - the gitconfig migration notice.
  - **BREAKING**: `PI_ENV_VARS` becomes `PI_CONTAINER_ENV_VARS`, and `PI_READONLY_CONFIG` becomes `PI_CONTAINER_READONLY_STATE` (a boolean). An invalid name in the forwarding list stops the launch.
  - **BREAKING**: unrestricted sessions no longer forward `ANTHROPIC_API_KEY`, `OPENAI_API_KEY` or `GOOGLE_API_KEY` unless `PI_CONTAINER_ENV_VARS` lists them.
  - **BREAKING**: `EDITOR` and `VISUAL` are always `nano`; the host values are no longer kept.
  - **BREAKING**: `/tmp` and `/var/tmp` grow to 512 MiB and the ephemeral home to 512 MiB, all `noexec`; `/run` (32 MiB) is no longer writable by the session user.
  - **BREAKING**: signals follow the shared core: shutdown starts at once, also during creation, within one 20-second deadline.
  - **BREAKING**: shell mode passes its arguments to Bash.
  - `PI_DEBUG` output is dropped; an unresolvable `HOME` no longer stops the launch; builds have no 300-second timeout; isolated-home children must be contained and private.
  - Every session gets `TERM`, `COLORTERM`, `LANG` and `LC_ALL` when set. Unrestricted sessions also forward the proxy variables, `ALL_PROXY` included.
- Update the README, `SECURITY.md`, `CONTRIBUTING.md`, `AGENTS.md`, `docs/setup.md`, `docs/network-contract.md`, `CHANGELOG.md` and `docs/validation.md`. The help text now comes from the core.

## Capabilities

### New Capabilities

- `shared-launcher`: Pi's launcher is the shared core with a thin entry script and the Pi agent part. The agent part stays consistent with the profile, and Pi's own tests cover its hooks and data.

### Modified Capabilities

- `container-launcher`:
  - help from the core without `--wrapper-help`;
  - a build followed by a session, and shell arguments;
  - retained controls under the new names, with credential, editor and debug rules;
  - the YOLO notice from the hook;
  - the build-only operation that validates every setting;
  - removal of the deprecated aliases and the ignored image variables.
- `container-isolation`: temporary storage sizes and the read-only `/run`; the dedicated home size; read-only state under its new name; isolated-home children; gitconfig without the alias and the migration notice.
- `container-session`:
  - provider default;
  - the shared 20-second shutdown and immediate interruption of creation;
  - qualification with the resolved mode;
  - extra variables by name, the session environment, shell arguments, session name and `--init`, and bounded engine queries;
  - first-user guidance without the migration history.
- `container-podman-access`: no deprecated delegation aliases; the `sandbox-ref-25` checks on the reported host socket path; private nested-Podman tmpfs mounts.
- `container-setup`: the installation contains the core and the agent part; the runtime image is built through the build-only operation without a profile field; an empty network override selects provider.
- `network-egress`:
  - provider default, which qualification also uses;
  - launcher files as protected restricted inputs;
  - the profile without `runtime_build`;
  - the shared `launcher/` component;
  - help printing each profile's hosts;
  - the protected optional-traffic settings under the new forwarding name.

## Impact

- **Code:** `pi-container.sh` shrinks to the thin entry script. Other code changes:
  - new `agent/launcher.sh`;
  - `agent/profile.json` loses `install.runtime_build`;
  - shared files copied from the tag;
  - wrapper-owned tests, `test.sh`, CI and docs updated.

  The `Containerfile` changes only in a comment that names the agent part as the source of `PI_VERSION`.
- **Qualification:** the qualification identity now includes the core and the agent part. Every installation needs `--container-setup` again; the operator runs it on the three reference hosts.
- **Users:**
  - scripts using the old `PI_*` names or `PI_ENV_VARS`/`PI_READONLY_CONFIG` switch to the `PI_CONTAINER_*` names;
  - unrestricted users who relied on forwarded API keys list them in `PI_CONTAINER_ENV_VARS`.
- **Other wrappers:** OpenCode adopts the core after Pi. If this adoption finds a lost behavior, a reference fix and a new tag come first.

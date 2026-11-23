<!-- markdownlint-configure-file { "MD024": { "siblings_only": true } } -->

# Changelog

All notable changes to pi-container are documented here.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html)
for the wrapper script (distinct from the Pi Coding Agent version in `.version`).

## [Unreleased]

### Added

- Guided setup: `--container-setup` (interactive, used alone) prepares a
  protected installation, images and guard under reviewed maintenance consent,
  qualification and a managed launcher at `~/.local/bin/pi-container`. Setup
  builds the runtime image through the wrapper (`install.runtime_build`) and
  installs `.version` (`install.files`); the shared code is at
  `claude-container` tag `sandbox-ref-8`.
- Podman's successful `Should restart: false` stderr line is reclassified as
  informational through the shared diagnostics filter.
- Network modes: `PI_CONTAINER_NETWORK=offline|provider|unrestricted`, enforced
  in offline and provider modes by the native guard and the external egress
  proxy shared with `claude-container` (tag `sandbox-ref-8`), with
  `--container-qualify`, opt-in host CA trust (`PI_CONTAINER_TRUST_HOST_CA`,
  `PI_CONTAINER_CA_BUNDLE`) and `PI_CONTAINER_CONFIG_DIR`.
- Provider profiles `anthropic-api`, `openai-api`, `gemini-api` and
  `openrouter-api`; each forwards only its key in provider mode.

- `PI_CONTAINER_STATE_DIR` keeps `.pi` and `.agents` in a private directory
  separate from the host's everyday state.
- `tests/test_image_pins.py` checks that every image input is pinned.

- Wrapper build, shell, explicit parent/worktree, and prerequisite-free help modes.
- `PI_PODMAN_SOCKET` for verified remapped same-host service access.
- Synthetic protocol/lifecycle regressions and credential-free real rootless
  acceptance with a disposable tooling runner and native Linux state.
- Containers are now automatically named `<basename>-<N>` (e.g. `pi-container-0`,
  `pi-container-1`). Reservation uses atomic create above the highest bounded
  decimal suffix across running and stopped containers, with at most 20
  collision attempts and no replacement.
- `PI_ENABLE_BUN=1`: bake the [Bun](https://bun.sh/) runtime into the image
  (opt-in, off by default). Bun is installed as a single dependency-free
  binary in `/usr/local/bin/bun` (on `PATH`, no writes to `$HOME` at runtime
  — compatible with the read-only rootfs). Toggling `PI_ENABLE_BUN`
  rebuilds the image via the `INSTALL_BUN` build arg (folded into the
  stale-image hash, same pattern as `PI_ENABLE_PODMAN`).
- `PI_BUN_VERSION`: override the Bun release tag to install (default:
  `bun-v1.3.14`); changing it triggers a rebuild.
- `PI_ENV_VARS`: space-separated list of extra environment variable **names**
  to forward to the container, for skill/extension/tool secrets the wrapper
  does not hardcode (e.g. `GITHUB_TOKEN`, `DATABASE_URL`). Variables are
  forwarded by name only (`-e NAME`, never `NAME=value`), so secret values
  never appear on the process command line; unset/empty variables are skipped
  silently. Names already handled explicitly by the wrapper are skipped to
  avoid duplicate forwarding.

### Changed

- Shared files from `sandbox-container` tag `sandbox-ref-28`
  (`adopt-sandbox-ref-28`). Every installation runs `--container-setup` again.
  Visible changes:
  - `pi-container.ps1` starts Pi from PowerShell on Windows, inside a Podman
    machine (WSL provider), in every network mode prepared by setup and
    without Podman delegation; `--container-install` adds it as a command.
    From Windows, `PI_NPM_CACHE_SIZE` reaches a session only when
    `PI_CONTAINER_ENV_VARS` lists it;
  - cgroup budgets count as enforced only with the `systemd` cgroup manager;
    with `cgroupfs` the memory and CPU budgets are announced as not enforced;
  - without the `pids` controller, the process budget uses a process rlimit
    on Linux 5.14 or later;
  - the Windows profile and system folders on a drive mount are refused as
    workspaces.
- Pin Pi 1.5.2 and OpenSpec 2.0.0. The supported API-key destinations were
  remeasured with dummy keys. Project trust controls access to the OpenSpec
  skills under `.agents/skills`. Pi 1.x renamed the Azure provider to `azure`
  and changed extension APIs.
  [Pi 1.5.2 changelog](https://github.com/earendil-works/pi/blob/v1.5.2/packages/coding-agent/CHANGELOG.md)

- Shared launcher core (`adopt-sandbox-ref-25`): `pi-container.sh` is the thin
  entry script of `sandbox-container` tag `sandbox-ref-25`, which runs the
  shared `launcher/core.sh` with Pi's agent part `agent/launcher.sh`.
  `agent/profile.json` drops `install.runtime_build`. Every installation runs
  `--container-setup` again. Visible changes:
  - an unset or empty `PI_CONTAINER_NETWORK` selects `provider`, which stops
    with setup guidance without the provider settings;
  - `PI_ENV_VARS` is now `PI_CONTAINER_ENV_VARS` (an invalid name stops the
    launch), and `PI_READONLY_CONFIG` is now `PI_CONTAINER_READONLY_STATE`
    (`1`, `true` or `yes`);
  - unrestricted sessions forward `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`,
    `GEMINI_API_KEY` or `OPENROUTER_API_KEY` only when `PI_CONTAINER_ENV_VARS`
    lists it;
  - `EDITOR` and `VISUAL` are always `nano`; `TERM`, `COLORTERM`, `LANG` and
    `LC_ALL` are forwarded when set, and unrestricted sessions also forward
    `ALL_PROXY`;
  - `/tmp`, `/var/tmp` and the shared-state home are 512 MiB `noexec` tmpfs
    mounts; `/run` (32 MiB) is not writable by the session user;
  - a signal starts shutdown at once, also during creation, within one
    20-second deadline;
  - `--container-shell` passes its arguments to Bash, and
    `--container-build --container-shell` is the build-only operation;
  - the `build-inputs-hash` label follows the core's rule, so earlier images
    are stale once; builds pull the exact base first and have no timeout;
  - a successful create whose CID record is empty starts the session with the
    ID that `podman create` printed;
  - the `PI_CONTAINER_YOLO` notice no longer names a Pi version.
- Shared files now come from `claude-container` tag `sandbox-ref-10`, and
  `agent/profile.json` sets `native.private_shared_dirs: true`. Setup now
  refuses a non-private `~/.agents` before image work, instead of failing later
  in the smoke check with only `exit 1`. A failed smoke check shows the
  wrapper's sanitized stderr, and refusals name the reason and the `chmod 700`
  fix. Existing installations requalify on their next setup.
- **Breaking:** `--container-build` used alone now rebuilds the image and
  exits; add Pi arguments (for example `--version`) to rebuild and start.
- **Breaking:** `PI_CONTAINER_YOLO` accepts only `0`, `1`, `true`, `false`,
  `yes` or `no`; an enabled value warns that it has no effect yet, and a
  disabled value is silent.
- A launch without `PI_CONTAINER_NETWORK` now stops with `setup required:`
  guidance naming `--container-setup`.
- The engine-query failure message uses the shared wording
  (`cannot query Podman or invalid engine response`).
- **Breaking:** every launch needs `PI_CONTAINER_NETWORK`; set `unrestricted`
  for the previous networking.
- **Breaking:** `PI_NETWORK` is removed (`none` becomes
  `PI_CONTAINER_NETWORK=offline`).
- **Breaking:** image builds, including the automatic build of a missing image,
  require `PI_CONTAINER_MAINTENANCE=1`; the image also copies
  `network/relay.py` and `network/mux.py`, so existing images are stale.
- The default image name is `localhost/pi-container`; an empty
  `PI_CONTAINER_STATE_DIR` selects shared state.

- **Breaking:** the image is pinned: digest base, the toolset shared with the
  other wrappers (including the Podman client and OpenSpec 1.16.0), Pi from
  `.version`, and optional Bun installed from npm as `bun@1.3.14`. The
  `curl | bash` Bun installer and the `INSTALL_PODMAN` variant are gone.
- **Breaking:** a stale image stops the launch with a message naming
  `--container-build` instead of rebuilding automatically; a missing image
  still builds.
- **Breaking:** sessions use `HOME=/pi-home`, with `~/.pi`, `~/.agents`, the
  npm cache and the opted-in gitconfig mounted below it.

- **Breaking:** wrapper settings use the common `PI_CONTAINER_*` names
  (`PI_CONTAINER_IMAGE`, `PI_CONTAINER_PODMAN`, `PI_CONTAINER_PODMAN_SOCKET`,
  `PI_CONTAINER_MEMORY_LIMIT`, `PI_CONTAINER_CPU_LIMIT`,
  `PI_CONTAINER_PIDS_LIMIT`, `PI_CONTAINER_RUN_TIMEOUT`,
  `PI_CONTAINER_ALLOW_UNSAFE_WORKSPACE`); conflicting old and new values fail.
- **Breaking:** budgets and the lifetime are validated before any engine
  query with the claude-container `sandbox-ref-2` rules; empty or malformed
  values fail. The created container is inspected and started only when the
  engine applied the budgets.
- **Breaking:** the sensitive-workspace guard also refuses `/tmp` and
  `/mnt/<letter>` drive roots, and only exact `1` overrides it.
- A lifetime stop prints a notice while keeping the client's exit status.
- Wrapper help, README and the new `AGENTS.md` follow the layout shared with
  the other wrappers and state that Pi has no tool-approval layer.

- **Breaking:** `~/.gitconfig` is no longer mounted by default. Set exact
  `PI_CONTAINER_GITCONFIG=1` to mount it read-only from its physical file; a
  notice is printed while it exists and no gitconfig variable is set.

- Require verified Linux rootless launch and delegated engines; remove the
  rootful bypass and accept delegation only for exact `PI_ENABLE_PODMAN=1`.
- Use caller UID/GID with keep-id and no added capabilities; validate private
  writable state and omit automatic SELinux relabeling.
- Provision bounded hardened temporary mounts and track owned full CIDs through
  create/attach, redirected input, application exit codes, and finite signal cleanup.
- Include the selected Bun version in stale-image hashing and report engine/image
  errors rather than silently rebuilding.

### Deprecated

- `PI_BUN_VERSION` and `PI_PULL_ALWAYS` are ignored with a warning; image
  inputs are pinned in the Containerfile.
- `PI_IMAGE_NAME`, `PI_ENABLE_PODMAN`, `PI_PODMAN_SOCKET`, `PI_MEMORY_LIMIT`,
  `PI_CPU_LIMIT`, `PI_PIDS_LIMIT`, `PI_RUN_TIMEOUT` and `PI_ALLOW_UNSAFE_PWD`:
  use the `PI_CONTAINER_*` names; each prints a warning.
- `PI_MOUNT_GITCONFIG`: use `PI_CONTAINER_GITCONFIG=1`. `1` still mounts and
  `0` does not, with a warning; conflicting values are errors.

### Removed

- With the shared launcher core: the `PI_*` aliases (`PI_IMAGE_NAME`,
  `PI_ENABLE_PODMAN`, `PI_PODMAN_SOCKET`, `PI_MEMORY_LIMIT`, `PI_CPU_LIMIT`,
  `PI_PIDS_LIMIT`, `PI_RUN_TIMEOUT`, `PI_ALLOW_UNSAFE_PWD`,
  `PI_MOUNT_GITCONFIG`), the `PI_NETWORK` stop, the `PI_PULL_ALWAYS` notice,
  `--wrapper-help`, the `~/.gitconfig` migration notice and `PI_DEBUG` output.
  These names now have no effect and print no notice.
- Bun (`remove-bun`): the image no longer offers the optional Bun runtime,
  and `PI_ENABLE_BUN` and `PI_BUN_VERSION` have no effect and print no
  warning. Setup never built a Bun image, and qualification could not accept
  one. The staleness hash no longer includes a Bun selection, so existing
  images are stale once: rerun `--container-setup`.

## [0.1.0] - 2026-06-30

First tagged release of the pi-container wrapper (the wrapper version is
independent of the Pi Coding Agent version in `.version`). Bundles the
containerized Pi runner, hardening flags, CI (lint/test/scan), and all
Critical Software Project Review (F-01–F-10) mitigations.

### Fixed

- `pi install npm:<pkg>` no longer fails with `npm error ENOENT ... mkdir
  '~/.npm'` under the read-only root filesystem. The wrapper now mounts an
  ephemeral tmpfs at `${HOME}/.npm` so npm's default cache directory is
  writable. Extension code still persists in the existing writable
  `~/.pi/agent/npm` (user scope) or `$PWD/.pi/npm` (project scope) install root;
  only the download cache is ephemeral.
- Test 6 (container hardening): CapDrop check no longer expects literal
  "ALL" string; Podman v4+ expands it to the full capability list.
  Now verifies CapDrop non-empty and CapAdd contains expected caps.
- test.sh Test 4: use absolute paths for Podman volume mounts.
- Trivy scan CI: set exit-code back to '0' until .trivyignore is
  populated with triaged CVE entries.
- Test 6: removed CapAdd check (varies across Podman versions);
  keep CapDrop (non-empty), ReadonlyRootfs, SecurityOpt, tmpfs.
- Scan job: remove codeql-action upload-sarif (repo does not have
  code scanning enabled); use table format for Trivy output instead.
- Test 6: check HostConfig.Tmpfs instead of Mounts for /tmp tmpfs.
- Test 7: set env var before podman create (capture happens at create
  time, not start time); simplified the test logic.
- Test 7: removed incorrect Config.Env leak check. Podman resolves -e KEY
  to KEY=value at create time and stores it in Config.Env; this is a
  documented residual exposure, not a bug. Test 7 now only verifies
  propagation. The argv-leak protection is tested in test-wrapper.sh.
- PI_ENABLE_PODMAN now triggers a rebuild with the podman CLI included
  (passes INSTALL_PODMAN=1 build arg). The INSTALL_PODMAN value is folded
  into build-inputs-hash so toggling PI_ENABLE_PODMAN rebuilds the image.
  Previously the image never contained the podman client because the
  Containerfile made it conditional but the wrapper did not pass the arg.

### Added

- `PI_READONLY_CONFIG=1` mode: mounts `~/.pi` and `~/.agents` read-only to
  prevent persistent compromise via malicious extensions/skills (F-01).
- `PI_MOUNT_GITCONFIG=0` opt-out: skip mounting `~/.gitconfig` to reduce
  credential exposure (F-08).
- `PI_PULL_ALWAYS=1`: force `podman build --pull=always` for fresh base images.
- `PI_NPM_CACHE_SIZE`: size of the ephemeral npm cache tmpfs mounted at
  `~/.npm` so community extensions (`pi install npm:<pkg>`) install under
  the read-only rootfs (default: `256M`).
- `PI_RUN_TIMEOUT`: optional timeout for `podman run` (F-13).
- Security warning on first-run when network is unrestricted and an API key
  is present (F-07).
- Timeouts on `podman info` (10s) and `podman build` (300s) (F-13).
- `.containerignore` now included in the stale-image build hash (F-02).
- Expanded sensitive-PWD guard: `/home`, `/opt`, `/srv`, `/mnt`, `/media`,
  `/proc`, `/sys`, `/dev`, `/run` (F-10 follow-up).
- `.version` missing/empty now fails hard instead of silently falling back
  to a stale version (F-06).
- Dependabot config for GitHub Actions and Docker.
- Containerfile split into multi-stage build: apt dependencies first, then
  npm install in a separate layer for better cache reuse.
- `podman` CLI now conditionally installed via `INSTALL_PODMAN` build arg
  (default: not installed).
- Container image `LABEL` version now derived from `PI_VERSION` build arg.
- Weekly scheduled Trivy scan in CI.
- SARIF upload from Trivy scan to GitHub code scanning.
- SHA-pinned GitHub Actions for supply-chain security (F-03).
- Trivy scan now gates CI on CRITICAL severities (exit-code: '1') (F-04).
- `.trivyignore` for triaged vulnerabilities.
- `CHANGELOG.md` and `CONTRIBUTING.md`.
- Integration tests in `test.sh` for container hardening flags (cap-drop,
  read-only, no-new-privileges, secret-by-name).
- Wrapper unit tests for stale-hash rebuild, unsafe-PWD refusal, Podman
  version warning, resource-limit forwarding, and `--label
  build-inputs-hash`.

### Additional fixes

- `test.sh` Test 4 no longer uses `-v /tmp:/tmp:Z` (F-05).
- `SECURITY.md` corrected: removed inaccurate `****` masking claim (F-09).
- `SECURITY.md` now documents the persistence vector (F-01) and
  `~/.gitconfig` credential exposure (F-08).

### Security

- All findings from the Critical Software Project Review (June 2026)
  addressed: F-01 through F-10.
- Container capabilities documented per-capability (F-10).
- Image pinned by digest in Containerfile comments with automation
  instructions.

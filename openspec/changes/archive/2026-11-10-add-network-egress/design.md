# Design

## Context

See `proposal.md`. The reference is `claude-container` at tag `sandbox-ref-5` (commit `3388b6e`). It is `sandbox-ref-2` plus three shared-test fixes found by the OpenCode port:
- a writable profile home in the guard test;
- API-key-only profiles in the setup test;
- nested configuration homes in the setup test.

Codex and OpenCode completed both Wave 3 changes on this tag. Their archived changes are the templates. The OpenCode port is the closest, because it also has a multi-provider agent with API-key profiles.

**Current Pi wrapper.** `pi-container.sh` (620 lines) already has the hardened baseline:
- no capabilities and no-new-privileges;
- validated and verified budgets;
- the workspace guard and the optional lifetime;
- atomic naming, bounded owned cleanup and strict engine verification.

It also has:
- `PI_CONTAINER_*` names with deprecated aliases;
- a noexec tmpfs `/pi-home` with `~/.pi` and `~/.agents` mounted (or `PI_CONTAINER_STATE_DIR`), and `PI_READONLY_CONFIG` for read-only state;
- a tmpfs npm cache and an opt-in read-only `~/.gitconfig`;
- optional Bun selected by `PI_ENABLE_BUN` and covered by the `build-inputs-hash` staleness label;
- `PI_CONTAINER_YOLO`, which only prints a warning, because Pi has no approval layer.

Ordinary networking is the default, and a raw `PI_NETWORK` value is passed to `--network`. The wrapper always forwards `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, `GOOGLE_API_KEY` and `HTTP(S)_PROXY`/`NO_PROXY` by name. It builds a missing image automatically. The default image name is `pi-container`, which is stored as `localhost/pi-container:latest`.

**Runtime image.** The base is `node:22-bookworm-slim` pinned by digest. The image installs Pi from `.version` (0.80.8) and OpenSpec 1.16.0, plus `python3`, `ca-certificates` (which brings `openssl`), `bubblewrap`, `podman` and the common toolset, and optionally Bun 1.3.14 from npm.

**Static inventory of Pi 0.80.8.**
- Agent-directory variable: `PI_CODING_AGENT_DIR`.
- Network controls: `PI_OFFLINE`, `PI_SKIP_VERSION_CHECK` (the version check is skipped when either is set), `PI_TELEMETRY`.
- Proxy handling: reads `HTTP_PROXY` and `HTTPS_PROXY`.
- Provider URLs (several dozen): `api.anthropic.com`, `api.openai.com`, `generativelanguage.googleapis.com`, `openrouter.ai`, `chatgpt.com`, `claude.ai`, gateway hosts and others.

**Tests.**
- `test-wrapper.sh` runs `tests/test_wrapper.py` with `tests/fake_podman.py`.
- `tests/run-runtime.sh` builds a disposable runner image from `tests/Containerfile.runner` (Python 3.11, Bash, Git, Podman) and runs `test_runtime.py` in it against native volume state.
- `test.sh` builds a disposable Pi image and runs the runtime suite with Bun.
- CI (`.github/workflows/ci.yml`) runs hadolint, the tests and Trivy.

## Goals / Non-Goals

**Goals:**
- `network/` and `setup/diagnostics.py` byte-identical to the reference tag (`sandbox-ref-6` after the apply finding below). Pi differences stay in `agent/`, the wrapper, the image files and the per-agent tests.
- Restricted Pi sessions behave like those of Claude, Codex and OpenCode. `unrestricted` keeps today's networking (without `PI_NETWORK`) and key forwarding.
- The Pi-specific risks are measured before the wrapper integration.

**Non-Goals:**
- Setup, the managed launcher and the parity row (all in `add-container-setup`).
- Changes to shared files. A defect is fixed in Claude first.
- OAuth and subscription profiles, gateways, cloud providers and local models.
- Authenticated checks in automated tests.

## Decisions

### Copy the reference tree from `sandbox-ref-5`

`git -C ../claude-container archive sandbox-ref-5 network setup/diagnostics.py <shared tests>`, without `test_alignment.py` and `test_setup.py`. The OpenCode `tests/test_reference_copy.py` of `add-network-egress` (agent-neutral) is reused, with the manifest moved to `sandbox-ref-5`.

### Mode variable and removal of `PI_NETWORK`

The profile's `env_prefix` is `PI_CONTAINER`, so the shared code requires `PI_CONTAINER_NETWORK`. The mode check comes first, before any other check:
- An unset or empty mode stops with a message naming the variable, its three values and `unrestricted` as the previous behavior.
- A set `PI_NETWORK`, in any mode, stops with migration guidance, as the operator decided on 2026-11-10. `none` maps to `offline`, and other values to `unrestricted`.

The raw `--network` option disappears, so a second network attachment cannot be added in any mode.

### Adopt `sandbox-ref-6` (found during apply)

The wrapper reads `.version` on every launch, but the installation manifest of `sandbox-ref-5` covered only the wrapper, `network/`, `setup/` and `agent/`. The shared qualification test therefore built an installation without `.version` (and without `Containerfile`), and five of its tests failed. As the operator decided on 2026-11-10, the fix went into Claude as `sandbox-ref-6` (commit `3150bfe`): an optional profile field `install.files` lists extra agent files. Setup installs them, the qualification identity binds them, and the shared qualification test installation copies them with `Containerfile` and `.containerignore`. Pi declares `.version`. Codex and OpenCode adopted the same tag.

### Pi agent profile

| Field | Value |
| --- | --- |
| `name` / `wrapper` | `pi-container` / `pi-container.sh` |
| `env_prefix` / `label_namespace` | `PI_CONTAINER` / `io.pi-container` |
| `identifiers` | `pi-container`, `anthropic`, `openai`, `gemini`, `openrouter` (the profile schema requires at least 3 characters; the scan result is checked in task 1.2) |
| `images` | `localhost/pi-container`, `localhost/pi-egress`, `localhost/pi-guard-toolchain` |
| `install.state_name` | `pi-egress` |
| `install.files` | `.version` (from `sandbox-ref-6`) |
| `native.home` / `command` | `/pi-home` / `pi` |
| `native.config_home` / `shared_dirs` | `.pi` / `.agents` |
| `native.config_dir_env` | `PI_CONTAINER_CONFIG_DIR` |
| `native.approval_bypass_env` | `PI_CONTAINER_YOLO` (existing; warning only) |

Authentication methods each have a single `credential_env`:

| Method | Policy profile |
| --- | --- |
| `anthropic` | `anthropic-api` |
| `openai` | `openai-api` |
| `gemini` | `gemini-api`; the variable is measured in task 2.1 (`GOOGLE_API_KEY` or `GEMINI_API_KEY`) |
| `openrouter` | `openrouter-api` |

The wrapper's default image name changes to `localhost/pi-container`. It is the same stored image, but the shared profile requires the explicit `localhost/` prefix.

### Configuration directory, following the OpenCode precedent

`PI_CODING_AGENT_DIR` names `~/.pi/agent`, not `~/.pi`, so it cannot be the profile's configuration variable. The new `PI_CONTAINER_CONFIG_DIR`:
- replaces `~/.pi` and conflicts with `PI_CONTAINER_STATE_DIR`;
- is set in every session to `/pi-home/.pi`, which the shared smoke check verifies;
- is reserved against `PI_ENV_VARS`; the host value is never forwarded.

`PI_CONTAINER_STATE_DIR` follows the OpenCode outcome:
- an empty value means shared state;
- lexical checks run before the engine;
- creation and validation run after it.

### Check order

The Claude, Codex and OpenCode order applies:
1. arguments;
2. mode, `PI_NETWORK` and delegation;
3. budgets and lifetime;
4. engine;
5. restricted platform queries;
6. state;
7. CA;
8. `session.py prepare`;
9. image operations under maintenance;
10. the immutable image ID;
11. `qualify.py check`;
12. `session.py start` and `agent-args`;
13. owned create and start;
14. `session.py stop`.

The existing Pi lifecycle code stays.

### Maintenance and staleness

Every `podman build` requires `PI_CONTAINER_MAINTENANCE=1`:
- the automatic build of a missing image;
- `--container-build`;
- a rebuild after a Bun change.

The `build-inputs-hash` label adds `network/relay.py` and `network/mux.py`. A stale image still stops with the existing `--container-build` message, which now also names the maintenance variable. Restricted launches resolve the image to its immutable ID. The qualification identity binds that ID, so the Bun choice is covered.

### Credentials and forwarding

| Mode | Provider keys | Proxy and CA variables |
| --- | --- | --- |
| Offline | none | none |
| Provider | only the profile's key, by name | none |
| Unrestricted | `ANTHROPIC_API_KEY`, `OPENAI_API_KEY` and `GOOGLE_API_KEY` as today | as today |

In offline and provider, `PI_ENV_VARS` treats these names as reserved, in both cases:
- the eight proxy variables;
- the four CA variables;
- the protected optional-traffic variables;
- `PI_CONTAINER_CONFIG_DIR`.

Other providers' keys listed there are still forwarded, because they cannot broaden the network.

### Optional traffic

The candidates are `PI_SKIP_VERSION_CHECK=1` and `PI_TELEMETRY` disabled, set after forwarding as literal values. `PI_OFFLINE=1` is used only if task 2.2 shows that it disables optional traffic without blocking model requests. Runtime package installs from npm or Bun need registries that no profile allows, so they fail; extensions are preinstalled during maintenance.

### Node proxy and CA behavior

Node 22's built-in `fetch` ignores `HTTPS_PROXY` unless the client wires a proxy agent. Pi references `HTTP_PROXY`/`HTTPS_PROXY`, so it is expected to install one. Task 2.3 measures this with the synthetic TLS fixture, covering HTTPS, server-sent event streaming and CA trust (`NODE_EXTRA_CA_CERTS`). If any transport bypasses the proxy, it fails closed and is documented. The allowlist is never broadened.

### No `--init` in restricted sessions (found during apply)

Pi launches with `--init`. Podman then bind-mounts `catatonit` at `/run/podman-init`. The guard treats that as a nested mount in its private `/run` hierarchy and stops (`nested private IPC mount validation failed`). Restricted sessions therefore omit `--init`, as Claude, Codex and OpenCode do, and the guard is the container's first process. `unrestricted` keeps `--init`.

### Tools, extensions and Bun under the guard

Task 2.4 runs the following in offline mode under the guard:
- the Pi TUI in a PTY;
- `pi -p` with a bash tool against a loopback OpenAI-compatible stub;
- the optional Bun runtime.

Unix-socket or registry dependencies are recorded and documented; the guard is never weakened. The noexec `/pi-home`, `/tmp` and `/var/tmp` and the npm cache tmpfs are checked against the guard's layout rules in task 2.5.

## Risks / Trade-offs

- **Two breaking changes at once** (mode required, `PI_NETWORK` removed). Mitigation: both messages name the replacement, and the README migration section and `CHANGELOG.md` cover them.
- **Pi's Node client bypasses the proxy for some transport.** Mitigation: that transport fails closed; the result is measured and documented; no allowlist widening.
- **Gemini and OpenRouter keys differ from today's forwarded set.** Mitigation: the measured variable names go into the profile; unrestricted forwarding is unchanged.
- **A shared-file defect appears.** Mitigation: fix it in Claude under a new tag, as for `sandbox-ref-3` to `sandbox-ref-5`.
- **The Pi tests use their own runner image.** Mitigation: the shared suites run in it if it satisfies their needs (Python 3.11, Podman remote, Git). Otherwise the runner switches to the Pi image, as OpenCode did (task 4.2).

## Migration Plan

1. To keep today's behavior, users set `PI_CONTAINER_NETWORK=unrestricted`, remove `PI_NETWORK` (`none` becomes `PI_CONTAINER_NETWORK=offline`), and add `PI_CONTAINER_MAINTENANCE=1` to commands that build.
2. Restricted use requires, in order:
   1. the operator build inputs;
   2. `PI_CONTAINER_NETWORK=offline bash ./pi-container.sh --container-qualify`;
   3. ordinary launches.

   Provider mode adds the proxy image and the profile, policy and runtime-directory variables.
3. Rollback: check out the previous `main` merge (`ef84689`).

## Open Questions

- The Gemini key variable and the semantics of the optional-traffic variables in 0.80.8 (task group 2).
- `PI_CONTAINER_YOLO` as the profile's approval variable: today it only warns. `add-container-setup` must ensure that a managed launch exporting `0` prints no warning. This affects only that change.

# Proposal

## Why

Every Pi session runs with full networking unless the operator passes a raw `PI_NETWORK` value to `podman --network`. Pi has no tool-approval layer, so a prompt-injected agent, an extension or any tool it runs can reach any host, the LAN and host services without a prompt. Codex and OpenCode already run the shared restricted-mode components of `claude-container` unchanged. This change ports the reference state (tag `sandbox-ref-5`) to Pi as the first of its two consolidated Wave 3 changes. `add-container-setup` follows with guided setup and the managed launcher.

## What Changes

- **BREAKING** `PI_CONTAINER_NETWORK` selects `offline`, `provider` or `unrestricted`.
  - An unset or empty mode stops ordinary launches before any engine call, with a message asking for an explicit mode.
  - Unknown values fail before image operations.
  - Restricted failures never fall back to unrestricted networking.

  This replaces the "default offline" note of 2026-11-08 in `todo.md`, as for Codex and OpenCode.
- **BREAKING** `PI_NETWORK` is removed, as the operator decided on 2026-11-10. When it is set, the wrapper stops before engine queries with migration guidance: `none` maps to `PI_CONTAINER_NETWORK=offline`, and other values to `unrestricted`.
- **BREAKING** Every image build requires the exact `PI_CONTAINER_MAINTENANCE=1`:
  - the automatic build of a missing image;
  - `--container-build`;
  - a Bun selection change.

  A stale image still stops with a `--container-build` message. A provider proxy image is pulled only under the same authorization and only by digest.
- **BREAKING** `PI_CONTAINER_PODMAN=1` (and the deprecated `PI_ENABLE_PODMAN=1`) is rejected in `offline` and `provider` before image or resource operations.
- The default image name becomes `localhost/pi-container`, the fully qualified name of the same local image. The shared profile requires `localhost/` image names.
- Copy `network/` and `setup/diagnostics.py` unchanged from `claude-container` `sandbox-ref-5`. The copy brings:
  - the guard;
  - the multiplexed relay and egress proxy with `tls-clienthello-sni-v2`;
  - protected policy and installation checks;
  - proxy hardening;
  - platform eligibility and local qualification;
  - the shared session helper.
- Add `agent/profile.json` and `agent/policies/default.json` with four exact API-key profiles, as the operator chose on 2026-11-10:

  | Profile | Host | Key |
  | --- | --- | --- |
  | `anthropic-api` | `api.anthropic.com:443` | `ANTHROPIC_API_KEY` |
  | `openai-api` | `api.openai.com:443` | `OPENAI_API_KEY` |
  | `gemini-api` | `generativelanguage.googleapis.com:443` | the Gemini key variable that Pi 0.80.8 reads, measured |
  | `openrouter-api` | `openrouter.ai:443` | `OPENROUTER_API_KEY` |

  Subscription and OAuth logins, cloud providers, gateways, custom base URLs and local model servers get no profile.
- Credentials and proxy settings by mode:
  - provider sessions forward only the profile's key;
  - offline sessions forward no provider key;
  - unrestricted keeps forwarding `ANTHROPIC_API_KEY`, `OPENAI_API_KEY` and `GOOGLE_API_KEY`;
  - restricted modes forward no host proxy or CA variable in either case, and `PI_ENV_VARS` cannot name them;
  - the shared helper sets the relay values and `NO_PROXY=localhost,127.0.0.1,::1`.
- In restricted modes, disable Pi's version check and telemetry with protected environment values (`PI_SKIP_VERSION_CHECK`, `PI_TELEMETRY` or `PI_OFFLINE`, as measured on 0.80.8). Runtime npm and Bun package installs stay denied.
- Add `--container-qualify` and require a current local qualification report before every ordinary `offline` or `provider` launch.
- Port opt-in host CA trust (`PI_CONTAINER_TRUST_HOST_CA`, `PI_CONTAINER_CA_BUNDLE`), with a read-only bundle at `/pi-home/ca/bundle.pem`. Restricted launches use the immutable image ID.
- State changes, applying the lessons from the OpenCode port:
  - `PI_CONTAINER_CONFIG_DIR` overrides `~/.pi`, conflicts with `PI_CONTAINER_STATE_DIR`, and is set in every session to `/pi-home/.pi`;
  - an empty `PI_CONTAINER_STATE_DIR` selects shared state;
  - isolated state is created after the engine verification, following the reference order.
- The runtime image copies `network/relay.py` and `network/mux.py`. `.containerignore` admits them, the staleness hash covers them, and `.version` must equal the policy's `tested.cli`.
- Port the shared tests, adapt the wrapper and runtime tests and the CI (hadolint and Trivy for the proxy and toolchain Containerfiles), and record real rootless evidence. Documentation covers the README, wrapper help, `SECURITY.md`, `CONTRIBUTING.md`, `CHANGELOG.md`, `AGENTS.md`, `docs/network-contract.md` and `docs/validation.md`.

Out of scope, deferred to `add-container-setup`:
- `--container-setup` and `setup/` other than `diagnostics.py`;
- the managed launcher and the setup acknowledgement;
- `docs/setup.md`;
- the missing-setup message;
- the Pi parity row.

## Capabilities

### New Capabilities

- `network-egress`: operator-selected network modes, the native guard, the multiplexed egress proxy, the protected policy and profile, the four Pi provider profiles, optional-traffic suppression, Pi tools and extensions under the guard, platform prerequisites, local qualification, owned proxy lifecycle, diagnostics and documented limits.
- `host-ca-trust`: opt-in exposure of one host CA bundle, read-only at `/pi-home/ca/bundle.pem`, with the standard CA variables.

### Modified Capabilities

- `container-session`: explicit network-mode admission, required qualification, consistent prerequisite decisions and the qualification binding of hardening settings.
- `container-launcher`:
  - help gains the network contract and `--container-qualify`;
  - every build needs maintenance authorization;
  - `PI_NETWORK` is removed and restricted forwarding is narrowed.
- `container-isolation`:
  - `PI_CONTAINER_CONFIG_DIR` and its session value;
  - isolated state checked lexically before the engine and created after it;
  - an empty `PI_CONTAINER_STATE_DIR` means shared state.
- `container-podman-access`: delegation only in explicit unrestricted mode.
- `runtime-image`:
  - `.version` matches the policy's tested CLI;
  - restricted launches use the immutable image identity;
  - proxy image acquisition needs maintenance and a digest;
  - the build context admits the relay and multiplex inputs.

## Impact

- **Code:**
  - `pi-container.sh` gains mode parsing, preflight, the `network/session.py` calls, `--container-qualify`, the state and CA changes, the maintenance gate and the restricted forwarding rules.
  - New directories: `network/` (copied), `setup/diagnostics.py`, `agent/`.
  - `Containerfile`, `.containerignore` and the staleness hash change.
- **Tests:**
  - the shared tests from Claude (except `test_alignment.py` and `test_setup.py`), plus the per-agent `tests/test_reference_copy.py`;
  - adapted `test_wrapper.py`, `fake_podman.py`, `test_runtime.py`, `test_image_pins.py` and `run-runtime.sh` modes;
  - a new `test_network_runtime.py` with `network_tls_fixture.py`;
  - the existing `test.sh` and `test-wrapper.sh`;
  - CI updates.
- **Users:**
  - existing launches must set `PI_CONTAINER_NETWORK=unrestricted` and drop `PI_NETWORK`;
  - builds need `PI_CONTAINER_MAINTENANCE=1`;
  - restricted modes need host Python 3, a same-host rootless Podman ≥ 4.9 Unix service with Netavark, Landlock ABI ≥ 3 and a passing `--container-qualify`.
- **Compatibility risks, measured before integration:**
  - whether Node 22 `fetch` in Pi honors `HTTPS_PROXY` (Node's built-in `fetch` does not by default), and how it honors CA variables;
  - the Gemini key variable;
  - the optional-traffic controls;
  - Pi, its extensions and optional Bun under the guard;
  - the noexec `/pi-home` and the npm cache tmpfs under the guard's layout checks.

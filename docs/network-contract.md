# Network policy contract

Status: ported by the `add-network-egress` and `add-container-setup` changes.

- Restricted modes are implemented and verified with synthetic and real
  rootless runtime suites.
- Guided setup and the managed launcher are described in [setup](setup.md).
- The authenticated provider checks are operator-run and recorded separately in
  [the validation record](validation.md).

The durable contract is [network-egress](../openspec/specs/network-egress/spec.md),
with [host-ca-trust](../openspec/specs/host-ca-trust/spec.md) and the session,
isolation, delegation, launcher and image specifications in `openspec/specs/`.

## Reference and intentional differences

The shared components are copied unchanged from `sandbox-container` at tag
`sandbox-ref-28` (commit `ba1ef1428a57625b70bb45d55cade5f08f46eecc`):

- `launcher/` (the shared launcher core);
- `network/` (except the build output `network/bin/`);
- `setup/`;
- the shared tests listed in that tag's `tests/test_alignment.py`.

The Pi port added three reference fixes:

- the optional profile field `install.files` (`sandbox-ref-6`), so setup and
  qualification install `.version`;
- the optional profile field `install.runtime_build` (`sandbox-ref-7`), so setup
  built the runtime image through the wrapper's build-only `--container-build`
  with Pi's build arguments and staleness label; since the shared launcher core
  every wrapper's setup builds this way and the field is gone;
- the shared setup test patching the runtime build dispatch point
  (`sandbox-ref-21`).

`tests/test_reference_copy.py` holds the SHA-256 of every copied file. It fails
on a changed, missing or extra file, or on a profile identifier
(`pi-container`, `anthropic`, `openai`, `gemini`, `openrouter`) in a copied
file. A defect in a shared file is fixed in `sandbox-container` first and then
copied; this repository never carries a fork.
[network/README.md](../network/README.md) is part of the copy and describes the
shared mechanism in agent-neutral terms.

Intentional differences are limited to per-agent files:

| File | Pi value or behavior |
| --- | --- |
| `agent/profile.json` | Identity: `pi-container`, prefix `PI_CONTAINER`, labels `io.pi-container.*`. Images: `localhost/pi-container`, `localhost/pi-egress`, `localhost/pi-guard-toolchain`. Runtime: home `/pi-home`, command `pi`. State: configuration `.pi` with override `PI_CONTAINER_CONFIG_DIR`, shared `.agents`. Approval variable `PI_CONTAINER_YOLO` (validated; a notice when enabled, because Pi has no approval layer). Four API-key methods. Installation file `.version` (`install.files`) |
| `agent/policies/default.json` | `anthropic-api`, `openai-api`, `gemini-api` and `openrouter-api`, revision `pi-2026-11-10-v1` |
| `pi-container.sh` | The thin entry script, identical to the reference's apart from the wrapper name |
| `agent/launcher.sh` | Pi's data for the shared core: `AGENT_EXEC=/usr/local/bin/pi`, `.version` as an installed build input, one credential per policy profile, protected `PI_OFFLINE=1`, `PI_SKIP_VERSION_CHECK=1` and `PI_TELEMETRY=0` in restricted sessions; hooks for the gitconfig opt-in, the npm cache tmpfs, `PI_VERSION`, the `PI_CONTAINER_YOLO` notice and the help |
| `Containerfile`, `.containerignore` | Pi image; copies `network/relay.py` and `network/mux.py`, which the staleness hash also covers |
| `tests/test_wrapper.py`, `test_runtime.py`, `test_network_runtime.py`, `network_tls_fixture.py`, `run-runtime.sh`, `Containerfile.runner`, `test_image_pins.py`, `test_reference_copy.py` | Pi names, synthetic OpenAI-compatible Chat Completions fixture, provider host inventories |

## Modes

| Mode | Agent access | Socket delegation |
| --- | --- | --- |
| unset or empty | `provider`; without the provider settings the launch stops with setup guidance before engine calls and state creation | Rejected |
| `offline` | Own loopback, pipes and connected socket pairs only | Rejected |
| `provider` | As offline, plus one preconnected channel to an exact-destination proxy | Rejected |
| `unrestricted` (explicit only) | Ordinary runtime networking | Exact opt-in allowed |

`PI_NETWORK` is rejected in every mode with migration guidance. Unknown modes
fail before image operations. Restricted failures never retry with unrestricted
networking. Pi has no tool-approval layer, so the guard and proxy are the only
enforcement. Writable `~/.pi` settings, models and auth files, extensions and
shell mode cannot broaden the outer policy. Restricted agents have no direct
route, external resolver, UDP/QUIC, host/LAN/metadata access or proxy
administration access. Every agent container, in every mode, drops all
capabilities, enables no-new-privileges and has verified memory, CPU and
process budgets.

Restricted launches follow the Claude wrapper order:

1. arguments;
2. mode, `PI_NETWORK` and delegation;
3. budgets and lifetime;
4. engine verification;
5. restricted platform queries;
6. state;
7. CA;
8. `network/session.py prepare`;
9. image operations under the maintenance gate;
10. the immutable image ID;
11. `network/qualify.py check`;
12. `session.py start` and `agent-args`;
13. owned create and start;
14. `session.py stop` within the remaining shutdown budget.

## Provider profiles

| Profile | Destination | Key | Status |
| --- | --- | --- | --- |
| `anthropic-api` | `api.anthropic.com:443` | `ANTHROPIC_API_KEY` | Measured on 1.5.2 with a dummy key |
| `openai-api` | `api.openai.com:443` | `OPENAI_API_KEY` | Measured on 1.5.2 with a dummy key |
| `gemini-api` | `generativelanguage.googleapis.com:443` | `GEMINI_API_KEY` | Measured on 1.5.2 with a dummy key |
| `openrouter-api` | `openrouter.ai:443` | `OPENROUTER_API_KEY` | Measured on 1.5.2 with a dummy key |

In provider mode the profile selects the only forwarded key; offline forwards
none. Unrestricted mode keeps forwarding `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`
and `GOOGLE_API_KEY` (Pi 1.5.2 reads `GEMINI_API_KEY` for Gemini).
Subscription and browser-callback logins, cloud providers, gateways, custom
base URLs and local model servers have no profile.

Restricted sessions set `PI_OFFLINE=1`, `PI_SKIP_VERSION_CHECK=1` and
`PI_TELEMETRY=0` after forwarding. On Pi 1.5.2, these suppressed startup
requests to `pi.dev` and GitHub in the TUI even with update checks and
telemetry enabled in the user's settings. Runtime package installs from
package registries fail. Extensions are preinstalled in unrestricted mode or
during maintenance.

MCP clients use the same destination policy as model requests. The provider
guard denied the out-of-profile host set in the user-level `mcp.json`. Pi's
MCP OAuth listener bound on the private loopback and accepted a synthetic
callback from inside the session.

## Limits

- The proxy binds the initial and retried TLS ClientHello server name
  (`tls-clienthello-sni-v2`) to the CONNECT host; TLS 1.2 renegotiation is
  encrypted and not inspected.
- It does not prove exclusive communication with the operator's provider
  account: the HTTP `Host`, shared-service routing and provider-side forwarding
  stay opaque.
- Allowed services can receive data: an injected agent can send workspace data
  to an allowed host with an attacker's key or account. Only `offline` removes
  this.
- Provider-hosted tools such as web search run outside the local boundary.
- Image pulls and build `RUN` steps happen outside runtime filtering and need
  separate maintenance authorization.
- Qualification reports are local (`locally-qualified`); the release
  acceptance inventory is empty.

## Five-wrapper parity

The same Pi row appears in `sandbox-container`, `claude-container`,
`codex-container`, `antigravity-container` and `opencode-container`.

| Wrapper | Contract adoption | Implementation | Real enforcement | Auth compatibility |
| --- | --- | --- | --- | --- |
| Sandbox (reference) | Reference (`sandbox-ref-36`, shared launcher core) | Guard, qualification and guided setup integrated; session container engine for image toolchains, with systemd in nested containers, host Podman delegation removed; Windows entry on a Podman machine (WSL provider) with installer, offline and unrestricted modes; no provider mode (no authentication method); provider mechanics covered by the fixture profile and the fixture agent part | WSL ABI 3: all runner modes passed (2026-11-22); `sandbox-ref-29` to `sandbox-ref-31` runner modes in a nested `cgroupfs` engine passed except the recorded budget and explicit-limit tests, `sandbox-ref-32` and `sandbox-ref-33` modes from a session passed except the nested-engine cases, `sandbox-ref-34` all modes from a session passed except the nested-engine cases and the tests that need cgroup limits, and its engine case passed on the machine's engine (2026-11-24), `sandbox-ref-35` all modes passed natively, the terminal tests included (2026-11-25), `sandbox-ref-36` the unit discovery, default, network, qualification, setup and setup runtime modes passed natively, the terminal tests included, and the engine started without a capability error (2026-11-26); Podman machine on Windows: validation script passed on both PowerShell editions (2026-11-21) and on 5.1 with the session engine (2026-11-24), nested systemd: runtime and qualification modes passed on the machine's engine (2026-11-26); native Linux (Rocky 9, Podman 5.8.0, `systemd` with `memory` and `pids`, no IPv6): `sandbox-ref-34` engine budgets and offline engine sessions verified, `sandbox-ref-35` every mode passed with the guarded terminal tests unavailable, and a terminal attached in an interactive session (2026-11-25), `sandbox-ref-36` the same modes as on WSL passed with the guarded terminal tests unavailable, and an unrestricted session started its engine without a capability error (2026-11-26) | Not applicable |
| Claude | Adopted `sandbox-ref-36`: shared launcher core | Shared launcher core, mandatory bootstrap, multiplexed proxy and guided setup integrated; session container engine for image toolchains, with systemd in nested containers, host Podman delegation removed; Windows entry on a Podman machine (WSL provider) with installer and every network mode | WSL ABI 3: all runner modes passed on `sandbox-ref-28` (2026-11-22); `sandbox-ref-34` modes from a Claude session with its engine passed except the nested-engine cases and the tests that need cgroup limits, and the engine and setup runtime cases passed on the machine's engine (2026-11-25), `sandbox-ref-35` unit discovery, guard, network, feasibility and setup runtime modes passed natively, the terminal tests included, with the interrupted-creation case passing alone after timeouts in the full network run (2026-11-25), and `sandbox-ref-36` unit tests of the changed files, setup, setup runtime, qualification and wrapper modes and the engine cases of the runtime and network suites passed natively, the other modes not rerun (2026-11-26); Podman machine on Windows: setup, account login, a Claude session and the validation script on both PowerShell editions passed (2026-11-22), and the validation script on 5.1 with the session engine (2026-11-24); native Linux (Rocky 9, Podman 5.8.0, `systemd` with `memory` and `pids`, no IPv6): `sandbox-ref-35` unit discovery, guard, network, feasibility and setup runtime modes passed with the guarded terminal tests unavailable, and a terminal attached in an interactive session (2026-11-25) | Account login, reuse and refresh passed; operator session with tool use passed (2026-11-11, `anthropic-account`); real-key API unavailable |
| Codex | Adopted `sandbox-ref-36`: shared launcher core | Shared launcher core, guard, multiplexed proxy, qualification and guided setup integrated; session container engine for image toolchains, with systemd in nested containers, host Podman delegation removed; Windows entry on a Podman machine (WSL provider) with installer and every network mode | WSL ABI 3: all runner modes passed on `sandbox-ref-28` (2026-11-22), and on `sandbox-ref-36` natively, the terminal tests and the engine cases included, with the shared and wrapper modes passing on a rerun after timing failures under load (2026-11-26); Podman machine on Windows: setup, device-code login, a Codex session, Codex's own sandbox in `unrestricted` and the validation script on both PowerShell editions passed (2026-11-22), the `sandbox-ref-36` smoke test pending (release risk) | Operator session with tool use passed (2026-11-11, `openai-account`; 2026-11-22 on Windows); refresh and real-key API checks pending; synthetic Responses API streaming and tool call passed |
| Antigravity | Adopted `sandbox-ref-36`: shared launcher core | Shared launcher core, guard, multiplexed proxy, qualification and guided setup integrated; private session engine for image toolchains with nested systemd; host delegation removed; keyring removed; Windows entry on a Podman machine (WSL provider) with installer and every network mode | WSL ABI 3: all runner modes passed on `sandbox-ref-28` (2026-11-23); Podman machine on Windows: setup, Google sign-in, an `agy` session with tool use, token reuse, the Gemini API key method with a dummy key and the validation script on both PowerShell editions passed (2026-11-23); `sandbox-ref-36` shared manifest, migration preflight and local synthetic suites recorded in the validation log, production checks scheduled after closure | Operator session with tool use passed (2026-11-11, `google-account`, policy `antigravity-2026-11-11-v2`; 2026-11-23 on Windows); refresh and real-key Gemini API checks pending; synthetic Gemini streaming and tool call passed |
| OpenCode | Adopted `sandbox-ref-36`: shared launcher core | Shared launcher core, guard, multiplexed proxy, qualification and guided setup integrated; private session container engine for image toolchains with nested systemd, host Podman delegation removed; Windows entry on a Podman machine (WSL provider) with installer and every network mode | WSL ABI 3: all runner modes passed on `sandbox-ref-28` (2026-11-23); Podman machine on Windows: setup, an OpenCode session with tool use (`openrouter-api`), native variables through `OPENCODE_CONTAINER_ENV_VARS` and the validation script on both PowerShell editions passed (2026-11-23); `sandbox-ref-36` shared manifest, alignment, static checks, OpenSpec merge preview and full non-runtime synthetic suites passed in the working session (2026-11-27), production WSL/Linux and Windows checks scheduled after closure | Operator session with tool use passed (2026-11-11, `anthropic-api`; 2026-11-23 on Windows, `openrouter-api`); the `openai-api` and `opencode-zen` profiles pending; synthetic Chat Completions streaming and tool call passed |
| Pi | Adopted `sandbox-ref-28`: shared launcher core | Shared launcher core, guard, multiplexed proxy, qualification and guided setup integrated; Windows entry on a Podman machine (WSL provider) with installer and every network mode, no delegation | WSL ABI 3: all runner modes passed on `sandbox-ref-28` (2026-11-23); Podman machine on Windows: setup, a Pi session with tool use (`openrouter-api`), `PI_NPM_CACHE_SIZE` through `PI_CONTAINER_ENV_VARS` and the validation script on both PowerShell editions passed (2026-11-23) | Operator session with tool use passed (2026-11-11, `anthropic-api`; 2026-11-23 on Windows, `openrouter-api`); the `openai-api` and `gemini-api` profiles pending; synthetic Chat Completions streaming and tool call passed |

## Port status

| Item | Status |
| --- | --- |
| Shared copy and identifier scan | Done (`tests/test_reference_copy.py`) |
| Shared suites, guard, mux, policy, feasibility, qualification | Passed in the runner; see [validation](validation.md) |
| Wrapper integration and restricted runtime acceptance | Passed; see [validation](validation.md) |
| Authenticated provider checks | Operator-run, pending |
| Shared setup suite and alignment | Passed (`tests/test_setup.py`, `tests/test_alignment.py`) |
| Guided setup acceptance | Passed; see [validation](validation.md) |

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

The shared components are copied unchanged from `claude-container` at tag
`sandbox-ref-10` (commit `0f6585f0973250a57398c0b187da4c99d2bfd09f`):

- `network/` (except the build output `network/bin/`);
- `setup/`;
- the shared tests listed in that tag's `tests/test_alignment.py`.

The Pi port added three reference fixes:

- the optional profile field `install.files` (`sandbox-ref-6`), so setup and
  qualification install `.version`;
- the optional profile field `install.runtime_build` (`sandbox-ref-7`), so setup
  builds the runtime image through the wrapper's build-only `--container-build`
  with Pi's build arguments and staleness label;
- the shared setup test patching the runtime build dispatch point
  (`sandbox-ref-10`).

`tests/test_reference_copy.py` holds the SHA-256 of every copied file. It fails
on a changed, missing or extra file, or on a profile identifier
(`pi-container`, `anthropic`, `openai`, `gemini`, `openrouter`) in a copied
file. A defect in a shared file is fixed in `claude-container` first and then
copied; this repository never carries a fork.
[network/README.md](../network/README.md) is part of the copy and describes the
shared mechanism in agent-neutral terms.

Intentional differences are limited to per-agent files:

| File | Pi value or behavior |
| --- | --- |
| `agent/profile.json` | Identity: `pi-container`, prefix `PI_CONTAINER`, labels `io.pi-container.*`. Images: `localhost/pi-container`, `localhost/pi-egress`, `localhost/pi-guard-toolchain`. Runtime: home `/pi-home`, command `pi`. State: configuration `.pi` with override `PI_CONTAINER_CONFIG_DIR`, shared `.agents`. Approval variable `PI_CONTAINER_YOLO` (validated; warns when enabled, because Pi has no approval layer). Four API-key methods. Installation file `.version` (`install.files`); runtime built through the wrapper (`install.runtime_build`) |
| `agent/policies/default.json` | `anthropic-api`, `openai-api`, `gemini-api` and `openrouter-api`, revision `pi-2026-11-10-v1` |
| `pi-container.sh` | Pi arguments, shared or isolated state, noexec `/pi-home` with the npm cache tmpfs, read-only state mode, removed `PI_NETWORK`, protected `PI_OFFLINE`, `PI_SKIP_VERSION_CHECK` and `PI_TELEMETRY` values, profile-selected key, no host proxy or CA variables in restricted modes, build-only `--container-build`, `--container-setup` and the `setup required:` message, diagnostics filter |
| `Containerfile`, `.containerignore` | Pi image with optional Bun; copies `network/relay.py` and `network/mux.py`, which the staleness hash also covers |
| `tests/test_wrapper.py`, `fake_podman.py`, `test_runtime.py`, `test_network_runtime.py`, `network_tls_fixture.py`, `run-runtime.sh`, `Containerfile.runner`, `test_image_pins.py`, `test_reference_copy.py` | Pi names, synthetic OpenAI-compatible Chat Completions fixture, provider host inventories |

## Modes

| Mode | Agent access | Socket delegation |
| --- | --- | --- |
| unset or empty | Launch stops before engine calls and state creation | No session |
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
| `anthropic-api` | `api.anthropic.com:443` | `ANTHROPIC_API_KEY` | Measured on 0.80.8; real key unverified |
| `openai-api` | `api.openai.com:443` | `OPENAI_API_KEY` | Measured on 0.80.8; real key unverified |
| `gemini-api` | `generativelanguage.googleapis.com:443` | `GEMINI_API_KEY` | Measured on 0.80.8; real key unverified |
| `openrouter-api` | `openrouter.ai:443` | `OPENROUTER_API_KEY` | Measured on 0.80.8; real key unverified |

In provider mode the profile selects the only forwarded key; offline forwards
none. Unrestricted mode keeps forwarding `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`
and `GOOGLE_API_KEY` (Pi 0.80.8 reads `GEMINI_API_KEY` for Gemini).
Subscription and browser-callback logins, cloud providers, gateways, custom
base URLs and local model servers have no profile.

Restricted sessions set `PI_OFFLINE=1`, `PI_SKIP_VERSION_CHECK=1` and
`PI_TELEMETRY=0` after forwarding. On 0.80.8 these remove the startup request
to `pi.dev` (version check and install telemetry), and a writable
`~/.pi/agent/settings.json` cannot re-enable it. Runtime package installs from
npm or Bun registries fail; extensions are preinstalled in unrestricted mode or
during maintenance.

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

The same Pi row appears in `claude-container`, `codex-container` and
`opencode-container`.

| Wrapper | Contract adoption | Implementation | Real enforcement | Auth compatibility |
| --- | --- | --- | --- | --- |
| Claude | Reference (`sandbox-ref-10`) | Mandatory bootstrap, multiplexed proxy and guided setup integrated | See the Claude validation record | Account login, reuse and refresh passed; operator session with tool use passed (2026-11-11, `anthropic-account`); real-key API unavailable |
| Codex | Ported from `sandbox-ref-10`; shared files unchanged | Guard, multiplexed proxy, qualification and guided setup integrated | WSL ABI 3: all runtime modes and setup acceptance passed (2026-11-09) | Operator session with tool use passed (2026-11-11, `openai-account`); refresh and API-key checks pending; synthetic Responses API streaming and tool call passed |
| Antigravity | Ported from `sandbox-ref-10`; shared files unchanged | Guard, multiplexed proxy, qualification and guided setup integrated; keyring removed | WSL ABI 3: all runtime modes and setup acceptance passed (2026-11-10) | Operator session with tool use passed (2026-11-11, `google-account`, policy `antigravity-2026-11-11-v2`); refresh and Gemini API-key checks pending; synthetic Gemini streaming and tool call passed |
| OpenCode | Ported from `sandbox-ref-10`; shared files unchanged | Guard, multiplexed proxy, qualification and guided setup integrated | WSL ABI 3: all runtime modes and setup acceptance passed (2026-11-10) | Operator session with tool use passed (2026-11-11, `anthropic-api`); the other three profiles pending; synthetic Chat Completions streaming and tool call passed |
| Pi | Ported from `sandbox-ref-10`; shared files unchanged | Guard, multiplexed proxy, qualification and guided setup integrated | WSL ABI 3: all runtime modes and setup acceptance passed (2026-11-10) | Operator session with tool use passed (2026-11-11, `anthropic-api`); the other three profiles pending; synthetic Chat Completions streaming and tool call passed |

## Port status

| Item | Status |
| --- | --- |
| Shared copy and identifier scan | Done (`tests/test_reference_copy.py`) |
| Shared suites, guard, mux, policy, feasibility, qualification | Passed in the runner; see [validation](validation.md) |
| Wrapper integration and restricted runtime acceptance | Passed; see [validation](validation.md) |
| Authenticated provider checks | Operator-run, pending |
| Shared setup suite and alignment | Passed (`tests/test_setup.py`, `tests/test_alignment.py`) |
| Guided setup acceptance | Passed; see [validation](validation.md) |

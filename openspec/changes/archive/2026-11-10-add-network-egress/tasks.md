# Tasks

## 1. Copy the shared components from `sandbox-ref-5`

- [x] 1.1 Create branch `add-network-egress` from `main`. Use `git -C ../claude-container archive sandbox-ref-5` to unpack:
  - `network/`, without `bin/` and `__pycache__`;
  - `setup/diagnostics.py`;
  - the shared tests listed in that tag's `tests/test_alignment.py`, except `test_alignment.py` and `test_setup.py`.

  Verify with `diff -r` against the tag tree: no differences.
- [x] 1.2 Add `tests/test_reference_copy.py`, reusing the agent-neutral OpenCode version with the manifest moved to `sandbox-ref-5`. Check that `pi-container`, `anthropic`, `openai`, `gemini` and `openrouter` occur in no shared file; drop and record any that do. Verify that the test passes, and that it fails on an injected byte change and on an injected identifier.

## 2. Measure the Pi-specific unknowns

- [x] 2.1 Build a static and credential-free inventory of Pi 0.80.8 in the image. Record in `docs/validation.md`:
  - the four provider hosts and the key variable for each (in particular Gemini: `GOOGLE_API_KEY` or `GEMINI_API_KEY`);
  - the version-check, telemetry and share hosts;
  - which `/login` methods need a browser callback.

  Confirm the hosts with logging-proxy runs of `pi -p` with dummy keys.
- [x] 2.2 Measure `PI_SKIP_VERSION_CHECK`, `PI_TELEMETRY` and `PI_OFFLINE` against a logging proxy:
  - which requests each suppresses;
  - whether `PI_OFFLINE` blocks model requests;
  - whether writable `~/.pi` settings can re-enable them.

  Record the chosen protected values.
- [x] 2.3 With the synthetic TLS fixture (a `CA:FALSE`, `serverAuth` leaf certificate) and a local CONNECT proxy, check whether Pi on Node honors:
  - `HTTPS_PROXY`/`https_proxy` and the loopback `NO_PROXY` for HTTPS and server-sent event streaming;
  - `NODE_EXTRA_CA_CERTS` and/or `SSL_CERT_FILE` for trust.

  Record any transport that bypasses the proxy, which must fail closed.
- [x] 2.4 Build the guard (task 3.2), then run in offline mode under the guard, with `--cap-drop=all` and no-new-privileges:
  - the Pi TUI in a PTY;
  - `pi -p` with a bash tool against a loopback OpenAI-compatible stub;
  - with a Bun image, a Bun command.

  Record the Unix-socket, registry or `bwrap` dependencies and the documented outcome.
- [x] 2.5 Run the guard runtime fixtures with Pi's layout: noexec `/pi-home`, `/tmp` and `/var/tmp`, the npm cache tmpfs and the `.pi`/`.agents` binds. Verify that layout validation passes. If it fails, stop and fix the shared code in Claude first.

## 3. Agent profile, policy and operator artifacts

- [x] 3.1 Write `agent/profile.json` from design.md, with the credential variables measured in task 2.1. Write `agent/policies/default.json` with:
  - `anthropic-api`, `openai-api`, `gemini-api` and `openrouter-api`;
  - revision `pi-2026-11-10-v1`, `source_date` and `sources`;
  - `tested.cli` `0.80.8`, with authentication marked unverified.

  Verify the profile query, the policy against the profile rules, and `tests/test_agent_profile.py` and `tests/test_network_policy.py`.
- [x] 3.2 Tag or build `localhost/pi-guard-toolchain:development` from `network/guard-build.Containerfile`. Package the guard with `PI_CONTAINER_MAINTENANCE=1 bash network/build-guard.sh` into a native directory. Build `localhost/pi-egress` from `network/Containerfile`. Verify that the guard SHA-256 equals the Claude, Codex and OpenCode guard, and that the guard runtime mode passes.
- [x] 3.3 Run the copied shared suites. They must all pass without edits to shared files.

## 4. Runtime image, staleness and test runner

- [x] 4.1 Add `COPY network/relay.py network/mux.py /opt/sandbox-egress/` to `Containerfile`, and admit only these two files in addition to the existing inputs in `.containerignore`. Add both files to the `build-inputs-hash` computation in the wrapper and `test.sh`. Extend `tests/test_image_pins.py` so that `.version` must equal the policy's `tested.cli`. Verify:
  - the pin tests, including an injected divergence;
  - the five-file build-context probe;
  - a rebuilt image whose `pi --version` reports 0.80.8, without and with Bun.
- [x] 4.2 Extend `tests/run-runtime.sh` with the Codex and OpenCode mode set:
  - `--wrapper` and `--shared`;
  - `--network-feasibility`, `--network-policy`, `--network`, `--mux`, `--guard`, `--guard-idle` and `--qualification`;
  - the default runtime mode.

  Run the suites in the existing runner image if it satisfies them; otherwise use the Pi image, as OpenCode does. Keep `test.sh` and `test-wrapper.sh` working. Verify that each mode starts and reports its suite.

## 5. Wrapper integration

- [x] 5.1 Mode admission:
  - parse `PI_CONTAINER_NETWORK`; an unset or empty value stops before engine calls, naming the three values and `unrestricted` as the previous behavior;
  - unknown values fail;
  - a set `PI_NETWORK` stops with migration guidance in every mode;
  - `PI_CONTAINER_PODMAN=1` and `PI_ENABLE_PODMAN=1` are rejected in restricted modes;
  - help gains the new options, variables, migration notes and the provider disclosure.

  Verify with `test_wrapper.py` cases across Pi, shell, build, worktree and the deprecated aliases.
- [x] 5.2 Maintenance gate: the automatic build, `--container-build` and Bun changes require the exact `PI_CONTAINER_MAINTENANCE=1`. A stale image keeps its message, which also names the variable. Restricted preconditions are checked before image operations. The default image becomes `localhost/pi-container`. Verify with fake-engine cases for:
  - present, absent and stale images;
  - an explicit build, with and without authorization;
  - an inspection error;
  - an invalid policy.
- [x] 5.3 State and CA:
  - the `PI_CONTAINER_CONFIG_DIR` override and its session value;
  - the conflict with `PI_CONTAINER_STATE_DIR`;
  - empty `PI_CONTAINER_STATE_DIR` as shared state;
  - lexical checks before the engine and creation after it;
  - `PI_CONTAINER_TRUST_HOST_CA` and `PI_CONTAINER_CA_BUNDLE`, giving a read-only `/pi-home/ca/bundle.pem` plus the four variables, with the private `ca` parent in writable isolated state;
  - the interaction with `PI_READONLY_CONFIG`.

  Verify with `test_wrapper.py` cases.
- [x] 5.4 Restricted forwarding:
  - no host proxy or CA variables;
  - the network names reserved in `PI_ENV_VARS`;
  - offline forwards no provider key;
  - provider forwards only the profile's key;
  - the protected optional-traffic values (task 2.2) follow forwarding.

  Unrestricted forwarding is unchanged. Verify with `test_wrapper.py` cases for every profile.
- [x] 5.5 Restricted preparation, in the reference order:
  1. platform queries;
  2. `session.py prepare` with the workspace, the `.pi` and `.agents` sources (or the state directory) and `/pi-home`;
  3. the immutable image ID;
  4. proxy image acquisition under maintenance and by digest;
  5. `qualify.py check`;
  6. `session.py start`, `agent-args` and container creation;
  7. `session.py stop` within the remaining budget.

  The guard replaces the `pi` entrypoint. Verify with fake-engine cases for order, arguments, interrupted start, exit status and owned cleanup.
- [x] 5.6 Add `--container-qualify` (alone) and `--container-qualify-probe` using `network/qualify.py`. Verify with fake-engine cases and `tests/test_qualification.py`.
- [x] 5.7 Unrestricted regression: the existing `test_wrapper.py`, `test_runtime.py`, `test.sh` and `test-wrapper.sh` cases pass, apart from the added mode and maintenance variables, the removed `PI_NETWORK` and the image name.

## 6. Runtime acceptance with real rootless Podman

- [x] 6.1 Add `tests/test_network_runtime.py` and `tests/network_tls_fixture.py`, adapted from OpenCode, with Pi names, controlled profiles for the four base profiles and a synthetic OpenAI-compatible streaming endpoint. Verify that every runner mode passes on the WSL target.
- [x] 6.2 Offline acceptance through `pi-container.sh` after `--container-qualify`:
  - IPv4, IPv6, DNS and UDP egress and host and abstract sockets are denied;
  - loopback and connected pairs work;
  - file ownership is preserved;
  - the Pi TUI starts and quits in a PTY.
- [x] 6.3 Provider acceptance with controlled fixtures:
  - matching CONNECT and SNI pass, and mismatched SNI is rejected;
  - denied authority, redirect, IP-literal and deceptive-suffix requests fail;
  - proxy loss fails closed;
  - CA trust off and on behave as specified;
  - the proxy budgets and hardening are verified;
  - a real `pi -p` run against the synthetic endpoint streams a response and executes a bash tool through the relay.
- [x] 6.4 Concurrency and cleanup: run two concurrent Pi provider sessions with different policies and check that ownership is distinct. Afterward nothing labeled `io.pi-container` remains. Pre-existing containers are untouched.

## 7. CI, documentation and evidence

- [x] 7.1 Extend `.github/workflows/ci.yml`:
  - hadolint for `network/Containerfile` and `network/guard-build.Containerfile`;
  - the credential-free shared suites and wrapper tests;
  - Trivy for the proxy image, if feasible.

  Verify with a local hadolint run and a YAML syntax check.
- [x] 7.2 Update the README with:
  - modes and migration (`PI_NETWORK` removal, maintenance, image name);
  - the prerequisites and `--container-qualify`;
  - the operator build inputs;
  - the four profiles and the credential rules;
  - the residual exfiltration disclosure;
  - the qualification behaviors;
  - the unsupported OAuth logins;
  - tool and extension compatibility.

  Update the wrapper help, `SECURITY.md`, `CONTRIBUTING.md`, `CHANGELOG.md` and `AGENTS.md`. Add `docs/network-contract.md`, modeled on OpenCode. Verify with markdownlint and `git diff --check`.
- [x] 7.3 Record in `docs/validation.md`:
  - the target, Podman version, guard digest, image IDs and results by mode;
  - the measurements from task group 2;
  - the operator-run authenticated checks, marked unavailable.
- [x] 7.4 Final verification:
  - `bash -n` and ShellCheck;
  - all runner modes, `test.sh` and `test-wrapper.sh`;
  - `openspec validate add-network-egress --strict`;
  - `git diff --check`.

  Update `todo.md` (N01–N14, C01–C10, C12, C14) with status and evidence.

## Workflow follow-up

- Operator-run authenticated checks for the four profiles.
- `/opsx:archive`, then commit and merge into `main`; the user pushes.
- Next change: `add-container-setup` for Pi (C11, the parity row, `PI_CONTAINER_YOLO` under managed launches).

# Design

## Context

See `proposal.md`. The reference is `claude-container` at tag `sandbox-ref-6` (commit `3150bfe`); this change moves it to `sandbox-ref-7`. `add-network-egress` (merged as `362ff85`) copied `network/`, `setup/diagnostics.py` and the shared tests except `test_setup.py` and `test_alignment.py`, and integrated the restricted modes into `pi-container.sh`. Codex and OpenCode completed the same step; OpenCode's archived `add-container-setup` is the template, because OpenCode also has only API-key methods.

**Observed in the reference.**

`setup/` takes every agent value from `agent/profile.json`. `setup.py`:
- proposes the first method of the profile as the default, which is `anthropic` here, and reports `Authentication pending. Supply <credential_env>` for API-key methods;
- asks `Enable pi-container permission bypass (YOLO)?` and saves `PI_CONTAINER_YOLO=0` or `1` for the managed launcher;
- prepares the runtime image in `prepare_artifacts`:
  - an existing image is retagged with `podman tag`, which keeps its labels;
  - otherwise `build_image(release, 'Containerfile', candidate_tag, maintenance)` runs `podman build --pull=never --tag <candidate> --file Containerfile <release>` with no build arguments;
- drives the wrapper through `--container-qualify`, `--container-shell` (the smoke check) and `--container-git-worktree`;
- installs a managed dispatcher that calls `setup/launch.py`, which validates `setup.json`, exports the saved variables and execs the installed wrapper.

`tests/test_setup.py` runs the real wrapper. It checks:
- `--container-setup` admission and help precedence;
- the `setup required:` message;
- managed launches;
- the diagnostics filter;
- a few literal wrapper messages.

**Observed in Pi.**

The Pi `Containerfile` declares:
- `ARG PI_VERSION` with no default, so `npm install` of an empty version fails or installs the wrong one;
- `ARG INSTALL_BUN=0`.

The wrapper:
- computes `build-inputs-hash` over `Containerfile`, `.containerignore`, `.version`, `network/relay.py`, `network/mux.py` and the Bun choice;
- stops every launch whose image label differs, with the stale-image message.

A plain `podman build` therefore yields an image the wrapper refuses.

`PI_CONTAINER_YOLO` currently prints a warning for any nonempty value, so the `0` saved by setup would warn on every managed launch.

The wrapper already has:
- the session helper calls;
- the `io.pi-container.session` label;
- empty-equals-unset `PI_CONTAINER_STATE_DIR`;
- `PI_CONTAINER_CONFIG_DIR` set in the session.

It does not yet:
- accept `--container-setup`;
- print `setup required:`;
- filter stderr.

`--container-build` today always continues into a launch.

## Goals / Non-Goals

**Goals:**
- `network/`, `setup/` and every shared test byte-identical to `sandbox-ref-7`. Unchanged `test_alignment.py` and `test_setup.py` pass against the Pi wrapper.
- A setup-built Pi image passes the wrapper's staleness check.
- Guided setup produces a working managed launcher in all three modes, with qualification and the smoke check passing on the WSL target.
- The Pi parity row is identical in the four ported repositories.

**Non-Goals:**
- Authenticated provider verification, which stays operator-run.
- A real Pi YOLO implementation; Pi has no approval layer to bypass.
- A Bun question in setup.
- Enabling real systemd user services in tests.
- The Antigravity port.

## Decisions

### Shared fix first: `install.runtime_build` (`sandbox-ref-7`)

The operator chose a shared fix on 2026-11-10. In `claude-container`, `network/agent_profile.py` accepts an optional `install.runtime_build`, either `recipe` (the default) or `wrapper`. `setup/setup.py` gets one dispatch point for the runtime image only:
- **`recipe`:** today's `build_image(release, 'Containerfile', …)`.
- **`wrapper`:** `run(['bash', release/PROFILE.wrapper, '--container-build'], maintenance | {<prefix>_NETWORK: 'unrestricted', <prefix>_IMAGE: candidate_tag})`, followed by `image_identity(candidate_tag)`. A missing identity raises the same `Built image is unavailable after preparation.` error.

The wrapper invocation uses the installed release, not the checkout, so the build inputs are the ones qualification binds. `unrestricted` is passed only because the wrapper requires an explicit mode before any image operation; a build-only invocation starts no session, so the mode grants nothing. The wrapper acquires the base image itself during its build, which the setup maintenance review already discloses.

The toolchain and proxy images keep the recipe path; they are agent-neutral.

`tests/test_setup.py` gains a case with a scratch profile declaring `wrapper` and a fake wrapper that records its arguments and environment. It checks the exact command, the maintenance and image variables, and the identity inspection. `tests/test_agent_profile.py` gains the invalid values. Claude, Codex and OpenCode declare nothing, so their behavior is unchanged; `--setup` and `--shared` must still pass in all three.

The steps are:
1. Merge in Claude and create the tag `sandbox-ref-7`.
2. Adopt it in Codex and OpenCode: manifest, references, `--shared`, `--setup` and `--qualification`.
3. Copy it here.

Rejected alternatives:
- **Profile-declared build arguments and labels.** The hash label is computed from agent files by agent code, and it would duplicate the wrapper's logic in shared code.
- **A Pi-only acceptance of unlabeled images.** It weakens the staleness check.

### A shared-test fix found during apply (`sandbox-ref-8`)

Running the shared `tests/test_setup.py` against Pi showed that `test_fresh_and_refresh_builds_keep_previous_runtime_tag` patched `build_image`, which `prepare_artifacts` reaches only through the default `recipe` path since `sandbox-ref-7`. With Pi's `wrapper` value the patch was never called. The test now patches the dispatch point `build_runtime`. No setup code changed. The fix went into Claude as `sandbox-ref-8` (commit `12cffab`), Codex and OpenCode adopted it, and this change copies from `sandbox-ref-8`.

The same run showed one wrapper message mismatch: the engine-query failure now uses the shared wording `cannot query Podman or invalid engine response; ...`.

### Pi build-only entry point

`--container-build` used alone (no Pi arguments, no other `--container-*` option) becomes a build-only operation. It keeps the reference check order up to image operations:
1. arguments;
2. mode, `PI_NETWORK` and delegation;
3. budgets;
4. engine verification;
5. the maintenance gate.

Then it builds with the existing `--build-arg PI_VERSION`, `INSTALL_BUN` and `--label build-inputs-hash` arguments and exits 0. It does not create state, a session or restricted preflight resources. Combined with arguments or `--container-shell`, it keeps today's refresh-then-launch behavior. The profile declares `"runtime_build": "wrapper"` under `install`.

### YOLO treated as a supported switch with a warning

The operator decided on 2026-11-10 that the variable behaves as if Pi supported YOLO, with a warning. `PI_CONTAINER_YOLO` is parsed like `OPENCODE_CONTAINER_YOLO`:
- `1`, `true` and `yes` enable it;
- `0`, `false` and `no` disable it;
- an empty or unset value means disabled;
- anything else fails with status 1 before engine queries.

Enabled prints one warning: `PI_CONTAINER_YOLO has no effect yet: Pi 0.80.8 has no tool-approval layer and the container is the only boundary`. Disabled is silent. Engine arguments never change.

Setup keeps the shared question. Its help text names permission bypass generically, and the README explains that for Pi it is reserved for a future approval layer. If a later Pi release adds an approval-bypass flag, the wrapper can map the enabled value to it without changing setup.

### Copy the remaining setup files and tests from the tag

`git -C ../claude-container archive sandbox-ref-7 network setup tests/<shared>`, unpacked over the checkout, including `tests/test_setup.py` and `tests/test_alignment.py`. `tests/test_reference_copy.py` extends its manifest to the new files and moves to `sandbox-ref-7`. The file is the agent-neutral OpenCode version; its own identifier scan stays next to `test_alignment.py`, as in OpenCode.

### Wrapper entry points follow the reference wrappers

- `--container-setup` is handled after help and qualification. It must be used alone, needs a terminal on stdin and stdout and host Python 3, and then `exec`s `python3 -I setup/setup.py`.
- The missing-mode message becomes `setup required: run bash <wrapper> --container-setup; use the managed launcher afterward or explicitly set PI_CONTAINER_NETWORK for an operator workflow (offline, provider, or unrestricted; unrestricted keeps the previous networking behavior)`, with the wrapper path quoted by `printf %q`.
- The attached client's stderr goes through `setup/diagnostics.py` on a FIFO in the private session directory. It is reaped within a one-second drain inside the `shutdown` budget, as in OpenCode.
- Messages that the shared tests check literally are aligned to the reference wording. Any mismatch found in task 3.3 is resolved in the wrapper; a mismatch caused by shared code goes to Claude.

### Authentication is API-key only

Setup offers `anthropic`, `openai`, `gemini` and `openrouter`, each mapped to its protected profile. After the sandbox is ready it reports `Authentication pending` naming the variable (`GEMINI_API_KEY` for Gemini). It makes no model call and stores no key. Keys stored by Pi's `/login` or in `~/.pi/agent/auth.json` keep working at runtime, but setup does not drive them.

### Parity table

`docs/network-contract.md` gets the five-wrapper table copied from Claude, with the Pi row:
- contract adoption: ported from `sandbox-ref-7`, shared files unchanged;
- implementation: guard, multiplexed proxy, qualification and guided setup integrated;
- real enforcement: WSL ABI 3, all runtime modes and setup acceptance passed (with the date);
- authentication: pending operator API-key checks for the four profiles; synthetic Chat Completions streaming and tool call passed.

The same row replaces "Pending (profile-based port planned)" in `claude-container`, `codex-container` and `opencode-container`. The Claude, Codex and OpenCode rows move to `sandbox-ref-7` in their own repositories during adoption.

### Setup runtime acceptance

`tests/test_setup_runtime.py` is ported from OpenCode with Pi names: `PI_CONTAINER_IMAGE`, `localhost/pi-container:latest`, `pi-container`, and `--version` printing `0.80.8`. It runs setup under a pseudo-terminal against the real same-host service, with:
- a disposable `HOME`, installation and command path;
- a disposable proxy image;
- prepared runtime images routed by tag lookups.

It adds one case with no reusable runtime image, so the build goes through the wrapper and the managed launch then passes the staleness check. It does not enable systemd services, read real credentials or send model requests.

## Risks / Trade-offs

- **Shared setup gains an agent-selected code path.** Mitigation: a single dispatch point; the default is unchanged, and the Claude, Codex and OpenCode suites run before the tag is used.
- **The setup build runs the wrapper with `unrestricted`.** Mitigation: the build-only path creates no container; the build itself is host maintenance, which runtime filtering never covered and which setup discloses.
- **A stale reusable image.** If `localhost/pi-container:latest` predates the current inputs, setup retags it and the smoke check stops it as stale. Mitigation: the stop is fail-closed, and the README tells the operator to rerun setup with refresh.
- **Invalid `PI_CONTAINER_YOLO` values now fail.** Mitigation: documented in `CHANGELOG.md`; the accepted set matches the other wrappers.
- **The diagnostics FIFO changes stderr buffering.** Mitigation: the design is measured in the three other wrappers, and the Pi TTY, pipe and signal tests are rerun, including the TUI in a PTY.

## Migration Plan

1. New users run `bash ./pi-container.sh --container-setup`, then use `~/.local/bin/pi-container`.
2. Direct invocations keep working with an explicit `PI_CONTAINER_NETWORK`. Without one, they get the setup-required message.
3. Rollback:
   - setup keeps the last working release and restores it on failed activation;
   - at the repository level, check out `362ff85`.

## Open Questions

None.

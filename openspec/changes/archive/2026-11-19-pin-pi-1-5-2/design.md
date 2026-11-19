## Context

`README.md`, section "Updating pinned image inputs", gives the update
procedure: change `.version` or the `Containerfile` pins, rebuild in
maintenance mode, rerun `./test-wrapper.sh` and `./test.sh`, then record the
result. `agent/launcher.sh` passes the first line of `.version` as
`PI_VERSION`, and `.version` is a hashed build input.

The 0.80.8 measurements (2026-11-10) cover:
- a static endpoint inventory;
- logging-proxy runs for `anthropic-api`, `openai-api`, `gemini-api` and
  `openrouter-api`;
- the controls in `AGENT_RESTRICTED_ENV`: `PI_OFFLINE=1`,
  `PI_SKIP_VERSION_CHECK=1` and `PI_TELEMETRY=0`.

The 1.5.2 documentation still lists these three variables, with the same
meaning.

Facts from the 1.5.2 changelog and docs that matter here:
- **Built-in MCP:**
  - user servers are read from `~/.pi/agent/mcp.json`;
  - project servers from `.pi/mcp.json`, only after project trust;
  - OAuth sign-in uses a local callback port.
- **Codemode** runs scripts in workers, with `quickjs-wasi`.
- **Project trust:**
  - `--approve` and `--no-approve` set the decision for one run;
  - otherwise `defaultProjectTrust` applies, with default `"ask"`;
  - in print, JSON and RPC modes, "ask" skips the project resources.

  This decides whether the project's `.agents/skills` load.
- **Breaking changes** concern extension and SDK APIs and the Azure provider
  name. The wrapper uses none of them.

## Goals / Non-Goals

**Goals:**
- Pin Pi 1.5.2 and OpenSpec 2.0.0 exactly. The build version checks and every
  suite must pass.
- Measure 1.5.2 from scratch with the 0.80.8 methods, then compare host by host:
  - what changes with the restricted controls set;
  - what changes without them.
- Find out how MCP, codemode and project trust behave under the guard. Record
  any visible change for the user to classify.
- Regenerate the tracked OpenSpec skills with 2.0.0.

**Non-Goals:**
- Enabling MCP servers or adding MCP hosts to any profile.
- Adapting user extensions.
- Changing the base digest or any shared file.

## Decisions

- **Remeasure everything, not only the differences.**
  - There are seven minor versions and one major between 0.80.8 and 1.5.2.
  - A full inventory costs about the same as a diff, and it makes `tested.cli`
    true.
- **MCP stays out of every profile.**
  - User-configured MCP servers reach only hosts that a profile allows. This is
    the same rule as for Codex and Claude.
  - The record states that an MCP OAuth callback listener is subject to the
    guard's listener policy. Whether it works or is denied is measured, not
    assumed.
- **Project trust is documented, not overridden.**
  - The wrapper does not pass `--approve` or `--no-approve` on its own.
  - The README and help text explain the trust gate. In print mode a project's
    `.agents/skills` is skipped unless the user approves it.
  - If the user wants a wrapper default, that is a separate decision. It
    pauses the work and goes to the user.
- **`PI_CONTAINER_YOLO` keeps "no effect" only if it is still true.**
  - Check whether 1.5.2 has any tool-approval prompt.
  - If it has one, `agent_approval_bypass` would need to map YOLO to it. That
    is a new behavior, so the work pauses and the question goes to the user.
- **Skills are regenerated inside the new image.**
  - Run `openspec update` with the image's OpenSpec 2.0.0 in shell mode on the
    checkout.
  - This keeps the operator's planning CLI at 1.16.0 until the final step of
    the plan.
  - The diff is reviewed and committed as generated.

## Risks / Trade-offs

- [New startup traffic, for example the model catalog refresh, the `pi.dev`
  schemas or MCP] → The static scan and logging-proxy runs measure it with and
  without the controls. Required hosts that change go to a spec delta.
  Optional traffic stays denied.
- [Codemode workers or the MCP callback need something the hardened container
  denies (seccomp, listeners, `/tmp` exec)] → Run a codemode script and an MCP
  `list` under the guard and record the result. A break of default Pi behavior
  is a visible change and goes to the user.
- [Existing `~/.pi` state written by 0.80.8 does not load in 1.5.2] → Start the
  new image against a copy of a 0.80.8 state directory. Record migrations or
  errors.
- [The old-test gate fails widely because of help text and notices] → Classify
  each failure as usual: a visible change, a lost behavior (ask the user) or
  agent-only behavior.
- [Rollback] → Revert `.version`, the OpenSpec pin and the skills, then rebuild.
  Existing state stays readable unless the previous risk shows that 1.5.2
  migrated it. In that case the record notes it.

## Migration Plan

1. The operator pushes `main`.
2. The next launch asks for `--container-build`.
3. The operator reruns `--container-setup` on the three hosts.

User extensions written for 0.80 may need the 1.x API. The CHANGELOG points to
upstream.

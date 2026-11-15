# Design

## Context

See proposal.md for the findings. Current Pi lifecycle:

- `pi-container.sh:1104` creates the container with the session label `io.pi-container.session=${session_tmp##*/}`
  and a private CID file.
- `cleanup()` recovers the ID from the CID file only (`recover_container_id`).
  With no ID it prints "creation outcome unresolved" (`pi-container.sh:1004`).
- `pi-container.sh:1120` treats any existing container with the candidate name as a
  collision.

The reference (`claude-container.sh`, `recover_container` and the create loop)
checks the label before treating a name as taken, and recovers an interrupted
creation with `ps --all --no-trunc --filter label=<label>=<token>`, then
confirms the label with `inspect` before removing.

## Goals / Non-Goals

**Goals:**
- Adopt `sandbox-ref-18` byte for byte and declare Pi's agent variables.
- Never leave or skip a container that carries this session's label.

**Non-Goals:**
- Rewriting Pi's lifecycle into the reference's structure. Only the two
  reconciliation rules are ported.
- Moving the lifecycle into shared code.

## Decisions

### Agent variables

Pi declares `PI_`, `ANTHROPIC_`, `OPENAI_`, `GEMINI_`, `OPENROUTER_`, `GOOGLE_API_KEY`. Prefixes cover controls a later release may add;
exact names are used where a prefix would also catch unrelated tools (for
example `GOOGLE_` would catch a Google Cloud SDK toolchain's settings).

### Ownership-checked collision

After a failed create with no ID, run `container exists` and, when it
exists, `inspect --type container --format '{{index .Config.Labels "<label>"}}'`.
Only a different label is a collision. The same label leaves the creation
pending, so cleanup reconciles it, and the wrapper exits with the create
status. An `inspect` failure is reported like an unconfirmed collision today:
exit with the create status, no retry.

Alternative: retry on the same label. Rejected: the reference reports the
original failure, and a retry would double the credential-bearing containers.

### Label recovery in cleanup

When `creating` is still set and `recover_container_id` found no ID, cleanup
runs `timeout --kill-after=1s 5s podman ps --all --no-trunc --filter
label=<label>=<token> --format '{{.ID}}'`. Exactly one 64-hex ID, whose label
`inspect` confirms, becomes `container_id` and is removed by the existing
removal path. Several IDs, an invalid ID, a failed lookup or a failed
confirmation keep today's "unresolved" message. The lookup shares the
20-second shutdown deadline.

Alternative: remove every ID the filter returns. Rejected: the label already
identifies one session, so more than one ID means something unexpected, and
the reference also refuses to guess.

## Risks / Trade-offs

- [The stricter alignment test or the shared overlap check fails on a Pi
  test fixture] → The adoption suites show it; the fixture is adapted in this
  change and recorded in `docs/validation.md`.
- [A legitimate toolchain sets a now-protected variable] → `launch-env`
  warns and leaves it out; the operator forwards it explicitly.
- [The extra lookup slows an interrupted shutdown] → It is bounded by the
  shared shutdown deadline.

## Migration Plan

Adopt on branch `adopt-sandbox-ref-18`, run the suites, merge with `--no-ff`.
The operator pushes and reruns `--container-setup` on the three hosts.
Rollback before the operator setup is a revert of the merge.

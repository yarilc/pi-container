# Proposal

## Why

Pi currently uses namespace root, permissive delegation switches, automatic SELinux relabeling, and an untracked `podman run` lifecycle, unlike the verified rootless execution boundary in the three sibling projects. The reviewed `todo.md` identifies concrete gaps that need enforceable acceptance criteria before implementation.

## What Changes

- **BREAKING** Require verified Linux rootless launch engines for builds and sessions; remove `PI_ALLOW_ROOTFUL` and reject unsupported remote contexts and malformed engine responses.
- **BREAKING** Enable host Podman delegation only for exact `PI_ENABLE_PODMAN=1`, verify the selected service, support host-side socket remapping, and fail before image operations when enabled access cannot be verified.
- **BREAKING** Run with caller UID/GID in keep-id mode, drop all capabilities without additions, validate private writable state, and remove automatic host relabeling.
- Explicitly provision bounded temporary filesystems and preserve Pi state, extension installation, optional Bun, resource limits, network controls, and by-name credential forwarding.
- Reserve session names atomically and manage creation, attachment, signals, status propagation, and full-ID cleanup with finite shutdown phases.
- Add wrapper build, shell, worktree, and help modes; preserve native Pi arguments and the existing wrapper-help alias.
- Distinguish image absence from operational failures and include the selected Bun version in stale-image inputs, correcting the current README/code discrepancy.
- Extend synthetic tests, add credential-free real rootless acceptance checks, and update operational and security documentation.

## Capabilities

### New Capabilities

- `container-engine`: Verified launch engine, strict response protocol, and explicit delegated service authority.
- `container-filesystem`: Caller identity, private persistent state, physical workspace boundaries, and explicit temporary storage.
- `container-session`: Atomic naming, owned lifecycle, input/output handling, exit codes, and bounded interruption cleanup.
- `container-wrapper`: Wrapper modes, native argument compatibility, image lifecycle, and retained Pi-specific configuration.

### Modified Capabilities

None. The project currently has no main capability specifications; these deltas establish its behavioral baseline.

## Impact

Implementation will affect `pi-container.sh`, `Containerfile`, `test-wrapper.sh`, `test.sh`, new runtime test support, CI as needed, README, SECURITY.md, and CONTRIBUTING.md. GNU timeout remains a required host tool; permission-sensitive tests need native Linux storage. Existing state remains in `~/.pi` and `~/.agents`; incompatible ownership/modes require explicit user repair, never automatic chmod/chown or credential copying. No authenticated agent operations, dependency upgrades, or sibling-project edits are in scope. This change creates planning artifacts only; `todo.md` remains open until implementation is verified.

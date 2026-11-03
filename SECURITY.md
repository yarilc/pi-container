# Security Policy

## Reporting a Vulnerability

If you discover a security vulnerability in pi-container, please report it
privately by opening a GitHub Security Advisory at:

[Open a private security advisory](https://github.com/yarilc/pi-container/security/advisories/new)

**Do not report security vulnerabilities via public GitHub issues.**

You should receive a response within 48 hours. If you don't, please follow
up to ensure the message was received.

## Scope

This security policy covers:

- The `pi-container.sh` wrapper script
- The `Containerfile` (container image definition)
- The build and runtime behavior of the containerized Pi agent

Issues in the upstream `@earendil-works/pi-coding-agent` package or Podman
itself should be reported to their respective projects.

## Known Security Considerations

### API Keys

API keys are passed to the container via environment variables. Keys are
forwarded by name (`-e KEY`) to avoid placing secret values on the process
command line. However, the following exposure surfaces exist:

- **Container `/proc`:** Processes with appropriate access to the agent environment
  can extract keys; untrusted code running as the same user shares its authority.
- **`podman inspect`:** The environment variables are visible in
  `podman inspect <container>` output on the host.
- **Host process list:** While keys are not on argv, they remain in the
  podman process's environment block, accessible to the host root user
  via `/proc/<pid>/environ`.
- **Debug output:** When `PI_DEBUG=1` is set, only argument counts are logged
  to stderr. However, because API keys are forwarded by name only (`-e KEY`
  not `-e KEY=value`), the actual key values never appear in the log.

**Recommendations:**

- Use API keys with usage limits and minimal permissions
- Rotate keys regularly
- Consider using `podman secret` for production deployments
- Do not use this tool on shared/multi-tenant systems without additional
  secret management

### Container Privileges

Pi runs as the caller's numeric UID/GID with keep-id, a read-only root
filesystem, all capabilities dropped without additions, no-new-privileges,
and configurable resource limits. Every build/session requires a verified
Linux rootless launch engine; the old PI_ALLOW_ROOTFUL bypass is removed.
Local and explicit same-host absolute Unix engines are supported; named,
TCP/SSH, and implicit remote connections are rejected. Complete engine
responses are validated before image operations.

Writable state must be physically resolved, caller-owned, accessible, and
private (no group/other permissions). Missing state is created privately;
existing invalid state is rejected without chmod/chown or credential import.
Read-only state needs existing readable/traversable directories; the wrapper
does not enforce their ownership/privacy, so confidentiality remains the
caller's responsibility. Prefer native Linux storage enforcing Unix modes.

Temporary stores are explicit, bounded, nosuid/nodev/noexec: /tmp and /var/tmp
256 MiB each, /run 32 MiB, npm cache 256 MiB by default. Delegated-client
stores are 256 MiB and 64 MiB. None persists after the session.

### Persistent Compromise via Extensions and Skills ⚠️

The directories `~/.pi` (which contains Pi extensions at
`~/.pi/agent/extensions/`) and `~/.agents` (which contains skills at
`~/.agents/skills/`) are **mounted read-write** by default.

This creates a **persistence vector**: a prompt-injected or compromised
agent can write a malicious Pi extension or skill into these directories.
Because these directories survive container rebuilds and image removal,
the malicious code will be loaded on **all future Pi invocations** — both
inside the container and, critically, when running `pi` natively on the
host without the container.

**Impact:** A one-time container compromise becomes a durable host-side
code execution path. The same attack surface exists for any file in
`~/.pi/` that Pi loads at startup, including `settings.json` and
session files.

**Mitigations:**

- Set `PI_READONLY_CONFIG=1` to mount `~/.pi` and `~/.agents` **read-only**
  when working with untrusted prompts or projects. This prevents the agent
  from writing any files into these directories.
- Treat the agent as trusted with everything it can read and write. Do not
  expose it to untrusted content without read-only config.
- Be aware that extensions in `~/.pi/agent/extensions/` have full access to
  Pi's internal APIs and can read/write any file the user can.

### Network Egress and Data Exfiltration (Primary Residual Risk)

The container has **unrestricted outbound network access by default**, and
mounts `~/.pi` (which contains `~/.pi/agent/auth.json` auth tokens) and the
current project directory read-write. The AI agent runs as the mapped caller with read access to all of this.

This means a **prompt-injected or misbehaving agent could read auth tokens or
project source and transmit them to an arbitrary endpoint.** The filesystem
and capability hardening does not mitigate this, because the agent legitimately
has read access and unrestricted egress.

**Recommendations:**

- Treat the agent as trusted with everything it can read and reach over the
  network. Do not run it on projects containing secrets you would not give it.
- Use `PI_NETWORK=none` to block all egress for tasks that do not need network
  access, or point `PI_NETWORK` at a restricted/proxied network.
- Be cautious with untrusted project content or untrusted prompts.

### Host Git Config Exposure

The file `~/.gitconfig` is mounted read-only into the container when present.
Git configurations routinely contain:

- Credential helper invocations (`credential.helper`)
- URL-based authentication tokens (`[url "https://token@github.com/"]`)
- `includePath` directives pointing at other host files
- Signing keys references (`user.signingkey`)

A compromised agent can read the mounted `.gitconfig` and exfiltrate any
embedded credentials over the unrestricted default network.

**Mitigations:**

- Set `PI_MOUNT_GITCONFIG=0` to prevent `~/.gitconfig` from being mounted.
- Consider creating a minimal gitconfig with only `user.name` and `user.email`
  for use with the container.
- Keep `PI_NETWORK=none` when working with untrusted content.

### Sensitive Working Directories

The physical workspace is mounted at the same absolute path and used as
workdir. No automatic :z/:Z relabeling or host policy bypass is performed.
SELinux denials require explicit host policy/permission inspection. The
sensitive-directory guard rejects /, HOME, /home, /etc, /usr, /var, /bin,
/sbin, /lib, /lib64, /boot, /root, /opt, /srv, /mnt, /media, /proc, /sys,
/dev, and /run unless PI_ALLOW_UNSAFE_PWD is nonempty. Worktree mode applies
the guard to the immediate parent it exposes. That explicit mode permits
read/write access to siblings in the whole parent while retaining the
original workdir. Always use a suitably narrow project directory.

### Podman Socket (Opt-In, Dangerous)

Only exact `PI_ENABLE_PODMAN=1` enables host authority and installs the
client. All other values disable delegation, including true/yes/0/false.
The selected absolute accessible socket (`PI_PODMAN_SOCKET`, Unix
`CONTAINER_HOST`, then XDG runtime/UID fallback) is canonicalized and queried
explicitly. It must report rootless operation and an absolute host socket
path. Enabled failures abort before image operations; services are never
started automatically. The reported host source is bound at
`/run/podman/podman.sock`; containerized callers must retain absolute host
workspace/state paths and select a same-host service. Unix transport alone
cannot establish host identity.

Delegation gives control over the service user's containers and permits host
mounts beyond the workspace. It removes the project-only access boundary.
Without it no socket is mounted and session CONTAINER_HOST is explicitly
unset, including PI_ENV_VARS requests. Connection forwarding cannot override
the selected endpoint. Bun and native Pi permission flags do not enable
socket access.

### Owned Cleanup and Residual Resources

Only the invocation's verified full CID from private bookkeeping authorizes
removal; no container is deleted by reusable name or prefix. TERM/INT/HUP
preserve the first interruption status (143/130/129); application exit codes,
including 125, survive cleanup errors. Controls have a 5s timeout plus 1s
kill-after, grace is 5s, and client cancellation is TERM 5s then KILL 1s.
Interrupted creation adds at most 5s completion grace before cancellation and
final CID recovery. Repeated signals cannot renew these deadlines.

Unknown/malformed IDs, unresponsive engines, SIGKILL, and delayed server
results may leave resources requiring explicit engine inspection. Local
client cancellation is not server cancellation. Diagnostics report owned IDs
or unresolved creation rather than attempting wider deletion.

### Supply Chain

The npm package `@earendil-works/pi-coding-agent` is pinned to a specific
version (see `.version` file) for reproducibility.

The base image uses a mutable tag (`node:22-bookworm-slim`) by default.
For pinning instructions, see the Containerfile comments. Weekly CI scans
(Trivy) monitor the built image for known vulnerabilities.

Third-party GitHub Actions are pinned by commit SHA. Dependabot is
configured to propose updates automatically.

See the "Updating" section in README.md for upgrade procedures.

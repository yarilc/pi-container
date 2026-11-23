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
- **Diagnostics:** keys are forwarded by name only (`--env KEY`, never
  `--env KEY=value`), so their values never appear in wrapper diagnostics.

Provider sessions receive only the selected profile's key and offline sessions
none. Unrestricted sessions receive a key only when `PI_CONTAINER_ENV_VARS`
lists it.

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
512 MiB each, the shared-state home 512 MiB, /run 32 MiB (not writable by the
session user), npm cache 256 MiB by default. Delegated-client stores are
256 MiB and 64 MiB. None persists after the session.

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

- Set `PI_CONTAINER_READONLY_STATE=1` to mount `~/.pi` and `~/.agents` **read-only**
  when working with untrusted prompts or projects. This prevents the agent
  from writing any files into these directories.
- Treat the agent as trusted with everything it can read and write. Do not
  expose it to untrusted content without read-only config.
- Be aware that extensions in `~/.pi/agent/extensions/` have full access to
  Pi's internal APIs and can read/write any file the user can.

### Network Egress and Data Exfiltration (Primary Residual Risk)

In `unrestricted` mode the container has **unrestricted outbound network
access**, and it mounts `~/.pi` (which contains `~/.pi/agent/auth.json` auth tokens) and the
current project directory read-write. The AI agent runs as the mapped caller with read access to all of this.

This means a **prompt-injected or misbehaving agent could read auth tokens or
project source and transmit them to an arbitrary endpoint.** The filesystem
and capability hardening does not mitigate this, because the agent legitimately
has read access and unrestricted egress.

**Recommendations:**

- Treat the agent as trusted with everything it can read and reach over the
  network. Do not run it on projects containing secrets you would not give it.
- Keep the default `provider` mode, which allows one exact provider profile,
  or use `PI_CONTAINER_NETWORK=offline` to block all egress for tasks that do
  not need network access. Both are enforced by a native guard and an external
  proxy, not by client settings.
- In provider mode the allowed host can still receive data sent with an
  attacker's key or account (residual exfiltration); only offline removes this
  channel. See [docs/network-contract.md](docs/network-contract.md).
- Be cautious with untrusted project content or untrusted prompts.

### Host Git Config Exposure

The file `~/.gitconfig` is not mounted by default. It is mounted read-only only
with exact `PI_CONTAINER_GITCONFIG=1`.
Git configurations routinely contain:

- Credential helper invocations (`credential.helper`)
- URL-based authentication tokens (`[url "https://token@github.com/"]`)
- `includePath` directives pointing at other host files
- Signing keys references (`user.signingkey`)

When it is opted in, a compromised agent can read the mounted `.gitconfig` and
exfiltrate any embedded credentials over the unrestricted default network.

**Mitigations:**

- Leave `PI_CONTAINER_GITCONFIG` unset (the default) unless the session needs
  the host Git configuration.
- Consider creating a minimal gitconfig with only `user.name` and `user.email`
  for use with the container.
- Keep `PI_CONTAINER_NETWORK=offline` when working with untrusted content.

### Sensitive Working Directories

The physical workspace is mounted at the same absolute path and used as
workdir. No automatic :z/:Z relabeling or host policy bypass is performed.
SELinux denials require explicit host policy/permission inspection. The
sensitive-workspace guard compares physical paths and rejects /, the caller's
home, /home, /root, /etc, /usr, /var, /bin, /sbin, /lib, /lib64, /boot, /opt,
/srv, /mnt, /media, /proc, /sys, /dev, /run, /tmp and /mnt/<letter> drive
roots, and on a drive mount the Windows `Users`, profile, `Documents`,
`OneDrive`, `Windows`, `Program Files` and `ProgramData` folders and anything
inside the profile's `AppData`, in any letter case, unless exactly
`PI_CONTAINER_ALLOW_UNSAFE_WORKSPACE=1` is set. Worktree mode applies
the guard to the immediate parent it exposes. That explicit mode permits
read/write access to siblings in the whole parent while retaining the
original workdir. Always use a suitably narrow project directory.

### No Tool-Approval Layer

Pi runs its tools without approval prompts, so the container is the only
boundary around them. `PI_CONTAINER_YOLO` exists for setup and future Pi
releases; enabling it changes nothing and prints a notice. Pi's `--approve`
option trusts project-local files for a run; it does not approve tools.
Combine `PI_CONTAINER_NETWORK=offline`, `PI_CONTAINER_READONLY_STATE=1` and narrow
workspaces for untrusted tasks.

### Resource Budgets

Every session has validated memory, CPU and process budgets
(`PI_CONTAINER_MEMORY_LIMIT`, `PI_CONTAINER_CPU_LIMIT`,
`PI_CONTAINER_PIDS_LIMIT`; defaults 4g, 2 and 512). Each budget is enforced
only when the rootless engine delegates its cgroup v2 controller, which needs
the `systemd` cgroup manager; with `cgroupfs`, as on a Podman machine on
Windows, no controller counts as delegated. Without the `pids` controller, the
process budget falls back to a per-container process rlimit on Linux 5.14 or
later. A budget without a mechanism stays unenforced, and every launch prints a
notice for it. The wrapper inspects the created container and starts it only
when every enforced budget equals its value and no unenforced one is present.
Budgets do not bound workspace or state storage growth.

### Podman Socket (Opt-In, Dangerous)

Only exact `PI_CONTAINER_PODMAN=1` enables host authority; the client is part
of every image. All other values disable delegation, including true/yes/0/false.
The selected absolute accessible socket (`PI_CONTAINER_PODMAN_SOCKET`, Unix
`CONTAINER_HOST`, then XDG runtime/UID fallback) is canonicalized and queried
explicitly. It must report rootless operation and an absolute host socket
path that is not made only of slashes and, when visible to the wrapper, is a
socket. Enabled failures abort before image operations; services are never
started automatically. The reported host source is bound at
`/run/podman/podman.sock`; containerized callers must retain absolute host
workspace/state paths and select a same-host service. Unix transport alone
cannot establish host identity.

Delegation gives control over the service user's containers and permits host
mounts beyond the workspace. It removes the project-only access boundary.
Without it no socket is mounted and session CONTAINER_HOST is explicitly
unset, including PI_CONTAINER_ENV_VARS requests. Connection forwarding cannot override
the selected endpoint. Native Pi permission flags do not enable socket
access.

### Owned Cleanup and Residual Resources

Only the invocation's verified full CID from private bookkeeping authorizes
removal; no container is deleted by reusable name or prefix. TERM/INT/HUP
preserve the first interruption status (143/130/129); application exit codes,
including 125, survive cleanup errors. A signal starts shutdown at once, also
during creation, and shutdown ends within one 20-second deadline: 5 seconds of
grace after the forwarded signal, then forced removal; each shutdown engine
call is bounded by the time left, and local clients are terminated and reaped
within the deadline. Interrupted creation is recovered through the validated
CID record, the create output and the session ownership label. Repeated
signals cannot renew the deadline.

Unknown/malformed IDs, unresponsive engines, SIGKILL, and delayed server
results may leave resources requiring explicit engine inspection. Local
client cancellation is not server cancellation. Diagnostics report owned IDs
or unresolved creation rather than attempting wider deletion.

### Supply Chain

Every image input is pinned: the base image `node:22-bookworm-slim` by
digest, `@earendil-works/pi-coding-agent` at the version in `.version`,
`@fission-ai/openspec` at the version recorded in the Containerfile. npm verifies each package's registry integrity; no remote
install script is piped to a shell, and `tests/test_image_pins.py` rejects
floating inputs. A stale image is never rebuilt silently. Weekly CI scans
(Trivy) monitor the built image for known vulnerabilities.

Third-party GitHub Actions are pinned by commit SHA. Dependabot is
configured to propose updates automatically.

See "Updating pinned image inputs" in README.md for upgrade procedures.

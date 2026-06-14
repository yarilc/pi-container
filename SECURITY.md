# Security Policy

## Reporting a Vulnerability

If you discover a security vulnerability in pi-container, please report it
privately by opening a GitHub Security Advisory at:

  https://github.com/yarilc/pi-container/security/advisories/new

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

- **Container `/proc`:** Any process running as root inside the container
  can read `/proc/1/environ` and extract keys.
- **`podman inspect`:** The environment variables are visible in
  `podman inspect <container>` output on the host.
- **Host process list:** While keys are not on argv, they remain in the
  podman process's environment block, accessible to the host root user
  via `/proc/<pid>/environ`.
- **Debug output:** When `PI_DEBUG=1` is set, masked key indicators
  (value shown as `****`) appear in stderr. The actual values are never
  logged.

**Recommendations:**
- Use API keys with usage limits and minimal permissions
- Rotate keys regularly
- Consider using `podman secret` for production deployments
- Do not use this tool on shared/multi-tenant systems without additional
  secret management

### Container Privileges

The pi process runs as `root` inside the container. This is by design:
rootless Podman maps container root (UID 0) to the host user, ensuring
correct file ownership on mounted volumes. Capabilities are restricted
(`--cap-drop=ALL` with minimal additions) and the root filesystem is
read-only (`--read-only`). Resource limits (`--memory=4g`, `--cpus=2`,
`--pids-limit=512`) prevent runaway processes.

### Network Egress and Data Exfiltration (Primary Residual Risk)

The container has **unrestricted outbound network access by default**, and
mounts `~/.pi` (which contains `~/.pi/agent/auth.json` auth tokens) and the
current project directory read-write. The AI agent runs as root inside the
container with read access to all of this.

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

### Sensitive Working Directories

The current working directory is bind-mounted with the `:Z` SELinux flag,
which **recursively relabels** the directory's SELinux contexts. Running from
`/`, `$HOME`, `/etc`, or similar would relabel and expose large/sensitive trees
(SSH keys, credentials). The wrapper refuses to run from such directories
unless `PI_ALLOW_UNSAFE_PWD=1` is set. Always run from a specific project
subdirectory.

### Podman Socket (Opt-In, Dangerous)

The host Podman socket can be mounted into the container by setting
`PI_ENABLE_PODMAN=1`. This gives the AI agent full control over the
host's container runtime (create privileged containers, mount host
filesystems). **This is disabled by default.** Enable only if you
understand the risks and need container management inside pi.

See README.md for setup instructions.

### Supply Chain

The npm package `@earendil-works/pi-coding-agent` is pinned to a specific
version (see `.version` file) for reproducibility.

The base image uses a mutable tag (`node:22-bookworm-slim`) by default.
For pinning instructions, see the Containerfile comments.

See the "Updating" section in README.md for upgrade procedures.

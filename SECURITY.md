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

API keys are passed to the container via environment variables. While
rootless Podman provides isolation from other host users, API keys are
visible in `podman inspect` output and inside the container's `/proc`.

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

# syntax=docker/dockerfile:1
# Pi Coding Agent — container image
#
# Designed for rootless Podman: the pi process runs as root inside the
# container. Rootless Podman maps root (UID 0) to the host user,
# ensuring correct file permissions on all mounted volumes.
#
# Single-stage build with separated layers:
#   Layer 1: system packages (git, ripgrep, nano, bash, ca-certificates)
#   Layer 2: podman CLI (conditional, only when INSTALL_PODMAN=1)
#   Layer 3: Pi Coding Agent (npm global install)
#
# Separating layers improves cache efficiency: changing Pi version only
# rebuilds the npm layer; changing system packages only rebuilds layer 1.
#
# Build arguments:
#   PI_VERSION      Pi Coding Agent version (set by pi-container.sh from .version)
#   INSTALL_PODMAN  Set to 1 to include the podman CLI (for PI_ENABLE_PODMAN feature)
#   INSTALL_BUN     Set to 1 to include the Bun runtime (for PI_ENABLE_BUN feature)
#   BUN_VERSION     Bun release tag (default: bun-v1.3.14)
#
# Base image pinning:
#   For production use, pin by digest:
#     1. podman pull docker.io/library/node:22-bookworm-slim
#     2. podman image inspect node:22-bookworm-slim | jq -r '.[0].Digest'
#     3. Replace the FROM line below with:
#        FROM docker.io/library/node:22-bookworm-slim@sha256:<digest>
#
#   The current mutable tag is used for ease of automated rebuilds.
#   Weekly CI scans (Trivy) monitor for CVEs in the floating base.

FROM docker.io/library/node:22-bookworm-slim

ARG PI_VERSION
ARG INSTALL_PODMAN=0
ARG INSTALL_BUN=0
ARG BUN_VERSION=bun-v1.3.14

RUN test -n "${PI_VERSION}" || (echo "PI_VERSION build arg is required" && exit 1)

# Use bash with pipefail as the default shell for RUN commands. The base image's
# default /bin/sh is dash, which does not support `set -o pipefail`; this makes
# pipe failures (e.g. `curl ... | bash`) propagate correctly and satisfies
# hadolint DL4006. bash is already present in the node base image.
SHELL ["/bin/bash", "-o", "pipefail", "-c"]

LABEL org.opencontainers.image.title="Pi Coding Agent Container"
LABEL org.opencontainers.image.description="Containerized Pi Coding Agent for Podman rootless"
LABEL org.opencontainers.image.version="${PI_VERSION}"
LABEL org.opencontainers.image.source="https://github.com/yarilc/pi-container"

# ---- Layer 1: system dependencies ----
# Separate from npm layer: changing apt packages does not invalidate npm cache.
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        bash \
        ca-certificates \
        git \
        nano \
        ripgrep \
    && rm -rf /var/lib/apt/lists/* \
    && apt-get clean

# ---- Layer 2: conditional podman client ----
# Only needed for the PI_ENABLE_PODMAN feature (opt-in, disabled by default).
RUN if [ "${INSTALL_PODMAN}" = "1" ]; then \
        apt-get update \
        && apt-get install -y --no-install-recommends podman \
        && rm -rf /var/lib/apt/lists/* \
        && apt-get clean; \
    fi

# ---- Layer 2.5: conditional Bun runtime ----
# Bun is a dependency-free single binary. Installed to /usr/local/bin so it is
# on PATH and requires no writes to $HOME at runtime (compatible with the
# read-only rootfs). curl and unzip are required only by the install script
# and are removed afterwards to keep the layer lean.
# Enabled by PI_ENABLE_BUN=1 (off by default).
RUN if [ "${INSTALL_BUN}" = "1" ]; then \
        apt-get update \
        && apt-get install -y --no-install-recommends curl unzip \
        && curl -fsSL https://bun.sh/install | BUN_INSTALL=/usr/local bash -s "${BUN_VERSION}" \
        && apt-get purge -y --auto-remove curl unzip \
        && rm -rf /var/lib/apt/lists/* \
        && apt-get clean \
        && bun --version; \
    fi

# ---- Layer 3: Pi Coding Agent ----
# npm global install creates the /usr/local/bin/pi symlink automatically.
RUN npm install -g "@earendil-works/pi-coding-agent@${PI_VERSION}" \
    && npm list -g "@earendil-works/pi-coding-agent" >/dev/null 2>&1 \
    && test -x /usr/local/bin/pi

ENTRYPOINT ["pi"]

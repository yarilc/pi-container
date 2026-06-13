# syntax=docker/dockerfile:1
# Pi Coding Agent — container image
#
# Designed for rootless Podman: the pi process runs as root inside the
# container. Rootless Podman maps root (UID 0) to the host user,
# ensuring correct file permissions on all mounted volumes.
#
# Base image: uses a mutable tag for convenience during development.
# For production use, pin by digest:
#   1. podman pull docker.io/library/node:22-bookworm-slim
#   2. podman image inspect node:22-bookworm-slim | jq -r '.[0].Digest'
#   3. Replace the FROM line with:
#      FROM docker.io/library/node:22-bookworm-slim@sha256:<digest>
FROM docker.io/library/node:22-bookworm-slim

LABEL org.opencontainers.image.title="Pi Coding Agent Container"
LABEL org.opencontainers.image.description="Containerized Pi Coding Agent for Podman rootless"
LABEL org.opencontainers.image.version="0.1.0"
LABEL org.opencontainers.image.source="https://github.com/yarilc/pi-container"

# ---- Build arguments ----
# PI_VERSION is set automatically by pi-container.sh from .version file.
# When building manually, override with: --build-arg PI_VERSION=<version>
ARG PI_VERSION=0.79.3

# ---- System dependencies and Pi installation ----
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        bash \
        ca-certificates \
        git \
        podman \
        ripgrep \
    && rm -rf /var/lib/apt/lists/* \
    && apt-get clean \
    && npm install -g "@earendil-works/pi-coding-agent@${PI_VERSION}" \
    && pi --version >/dev/null 2>&1

ENTRYPOINT ["pi"]

# syntax=docker/dockerfile:1
# Pi Coding Agent — container image
#
# Designed for rootless Podman with keep-id: the launcher runs Pi as the
# caller's numeric UID/GID without capabilities. Tooling in /usr/local is
# readable/executable by arbitrary users; state/cache mounts provide writes.
#
# Image inputs are pinned. Update them only through the maintenance procedure
# in README.md ("Updating pinned image inputs") and record the result in
# docs/validation.md. The Pi version comes from .version via PI_VERSION.
#
# Build arguments:
#   PI_VERSION        Pi Coding Agent version (agent/launcher.sh passes the first
#                     line of .version to every build)
#   OPENSPEC_VERSION  pinned OpenSpec release

FROM docker.io/library/node:22-bookworm-slim@sha256:4b150b48b4116e2a22f2c39cc27025fbf4f153e2078fd3b14d159fdb5c7279da

ARG PI_VERSION
ARG OPENSPEC_VERSION=2.0.0

# Bash with pipefail for RUN commands (hadolint DL4006).
SHELL ["/bin/bash", "-o", "pipefail", "-c"]

LABEL org.opencontainers.image.title="Pi Coding Agent Container"
LABEL org.opencontainers.image.description="Containerized Pi Coding Agent for Podman rootless"
LABEL org.opencontainers.image.version="${PI_VERSION}"
LABEL org.opencontainers.image.source="https://github.com/yarilc/pi-container"

ENV DEBIAN_FRONTEND=noninteractive \
    HOME=/pi-home

# Common toolset shared with the other wrappers, including the Podman client.
# Debian packages are fetched only over verified HTTPS, so builds need no outbound
# port 80. The slim base has no ca-certificates, so the pinned base's Node.js root
# certificates verify the fetches until Debian ca-certificates is installed. With
# host CA trust enabled, the selected bundle arrives as the optional build-ca
# secret (never stored in a layer) and is appended for TLS-intercepting networks.
# The temporary bundle stays readable by apt's _apt user and is removed in this step.
RUN --mount=type=secret,id=build-ca,required=false \
    test -n "${PI_VERSION}" || { echo "PI_VERSION build arg is required" >&2; exit 1; } \
    && node -e 'process.stdout.write(require("tls").rootCertificates.join("\n") + "\n")' \
        > /tmp/apt-bootstrap-ca.pem \
    && if [ -s /run/secrets/build-ca ]; then cat /run/secrets/build-ca >> /tmp/apt-bootstrap-ca.pem; fi \
    && sed -i 's|^URIs: http://|URIs: https://|' /etc/apt/sources.list.d/debian.sources \
    && apt-get -o Acquire::https::CAInfo=/tmp/apt-bootstrap-ca.pem update \
    && apt-get -o Acquire::https::CAInfo=/tmp/apt-bootstrap-ca.pem install --no-install-recommends -y \
        bash \
        bubblewrap \
        bzip2 \
        ca-certificates \
        coreutils \
        curl \
        diffutils \
        file \
        findutils \
        gawk \
        git \
        grep \
        jq \
        less \
        nano \
        patch \
        podman \
        procps \
        python3 \
        ripgrep \
        sed \
        tar \
        unzip \
        util-linux \
        xz-utils \
        zip \
    && rm -f /tmp/apt-bootstrap-ca.pem \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# npm verifies the registry integrity of every package.
RUN npm install --global --omit=dev \
        "@earendil-works/pi-coding-agent@${PI_VERSION}" \
        "@fission-ai/openspec@${OPENSPEC_VERSION}" \
    && test "$(pi --version)" = "${PI_VERSION}" \
    && test "$(openspec --version)" = "${OPENSPEC_VERSION}" \
    && rm -rf /root/.npm /root/.cache /pi-home \
    && mkdir -m 1777 /pi-home

# Agent-side relay for restricted sessions; the guard is mounted from the
# protected installation at launch, never baked into this image.
COPY network/relay.py network/mux.py /opt/sandbox-egress/

ENTRYPOINT ["pi"]

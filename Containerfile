# syntax=docker/dockerfile:1
# Pi Coding Agent — container image
#
# Progettata per Podman rootless: il processo pi gira come root dentro
# il container. Podman rootless mappa root (UID 0) all'utente host,
# garantendo permessi corretti su tutti i volumi montati.

FROM docker.io/library/node:22-bookworm-slim

# ---- Dipendenze di sistema ----
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        bash \
        ca-certificates \
        git \
        ripgrep \
        vim-tiny \
    && rm -rf /var/lib/apt/lists/*

# ---- Installa pi globalmente ----
RUN npm install -g --ignore-scripts @earendil-works/pi-coding-agent

WORKDIR /workspace
ENTRYPOINT ["pi"]

#!/usr/bin/env bash
set -euo pipefail

IMAGE_NAME="pi-container"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# ---- Verifica/Costruzione immagine ----
if ! podman image exists "${IMAGE_NAME}" 2>/dev/null; then
    printf 'Building pi container image...\n'

    podman build \
        -t "${IMAGE_NAME}" \
        -f "${SCRIPT_DIR}/Containerfile" \
        "${SCRIPT_DIR}"
fi

# ---- Assicura che le directory di mount esistano ----
mkdir -p "${HOME}/.pi" "${HOME}/.agents"

# ---- Esegui pi nel container ----
exec podman run --rm -it \
    -e "HOME=${HOME}" \
    -e "TERM=${TERM:-xterm-256color}" \
    -e "EDITOR=vi" \
    -e "VISUAL=vi" \
    -e "ANTHROPIC_API_KEY=${ANTHROPIC_API_KEY:-}" \
    -e "OPENAI_API_KEY=${OPENAI_API_KEY:-}" \
    -e "GOOGLE_API_KEY=${GOOGLE_API_KEY:-}" \
    -v "${HOME}/.pi:${HOME}/.pi" \
    -v "${HOME}/.agents:${HOME}/.agents" \
    -v "${PWD}:${PWD}" \
    -w "${PWD}" \
    "${IMAGE_NAME}" \
    "$@"

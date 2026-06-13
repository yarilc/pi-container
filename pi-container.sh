#!/usr/bin/env bash
# pi-container — transparent containerized Pi Coding Agent
#
# Usage: ./pi-container.sh [PI_OPTIONS...]
#
# All arguments are forwarded to the `pi` CLI inside the container.
#
# Environment variables:
#   PI_ENABLE_PODMAN    Set to 1 to mount the host Podman socket (opt-in)
#   PI_IMAGE_NAME       Override the container image name (default: pi-container)
#   PI_DEBUG            Set to any value to enable verbose debug output
#   ANTHROPIC_API_KEY   Anthropic/Claude API key (forwarded to container)
#   OPENAI_API_KEY      OpenAI API key (forwarded to container)
#   GOOGLE_API_KEY      Google/Gemini API key (forwarded to container)

set -euo pipefail

# ---- Configuration ----
readonly VERSION_FILE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/.version"
IMAGE_NAME="${PI_IMAGE_NAME:-pi-container}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Read pi version from .version file (single source of truth)
PI_VERSION=""
if [[ -f "${VERSION_FILE}" ]]; then
    PI_VERSION="$(head -1 "${VERSION_FILE}" | tr -d '[:space:]')"
fi
if [[ -z "${PI_VERSION}" ]]; then
    PI_VERSION="0.79.3"
fi
readonly PI_VERSION

# ---- Help ----
if [[ "${1:-}" == "--help" ]]; then
    cat <<EOF
Usage: $(basename "$0") [PI_OPTIONS...]
Runs Pi Coding Agent in a Podman container.
All arguments are passed to Pi inside the container.

Examples:
  $(basename "$0") "Refactor this code"
  $(basename "$0") --version
  $(basename "$0") -p "Summarize the README"
  $(basename "$0") --model sonnet "Review the test suite"

Environment variables forwarded to the container:
  ANTHROPIC_API_KEY, OPENAI_API_KEY, GOOGLE_API_KEY,
  HTTP_PROXY, HTTPS_PROXY, NO_PROXY

Override image name: PI_IMAGE_NAME=my-pi $(basename "$0") ...
Enable debug output: PI_DEBUG=1 $(basename "$0") ...
Mount host Podman socket (dangerous): PI_ENABLE_PODMAN=1 $(basename "$0") ...
EOF
    exit 0
fi

# ---- Debug helper ----
debug() {
    if [[ -n "${PI_DEBUG:-}" ]]; then
        printf '[DEBUG] %s\n' "$*" >&2
    fi
}

# ---- Pre-flight checks ----
debug "Pre-flight checks..."

if ! command -v podman >/dev/null 2>&1; then
    printf 'ERROR: podman is required but not found in PATH.\n' >&2
    printf 'Install Podman: https://podman.io/docs/installation\n' >&2
    exit 1
fi

PODMAN_VERSION="$(podman --version 2>/dev/null | sed -n 's/.* \([0-9]*\)\.[0-9]*.*/\1/p')"
if [[ -z "${PODMAN_VERSION}" || "${PODMAN_VERSION}" -lt 4 ]]; then
    printf 'WARNING: Podman >= 4.x recommended (found version %s).\n' \
        "$(podman --version 2>/dev/null | sed -n 's/.* \([0-9]*\.[0-9]*\).*/\1/p' || echo '?')" >&2
fi

# Validate HOME
if [[ -z "${HOME:-}" ]]; then
    printf 'ERROR: HOME is not set. Cannot determine mount paths.\n' >&2
    exit 1
fi

# Validate PWD
if [[ ! -d "${PWD}" ]]; then
    printf 'ERROR: Current working directory (%s) does not exist or is not a directory.\n' "${PWD}" >&2
    exit 1
fi

# Warn about spaces in PWD
if [[ "${PWD}" =~ [[:space:]] ]]; then
    printf 'WARNING: PWD contains spaces — volume mounts may behave unexpectedly.\n' >&2
fi

# Check that at least one API key is set
if [[ -z "${ANTHROPIC_API_KEY:-}" && -z "${OPENAI_API_KEY:-}" && -z "${GOOGLE_API_KEY:-}" ]]; then
    printf 'WARNING: No API key found. Pi requires at least one provider key.\n' >&2
    printf '  Set ANTHROPIC_API_KEY, OPENAI_API_KEY, or GOOGLE_API_KEY.\n' >&2
fi

# ---- Podman socket (opt-in, off by default) ----
# WARNING: Mounting the host Podman socket gives the container full control
# over the host's container runtime. The AI agent can use this to escape
# container isolation. Only enable if you explicitly need podman inside.
PODMAN_SOCKET_ACTIVE=false
if [[ -n "${PI_ENABLE_PODMAN:-}" ]]; then
    HOST_UID="$(id -u)"
    PODMAN_SOCKET="/run/user/${HOST_UID}/podman/podman.sock"

    if [[ -S "${PODMAN_SOCKET}" ]]; then
        debug "Podman socket found at ${PODMAN_SOCKET}"
        PODMAN_SOCKET_ACTIVE=true
    else
        printf 'WARNING: PI_ENABLE_PODMAN is set but socket %s not found.\n' "${PODMAN_SOCKET}" >&2
        printf '  Ensure Podman service is running: systemctl --user enable --now podman.socket\n' >&2
    fi
fi

# ---- Stale image detection ----
CONTAINERFILE_HASH=""
if [[ -f "${SCRIPT_DIR}/Containerfile" ]]; then
    CONTAINERFILE_HASH="$(sha256sum "${SCRIPT_DIR}/Containerfile" | cut -d' ' -f1)"
fi

NEEDS_REBUILD=false
if ! podman image exists "${IMAGE_NAME}" 2>/dev/null; then
    debug "Image ${IMAGE_NAME} not found."
    NEEDS_REBUILD=true
else
    # Check image label for containerfile hash (no external dependencies)
    LABEL_HASH="$(podman image inspect "${IMAGE_NAME}" --format '{{index .Labels "containerfile-hash"}}' 2>/dev/null || true)"
    if [[ -n "${CONTAINERFILE_HASH}" && "${CONTAINERFILE_HASH}" != "${LABEL_HASH}" ]]; then
        debug "Containerfile changed (hash mismatch). Rebuilding."
        NEEDS_REBUILD=true
    fi
fi

# ---- Build image ----
if [[ "${NEEDS_REBUILD}" == true ]]; then
    printf 'Building pi container image (Pi v%s)...\n' "${PI_VERSION}" >&2

    BUILD_ARGS=(
        -t "${IMAGE_NAME}"
        -f "${SCRIPT_DIR}/Containerfile"
        --build-arg "PI_VERSION=${PI_VERSION}"
    )

    # Add containerfile hash as a label for staleness detection
    if [[ -n "${CONTAINERFILE_HASH}" ]]; then
        BUILD_ARGS+=(--label "containerfile-hash=${CONTAINERFILE_HASH}")
    fi

    if ! podman build "${BUILD_ARGS[@]}" "${SCRIPT_DIR}"; then
        printf 'ERROR: Image build failed. Check Containerfile and network connectivity.\n' >&2
        exit 1
    fi

    printf 'Build complete.\n' >&2
fi

# ---- Ensure mount directories exist ----
mkdir -p "${HOME}/.pi" "${HOME}/.agents"

# ---- Build runtime arguments ----
RUNTIME_ARGS=(
    --rm
    -e "HOME=${HOME}"
    -e "TERM=${TERM:-xterm-256color}"
)

# Conditional TTY: only allocate if stdin is a terminal
if [[ -t 0 ]]; then
    RUNTIME_ARGS+=(-t)
fi
RUNTIME_ARGS+=(-i)

# Container hardening
RUNTIME_ARGS+=(
    --cap-drop=ALL
    --cap-add=DAC_OVERRIDE
    --cap-add=CHOWN
    --cap-add=SETGID
    --cap-add=SETUID
    --security-opt=no-new-privileges
    --memory=4g
    --cpus=2
    --pids-limit=512
    --read-only
    --tmpfs /tmp:noexec,nosuid,size=256M
)

# SELinux context (relabel for single container use)
RUNTIME_ARGS+=(
    -v "${HOME}/.pi:${HOME}/.pi:Z"
    -v "${HOME}/.agents:${HOME}/.agents:Z"
    -v "${PWD}:${PWD}:Z"
)

# Podman socket: only mounted when explicitly enabled via PI_ENABLE_PODMAN.
# No :Z to avoid relabeling the host's socket.
if [[ "${PODMAN_SOCKET_ACTIVE}" == true ]]; then
    RUNTIME_ARGS+=(
        -e "CONTAINER_HOST=unix://${PODMAN_SOCKET}"
        -v "${PODMAN_SOCKET}:${PODMAN_SOCKET}"
    )
    debug "Podman socket mounted at ${PODMAN_SOCKET}"
fi

# Working directory
RUNTIME_ARGS+=(-w "${PWD}")

# Forward host editor preferences with fallback
RUNTIME_ARGS+=(
    -e "EDITOR=${EDITOR:-vi}"
    -e "VISUAL=${VISUAL:-vi}"
)

# Forward API keys only if set and non-empty
if [[ -n "${ANTHROPIC_API_KEY:-}" ]]; then
    RUNTIME_ARGS+=(-e "ANTHROPIC_API_KEY=${ANTHROPIC_API_KEY}")
fi
if [[ -n "${OPENAI_API_KEY:-}" ]]; then
    RUNTIME_ARGS+=(-e "OPENAI_API_KEY=${OPENAI_API_KEY}")
fi
if [[ -n "${GOOGLE_API_KEY:-}" ]]; then
    RUNTIME_ARGS+=(-e "GOOGLE_API_KEY=${GOOGLE_API_KEY}")
fi

# Forward proxy environment variables if set
if [[ -n "${HTTP_PROXY:-}" ]]; then
    RUNTIME_ARGS+=(-e "HTTP_PROXY=${HTTP_PROXY}")
fi
if [[ -n "${HTTPS_PROXY:-}" ]]; then
    RUNTIME_ARGS+=(-e "HTTPS_PROXY=${HTTPS_PROXY}")
fi
if [[ -n "${NO_PROXY:-}" ]]; then
    RUNTIME_ARGS+=(-e "NO_PROXY=${NO_PROXY}")
fi

# Image name
RUNTIME_ARGS+=("${IMAGE_NAME}")

debug "Runtime args: ${RUNTIME_ARGS[*]}"
debug "Pi arguments: $*"

# ---- Run pi ----
exec podman run "${RUNTIME_ARGS[@]}" "$@"

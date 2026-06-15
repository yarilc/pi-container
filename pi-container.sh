#!/usr/bin/env bash
# pi-container — transparent containerized Pi Coding Agent
#
# Usage: ./pi-container.sh [PI_OPTIONS...]
#
# All arguments are forwarded to the `pi` CLI inside the container.
#
# Environment variables:
#   PI_ENABLE_PODMAN      Set to 1 to mount the host Podman socket (opt-in, dangerous)
#   PI_IMAGE_NAME         Override the container image name (default: pi-container)
#   PI_DEBUG              Set to any value to enable verbose debug output
#   PI_MEMORY_LIMIT       Container memory limit (default: 4g)
#   PI_CPU_LIMIT          Container CPU limit (default: 2)
#   PI_PIDS_LIMIT         Container PID limit (default: 512)
#   PI_NETWORK            Container network mode (e.g. none, host); default: full access
#   PI_ALLOW_ROOTFUL      Set to 1 to allow running under rootful Podman (not recommended)
#   PI_ALLOW_UNSAFE_PWD   Set to 1 to allow running from sensitive directories (not recommended)
#   ANTHROPIC_API_KEY     Anthropic/Claude API key (forwarded to container)
#   OPENAI_API_KEY        OpenAI API key (forwarded to container)
#   GOOGLE_API_KEY        Google/Gemini API key (forwarded to container)

set -euo pipefail

# ---- Configuration ----
VERSION_FILE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/.version"
readonly VERSION_FILE
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
# Use --wrapper-help for wrapper-specific help; --help is forwarded to Pi.
if [[ "${1:-}" == "--wrapper-help" ]]; then
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
Override resource limits: PI_MEMORY_LIMIT=8g PI_CPU_LIMIT=4 $(basename "$0") ...
Restrict network egress: PI_NETWORK=none $(basename "$0") ...
Allow rootful Podman (dangerous): PI_ALLOW_ROOTFUL=1 $(basename "$0") ...

Use --help to see Pi's own CLI help.
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

# Verify rootless Podman (the entire security model depends on it)
ROOTLESS="$(podman info --format '{{.Host.Security.Rootless}}' 2>/dev/null || echo "unknown")"
if [[ "${ROOTLESS}" != "true" ]]; then
    if [[ -n "${PI_ALLOW_ROOTFUL:-}" ]]; then
        printf 'WARNING: Not running rootless Podman (detected: %s). Continuing due to PI_ALLOW_ROOTFUL.\n' "${ROOTLESS}" >&2
    else
        printf 'ERROR: Rootless Podman required (detected: %s).\n' "${ROOTLESS}" >&2
        printf '  The container runs as root inside, relying on rootless UID mapping.\n' >&2
        printf '  Under rootful Podman, UID 0 inside = UID 0 on host, which breaks the security model.\n' >&2
        printf '  Run without sudo, or set PI_ALLOW_ROOTFUL=1 to override (not recommended).\n' >&2
        exit 1
    fi
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

# Refuse to run from sensitive directories: mounting them with :Z would
# recursively relabel SELinux contexts and expose their entire contents.
PWD_REAL="$(realpath "${PWD}" 2>/dev/null || echo "${PWD}")"
case "${PWD_REAL}" in
    / | "${HOME}" | /etc | /usr | /var | /bin | /sbin | /lib | /lib64 | /boot | /root)
        if [[ -n "${PI_ALLOW_UNSAFE_PWD:-}" ]]; then
            printf 'WARNING: Running from sensitive directory %s (PI_ALLOW_UNSAFE_PWD set).\n' "${PWD_REAL}" >&2
        else
            printf 'ERROR: Refusing to run from sensitive directory: %s\n' "${PWD_REAL}" >&2
            printf '  Mounting this directory with :Z recursively relabels SELinux contexts\n' >&2
            printf '  and exposes its entire contents (SSH keys, credentials) to the container.\n' >&2
            printf '  cd into a project subdirectory, or set PI_ALLOW_UNSAFE_PWD=1 to override.\n' >&2
            exit 1
        fi
        ;;
esac

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
# Hash both Containerfile and .version so that changing either triggers a rebuild.
# .version is the documented "single source of truth" for the Pi version.
BUILD_INPUTS_HASH=""
if [[ -f "${SCRIPT_DIR}/Containerfile" ]]; then
    BUILD_INPUTS_HASH="$( (cat "${SCRIPT_DIR}/Containerfile"; cat "${VERSION_FILE}" 2>/dev/null || true) | sha256sum | cut -d' ' -f1)"
fi

NEEDS_REBUILD=false
if ! podman image exists "${IMAGE_NAME}" 2>/dev/null; then
    debug "Image ${IMAGE_NAME} not found."
    NEEDS_REBUILD=true
else
    # Check image label for build-inputs hash
    LABEL_HASH="$(podman image inspect "${IMAGE_NAME}" --format '{{index .Labels "build-inputs-hash"}}' 2>/dev/null || true)"
    if [[ -n "${BUILD_INPUTS_HASH}" && "${BUILD_INPUTS_HASH}" != "${LABEL_HASH}" ]]; then
        debug "Containerfile or .version changed (hash mismatch). Rebuilding."
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

    # Add build-inputs hash as a label for staleness detection
    if [[ -n "${BUILD_INPUTS_HASH}" ]]; then
        BUILD_ARGS+=(--label "build-inputs-hash=${BUILD_INPUTS_HASH}")
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
# Note: --init runs a tiny init as PID 1 that forwards signals to Pi and
# reaps zombies (Pi runs as a child of the init shim).
RUNTIME_ARGS+=(
    --init
    --cap-drop=ALL
    --cap-add=DAC_OVERRIDE
    --cap-add=CHOWN
    --cap-add=SETGID
    --cap-add=SETUID
    --security-opt=no-new-privileges
    --memory="${PI_MEMORY_LIMIT:-4g}"
    --cpus="${PI_CPU_LIMIT:-2}"
    --pids-limit="${PI_PIDS_LIMIT:-512}"
    --read-only
    "--tmpfs" "/tmp:noexec,nosuid,size=256M"
)

# SELinux context (relabel for single container use)
RUNTIME_ARGS+=(
    -v "${HOME}/.pi:${HOME}/.pi:Z"
    -v "${HOME}/.agents:${HOME}/.agents:Z"
    -v "${PWD}:${PWD}:Z"
)

# Mount host git config read-only if present, so git commits have an identity.
if [[ -f "${HOME}/.gitconfig" ]]; then
    RUNTIME_ARGS+=(-v "${HOME}/.gitconfig:${HOME}/.gitconfig:ro")
fi

# Optional network restriction (e.g. PI_NETWORK=none to block all egress).
if [[ -n "${PI_NETWORK:-}" ]]; then
    RUNTIME_ARGS+=(--network "${PI_NETWORK}")
fi

# Podman socket: only mounted when explicitly enabled via PI_ENABLE_PODMAN.
# No :Z to avoid relabeling the host's socket.
# Podman client needs writable directories even when just querying the host socket.
if [[ "${PODMAN_SOCKET_ACTIVE}" == true ]]; then
    RUNTIME_ARGS+=(
        -e "CONTAINER_HOST=unix://${PODMAN_SOCKET}"
        -v "${PODMAN_SOCKET}:${PODMAN_SOCKET}"
        "--tmpfs" "/var/lib/containers:rw,noexec,nosuid,size=256M"
        "--tmpfs" "/run/containers:rw,noexec,nosuid,size=64M"
    )
    debug "Podman socket mounted at ${PODMAN_SOCKET}"
fi

# Working directory
RUNTIME_ARGS+=(-w "${PWD}")

# Forward host editor preferences. Default to nano, which is installed in the
# image (the slim base image does not ship vi).
RUNTIME_ARGS+=(
    -e "EDITOR=${EDITOR:-nano}"
    -e "VISUAL=${VISUAL:-nano}"
)

# Forward API keys only if set and non-empty.
# Keys are passed by name only (-e KEY, not -e KEY=value) to avoid
# exposing secret values on the process command line (visible via ps aux).
if [[ -n "${ANTHROPIC_API_KEY:-}" ]]; then
    RUNTIME_ARGS+=(-e "ANTHROPIC_API_KEY")
fi
if [[ -n "${OPENAI_API_KEY:-}" ]]; then
    RUNTIME_ARGS+=(-e "OPENAI_API_KEY")
fi
if [[ -n "${GOOGLE_API_KEY:-}" ]]; then
    RUNTIME_ARGS+=(-e "GOOGLE_API_KEY")
fi

# Forward proxy environment variables if set (by name only)
if [[ -n "${HTTP_PROXY:-}" ]]; then
    RUNTIME_ARGS+=(-e "HTTP_PROXY")
fi
if [[ -n "${HTTPS_PROXY:-}" ]]; then
    RUNTIME_ARGS+=(-e "HTTPS_PROXY")
fi
if [[ -n "${NO_PROXY:-}" ]]; then
    RUNTIME_ARGS+=(-e "NO_PROXY")
fi

# Image name
RUNTIME_ARGS+=("${IMAGE_NAME}")

# Runtime args are safe to log: API keys are forwarded by name only (-e KEY),
# so no secret values appear in RUNTIME_ARGS.
debug "Runtime args: ${RUNTIME_ARGS[*]}"
# Do not log Pi arguments verbatim: a user may pass a secret as an argument.
debug "Pi argument count: $#"

# ---- Run pi ----
exec podman run "${RUNTIME_ARGS[@]}" "$@"

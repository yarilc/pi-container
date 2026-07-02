#!/usr/bin/env bash
# pi-container image smoke tests
#
# Usage: ./test.sh [--image IMAGE_NAME]
#
# Builds a throwaway test image and verifies it. The test refuses to operate
# on a pre-existing image, and only removes the image it built itself.
#
# Tests:
#   1. Image builds successfully
#   2. `pi --version` works inside the container
#   3. Volume mounts are accessible (read-write round-trip)
#   4. HOME environment is forwarded correctly
#   5. Expected tools (git, ripgrep) are available
#   6. Container hardening flags are applied (cap-drop, read-only, seccomp)
#   7. API keys forwarded by name only (value reaches the container)
#   8. pi install npm:<pkg> works (npm cache tmpfs)
#   9. Bun runtime available when INSTALL_BUN=1 (opt-in)

set -euo pipefail

# ---- Argument parsing ----
# Default to a PID-unique tag so concurrent/leftover runs never collide.
IMAGE_NAME="pi-container-test-$$"
while [[ $# -gt 0 ]]; do
    case "$1" in
        --image)
            if [[ $# -lt 2 ]]; then
                echo "ERROR: --image requires a value" >&2
                exit 1
            fi
            IMAGE_NAME="$2"
            shift 2
            ;;
        --help|-h)
            echo "Usage: $0 [--image IMAGE_NAME]"
            exit 0
            ;;
        *)
            echo "Unknown option: $1" >&2
            exit 1
            ;;
    esac
done

readonly IMAGE_NAME

# Read Pi version from .version file for build arg
PI_VERSION="$(head -1 "$(dirname "$0")/.version" | tr -d '[:space:]')"
if [[ -z "${PI_VERSION}" ]]; then
    echo "ERROR: .version is missing or empty" >&2
    exit 1
fi
readonly PI_VERSION

# Guard: never overwrite or delete a pre-existing image (e.g. the user's
# real 'pi-container'). The test removes whatever image it builds, so it
# must only ever build a fresh, non-existent tag.
if podman image exists "${IMAGE_NAME}" 2>/dev/null; then
    echo "ERROR: Image '${IMAGE_NAME}' already exists." >&2
    echo "  This test builds and then removes its image, so it refuses to" >&2
    echo "  touch a pre-existing image. Choose a different --image name." >&2
    exit 1
fi

# ---- Cleanup ----
BUILT_IMAGE=""
TEST_DIR=""
CONTAINER_IDS=()
cleanup() {
    local exit_code=$?
    # Remove any containers we created
    for cid in "${CONTAINER_IDS[@]}"; do
        podman rm -f "${cid}" >/dev/null 2>&1 || true
    done
    [[ -n "${TEST_DIR}" && -d "${TEST_DIR}" ]] && rm -rf "${TEST_DIR}"
    # Only remove the image if we built it
    [[ -n "${BUILT_IMAGE}" ]] && podman rmi "${BUILT_IMAGE}" >/dev/null 2>&1 || true
    exit "${exit_code}"
}
trap cleanup EXIT

# ---- Test 1: Image builds ----
echo "=== Test 1: Image builds ==="
podman build --format docker -t "${IMAGE_NAME}" -f Containerfile --build-arg "PI_VERSION=${PI_VERSION}" --build-arg "INSTALL_PODMAN=0" --build-arg "INSTALL_BUN=0" .
BUILT_IMAGE="${IMAGE_NAME}"
echo "PASS"

# ---- Test 2: pi --version ----
echo ""
echo "=== Test 2: pi --version ==="
VERSION="$(podman run --rm "${IMAGE_NAME}" --version 2>/dev/null)"
echo "Pi version: ${VERSION}"
if [[ -z "${VERSION}" ]]; then
    echo "FAIL: --version returned empty"
    exit 1
fi
echo "PASS"

# ---- Test 3: Volume mounts ----
echo ""
echo "=== Test 3: Volume mounts ==="
# Use absolute path: Podman volume mounts require absolute paths
SCRIPT_ABS_DIR="$(cd "$(dirname "$0")" && pwd -P)"
TEST_DIR="$(mktemp -d "${SCRIPT_ABS_DIR}/.container-test-XXXXXX")"

# The container write is synchronous for bind mounts; verify it round-trips.
podman run --rm \
    -v "${TEST_DIR}:/workspace:Z" \
    -w "/workspace" \
    --entrypoint bash \
    "${IMAGE_NAME}" \
    -c 'echo "mount-ok" > /workspace/test.txt && cat /workspace/test.txt'

RESULT="$(cat "${TEST_DIR}/test.txt" 2>/dev/null || true)"
if [[ "${RESULT}" != "mount-ok" ]]; then
    echo "FAIL: Volume mount not working (expected 'mount-ok', got '${RESULT}')"
    exit 1
fi
echo "PASS"

# ---- Test 4: HOME environment ----
echo ""
echo "=== Test 4: HOME environment ==="
# Use a private tmpdir inside TEST_DIR instead of /tmp:/tmp:Z (F-05)
TEST_TMP="${TEST_DIR}/tmp-home"
mkdir -p "${TEST_TMP}"
podman run --rm \
    -e "HOME=${TEST_TMP}" \
    -v "${TEST_TMP}:${TEST_TMP}:Z" \
    --entrypoint bash \
    "${IMAGE_NAME}" \
    -c '[ "$HOME" = "'"${TEST_TMP}"'" ]'

echo "PASS"

# ---- Test 5: Expected tools (git, rg) are available ----
echo ""
echo "=== Test 5: Expected tools (git, rg, nano) are available ==="
podman run --rm \
    --entrypoint bash \
    "${IMAGE_NAME}" \
    -c 'git --version && rg --version && nano --version'
echo "PASS"

# ---- Test 6: Container hardening (cap-drop, read-only, no-new-privileges) ----
echo ""
echo "=== Test 6: Container hardening ==="
# Create a container (without --rm) to inspect its configuration
CID="$(podman create \
    --cap-drop=ALL \
    --cap-add=DAC_OVERRIDE \
    --cap-add=CHOWN \
    --cap-add=SETGID \
    --cap-add=SETUID \
    --security-opt=no-new-privileges \
    --read-only \
    --tmpfs /tmp:noexec,nosuid,size=256M \
    --tmpfs "${HOME}/.npm:rw,noexec,nosuid,size=256M" \
    "${IMAGE_NAME}" --version 2>/dev/null)"
CONTAINER_IDS+=("${CID}")

# Check that capabilities were dropped (CapDrop should not be empty).
# Podman v4+ expands --cap-drop=ALL into the full list of droppable caps
# rather than storing the literal "ALL", so we verify non-empty.
# We do not check CapAdd because its contents vary across Podman versions
# (some versions merge drop+add into CapDrop).
CAPDROP="$(podman inspect "${CID}" --format '{{join .HostConfig.CapDrop ","}}')"
if [[ -z "${CAPDROP}" ]]; then
    echo "FAIL: CapDrop is empty — --cap-drop=ALL was not applied"
    exit 1
fi

# Check read-only rootfs
READONLY="$(podman inspect "${CID}" --format '{{.HostConfig.ReadonlyRootfs}}')"
if [[ "${READONLY}" != "true" ]]; then
    echo "FAIL: ReadonlyRootfs is not true: ${READONLY}"
    exit 1
fi

# Check no-new-privileges
SECOPTS="$(podman inspect "${CID}" --format '{{join .HostConfig.SecurityOpt ","}}')"
if ! echo "${SECOPTS}" | grep -q "no-new-privileges"; then
    echo "FAIL: no-new-privileges missing from SecurityOpt: ${SECOPTS}"
    exit 1
fi

# Check that tmpfs is present for /tmp (stored in HostConfig.Tmpfs, not Mounts)
TMPFS="$(podman inspect "${CID}" --format '{{json .HostConfig.Tmpfs}}')"
if ! echo "${TMPFS}" | grep -q '"/tmp"'; then
    echo "FAIL: /tmp tmpfs mount not found in HostConfig.Tmpfs: ${TMPFS}"
    exit 1
fi
# Check that the npm cache tmpfs is present at ~/.npm (enables `pi install`)
if ! echo "${TMPFS}" | grep -qF "\"${HOME}/.npm\""; then
    echo "FAIL: ~/.npm tmpfs mount not found in HostConfig.Tmpfs: ${TMPFS}"
    exit 1
fi

podman rm -f "${CID}" >/dev/null 2>&1 || true
# Remove from cleanup list
CONTAINER_IDS=("${CONTAINER_IDS[@]/${CID}}")
echo "PASS"

# ---- Test 7: Secret propagation (key available inside container) ----
echo ""
echo "=== Test 7: Secret propagation ==="
# Verify that -e KEY (name only) forwards a host env var into the container.
#
# NOTE: The wrapper's real security property — that the secret VALUE never
# appears on the `podman run` argv (visible via `ps aux`) — is verified in
# test-wrapper.sh Test 2 using a fake podman that captures argv. That cannot
# be tested here with real podman.
#
# Podman resolves -e KEY at create time from the creating process's
# environment and stores KEY=value in Config.Env. That Config.Env exposure is
# a documented residual risk (see SECURITY.md), not something this test
# checks. Here we only verify the value reaches the container.
CID3="$(ANTHROPIC_API_KEY=test-key-value-12345 podman create \
    -e "ANTHROPIC_API_KEY" \
    --entrypoint bash \
    "${IMAGE_NAME}" -c 'echo "${ANTHROPIC_API_KEY}"' 2>/dev/null)"
CONTAINER_IDS+=("${CID3}")

OUTPUT="$(podman start -a "${CID3}" 2>/dev/null || true)"
if echo "${OUTPUT}" | grep -q "test-key-value-12345"; then
    : # key value available inside container
else
    echo "FAIL: Key value not propagated (got: '${OUTPUT}')"
    exit 1
fi

podman rm -f "${CID3}" >/dev/null 2>&1 || true
CONTAINER_IDS=("${CONTAINER_IDS[@]/${CID3}}")
echo "PASS"

# ---- Test 8: pi install npm:<pkg> works (npm cache tmpfs) ----
echo ""
echo "=== Test 8: pi install npm:pi-web-access (npm cache tmpfs) ==="
# Reproduce the wrapper's mount strategy: only ~/.pi, ~/.agents, and $PWD are
# writable bind mounts; the rest of $HOME stays on the read-only overlay, so
# npm's default cache at ~/.npm is unwritable unless the ~/.npm tmpfs is
# present. Use a synthetic HOME (/home/testuser) so the test never touches
# the real ~/.pi on the host.
EXT_HOME="/home/testuser"
EXT_PI="${TEST_DIR}/ext-pi"
EXT_AGENTS="${TEST_DIR}/ext-agents"
EXT_PROJECT="${TEST_DIR}/ext-project"
mkdir -p "${EXT_PI}" "${EXT_AGENTS}" "${EXT_PROJECT}"

INSTALL_OUTPUT="$(timeout 180 podman run --rm \
    --read-only \
    --tmpfs /tmp:noexec,nosuid,size=256M \
    --tmpfs "${EXT_HOME}/.npm:rw,noexec,nosuid,size=256M" \
    -e "HOME=${EXT_HOME}" \
    -v "${EXT_PI}:${EXT_HOME}/.pi:Z" \
    -v "${EXT_AGENTS}:${EXT_HOME}/.agents:Z" \
    -v "${EXT_PROJECT}:${EXT_PROJECT}:Z" \
    -w "${EXT_PROJECT}" \
    --entrypoint bash \
    "${IMAGE_NAME}" \
    -c 'pi install npm:pi-web-access 2>&1; echo "EXIT=$?"' 2>&1 </dev/null)"

if ! echo "${INSTALL_OUTPUT}" | grep -q "Installed npm:pi-web-access"; then
    echo "FAIL: pi install npm:pi-web-access did not succeed"
    echo "${INSTALL_OUTPUT}" | tail -15
    exit 1
fi
# Confirm the package actually landed in the user-scope install root.
if [[ ! -d "${EXT_PI}/agent/npm/node_modules/pi-web-access" ]]; then
    echo "FAIL: pi-web-access not installed under ~/.pi/agent/npm/node_modules"
    exit 1
fi
echo "PASS"

# ---- Test 9: PI_ENABLE_BUN bakes the Bun runtime into the image ----
echo ""
echo "=== Test 9: Bun runtime available when INSTALL_BUN=1 ==="
# Build a dedicated image with INSTALL_BUN=1 so the default test image stays
# bun-free (verifying bun is truly opt-in). The cleanup trap removes it.
BUN_IMAGE_NAME="${IMAGE_NAME}-bun"
if podman image exists "${BUN_IMAGE_NAME}" 2>/dev/null; then
    echo "ERROR: Image '${BUN_IMAGE_NAME}' already exists." >&2
    exit 1
fi
podman build --format docker -t "${BUN_IMAGE_NAME}" -f Containerfile \
    --build-arg "PI_VERSION=${PI_VERSION}" \
    --build-arg "INSTALL_PODMAN=0" \
    --build-arg "INSTALL_BUN=1" \
    --build-arg "BUN_VERSION=bun-v1.3.14" .
BUILT_IMAGE="${BUN_IMAGE_NAME} ${BUILT_IMAGE}"
# Verify bun is on PATH and reports the expected version
BUN_VERSION_OUT="$(podman run --rm --entrypoint bash "${BUN_IMAGE_NAME}" -c 'bun --version')"
if [[ -z "${BUN_VERSION_OUT}" ]]; then
    echo "FAIL: bun --version returned empty"
    exit 1
fi
echo "Bun version: ${BUN_VERSION_OUT}"
# Verify the default test image does NOT contain bun (opt-in is enforced)
if podman run --rm --entrypoint bash "${IMAGE_NAME}" -c 'command -v bun' 2>/dev/null | grep -q bun; then
    echo "FAIL: bun present in default image (should be opt-in only)"
    exit 1
fi
echo "PASS"

echo ""
echo "=== All tests passed ==="

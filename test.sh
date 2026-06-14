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
cleanup() {
    local exit_code=$?
    [[ -n "${TEST_DIR}" && -d "${TEST_DIR}" ]] && rm -rf "${TEST_DIR}"
    # Only remove the image if we built it
    [[ -n "${BUILT_IMAGE}" ]] && podman rmi "${BUILT_IMAGE}" >/dev/null 2>&1 || true
    exit "${exit_code}"
}
trap cleanup EXIT

# ---- Test 1: Image builds ----
echo "=== Test 1: Image builds ==="
podman build -t "${IMAGE_NAME}" -f Containerfile .
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
TEST_DIR="$(mktemp -d "$(dirname "$0")/.container-test-XXXXXX")"

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
podman run --rm \
    -e "HOME=/tmp/test-home" \
    -v /tmp:/tmp:Z \
    --entrypoint bash \
    "${IMAGE_NAME}" \
    -c '[ "$HOME" = "/tmp/test-home" ]'

echo "PASS"

# ---- Test 5: Expected tools (git, rg) are available ----
echo ""
echo "=== Test 5: Expected tools (git, rg, nano) are available ==="
podman run --rm \
    --entrypoint bash \
    "${IMAGE_NAME}" \
    -c 'git --version && rg --version && nano --version'
echo "PASS"

echo ""
echo "=== All tests passed ==="

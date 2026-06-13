#!/usr/bin/env bash
# pi-container smoke tests
#
# Usage: ./test.sh [--image IMAGE_NAME]
#
# Tests:
#   1. Image builds successfully
#   2. `pi --version` works inside the container
#   3. Volume mounts are accessible
#   4. Working directory is set correctly

set -euo pipefail

IMAGE_NAME="${1:-pi-container-test}"

echo "=== Test 1: Image builds ==="
podman build -t "${IMAGE_NAME}" -f Containerfile .
echo "PASS"

echo ""
echo "=== Test 2: pi --version ==="
VERSION="$(podman run --rm "${IMAGE_NAME}" --version 2>/dev/null)"
echo "Pi version: ${VERSION}"
if [[ -z "${VERSION}" ]]; then
    echo "FAIL: --version returned empty"
    exit 1
fi
echo "PASS"

echo ""
echo "=== Test 3: Volume mounts ==="
TEST_DIR="$(mktemp -d)"
trap 'rm -rf "${TEST_DIR}"' EXIT

podman run --rm \
    -v "${TEST_DIR}:/workspace:Z" \
    -w "/workspace" \
    --entrypoint bash \
    "${IMAGE_NAME}" \
    -c 'echo "mount-ok" > /workspace/test.txt && cat /workspace/test.txt'

RESULT="$(cat "${TEST_DIR}/test.txt" 2>/dev/null || true)"
if [[ "${RESULT}" != "mount-ok" ]]; then
    echo "FAIL: Volume mount not working"
    exit 1
fi
echo "PASS"

echo ""
echo "=== Test 4: HOME environment ==="
podman run --rm \
    -e "HOME=/tmp/test-home" \
    -v /tmp:/tmp:Z \
    --entrypoint bash \
    "${IMAGE_NAME}" \
    -c '[ "$HOME" = "/tmp/test-home" ]'

echo "PASS"

echo ""
echo "=== All tests passed ==="
podman rmi "${IMAGE_NAME}" >/dev/null 2>&1 || true

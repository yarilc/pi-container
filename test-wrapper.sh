#!/usr/bin/env bash
# pi-container wrapper-logic tests
#
# These tests exercise pi-container.sh itself (the security boundary) WITHOUT
# building or running a real container. A fake `podman` on PATH records the
# arguments the wrapper would pass to `podman run`, so we can assert that the
# hardening flags, secret handling, and the rootless gate behave correctly.
#
# Usage: ./test-wrapper.sh

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
WRAPPER="${SCRIPT_DIR}/pi-container.sh"

# Create the work dir under the script dir (not /tmp): the hardened container
# may mount /tmp noexec, which would prevent executing the fake podman.
FAKE_DIR="$(mktemp -d "${SCRIPT_DIR}/.wrapper-test-XXXXXX")"
CAPTURE="${FAKE_DIR}/run-args.txt"
FAKE_HOME="${FAKE_DIR}/home"
PROJECT_DIR="${FAKE_DIR}/project"
mkdir -p "${FAKE_HOME}" "${PROJECT_DIR}"

cleanup() { rm -rf "${FAKE_DIR}"; }
trap cleanup EXIT

# ---- Fake podman ----
# Records `run` arguments to PODMAN_CAPTURE; simulates rootless via FAKE_ROOTLESS.
cat > "${FAKE_DIR}/podman" <<'FAKE'
#!/usr/bin/env bash
case "${1:-}" in
    --version) echo "podman version 4.9.3" ;;
    info)      echo "${FAKE_ROOTLESS:-true}" ;;
    image)
        case "${2:-}" in
            exists)  exit 1 ;;   # pretend not built -> deterministic rebuild path
            inspect) echo "" ;;
        esac
        ;;
    build) exit 0 ;;
    run)
        shift
        : > "${PODMAN_CAPTURE}"
        for a in "$@"; do printf '%s\n' "${a}" >> "${PODMAN_CAPTURE}"; done
        exit 0
        ;;
esac
exit 0
FAKE
chmod +x "${FAKE_DIR}/podman"

# ---- Helpers ----
PASS_COUNT=0
fail() { echo "FAIL: $1" >&2; exit 1; }
pass() { PASS_COUNT=$((PASS_COUNT + 1)); echo "PASS"; }

# Run the wrapper with the fake podman first on PATH, from a safe project dir.
# Extra VAR=value pairs may be passed before the wrapper args via env.
run_wrapper() {
    ( cd "${PROJECT_DIR}" && \
      env PATH="${FAKE_DIR}:${PATH}" HOME="${FAKE_HOME}" PODMAN_CAPTURE="${CAPTURE}" "$@" \
      bash "${WRAPPER}" --version </dev/null )
}

assert_capture_has() {
    grep -qF -- "$1" "${CAPTURE}" || fail "$2 (missing: $1)"
}
assert_capture_lacks() {
    ! grep -qF -- "$1" "${CAPTURE}" || fail "$2 (unexpectedly found: $1)"
}

# ---- Test 1: hardening flags are present ----
echo "=== Test 1: container hardening flags ==="
: > "${CAPTURE}"
run_wrapper ANTHROPIC_API_KEY=supersecret123 >/dev/null 2>&1
for flag in "--read-only" "--cap-drop=ALL" "--security-opt=no-new-privileges" "--init" "--rm"; do
    assert_capture_has "${flag}" "hardening flag absent"
done
pass

# ---- Test 2: API keys forwarded by name, never by value ----
echo ""
echo "=== Test 2: API key forwarded by name only (no value on argv) ==="
assert_capture_has "ANTHROPIC_API_KEY" "API key name not forwarded"
assert_capture_lacks "supersecret123" "API key VALUE leaked onto podman run argv"
assert_capture_lacks "ANTHROPIC_API_KEY=supersecret123" "API key passed as KEY=value"
pass

# ---- Test 3: rootless gate blocks rootful Podman ----
echo ""
echo "=== Test 3: rootless gate refuses rootful Podman ==="
if run_wrapper FAKE_ROOTLESS=false >/dev/null 2>"${FAKE_DIR}/err.txt"; then
    fail "wrapper did not exit non-zero under rootful Podman"
fi
grep -q "Rootless Podman required" "${FAKE_DIR}/err.txt" || fail "missing rootless error message"
pass

# ---- Test 4: PI_ALLOW_ROOTFUL override continues with a warning ----
echo ""
echo "=== Test 4: PI_ALLOW_ROOTFUL override ==="
: > "${CAPTURE}"
run_wrapper FAKE_ROOTLESS=false PI_ALLOW_ROOTFUL=1 >/dev/null 2>"${FAKE_DIR}/err.txt"
grep -q "WARNING" "${FAKE_DIR}/err.txt" || fail "override did not warn"
assert_capture_has "--read-only" "override did not proceed to run"
pass

# ---- Test 5: --wrapper-help prints usage and does not invoke run ----
echo ""
echo "=== Test 5: --wrapper-help ==="
: > "${CAPTURE}"
OUT="$( cd "${PROJECT_DIR}" && env PATH="${FAKE_DIR}:${PATH}" HOME="${FAKE_HOME}" \
        PODMAN_CAPTURE="${CAPTURE}" bash "${WRAPPER}" --wrapper-help </dev/null )"
echo "${OUT}" | grep -q "Runs Pi Coding Agent in a Podman container" || fail "wrapper help text missing"
[[ ! -s "${CAPTURE}" ]] || fail "--wrapper-help should not invoke podman run"
pass

# ---- Test 6: --help is forwarded to Pi (not intercepted) ----
echo ""
echo "=== Test 6: --help is forwarded to Pi ==="
: > "${CAPTURE}"
( cd "${PROJECT_DIR}" && env PATH="${FAKE_DIR}:${PATH}" HOME="${FAKE_HOME}" \
    PODMAN_CAPTURE="${CAPTURE}" bash "${WRAPPER}" --help </dev/null >/dev/null 2>&1 )
assert_capture_has "--help" "--help was not forwarded to the container"
pass

# ---- Test 7: PI_NETWORK restricts networking ----
echo ""
echo "=== Test 7: PI_NETWORK=none restricts egress ==="
: > "${CAPTURE}"
run_wrapper PI_NETWORK=none >/dev/null 2>&1
assert_capture_has "none" "PI_NETWORK value not applied"
pass

echo ""
echo "=== All ${PASS_COUNT} wrapper tests passed ==="

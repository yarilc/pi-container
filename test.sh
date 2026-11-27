#!/usr/bin/env bash
# Credential-free image and actual-wrapper acceptance, with owned image cleanup.
set -Eeuo pipefail
root=$(CDPATH='' cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)
image="localhost/pi-container-test-$$"
while (($#)); do
    case "$1" in
        --image) [[ $# -ge 2 ]] || { printf '%s\n' '--image needs a value' >&2; exit 1; }; image=$2; shift 2 ;;
        --help|-h) printf 'Usage: test.sh [--image IMAGE]\nBuild a disposable image and run credential-free rootless acceptance.\n'; exit 0 ;;
        *) printf 'Unknown option: %s\n' "$1" >&2; exit 1 ;;
    esac
done
if podman image exists "$image"; then
    printf 'Refusing to replace pre-existing test image: %s\n' "$image" >&2; exit 1
else
    image_status=$?
    [[ "$image_status" == 1 ]] || exit "$image_status"
fi
owned=0
cleanup() {
    status=$?
    ((owned == 0)) || podman rmi "$image" >/dev/null || true
    return "$status"
}
trap cleanup EXIT
info=$(podman info --format '{{.Host.Security.Rootless}} {{.Host.OS}}')
[[ "$info" == 'true linux' ]] || { printf 'Linux rootless Podman is required\n' >&2; exit 1; }
# The wrapper's build-only operation builds the image with the launcher core's
# build arguments and build-inputs-hash label.
owned=1
PI_CONTAINER_IMAGE="$image" PI_CONTAINER_NETWORK=unrestricted PI_CONTAINER_MAINTENANCE=1 \
    bash "$root/pi-container.sh" --container-build
# Actual wrapper acceptance verifies the built image, installation, ownership,
# temp mounts, worktrees, session container engine, native timeout, and bounded signals.
PI_CONTAINER_IMAGE="$image" bash "$root/tests/run-runtime.sh"

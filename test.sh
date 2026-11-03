#!/usr/bin/env bash
# Credential-free image and actual-wrapper acceptance, with owned image cleanup.
set -Eeuo pipefail
root=$(CDPATH='' cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)
image="localhost/pi-container-test-$$"
while (($#)); do
    case "$1" in
        --image) [[ $# -ge 2 ]] || { printf '%s\n' '--image needs a value' >&2; exit 1; }; image=$2; shift 2 ;;
        --help|-h) printf 'Usage: test.sh [--image IMAGE]\nBuild a disposable image and run credential-free rootless acceptance, including Bun.\n'; exit 0 ;;
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
version=$(head -1 "$root/.version" | tr -d '[:space:]')
[[ -n "$version" ]] || exit 1
hash=$({ cat "$root/Containerfile" "$root/.containerignore" "$root/.version"; printf 'INSTALL_PODMAN=0\nINSTALL_BUN=0\nBUN_VERSION=bun-v1.3.14\n'; } | sha256sum)
hash=${hash%% *}
podman build --format docker --tag "$image" --file "$root/Containerfile" \
    --build-arg "PI_VERSION=$version" --build-arg INSTALL_PODMAN=0 --build-arg INSTALL_BUN=0 \
    --label "build-inputs-hash=$hash" "$root"
owned=1
# Actual wrapper acceptance verifies the built image, installation, ownership,
# temp mounts, worktrees, delegated children, native timeout, and bounded signals.
PI_IMAGE_NAME="$image" PI_TEST_BUN=1 bash "$root/tests/run-runtime.sh"

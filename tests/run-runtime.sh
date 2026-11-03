#!/usr/bin/env bash
# Execute credential-free acceptance from native Linux volume storage.
set -Eeuo pipefail
root=$(CDPATH='' cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)
image=${PI_IMAGE_NAME:-pi-container}
command -v podman >/dev/null || { printf 'Podman is required\n' >&2; exit 1; }
info=$(podman info --format '{{.Host.Security.Rootless}} {{.Host.OS}}')
[[ "$info" == 'true linux' ]] || { printf 'A Linux rootless Podman engine is required\n' >&2; exit 1; }
podman image exists "$image" || { printf 'Build the Pi image first: PI_IMAGE_NAME=%s ./pi-container.sh --container-build --version\n' "$image" >&2; exit 1; }
socket=${PI_PODMAN_SOCKET:-}
if [[ -z "$socket" && "${CONTAINER_HOST:-}" == unix:///?* ]]; then socket=${CONTAINER_HOST#unix://}; fi
socket=${socket:-${XDG_RUNTIME_DIR:-/run/user/$(id -u)}/podman/podman.sock}
response=$(podman --remote --url "unix://$socket" info --format '{{.Host.Security.Rootless}}{{"\n"}}{{.Host.RemoteSocket.Path}}')
[[ "$response" == true$'\n'/* && "$response" != *$'\r'* ]] || { printf 'An accessible rootless Unix service with an absolute host socket path is required\n' >&2; exit 1; }
host_socket=${response#*$'\n'}
[[ "$host_socket" != *$'\n'* && -n "${host_socket//\//}" ]] || exit 1
runner="localhost/pi-runtime-runner-$(id -u)-$$"
volume=''
runner_created=0
cleanup() {
    status=$?
    [[ -z "$volume" ]] || podman volume rm --force "$volume" >/dev/null || true
    ((runner_created == 0)) || podman rmi "$runner" >/dev/null || true
    return "$status"
}
trap cleanup EXIT
if podman image exists "$runner"; then
    printf 'Refusing to replace existing runner image: %s\n' "$runner" >&2; exit 1
else
    image_status=$?
    [[ "$image_status" == 1 ]] || exit "$image_status"
fi
podman build --tag "$runner" --file "$root/tests/Containerfile.runner" "$root/tests"
runner_created=1
volume=$(podman volume create)
native_root=$(podman volume inspect --format '{{.Mountpoint}}' "$volume")
podman run --rm --interactive --userns=keep-id --user "$(id -u):$(id -g)" \
    --volume "$root:$root:ro" --volume "$native_root:$native_root:rw" \
    --volume "$host_socket:/run/podman/podman.sock:rw" --workdir "$root" \
    --env CONTAINER_HOST=unix:///run/podman/podman.sock \
    --env "PI_TEST_RUNNER_IMAGE=$runner" --env PI_RUNTIME_TESTS=1 --env "PI_TEST_ROOT=$native_root" \
    --env "PI_IMAGE_NAME=$image" --env "PI_TEST_BUN=${PI_TEST_BUN:-0}" \
    --entrypoint python3 "$runner" -B -m unittest discover -s tests -p test_runtime.py -v "$@"

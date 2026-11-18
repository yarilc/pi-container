#!/usr/bin/env bash
# Execute credential-free acceptance from native Linux volume storage.
set -Eeuo pipefail
root=$(CDPATH='' cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)
image=${PI_CONTAINER_IMAGE:-localhost/pi-container:latest}
command -v podman >/dev/null || { printf 'Podman is required\n' >&2; exit 1; }
info=$(podman info --format '{{.Host.Security.Rootless}} {{.Host.OS}}')
[[ "$info" == 'true linux' ]] || { printf 'A Linux rootless Podman engine is required\n' >&2; exit 1; }
podman image exists "$image" || { printf 'Build the Pi image first: PI_CONTAINER_NETWORK=unrestricted PI_CONTAINER_MAINTENANCE=1 PI_CONTAINER_IMAGE=%s ./pi-container.sh --container-build\n' "$image" >&2; exit 1; }
# Mode selection: the default runs the unrestricted runtime suite.
pattern=test_runtime.py
selection_env=(--env PI_RUNTIME_TESTS=1 --env SANDBOX_RUNTIME_TESTS=1)
guard_environment=()
project_mode=ro
shared=(test_reference_copy test_alignment test_launcher test_agent_profile test_network_policy test_mux test_tls_client_hello
    test_tls_proxy test_platform test_qualification test_guard test_session test_network_feasibility)
case "${1:-}" in
    # The shared launcher tests and this wrapper's own: test_launcher.py, test_wrapper.py.
    --wrapper) pattern='test_[lw][ar][au]*.py' ;;
    --shared) pattern='' ;;
    --qualification) pattern=test_qualification.py ;;
    --setup) pattern=test_setup.py; project_mode=rw ;;
    --setup-runtime) pattern=test_setup_runtime.py; project_mode=rw ;;
    --network-feasibility) pattern=test_network_feasibility.py ;;
    --network) pattern=test_network_runtime.py; project_mode=rw ;;
    --network-policy) pattern=test_network_policy.py ;;
    --mux) pattern=test_mux.py ;;
    --guard|--guard-idle)
        pattern=test_guard.py
        guard_toolchain=$(podman image inspect --format '{{.Id}}' \
            "${SANDBOX_GUARD_TOOLCHAIN:-localhost/pi-guard-toolchain:development}")
        guard_environment=(--env SANDBOX_GUARD_TESTS=1 --env "SANDBOX_GUARD_TOOLCHAIN=$guard_toolchain")
        if [[ "$1" == --guard-idle ]]; then
            guard_environment+=(--env SANDBOX_IDLE_TESTS=1)
            set -- "$1" -k test_guarded_multiplex_idle_resume "${@:2}"
        fi
        ;;
    *) set -- '' "$@" ;;
esac
shift
if [[ -n "$pattern" ]]; then
    selection=(discover -s tests -p "$pattern" -v)
else
    selection=(-v "${shared[@]/#/tests.}")
    selection_env=()
fi
socket=${PI_CONTAINER_PODMAN_SOCKET:-}
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
# Wrapper fixtures need private, executable temporary storage: the runner's
# /tmp is world-writable, and the toolchain library refuses such ancestors.
podman run --rm --interactive --userns=keep-id --user "$(id -u):$(id -g)" \
    --volume "$root:$root:$project_mode" --volume "$native_root:$native_root:rw" \
    --volume "$host_socket:/run/podman/podman.sock:rw" --workdir "$root" \
    --env CONTAINER_HOST=unix:///run/podman/podman.sock \
    --env "PI_TEST_RUNNER_IMAGE=$runner" "${selection_env[@]}" --env "PI_TEST_ROOT=$native_root" \
    --env "SANDBOX_TEST_STATE_ROOT=$native_root" "${guard_environment[@]}" \
    --env "PI_CONTAINER_IMAGE=$image" \
    --tmpfs /tmp:rw,exec,nosuid,nodev,mode=1777 \
    --mount type=tmpfs,destination=/sandbox-test-tmp,tmpfs-mode=0700,U=true,tmpfs-size=1g \
    --env SANDBOX_TEST_TMPDIR=/sandbox-test-tmp \
    --entrypoint python3 "$runner" -B -m unittest "${selection[@]}" "$@"

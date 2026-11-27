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
# Shared suites copied from the reference, run without real-engine opt-ins: every
# shared test module of tests/test_alignment.py except test_setup, which --setup
# runs with a writable checkout, plus Pi's image-pin checks.
shared=(test_reference_copy test_alignment test_launcher test_agent_profile test_network_policy test_mux test_tls_client_hello
    test_tls_proxy test_platform test_qualification test_guard test_session test_network_feasibility
    test_engine test_toolchains test_windows_bootstrap test_windows_enter test_image_pins)
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
# The launch service's socket: a Unix CONTAINER_HOST, else the runtime directory's.
# Host Podman delegation was removed, so no delegation override applies.
socket=''
if [[ "${CONTAINER_HOST:-}" == unix:///?* ]]; then socket=${CONTAINER_HOST#unix://}; fi
socket=${socket:-${XDG_RUNTIME_DIR:-/run/user/$(id -u)}/podman/podman.sock}
response=$(podman --remote --url "unix://$socket" info --format '{{.Host.Security.Rootless}}{{"\n"}}{{.Host.RemoteSocket.Path}}')
[[ "$response" == true$'\n'* && "$response" != *$'\r'* ]] || { printf 'An accessible rootless Unix service with an absolute host socket path is required\n' >&2; exit 1; }
host_socket=${response#*$'\n'}
host_socket=${host_socket#unix://}
[[ "$host_socket" == /* && "$host_socket" != *$'\n'* && -n "${host_socket//\//}" ]] || { printf 'An accessible rootless Unix service with an absolute host socket path is required\n' >&2; exit 1; }
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
optional_env=()
for name in PI_CONTAINER_ENGINE_IMAGE SANDBOX_TEST_ENGINE_SAMPLE SANDBOX_TEST_SYSTEMD_SAMPLE; do
    [[ -z "${!name:-}" ]] || optional_env+=(--env "$name=${!name}")
done
# Wrapper fixtures need private, executable temporary storage: the runner's
# /tmp is world-writable, and the toolchain library refuses such ancestors.
podman run --rm --interactive --userns=keep-id --user "$(id -u):$(id -g)" \
    --volume "$root:$root:$project_mode" --volume "$native_root:$native_root:rw" \
    --volume "$host_socket:/run/podman/podman.sock:rw" --workdir "$root" \
    --env CONTAINER_HOST=unix:///run/podman/podman.sock \
    --env "PI_TEST_RUNNER_IMAGE=$runner" "${selection_env[@]}" --env "PI_TEST_ROOT=$native_root" \
    --env "SANDBOX_TEST_STATE_ROOT=$native_root" "${guard_environment[@]}" \
    --env "PI_CONTAINER_IMAGE=$image" "${optional_env[@]}" \
    --tmpfs /tmp:rw,exec,nosuid,nodev,mode=1777 \
    --mount type=tmpfs,destination=/sandbox-test-tmp,tmpfs-mode=0700,U=true,tmpfs-size=1g \
    --env SANDBOX_TEST_TMPDIR=/sandbox-test-tmp \
    --entrypoint python3 "$runner" -B -m unittest "${selection[@]}" "$@"

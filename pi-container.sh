#!/usr/bin/env bash
# Transparent Pi sessions with a verified rootless execution boundary.
set -Eeuo pipefail

die() { printf 'pi-container: %s\n' "$*" >&2; exit 1; }
debug() { if [[ -n "${PI_DEBUG:-}" ]]; then printf '[DEBUG] %s\n' "$*" >&2; fi; }
usage() {
    cat <<'HELP'
Usage: pi-container.sh [container options] [Pi arguments...]

  --container-build         force image refresh, then start the selected session
  --container-shell         start Bash instead of Pi (discard Pi arguments)
  --container-git-worktree  expose the physical workspace's immediate parent
                            read/write; retain the original working directory
  --container-help          show this help without runtime prerequisites
  --wrapper-help            alias for --container-help

All other arguments, including --help, are passed unchanged to Pi.
Launch requires a verified Linux rootless engine, without a rootful override.
Use local Podman or an explicit same-host absolute Unix CONTAINER_HOST.
Named connections, TCP/SSH, implicit remote contexts, and slash-only paths fail.
Writable ~/.pi and ~/.agents must be caller-owned, accessible, and private
(no group/other permissions). Missing writable state is created privately;
existing state is never repaired. Use native Linux storage for Unix modes.
Read-only state must already exist and be readable/traversable.
Sessions use caller UID/GID, keep-id, no capabilities, and a read-only rootfs.
No automatic SELinux relabeling or confinement overrides are performed.
Temporary /tmp and /var/tmp: 256 MiB each; /run: 32 MiB; npm cache: 256 MiB.
All temporary stores use nosuid,nodev,noexec and disappear after the session.
TTY requires terminal stdin AND stdout; redirected input and EOF are retained.
Names use a sanitized directory prefix and highest existing decimal suffix+1;
create reserves atomically with at most 20 attempts, without replacement.

Environment:
  PI_IMAGE_NAME          image name (default: pi-container)
  PI_ENABLE_PODMAN       delegation/client enabled only for exact 1
  PI_PODMAN_SOCKET       absolute socket override; then Unix CONTAINER_HOST;
                         then ${XDG_RUNTIME_DIR:-/run/user/<uid>}/podman/podman.sock
  PI_ENABLE_BUN          nonempty enables optional Bun (legacy switch semantics)
  PI_BUN_VERSION         default: bun-v1.3.14; participates in image freshness
  PI_MEMORY_LIMIT        default: 4g
  PI_CPU_LIMIT           default: 2
  PI_PIDS_LIMIT          default: 512
  PI_NPM_CACHE_SIZE      default: 256M
  PI_NETWORK             optional network selection, e.g. none (default: full)
  PI_READONLY_CONFIG     nonempty mounts existing state read-only
  PI_MOUNT_GITCONFIG     0 skips optional read-only ~/.gitconfig
  PI_ALLOW_UNSAFE_PWD    nonempty bypasses the sensitive-directory guard
  PI_PULL_ALWAYS         nonempty selects --pull=always on a build
  PI_RUN_TIMEOUT         native Podman container lifetime in seconds; 0 disables
                         independent from wrapper shutdown budgets
  PI_ENV_VARS            space-separated extra variable names; never values
  PI_DEBUG               nonempty enables debug output without secret values
  EDITOR, VISUAL         defaults: nano

API keys and proxy variables are forwarded by name only when nonempty.
Engine verification rejects incomplete/extra records and CR characters.
Delegation verifies the selected rootless service and binds its reported
host-side socket to /run/podman/podman.sock; it never starts a service.
Without delegation session CONTAINER_HOST is explicitly unset, even if listed
in PI_ENV_VARS. Connection settings cannot override the selected session URI.
Delegation grants the service user's host authority, including further mounts.
Worktree mode exposes siblings in the whole immediate parent read/write.
Bun and native Pi permissions are independent of delegation.

TERM/INT/HUP select 143/130/129. The first signal is forwarded once; later
signals do not replace status or renew deadlines. Application grace: 5s.
Each control call: 5s plus 1s kill-after; client cancellation: TERM 5s, KILL 1s.
Interrupted creation: completion 5s, cancellation 5s+1s, owned removal 5s+1s.
Only this invocation's full verified CID is removed. Cancellation does not
prove the server request stopped. Unknown IDs, engine loss, or SIGKILL can
leave resources requiring manual inspection. Cleanup preserves exit codes,
including 125. Host GNU coreutils timeout is required.
HELP
}

build_image=0
shell_mode=0
git_worktree=0
args=()
for arg in "$@"; do
    case "$arg" in
        --container-help|--wrapper-help) usage; exit 0 ;;
        --container-build) build_image=1 ;;
        --container-shell) shell_mode=1 ;;
        --container-git-worktree) git_worktree=1 ;;
        *) args+=("$arg") ;;
    esac
done

for tool in podman timeout stat readlink sha256sum; do
    command -v "$tool" >/dev/null || die "$tool is required on the host"
done
script_path=$(readlink -f -- "${BASH_SOURCE[0]}")
script_dir=$(dirname -- "$script_path")
version_file=$script_dir/.version
[[ -s "$version_file" ]] || die '.version is missing or empty'
pi_version=$(head -1 "$version_file" | tr -d '[:space:]')
[[ -n "$pi_version" ]] || die '.version is missing or empty'
image=${PI_IMAGE_NAME:-pi-container}
caller_uid=$(id -u)
caller_gid=$(id -g)
[[ "${HOME:-}" == /* ]] || die 'HOME must be an absolute directory path'
workspace=$(pwd -P) || die 'Cannot resolve physical workspace'
workspace_mount=$workspace
((git_worktree == 0)) || workspace_mount=$(dirname -- "$workspace")
physical_home=$(CDPATH='' cd -- "$HOME" && pwd -P) || die 'Cannot resolve HOME'
case "$workspace_mount" in
    /|"$physical_home"|/home|/etc|/usr|/var|/bin|/sbin|/lib|/lib64|/boot|/root|/opt|/srv|/mnt|/media|/proc|/sys|/dev|/run)
        [[ -n "${PI_ALLOW_UNSAFE_PWD:-}" ]] || die "Refusing sensitive exposed directory: $workspace_mount (use a project subdirectory)"
        printf 'pi-container: WARNING: sensitive directory explicitly exposed: %s\n' "$workspace_mount" >&2 ;;
esac

[[ -z "${CONTAINER_CONNECTION:-}" ]] || die 'Named Podman connections are not supported; use local Podman or a same-host Unix CONTAINER_HOST'
case "${CONTAINER_HOST:-}" in
    '') ;;
    unix://*)
        launch_socket=${CONTAINER_HOST#unix://}
        [[ "$launch_socket" == /* && -n "${launch_socket//\//}" ]] || die 'CONTAINER_HOST requires an absolute Unix socket path beyond /' ;;
    *) die 'Unsupported Podman connection; use local Podman or an absolute same-host Unix CONTAINER_HOST' ;;
esac
engine_response=''
capture_engine_info() {
    # A success-only sentinel preserves failed queries and trailing records.
    engine_response=$(timeout --kill-after=1s 10s podman "$@" && printf '\001') || return 1
    engine_response=${engine_response%$'\001'}
    engine_response=${engine_response%$'\n'}
    [[ "$engine_response" != *$'\r'* ]]
}
capture_engine_info info --format '{{.Host.Security.Rootless}} {{.Host.OS}} {{.Host.ServiceIsRemote}}' || die 'Cannot query launch engine or invalid response; check the Linux rootless service'
read -r rootless runtime_os service_remote extra <<< "$engine_response"
[[ "$rootless" == true && "$runtime_os" == linux && -z "$extra" && "$engine_response" != *$'\n'* ]] || die 'The launch engine must report complete Linux rootless operation'
case "$service_remote" in
    false) ;;
    true) [[ "${CONTAINER_HOST:-}" == unix:///?* ]] || die 'A remote launch engine requires an explicit same-host Unix CONTAINER_HOST' ;;
    *) die 'Cannot verify launch engine ServiceIsRemote (expected true or false)' ;;
esac

install_podman=0
if [[ "${PI_ENABLE_PODMAN:-}" == 1 ]]; then
    install_podman=1
    socket=${PI_PODMAN_SOCKET:-}
    if [[ -z "$socket" && "${CONTAINER_HOST:-}" == unix:///?* ]]; then socket=${CONTAINER_HOST#unix://}; fi
    socket=${socket:-${XDG_RUNTIME_DIR:-/run/user/$caller_uid}/podman/podman.sock}
    [[ "$socket" == /* ]] || die "Podman socket path must be absolute: $socket"
    selected_socket=$socket
    socket=$(readlink -f -- "$selected_socket") || die "Cannot resolve Podman socket: $selected_socket"
    [[ -S "$socket" && -r "$socket" && -w "$socket" ]] || die "Podman socket not accessible: $selected_socket (start the rootless service explicitly; check permissions and SELinux policy)"
    capture_engine_info --remote --url "unix://$socket" info --format '{{.Host.Security.Rootless}}{{"\n"}}{{.Host.RemoteSocket.Path}}' || die "Cannot query selected Podman socket or invalid response: $socket"
    [[ "$engine_response" == true$'\n'* ]] || die 'Selected socket must report rootless true and an absolute host socket path'
    host_socket=${engine_response#*$'\n'}
    [[ "$host_socket" == /* && -n "${host_socket//\//}" && "$host_socket" != *$'\n'* ]] || die 'Selected socket must report one absolute host socket path beyond /'
fi

state_mode=rw
[[ -z "${PI_READONLY_CONFIG:-}" ]] || state_mode=ro
validate_state() {
    local path=$1 owner mode
    if [[ "$state_mode" == rw && ! -e "$path" && ! -L "$path" ]]; then
        (umask 077; mkdir -p -- "$path") || die "Cannot create private state: $path"
    fi
    [[ -d "$path" ]] || die "State is not a directory: $path"
    state_path=$(CDPATH='' cd -- "$path" && pwd -P) || die "Cannot resolve state: $path"
    [[ -r "$state_path" && -x "$state_path" ]] || die "State is not readable/traversable: $path"
    if [[ "$state_mode" == rw ]]; then
        [[ -w "$state_path" ]] || die "State is not writable: $path"
        owner=$(stat -c '%u' -- "$state_path") || die "Cannot inspect state owner: $path"
        mode=$(stat -c '%a' -- "$state_path") || die "Cannot inspect state permissions: $path"
        [[ "$owner" == "$caller_uid" ]] || die "State must belong to the calling user: $path"
        [[ "$mode" =~ ^[0-7]{3,4}$ ]] || die "Cannot verify state permissions: $path"
        (( (8#$mode & 077) == 0 )) || die "State must be private: $path (explicitly repair it or use a filesystem that enforces Unix permissions)"
    fi
}
validate_state "$HOME/.pi"; pi_state=$state_path
validate_state "$HOME/.agents"; agents_state=$state_path

install_bun=0
[[ -z "${PI_ENABLE_BUN:-}" ]] || install_bun=1
bun_version=${PI_BUN_VERSION:-bun-v1.3.14}
build_hash=$({ cat "$script_dir/Containerfile" "$script_dir/.containerignore" "$version_file"; printf 'INSTALL_PODMAN=%s\nINSTALL_BUN=%s\nBUN_VERSION=%s\n' "$install_podman" "$install_bun" "$bun_version"; } | sha256sum)
build_hash=${build_hash%% *}
needs_build=$build_image
if ((build_image == 0)); then
    if podman image exists "$image"; then
        label_hash=$(podman image inspect "$image" --format '{{index .Labels "build-inputs-hash"}}') || die "Cannot inspect staleness label for $image; check engine/storage"
        [[ "$label_hash" == "$build_hash" ]] || needs_build=1
    else
        image_status=$?
        [[ "$image_status" == 1 ]] || { printf 'pi-container: Cannot inspect image %s (status %s)\n' "$image" "$image_status" >&2; exit "$image_status"; }
        needs_build=1
    fi
fi
if ((needs_build)); then
    build_args=(--tag "$image" --file "$script_dir/Containerfile" --format docker
        --build-arg "PI_VERSION=$pi_version" --build-arg "INSTALL_PODMAN=$install_podman"
        --build-arg "INSTALL_BUN=$install_bun" --build-arg "BUN_VERSION=$bun_version"
        --label "build-inputs-hash=$build_hash")
    [[ -z "${PI_PULL_ALWAYS:-}" ]] || build_args+=(--pull=always)
    printf 'Building Pi v%s image...\n' "$pi_version" >&2
    timeout --kill-after=1s 300s podman build "${build_args[@]}" "$script_dir" </dev/null || die 'Image build failed or timed out (300s); check build output and network'
fi

podman_args=(--rm --interactive --init --read-only --read-only-tmpfs=false
    --userns=keep-id --user "$caller_uid:$caller_gid"
    --cap-drop=ALL --security-opt=no-new-privileges
    "--memory=${PI_MEMORY_LIMIT:-4g}" "--cpus=${PI_CPU_LIMIT:-2}" "--pids-limit=${PI_PIDS_LIMIT:-512}"
    --workdir "$workspace" --env "HOME=$HOME"
    --env "EDITOR=${EDITOR:-nano}" --env "VISUAL=${VISUAL:-nano}"
    --tmpfs "/tmp:rw,noexec,nosuid,nodev,mode=1777,size=256M"
    --tmpfs "/var/tmp:rw,noexec,nosuid,nodev,mode=1777,size=256M"
    --tmpfs "/run:rw,noexec,nosuid,nodev,mode=1777,size=32M"
    --tmpfs "$HOME/.npm:rw,noexec,nosuid,nodev,mode=0700,U,size=${PI_NPM_CACHE_SIZE:-256M}"
    --volume "$workspace_mount:$workspace_mount:rw"
    --volume "$pi_state:$HOME/.pi:$state_mode"
    --volume "$agents_state:$HOME/.agents:$state_mode")
if [[ -t 0 && -t 1 ]]; then
    podman_args+=(--tty)
    [[ -z "${TERM:-}" ]] || podman_args+=(--env TERM)
fi
[[ ! -f "$HOME/.gitconfig" || "${PI_MOUNT_GITCONFIG:-1}" == 0 ]] || podman_args+=(--volume "$HOME/.gitconfig:$HOME/.gitconfig:ro")
[[ -z "${PI_NETWORK:-}" ]] || podman_args+=(--network "$PI_NETWORK")
[[ -z "${PI_RUN_TIMEOUT:-}" ]] || podman_args+=(--timeout "$PI_RUN_TIMEOUT")
# Values for credentials remain in the creating client's environment, never argv.
for variable in ANTHROPIC_API_KEY OPENAI_API_KEY GOOGLE_API_KEY HTTP_PROXY HTTPS_PROXY NO_PROXY; do
    [[ -z "${!variable:-}" ]] || podman_args+=(--env "$variable")
done
extra_vars=()
read -r -a extra_vars <<< "${PI_ENV_VARS:-}"
for variable in "${extra_vars[@]}"; do
    [[ "$variable" =~ ^[a-zA-Z_][a-zA-Z0-9_]*$ ]] || die "Invalid environment variable name: $variable"
    case "$variable" in
        HOME|TERM|EDITOR|VISUAL|CONTAINER_NAME|CONTAINER_HOST|CONTAINER_CONNECTION|ANTHROPIC_API_KEY|OPENAI_API_KEY|GOOGLE_API_KEY|HTTP_PROXY|HTTPS_PROXY|NO_PROXY) continue ;;
    esac
    [[ -z "${!variable:-}" ]] || podman_args+=(--env "$variable")
done
# Last authoritative connection setting, independent of extra forwarding.
podman_args+=(--unsetenv CONTAINER_CONNECTION)
if ((install_podman)); then
    podman_args+=(--volume "$host_socket:/run/podman/podman.sock:rw"
        --env CONTAINER_HOST=unix:///run/podman/podman.sock
        --tmpfs "/var/lib/containers:rw,noexec,nosuid,nodev,mode=0700,U,size=256M"
        --tmpfs "/run/containers:rw,noexec,nosuid,nodev,mode=0700,U,size=64M")
else
    podman_args+=(--unsetenv CONTAINER_HOST)
fi
if ((shell_mode)); then podman_args+=(--entrypoint /bin/bash); args=(); fi
debug "Runtime option count: ${#podman_args[@]}; native argument count: ${#args[@]}"
container_prefix=${workspace##*/}
container_prefix=$(printf '%s' "$container_prefix" | LC_ALL=C sed -E 's/[^a-zA-Z0-9_.-]+/-/g; s/^[.-]+//; s/[.-]+$//')
container_prefix=${container_prefix:0:64}
container_prefix=${container_prefix:-pi}

container_id=''
client_pid=''
session_tmp=''
pending_signal=''
pending_status=0
attached=0
creating=0

# shellcheck disable=SC2329 # Invoked through signal/EXIT cleanup.
record_signal() {
    if ((pending_status == 0)); then
        pending_signal=$1
        pending_status=$2
    fi
    if ((attached || creating)) && [[ -n "$client_pid" ]]; then
        exit "$pending_status"
    fi
}

# An interrupted create enters EXIT reconciliation with its PID still tracked.
wait_for_create() {
    ((pending_status == 0)) || exit "$pending_status"
    local status=0
    wait "$client_pid" || status=$?
    ((pending_status == 0)) || exit "$pending_status"
    return "$status"
}

# Consult Bash's child table rather than potentially recycled process IDs.
# shellcheck disable=SC2329 # Invoked through signal/EXIT cleanup.
client_running() {
    local child
    [[ -n "$client_pid" ]] || return 1
    while IFS= read -r child; do
        [[ "$child" != "$client_pid" ]] || return 0
    done < <(jobs -p)
    return 1
}

# shellcheck disable=SC2329 # Invoked through signal/EXIT cleanup.
wait_for_client_until() {
    local deadline=$1
    while client_running; do
        ((SECONDS < deadline)) || return 1
        sleep 0.05
    done
}

# shellcheck disable=SC2329 # Invoked through signal/EXIT cleanup.
reap_client() {
    [[ -n "$client_pid" ]] || return 0
    if client_running; then
        kill -TERM "$client_pid" 2>/dev/null || true
        if ! wait_for_client_until "$((SECONDS + 5))"; then
            kill -KILL "$client_pid" 2>/dev/null || true
        fi
    fi
    if wait_for_client_until "$((SECONDS + 1))"; then
        wait "$client_pid" 2>/dev/null || true
    else
        printf 'pi-container: Cannot reap Podman client %s within deadline; inspect it explicitly\n' "$client_pid" >&2
    fi
    client_pid=''
}

recover_container_id() {
    local recovered='' has_nul=0
    [[ -z "$container_id" && -n "$session_tmp" && -s "$session_tmp/cid" ]] || return 0
    # read preserves all LFs; a NUL delimiter is itself invalid CID data.
    IFS= read -r -d '' recovered < "$session_tmp/cid" && has_nul=1
    recovered=${recovered%$'\n'}
    if ((has_nul)) || [[ ! "$recovered" =~ ^[a-f0-9]{64}$ ]]; then
        printf 'pi-container: Invalid container ID in private creation record; inspect creation explicitly\n' >&2
        return 1
    fi
    container_id=$recovered
}

# shellcheck disable=SC2329 # Invoked through signal/EXIT cleanup.
cleanup() {
    local status=$? control_status
    trap '' TERM INT HUP
    ((pending_status == 0)) || status=$pending_status
    if ((creating)); then
        if [[ -n "$client_pid" ]]; then
            wait_for_client_until "$((SECONDS + 5))" || true
            reap_client
        fi
        # The client can publish its CID while responding to cancellation.
        recover_container_id || true
        if ((pending_status)) && [[ -z "$container_id" ]]; then
            printf 'pi-container: Creation outcome unresolved for %s (no verified owned ID); inspect the engine explicitly\n' "$name" >&2
        fi
    fi
    if [[ -n "$container_id" ]]; then
        if ((pending_status && attached)); then
            if timeout --kill-after=1s 5s podman kill --signal "$pending_signal" "$container_id" >/dev/null; then
                wait_for_client_until "$((SECONDS + 5))" || true
            else
                printf 'pi-container: Cannot forward %s to owned container %s\n' "$pending_signal" "$container_id" >&2
            fi
        fi
        control_status=0
        timeout --kill-after=1s 5s podman rm --force --ignore --time 0 "$container_id" >/dev/null || control_status=$?
        if ((control_status)); then
            printf 'pi-container: Cannot remove owned container %s (status %s); check the engine and remove it explicitly\n' "$container_id" "$control_status" >&2
        fi
    fi
    reap_client
    [[ -z "$session_tmp" ]] || rm -rf -- "$session_tmp"
    return "$status"
}

trap cleanup EXIT
trap 'record_signal TERM 143' TERM
trap 'record_signal INT 130' INT
trap 'record_signal HUP 129' HUP
session_tmp=$(umask 077; mktemp -d) || die "Cannot create private session bookkeeping directory"
((pending_status == 0)) || exit "$pending_status"
names=$(podman ps --all --format '{{.Names}}') || die "Cannot list Podman containers; check the launch engine"
((pending_status == 0)) || exit "$pending_status"
next_index=0
while IFS= read -r name; do
    [[ "$name" == "$container_prefix"-* ]] || continue
    suffix=${name#"$container_prefix"-}
    [[ "$suffix" =~ ^[0-9]{1,9}$ ]] || continue
    numeric=$((10#$suffix))
    ((numeric < next_index)) || next_index=$((numeric + 1))
done <<< "$names"

for ((attempt=0; attempt<20; attempt++)); do
    ((pending_status == 0)) || exit "$pending_status"
    name="$container_prefix-$next_index"
    rm -f -- "$session_tmp/cid"
    creating=1
    podman create --name "$name" --cidfile "$session_tmp/cid" "${podman_args[@]}" --env "CONTAINER_NAME=$name" "$image" "${args[@]}" \
        </dev/null >"$session_tmp/output" 2>"$session_tmp/error" &
    client_pid=$!
    create_status=0
    wait_for_create || create_status=$?
    client_pid=''
    recover_container_id || die "Invalid container ID returned by creation"
    creating=0
    ((pending_status == 0)) || exit "$pending_status"
    if ((create_status == 0)); then
        [[ -n "$container_id" ]] || die "Creation succeeded without a container ID; outcome unresolved, inspect the engine explicitly"
        break
    fi
    cat -- "$session_tmp/error" >&2
    [[ -z "$container_id" ]] || exit "$create_status"
    exists_status=0
    podman container exists "$name" || exists_status=$?
    ((pending_status == 0)) || exit "$pending_status"
    case "$exists_status" in
        0) next_index=$((next_index + 1)) ;;
        1) exit "$create_status" ;;
        *) die "Cannot verify container name collision for $name (status $exists_status)" ;;
    esac
done
[[ -n "$container_id" ]] || die "Cannot reserve a container name after 20 attempts"
((pending_status == 0)) || exit "$pending_status"

# Explicit redirection retains redirected stdin for the background client.
attached=1
podman start --attach --interactive --sig-proxy=false "$container_id" <&0 &
client_pid=$!
if ((pending_status)); then
    exit "$pending_status"
fi
status=0
wait "$client_pid" || status=$?
((pending_status == 0)) || exit "$pending_status"
client_pid=''
exit "$status"

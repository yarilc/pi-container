#!/usr/bin/env bash
# Transparent Pi sessions with a verified rootless execution boundary.
set -Eeuo pipefail

die() { printf 'pi-container: %s\n' "$*" >&2; exit 1; }
debug() { if [[ -n "${PI_DEBUG:-}" ]]; then printf '[DEBUG] %s\n' "$*" >&2; fi; }
usage() {
    cat <<'HELP'
Usage: pi-container.sh [container options] [Pi arguments...]

Container options:
  --container-setup      interactively prepare a complete user installation and
                         its managed launcher; must be used alone
  --container-qualify    verify a prepared restricted installation with fixed
                         local controls; must be used alone
  --container-build      force image refresh, then start the selected session;
                         used alone, refresh the image and exit without a
                         session (requires PI_CONTAINER_MAINTENANCE=1)
  --container-shell      start Bash instead of Pi (discard Pi arguments)
  --container-git-worktree expose the physical workspace's immediate parent
                         read/write; retain the original working directory
  --container-help       show this help without runtime prerequisites
  --wrapper-help         alias for --container-help

All other arguments, including --help, are passed unchanged to Pi.
TERM/INT/HUP select 143/130/129. The first signal is forwarded once; later
signals do not replace status or renew deadlines. Application grace: 5s.
Each control call: 5s plus 1s kill-after; client cancellation: TERM 5s, KILL 1s.
Interrupted creation: completion 5s, cancellation 5s+1s, owned removal 5s+1s.
Only this invocation's full verified CID is removed. Cancellation does not
prove the server request stopped. Unknown IDs, engine loss, or SIGKILL can
leave resources requiring manual inspection. Cleanup preserves exit codes,
including 125. Host GNU coreutils timeout is required.
TTY requires terminal stdin AND stdout; redirected input and EOF are retained.
Names use a sanitized directory prefix and highest existing decimal suffix+1;
create reserves atomically with at most 20 attempts, without replacement.

Environment:
  PI_CONTAINER_NETWORK   offline, provider, or unrestricted; required for every
                         launch (unrestricted is the previous behavior)
  PI_CONTAINER_NETWORK_PROFILE protected provider policy profile name
                         (anthropic-api, openai-api, gemini-api or openrouter-api)
  PI_CONTAINER_NETWORK_POLICY absolute operator policy JSON path
  PI_CONTAINER_NETWORK_RUNTIME_DIR private native directory at its host path
  PI_CONTAINER_EGRESS_IMAGE immutable proxy image ID or registry digest
  PI_CONTAINER_MAINTENANCE authorize image builds and proxy pulls only with
                         exact value 1, including the build of a missing image
  PI_CONTAINER_IMAGE     image name (default: localhost/pi-container)
  PI_CONTAINER_PODMAN    delegation/client enabled only for exact 1
                         (default: disabled; other values also disable it);
                         rejected in offline and provider modes
  PI_CONTAINER_PODMAN_SOCKET absolute socket override; then Unix CONTAINER_HOST;
                         then ${XDG_RUNTIME_DIR:-/run/user/<uid>}/podman/podman.sock
  PI_CONTAINER_MEMORY_LIMIT session memory, integer with k/m/g unit (default: 4g)
  PI_CONTAINER_CPU_LIMIT    session CPUs, up to 3 decimals (default: 2)
  PI_CONTAINER_PIDS_LIMIT   session process limit (default: 512)
                         Budgets cannot be disabled; each is enforced only when
                         the rootless engine delegates its cgroup v2 controller
                         (memory, cpu, pids). A missing controller leaves that
                         budget unenforced with a notice; without memory or
                         process budgets a session can exhaust host resources
  PI_CONTAINER_RUN_TIMEOUT  session container lifetime in whole seconds
                         (default: 0, disabled); independent from shutdown budgets
  PI_CONTAINER_ALLOW_UNSAFE_WORKSPACE exact 1 permits a refused sensitive
                         workspace with a warning (default: disabled)
  PI_CONTAINER_GITCONFIG exactly 1 mounts ~/.gitconfig read-only (default: not
                         mounted; it may hold credential helpers or tokens)
  PI_CONTAINER_STATE_DIR private host directory holding .pi and .agents instead
                         of ~/.pi and ~/.agents; writable mode makes it the
                         persistent /pi-home (default: unset or empty, shared
                         host state); conflicts with PI_CONTAINER_CONFIG_DIR
  PI_CONTAINER_CONFIG_DIR private host directory replacing only ~/.pi; inside
                         the session it is always /pi-home/.pi
  PI_CONTAINER_TRUST_HOST_CA trust a host CA bundle: 1, true, or yes
                         (default: disabled)
  PI_CONTAINER_CA_BUNDLE CA bundle file to trust (default: first of
                         /etc/ssl/certs/ca-certificates.crt and
                         /etc/pki/tls/certs/ca-bundle.crt)
  PI_CONTAINER_YOLO      permission bypass: 0, 1, true, false, yes, or no
                         (default: disabled); Pi 0.80.8 has no tool-approval
                         layer, so an enabled value only prints a warning
  PI_NPM_CACHE_SIZE      default: 256M
  PI_READONLY_CONFIG     nonempty mounts existing state read-only
  PI_ENV_VARS            space-separated extra variable names; never values
  PI_DEBUG               nonempty enables debug output without secret values
  EDITOR, VISUAL         defaults: nano

Deprecated names (warned; conflicting old and new values are errors):
  PI_IMAGE_NAME, PI_ENABLE_PODMAN, PI_PODMAN_SOCKET, PI_MEMORY_LIMIT,
  PI_CPU_LIMIT, PI_PIDS_LIMIT, PI_RUN_TIMEOUT, PI_ALLOW_UNSAFE_PWD (exact 1
  only) and PI_MOUNT_GITCONFIG map to the PI_CONTAINER_* names above.
  PI_PULL_ALWAYS is ignored: image inputs (base digest, Pi from .version and
  OpenSpec) are pinned in Containerfile.

A missing image is built only with exact PI_CONTAINER_MAINTENANCE=1. A stale
image (Containerfile, .containerignore, .version, network/relay.py
or network/mux.py changed) stops the launch until
--container-build is run explicitly under maintenance.
Sessions use HOME=/pi-home, an ephemeral noexec tmpfs, with ~/.pi, ~/.agents,
the npm cache and an opted-in ~/.gitconfig mounted below it; other files
written in /pi-home do not survive the session.

Pi has no tool-approval layer: its tools run without prompts, so the container
is the only boundary. PI_CONTAINER_YOLO is accepted for setup and future Pi
releases but has no effect yet. Pi's --approve trusts project-local files; it
does not approve tools.
Launch requires a verified Linux rootless engine, without a rootful override.
Use local Podman or an explicit same-host absolute Unix CONTAINER_HOST.
Named connections, TCP/SSH, implicit remote contexts, and slash-only paths fail.
Engine verification rejects incomplete/extra records and CR characters.
Writable ~/.pi and ~/.agents must be caller-owned, accessible, and private
(no group/other permissions). Missing writable state is created privately;
existing state is never repaired. Use native Linux storage for Unix modes.
Read-only state must already exist and be readable/traversable.
Sessions use caller UID/GID, keep-id, no capabilities, no-new-privileges and a
read-only rootfs. No automatic SELinux relabeling or confinement overrides are
performed. Budgets and tmpfs sizes do not limit workspace or state storage.
When the lifetime limit stops a session, a notice is printed and the engine
client's exit status is kept.
Temporary /tmp and /var/tmp: 256 MiB each; /run: 32 MiB; npm cache: 256 MiB.
All temporary stores use nosuid,nodev,noexec and disappear after the session.
The writable workspace (or worktree parent) must not physically be /, /home,
/root, /etc, /usr, /var, /bin, /sbin, /lib, /lib64, /boot, /opt, /srv, /mnt,
/media, /proc, /sys, /dev, /run, /tmp, the caller's home or a /mnt/<letter>
drive root; descendants such as /mnt/d/project are allowed.
In unrestricted mode, ANTHROPIC_API_KEY, OPENAI_API_KEY, GOOGLE_API_KEY and
proxy variables are forwarded by name only when nonempty.
Delegation verifies the selected rootless service and binds its reported
host-side socket to /run/podman/podman.sock; it never starts a service.
Without delegation session CONTAINER_HOST is explicitly unset, even if listed
in PI_ENV_VARS. Connection settings cannot override the selected session URI.
Delegation grants the service user's host authority, including further mounts.
Worktree mode exposes siblings in the whole immediate parent read/write.
Native Pi permissions are independent of delegation.

New users must first run: bash ./pi-container.sh --container-setup
Then use the managed launch command printed by setup (by default
~/.local/bin/pi-container) from your workspace. An ordinary launch with an
unset or empty PI_CONTAINER_NETWORK stops with setup guidance before runtime
checks or state creation. Direct operator launches remain available with an
explicit mode.

Migration: every direct launch now needs an explicit PI_CONTAINER_NETWORK, and
PI_NETWORK is no longer supported (none becomes PI_CONTAINER_NETWORK=offline;
other values become unrestricted). Set PI_CONTAINER_NETWORK=unrestricted to keep
the previous networking, and add PI_CONTAINER_MAINTENANCE=1 to commands that
build the image, e.g.:
  PI_CONTAINER_NETWORK=unrestricted PI_CONTAINER_MAINTENANCE=1 bash ./pi-container.sh --container-build --version
Offline sessions cannot reach any model provider. Restricted failures never
retry unrestricted networking.

Restricted modes (offline, provider) require host Python 3, a same-host Unix
rootless Netavark service with Podman >= 4.9, standard OCI seccomp, usable
Landlock ABI >= 3, a protected installation outside writable workspace/state
trees, a static guard and SHA-256 manifest in network/bin, and a current local
qualification report (run --container-qualify alone after preparation or
relevant updates). Changed boot, engine/backend/security, code/images,
policy/profile, CA trust or hardening invalidates the report; an unidentifiable
active LSM policy requires the gate on each launch. Locally-qualified
installations are distinguished from release-measured acceptance records.
Restricted sessions receive no host proxy or CA variables; provider mode
forwards only the key of the selected profile (ANTHROPIC_API_KEY,
OPENAI_API_KEY, GEMINI_API_KEY or OPENROUTER_API_KEY) and offline forwards none.
PI_OFFLINE=1, PI_SKIP_VERSION_CHECK=1 and PI_TELEMETRY=0 are set after
forwarding. Runtime package installs and named Unix sockets are unavailable.
Provider mode uses an external CONNECT proxy that binds the TLS server name
(initial and retried ClientHello) to the CONNECT host before forwarding; it
does not prove exclusive communication with your provider account. Allowed
services can receive data: an injected agent can send workspace data to an
allowed host (anthropic-api: api.anthropic.com; openai-api: api.openai.com;
gemini-api: generativelanguage.googleapis.com; openrouter-api: openrouter.ai)
with an attacker's key or account. Only offline removes this. Provider-hosted
tools such as web search run at the provider, outside this boundary.
Subscription and browser-callback logins are unsupported; use API keys. See
network/README.md and docs/network-contract.md.
HELP
}

# Help takes precedence regardless of option order and never needs Podman.
for arg in "$@"; do
    case "$arg" in --container-help|--wrapper-help) usage; exit 0 ;; esac
done
for arg in "$@"; do
    if [[ "$arg" == --container-qualify ]]; then
        [[ $# == 1 ]] || die '--container-qualify must be used alone'
        command -v python3 >/dev/null || die 'host Python 3 is required for qualification'
        qualify_dir=$(dirname -- "$(readlink -f -- "${BASH_SOURCE[0]}")")
        exec python3 -I "$qualify_dir/network/qualify.py" qualify
    fi
done

for arg in "$@"; do
    if [[ "$arg" == --container-setup ]]; then
        [[ $# == 1 ]] || die '--container-setup must be used alone'
        [[ -t 0 && -t 1 ]] || die '--container-setup requires an interactive terminal'
        command -v python3 >/dev/null || die 'host Python 3 is required for interactive setup'
        setup_script=$(readlink -f -- "${BASH_SOURCE[0]}")
        exec python3 -I "$(dirname -- "$setup_script")/setup/setup.py"
    fi
done

build_image=0
qualification_probe=0
shell_mode=0
git_worktree=0
args=()
for arg in "$@"; do
    case "$arg" in
        --container-qualify-probe)
            [[ $# == 1 ]] || die 'the fixed qualification probe must be used alone'
            qualification_probe=1 ;;
        --container-build) build_image=1 ;;
        --container-shell) shell_mode=1 ;;
        --container-git-worktree) git_worktree=1 ;;
        *) args+=("$arg") ;;
    esac
done
# --container-build alone refreshes the image and exits; guided setup uses it.
build_only=0
[[ $# != 1 || "$build_image" != 1 ]] || build_only=1

# An explicit mode precedes every other check, engine query and state operation.
if [[ -z "${PI_CONTAINER_NETWORK:-}" ]]; then
    setup_wrapper=${BASH_SOURCE[0]}
    [[ "$setup_wrapper" == /* ]] || setup_wrapper="$PWD/$setup_wrapper"
    printf -v setup_command 'bash %q --container-setup' "$setup_wrapper"
    die "setup required: run $setup_command; use the managed launcher afterward or explicitly set PI_CONTAINER_NETWORK for an operator workflow (offline, provider, or unrestricted; unrestricted keeps the previous networking behavior)"
fi
network_mode=$PI_CONTAINER_NETWORK
case "$network_mode" in
    offline|provider|unrestricted) ;;
    *) die 'PI_CONTAINER_NETWORK must be offline, provider, or unrestricted' ;;
esac
if [[ -n "${PI_NETWORK:-}" ]]; then
    case "$PI_NETWORK" in
        none) die 'PI_NETWORK is no longer supported; use PI_CONTAINER_NETWORK=offline instead of PI_NETWORK=none' ;;
        *) die "PI_NETWORK is no longer supported; unset it and use PI_CONTAINER_NETWORK=unrestricted for ordinary networking (PI_NETWORK=$PI_NETWORK selected a raw Podman network)" ;;
    esac
fi
restricted=0
[[ "$network_mode" == unrestricted ]] || restricted=1
trust_host_ca=0
case "${PI_CONTAINER_TRUST_HOST_CA:-}" in
    [Tt][Rr][Uu][Ee]|[Yy][Ee][Ss]|1) trust_host_ca=1 ;;
    ''|0|[Ff][Aa][Ll][Ss][Ee]|[Nn][Oo]) ;;
    *) die 'PI_CONTAINER_TRUST_HOST_CA must be 0, 1, true, false, yes, or no' ;;
esac
# The host CA bundle is selected from the environment alone, before any build:
# the build-only refresh (used by setup) exits before state validation, and its
# HTTPS package fetches must verify against the same bundle as a session.
ca_bundle=''
select_ca_bundle() {
    ((trust_host_ca)) || return 0
    if [[ -n "${PI_CONTAINER_CA_BUNDLE:-}" ]]; then
        [[ -f "$PI_CONTAINER_CA_BUNDLE" ]] || die "PI_CONTAINER_CA_BUNDLE is not a file: $PI_CONTAINER_CA_BUNDLE"
        ca_bundle=$(readlink -f -- "$PI_CONTAINER_CA_BUNDLE")
    else
        for candidate in /etc/ssl/certs/ca-certificates.crt /etc/pki/tls/certs/ca-bundle.crt; do
            if [[ -f "$candidate" ]]; then
                ca_bundle=$candidate
                break
            fi
        done
        [[ -n "$ca_bundle" ]] || die 'no default CA bundle found; set PI_CONTAINER_CA_BUNDLE to a bundle file'
    fi
    [[ "$ca_bundle" != *[:$'\n'$'\r']* ]] || die "CA bundle path must not contain colon, CR or LF: $ca_bundle"
}
select_ca_bundle
config_override=${PI_CONTAINER_CONFIG_DIR:-}
if [[ -n "$config_override" ]]; then
    [[ -z "${PI_CONTAINER_STATE_DIR:-}" ]] \
        || die 'PI_CONTAINER_STATE_DIR conflicts with PI_CONTAINER_CONFIG_DIR; unset PI_CONTAINER_CONFIG_DIR to isolate state, or unset PI_CONTAINER_STATE_DIR to keep shared state'
    [[ "$config_override" == /* && "$config_override" != *:* && "$config_override" != *$'\n'* && "$config_override" != *$'\r'* ]] \
        || die "PI_CONTAINER_CONFIG_DIR must be an absolute path without colon, CR or LF: $config_override"
fi
# The provider credential follows the selected profile (agent/profile.json).
profile_credential=''
if [[ "$network_mode" == provider ]]; then
    case "${PI_CONTAINER_NETWORK_PROFILE:-}" in
        anthropic-api) profile_credential=ANTHROPIC_API_KEY ;;
        openai-api) profile_credential=OPENAI_API_KEY ;;
        gemini-api) profile_credential=GEMINI_API_KEY ;;
        openrouter-api) profile_credential=OPENROUTER_API_KEY ;;
    esac
fi

# Common PI_CONTAINER_* names; earlier names remain deprecated aliases.
# select_setting NEW OLD [switch] sets setting_value and setting_set.
select_setting() {
    local new=$1 old=$2 kind=${3:-text} new_on old_on
    setting_value=''
    setting_set=0
    if [[ -n "${!old+x}" ]]; then
        if [[ "$kind" == switch ]]; then
            printf 'pi-container: %s is deprecated; use %s (only the exact value 1 enables it)\n' "$old" "$new" >&2
        else
            printf 'pi-container: %s is deprecated; use %s\n' "$old" "$new" >&2
        fi
    fi
    if [[ -n "${!new+x}" ]]; then
        if [[ -n "${!old+x}" ]]; then
            if [[ "$kind" == switch ]]; then
                new_on=0; old_on=0
                [[ "${!new}" != 1 ]] || new_on=1
                [[ "${!old}" != 1 ]] || old_on=1
                ((new_on == old_on)) || die "$old and $new conflict; set only $new"
            else
                [[ "${!new}" == "${!old}" ]] || die "$old and $new conflict; set only $new"
            fi
        fi
        setting_value=${!new}
        setting_set=1
    elif [[ -n "${!old+x}" ]]; then
        setting_value=${!old}
        setting_set=1
    fi
}
select_setting PI_CONTAINER_IMAGE PI_IMAGE_NAME; image_setting=$setting_value
select_setting PI_CONTAINER_PODMAN PI_ENABLE_PODMAN switch; podman_setting=$setting_value
if ((restricted)) && [[ "$podman_setting" == 1 ]]; then
    die 'restricted networking rejects PI_CONTAINER_PODMAN=1: the host API bypasses egress enforcement; select explicit unrestricted mode for delegation'
fi
if [[ "$network_mode" == provider ]]; then
    [[ -n "${PI_CONTAINER_NETWORK_PROFILE:-}" && -n "${PI_CONTAINER_NETWORK_POLICY:-}" ]] \
        || die 'provider mode requires PI_CONTAINER_NETWORK_PROFILE and PI_CONTAINER_NETWORK_POLICY'
    [[ -n "${PI_CONTAINER_NETWORK_RUNTIME_DIR:-}" && -n "${PI_CONTAINER_EGRESS_IMAGE:-}" ]] \
        || die 'provider mode requires a private host-path PI_CONTAINER_NETWORK_RUNTIME_DIR and immutable PI_CONTAINER_EGRESS_IMAGE'
fi
select_setting PI_CONTAINER_PODMAN_SOCKET PI_PODMAN_SOCKET; socket_setting=$setting_value
select_setting PI_CONTAINER_MEMORY_LIMIT PI_MEMORY_LIMIT
memory_text=4g; ((setting_set == 0)) || memory_text=$setting_value
select_setting PI_CONTAINER_CPU_LIMIT PI_CPU_LIMIT
cpu_text=2; ((setting_set == 0)) || cpu_text=$setting_value
select_setting PI_CONTAINER_PIDS_LIMIT PI_PIDS_LIMIT
pids_text=512; ((setting_set == 0)) || pids_text=$setting_value
select_setting PI_CONTAINER_RUN_TIMEOUT PI_RUN_TIMEOUT; timeout_text=${setting_value:-0}
select_setting PI_CONTAINER_ALLOW_UNSAFE_WORKSPACE PI_ALLOW_UNSAFE_PWD switch; unsafe_setting=$setting_value
if [[ -n "${PI_PULL_ALWAYS+x}" ]]; then
    printf 'pi-container: PI_PULL_ALWAYS is ignored; image inputs are pinned in Containerfile\n' >&2
fi
# Validated like the other wrappers' approval switches; setup saves 0 or 1.
case "${PI_CONTAINER_YOLO:-}" in
    [Tt][Rr][Uu][Ee]|[Yy][Ee][Ss]|1)
        printf 'pi-container: PI_CONTAINER_YOLO has no effect yet: Pi 0.80.8 has no tool-approval layer and the container is the only boundary\n' >&2 ;;
    ''|0|[Ff][Aa][Ll][Ss][Ee]|[Nn][Oo]) ;;
    *) die 'PI_CONTAINER_YOLO must be 0, 1, true, false, yes, or no' ;;
esac

# Session budgets and lifetime, validated before any engine or state operation.
# Same rules and messages as the claude-container reference (sandbox-ref-2).
# Only an unset budget selects its default; no value disables a budget.
memory_bytes=0
if [[ "$memory_text" =~ ^([1-9][0-9]{0,15})([kmgKMG])$ ]]; then
    case "${BASH_REMATCH[2],,}" in
        k) unit=1024 ;;
        m) unit=1048576 ;;
        *) unit=1073741824 ;;
    esac
    ((10#${BASH_REMATCH[1]} > (1 << 50) / unit)) || memory_bytes=$((10#${BASH_REMATCH[1]} * unit))
fi
((memory_bytes > 0)) || die 'PI_CONTAINER_MEMORY_LIMIT must be a positive integer with unit k, m or g, for example 4g'
cpu_nano=0
if [[ "$cpu_text" =~ ^([0-9]{1,4})(\.([0-9]{1,3}))?$ ]]; then
    fraction=${BASH_REMATCH[3]}000
    cpu_nano=$((10#${BASH_REMATCH[1]} * 1000000000 + 10#${fraction:0:3} * 1000000))
    ((cpu_nano <= 1024000000000)) || cpu_nano=0
fi
((cpu_nano > 0)) || die 'PI_CONTAINER_CPU_LIMIT must be a positive number of CPUs with at most 3 decimals, for example 2 or 1.5'
# shellcheck disable=SC2015 # die must run when either test fails.
[[ "$pids_text" =~ ^(0|[1-9][0-9]{0,9})$ ]] && ((pids_text > 0 && pids_text <= 4194304)) \
    || die 'PI_CONTAINER_PIDS_LIMIT must be a positive integer process count up to 4194304'
# shellcheck disable=SC2015 # die must run when either test fails.
[[ "$timeout_text" =~ ^(0|[1-9][0-9]{0,9})$ ]] && ((timeout_text <= 2147483647)) \
    || die 'PI_CONTAINER_RUN_TIMEOUT must be whole seconds; 0 disables the lifetime limit'
pids_limit=$((10#$pids_text))
run_timeout=$((10#$timeout_text))

for tool in podman timeout stat readlink sha256sum; do
    command -v "$tool" >/dev/null || die "$tool is required on the host"
done
script_path=$(readlink -f -- "${BASH_SOURCE[0]}")
script_dir=$(dirname -- "$script_path")
version_file=$script_dir/.version
[[ -s "$version_file" ]] || die '.version is missing or empty'
pi_version=$(head -1 "$version_file" | tr -d '[:space:]')
[[ -n "$pi_version" ]] || die '.version is missing or empty'
image=${image_setting:-localhost/pi-container}
caller_uid=$(id -u)
caller_gid=$(id -g)
[[ "${HOME:-}" == /* ]] || die 'HOME must be an absolute directory path'
workspace=$(pwd -P) || die 'Cannot resolve physical workspace'
workspace_mount=$workspace
((git_worktree == 0)) || workspace_mount=$(dirname -- "$workspace")
physical_home=$(CDPATH='' cd -- "$HOME" && pwd -P) || die 'Cannot resolve HOME'
# Refuse sensitive writable workspaces before any engine or state operation.
unsafe_workspace=0
case "$workspace_mount" in
    /|/home|/root|/etc|/usr|/var|/bin|/sbin|/lib|/lib64|/boot|/opt|/srv|/mnt|/media|/proc|/sys|/dev|/run|/tmp)
        unsafe_workspace=1 ;;
esac
[[ "$workspace_mount" != "$physical_home" && ! "$workspace_mount" =~ ^/mnt/[A-Za-z]$ ]] || unsafe_workspace=1
# A build-only refresh mounts no workspace.
((build_only == 0)) || unsafe_workspace=0
if ((unsafe_workspace)); then
    [[ "$unsafe_setting" == 1 ]] \
        || die "refusing sensitive workspace $workspace_mount; launch from a project subdirectory or set exact PI_CONTAINER_ALLOW_UNSAFE_WORKSPACE=1"
    printf 'pi-container: WARNING: sensitive workspace explicitly exposed read/write: %s\n' "$workspace_mount" >&2
fi
readonly CONTAINER_HOME=/pi-home
state_mode=rw
[[ -z "${PI_READONLY_CONFIG:-}" ]] || state_mode=ro
# Isolated state replaces ~/.pi and ~/.agents; it is validated before engine use.
state_root=$HOME
isolated_home=''
# An empty value selects shared state, like an unset one (as in the other wrappers).
if [[ -n "${PI_CONTAINER_STATE_DIR:-}" ]]; then
    state_request=$PI_CONTAINER_STATE_DIR
    [[ "$state_request" == /* && "$state_request" != *:* && "$state_request" != *$'\n'* && "$state_request" != *$'\r'* ]] \
        || die "PI_CONTAINER_STATE_DIR must be an absolute path without colon, CR or LF: $state_request"
    state_physical=$state_request
    if [[ -d "$state_request" ]]; then
        state_physical=$(CDPATH='' cd -- "$state_request" && pwd -P)
    elif [[ -d "$(dirname -- "$state_request")" ]]; then
        state_physical=$(CDPATH='' cd -- "$(dirname -- "$state_request")" && pwd -P)/$(basename -- "$state_request")
    fi
    state_physical=${state_physical%/}
    [[ "$state_physical/" != "$workspace_mount/"* && "$workspace_mount/" != "$state_physical/"* ]] \
        || die "PI_CONTAINER_STATE_DIR must not overlap the workspace: $state_request"
    state_root=$state_physical
fi

# Host Git configuration is mounted only on exact opt-in, from its physical file.
gitconfig_source=''
gitconfig_request=0
[[ "${PI_CONTAINER_GITCONFIG:-}" != 1 ]] || gitconfig_request=1
if [[ -n "${PI_MOUNT_GITCONFIG+x}" ]]; then
    case "$PI_MOUNT_GITCONFIG" in
        0|1) ;;
        *) die 'PI_MOUNT_GITCONFIG must be 0 or 1; use PI_CONTAINER_GITCONFIG=1 instead' ;;
    esac
    printf 'pi-container: PI_MOUNT_GITCONFIG is deprecated; use PI_CONTAINER_GITCONFIG=1 to mount ~/.gitconfig\n' >&2
    if [[ -n "${PI_CONTAINER_GITCONFIG+x}" ]]; then
        [[ "$PI_MOUNT_GITCONFIG" == "$gitconfig_request" ]] \
            || die 'PI_MOUNT_GITCONFIG and PI_CONTAINER_GITCONFIG conflict; set only PI_CONTAINER_GITCONFIG'
    else
        gitconfig_request=$PI_MOUNT_GITCONFIG
    fi
elif [[ -z "${PI_CONTAINER_GITCONFIG+x}" && -e "$HOME/.gitconfig" ]]; then
    printf 'pi-container: ~/.gitconfig is no longer mounted by default; set PI_CONTAINER_GITCONFIG=1 to mount it read-only (PI_CONTAINER_GITCONFIG=0 silences this notice)\n' >&2
fi
if ((gitconfig_request)); then
    gitconfig_source=$(readlink -f -- "$HOME/.gitconfig") && [[ -f "$gitconfig_source" ]] \
        || die "PI_CONTAINER_GITCONFIG=1 requires a regular file: $HOME/.gitconfig"
    [[ "$gitconfig_source" != *[:$'\n'$'\r']* ]] \
        || die "gitconfig path must not contain colon, CR or LF: $gitconfig_source"
fi

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
capture_engine_info info --format '{{.Host.Security.Rootless}} {{.Host.OS}} {{.Host.ServiceIsRemote}}' || die 'cannot query Podman or invalid engine response; check local rootless Podman or the same-host Unix service'
read -r rootless runtime_os service_remote extra <<< "$engine_response"
[[ "$rootless" == true && "$runtime_os" == linux && -z "$extra" && "$engine_response" != *$'\n'* ]] || die 'The launch engine must report complete Linux rootless operation'
case "$service_remote" in
    false) ;;
    true) [[ "${CONTAINER_HOST:-}" == unix:///?* ]] || die 'A remote launch engine requires an explicit same-host Unix CONTAINER_HOST' ;;
    *) die 'Cannot verify launch engine ServiceIsRemote (expected true or false)' ;;
esac
runtime_info=$engine_response

# Build inputs and the staleness label shared by launches and build-only refreshes.
build_hash=$(cat "$script_dir/Containerfile" "$script_dir/.containerignore" "$version_file" "$script_dir/network/relay.py" "$script_dir/network/mux.py" | sha256sum)
build_hash=${build_hash%% *}
build_runtime_image() {
    local build_args=(--tag "$image" --file "$script_dir/Containerfile" --format docker
        --build-arg "PI_VERSION=$pi_version"
        --label "build-inputs-hash=$build_hash")
    # The opted-in host CA bundle also verifies the build's package fetches. It is
    # a build secret: mounted only for its RUN step, never stored in a layer and
    # not a build input, so it does not enter the staleness hash.
    [[ -z "$ca_bundle" ]] || build_args+=(--secret "id=build-ca,src=$ca_bundle")
    printf 'Building Pi v%s image...\n' "$pi_version" >&2
    timeout --kill-after=1s 300s podman build "${build_args[@]}" "$script_dir" </dev/null || die 'Image build failed or timed out (300s); check build output and network'
}
if ((build_only)); then
    [[ "${PI_CONTAINER_MAINTENANCE:-}" == 1 ]] \
        || die "image $image build requires exact PI_CONTAINER_MAINTENANCE=1 (host pulls and build RUN steps are outside runtime filtering)"
    build_runtime_image
    exit 0
fi

# A budget is enforced only when the verified engine reports its cgroup v2
# controller as delegated. Unenforced budgets are not requested, are announced,
# and must be absent from the created configuration (see network/agent_budgets.py).
capture_engine_info info --format '{{.Host.CgroupControllers}}' \
    || die 'cannot query the rootless cgroup controllers; check the Podman engine'
cgroup_controllers=$engine_response
[[ "$cgroup_controllers" =~ ^\[([a-z_]+( [a-z_]+)*)?\]$ ]] \
    || die 'unverifiable cgroup controller list from the Podman engine'
controller_delegated() {
    [[ " ${cgroup_controllers:1:${#cgroup_controllers}-2} " == *" $1 "* ]]
}
budget_args=()
expected_memory=0
expected_cpu=0
pids_enforced=0
if controller_delegated memory; then
    budget_args+=("--memory=$memory_bytes")
    expected_memory=$memory_bytes
else
    printf 'pi-container: agent memory budget not enforced: cgroup controller memory is not delegated to the rootless engine\n' >&2
fi
if controller_delegated cpu; then
    budget_args+=("--cpus=$cpu_text")
    expected_cpu=$cpu_nano
else
    printf 'pi-container: agent CPU budget not enforced: cgroup controller cpu is not delegated to the rootless engine\n' >&2
fi
if controller_delegated pids; then
    budget_args+=("--pids-limit=$pids_limit")
    pids_enforced=1
else
    # Override any containers.conf default that would request the missing controller.
    budget_args+=(--pids-limit=-1)
    printf 'pi-container: agent process budget not enforced: cgroup controller pids is not delegated to the rootless engine\n' >&2
fi
if ((restricted)); then
    command -v python3 >/dev/null || die 'host Python 3 is required for restricted network policy validation'
    [[ "$service_remote" == true ]] \
        || die 'restricted networking currently requires the tested same-host Unix service; local-engine enforcement is unverified'
    capture_engine_info info --format '{{.Host.NetworkBackend}}' || die 'cannot verify restricted network backend'
    network_backend=$engine_response
    capture_engine_info version --format '{{.Server.Version}}' || die 'cannot verify restricted network server version'
    network_version=$engine_response
    capture_engine_info info --format '{{json .Host}}' || die 'cannot verify restricted platform security policy'
    network_platform=$engine_response
elif ((qualification_probe)); then
    die 'qualification probes require restricted networking'
fi

install_podman=0
if [[ "$podman_setting" == 1 ]]; then
    install_podman=1
    socket=$socket_setting
    if [[ -z "$socket" && "${CONTAINER_HOST:-}" == unix:///?* ]]; then socket=${CONTAINER_HOST#unix://}; fi
    socket=${socket:-${XDG_RUNTIME_DIR:-/run/user/$caller_uid}/podman/podman.sock}
    [[ "$socket" == /* ]] || die "Podman socket path must be absolute: $socket"
    selected_socket=$socket
    socket=$(readlink -f -- "$selected_socket") || die "Cannot resolve Podman socket: $selected_socket"
    [[ -S "$socket" && -r "$socket" && -w "$socket" ]] || die "Podman socket not accessible: $selected_socket (start the rootless service explicitly; check permissions and SELinux policy)"
    capture_engine_info --remote --url "unix://$socket" info --format '{{.Host.Security.Rootless}}{{"\n"}}{{.Host.RemoteSocket.Path}}' || die "Cannot query selected Podman socket or invalid response: $socket"
    [[ "$engine_response" == true$'\n'* ]] || die 'Selected socket must report rootless true and an absolute host socket path'
    host_socket=${engine_response#*$'\n'}
    # Podman 5 reports the service socket as a unix:// URL; earlier releases report the bare path.
    host_socket=${host_socket#unix://}
    [[ "$host_socket" == /* && -n "${host_socket//\//}" && "$host_socket" != *$'\n'* ]] || die 'Selected socket must report one absolute host socket path beyond /'
fi

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
# Isolated state is created and validated after engine verification, as in the
# reference order; only lexical checks precede the engine.
if [[ -n "${PI_CONTAINER_STATE_DIR:-}" ]]; then
    if [[ "$state_mode" == rw ]]; then
        if [[ ! -e "$state_request" && ! -L "$state_request" ]]; then
            (umask 077; mkdir -p -- "$state_request") || die "Cannot create PI_CONTAINER_STATE_DIR: $state_request"
        fi
        [[ -d "$state_request" ]] || die "PI_CONTAINER_STATE_DIR is not a directory: $state_request"
        isolated_home=$(CDPATH='' cd -- "$state_request" && pwd -P) || die "Cannot resolve PI_CONTAINER_STATE_DIR: $state_request"
        [[ -r "$isolated_home" && -w "$isolated_home" && -x "$isolated_home" ]] || die "PI_CONTAINER_STATE_DIR is not accessible: $state_request"
        state_owner=$(stat -c '%u' -- "$isolated_home") || die "Cannot inspect PI_CONTAINER_STATE_DIR owner: $state_request"
        state_perm=$(stat -c '%a' -- "$isolated_home") || die "Cannot inspect PI_CONTAINER_STATE_DIR permissions: $state_request"
        [[ "$state_owner" == "$caller_uid" ]] || die "PI_CONTAINER_STATE_DIR must belong to the calling user: $state_request"
        # shellcheck disable=SC2015 # die must run when either test fails.
        [[ "$state_perm" =~ ^[0-7]{3,4}$ ]] && (( (8#$state_perm & 077) == 0 )) \
            || die "PI_CONTAINER_STATE_DIR must be private: $state_request (explicitly repair it or use a filesystem that enforces Unix permissions)"
    fi
fi
validate_state "${config_override:-$state_root/.pi}"; pi_state=$state_path
validate_state "$state_root/.agents"; agents_state=$state_path
# The CA bundle itself was selected before any build (select_ca_bundle); only
# the isolated-home mount parent depends on the validated state.
if ((trust_host_ca)); then
    if [[ -n "$isolated_home" ]]; then
        # Resolve first so an existing symlink cannot move the CA mount parent.
        ca_parent=$(readlink -m -- "$isolated_home/ca")
        [[ "$ca_parent" == "$isolated_home/ca" ]] || die "isolated CA mount parent escapes the state home: $isolated_home/ca"
        if [[ ! -e "$ca_parent" ]]; then
            (umask 077; mkdir -- "$ca_parent") || die "Cannot create private state: $ca_parent"
        fi
        validate_state "$ca_parent"
    fi
fi

# Restricted sessions use the shared helper; this wrapper keeps only the
# agent-specific command, environment, state and credentials.
session_helper=(python3 -I "$script_dir/network/session.py")
network_inputs=()
qualification_inputs=()
guard_digest=''
if ((restricted)); then
    network_inputs=(--installation "$script_dir" --writable "$workspace_mount"
        --mount-target "$workspace_mount" --mount-target "$CONTAINER_HOME")
    if [[ -n "$isolated_home" ]]; then
        network_inputs+=(--writable "$isolated_home")
    elif [[ "$state_mode" == rw ]]; then
        network_inputs+=(--writable "$pi_state" --writable "$agents_state")
    fi
    if [[ "$network_mode" == provider ]]; then
        network_inputs+=(--policy "$PI_CONTAINER_NETWORK_POLICY"
            --profile "$PI_CONTAINER_NETWORK_PROFILE" --proxy-image "$PI_CONTAINER_EGRESS_IMAGE"
            --runtime "$PI_CONTAINER_NETWORK_RUNTIME_DIR")
    fi
    prepare_inputs=(--mode "$network_mode" --server-version "$network_version"
        --backend "$network_backend" --endpoint "${CONTAINER_HOST:-}" --engine "$runtime_info")
    if ((qualification_probe)); then
        prepare_inputs+=(--probe --qualification-input "${PI_CONTAINER_QUALIFICATION_INPUT:-}"
            --workspace "$workspace")
    fi
    prepared=$(printf '%s\n' "$network_platform" | "${session_helper[@]}" prepare "${network_inputs[@]}" "${prepare_inputs[@]}") \
        || exit 1
    read -r guard_digest qualification_token qualification_tls <<< "$prepared"
    if ((qualification_probe)); then
        qualification_inputs=(--probe --token "$qualification_token" --workspace "$workspace"
            --qualification-input "${PI_CONTAINER_QUALIFICATION_INPUT:-}")
        [[ "$qualification_tls" != 1 ]] || qualification_inputs+=(--tls)
    fi
fi

needs_build=$build_image
# Every build, including the automatic build of a missing image, is maintenance.
maintenance=0
[[ "${PI_CONTAINER_MAINTENANCE:-}" != 1 ]] || maintenance=1
if ((build_image == 0)); then
    if podman image exists "$image"; then
        label_hash=$(podman image inspect "$image" --format '{{index .Labels "build-inputs-hash"}}') || die "Cannot inspect staleness label for $image; check engine/storage"
        [[ "$label_hash" == "$build_hash" ]] \
            || die "Image $image is stale for the current inputs (Containerfile, .containerignore, .version, network/relay.py or network/mux.py); rebuild explicitly with --container-build and PI_CONTAINER_MAINTENANCE=1"
    else
        image_status=$?
        [[ "$image_status" == 1 ]] || { printf 'pi-container: Cannot inspect image %s (status %s)\n' "$image" "$image_status" >&2; exit "$image_status"; }
        needs_build=1
    fi
fi
if ((needs_build)); then
    ((maintenance)) || die "image $image needs a build; prepare it with exact PI_CONTAINER_MAINTENANCE=1 (host pulls and build RUN steps are outside runtime filtering)"
    build_runtime_image
fi

if [[ "$network_mode" == provider ]]; then
    if podman image exists "$PI_CONTAINER_EGRESS_IMAGE"; then
        :
    else
        image_status=$?
        [[ "$image_status" == 1 ]] || die 'cannot inspect immutable egress proxy image'
        ((maintenance)) && [[ "$PI_CONTAINER_EGRESS_IMAGE" == *@sha256:* ]] \
            || die 'proxy image is absent; prepare the pinned artifact under explicit operator maintenance authorization (PI_CONTAINER_MAINTENANCE=1 and a registry digest)'
        podman pull "$PI_CONTAINER_EGRESS_IMAGE"
    fi
fi
# Restricted sessions and their qualification bind the immutable image ID.
session_image=$image
if ((restricted)); then
    capture_engine_info image inspect --format '{{.Id}}' "$image" || die 'cannot resolve restricted runtime image identity'
    [[ "$engine_response" =~ ^(sha256:)?[a-f0-9]{64}$ ]] || die 'invalid restricted runtime image identity'
    session_image=$engine_response
fi

podman_args=(--rm --interactive --read-only
    --userns=keep-id --user "$caller_uid:$caller_gid"
    --cap-drop=ALL --security-opt=no-new-privileges
    "${budget_args[@]}"
    --workdir "$workspace" --env "HOME=$CONTAINER_HOME"
    --env "EDITOR=${EDITOR:-nano}" --env "VISUAL=${VISUAL:-nano}"
    --tmpfs "/tmp:rw,noexec,nosuid,nodev,mode=1777,size=256M"
    --tmpfs "/var/tmp:rw,noexec,nosuid,nodev,mode=1777,size=256M"
    --tmpfs "/run:rw,noexec,nosuid,nodev,mode=1777,size=32M"
    # Mask engine default mounts at /run/secrets (RHEL subscription secrets from
    # mounts.conf): Podman skips its own mount there, leaving an empty read-only
    # tmpfs that the guard accepts and that exposes no host material.
    --mount type=tmpfs,destination=/run/secrets,ro=true
    # Podman forces /dev read-only with --read-only-tmpfs=false, and crun >= 1.27
    # must replace /dev/console to attach a terminal, so automatic provisioning
    # stays on. /dev and /dev/pts are left to the engine: an explicit /dev/pts mount
    # gets ptmxmode=000 (Podman rejects the option), so no pseudo-terminal could
    # be opened. Only /dev/shm is overridden, with an empty read-only tmpfs.
    --mount type=tmpfs,destination=/dev/shm,ro=true
    --volume "$workspace_mount:$workspace_mount:rw")
# The dedicated home is a private state directory or an ephemeral tmpfs.
if [[ -n "$isolated_home" ]]; then
    podman_args+=(--volume "$isolated_home:$CONTAINER_HOME:rw")
else
    podman_args+=(--tmpfs "$CONTAINER_HOME:rw,noexec,nosuid,nodev,mode=1777,size=64M"
        --volume "$pi_state:$CONTAINER_HOME/.pi:$state_mode"
        --volume "$agents_state:$CONTAINER_HOME/.agents:$state_mode")
fi
podman_args+=(--tmpfs "$CONTAINER_HOME/.npm:rw,noexec,nosuid,nodev,mode=0700,U,size=${PI_NPM_CACHE_SIZE:-256M}")
if [[ -t 0 && -t 1 ]]; then
    podman_args+=(--tty)
    [[ -z "${TERM:-}" ]] || podman_args+=(--env TERM)
fi
[[ -z "$gitconfig_source" ]] || podman_args+=(--volume "$gitconfig_source:$CONTAINER_HOME/.gitconfig:ro")
# --init bind-mounts catatonit below /run, which the guard rejects as a nested
# private IPC mount; restricted sessions start the guard directly instead.
((restricted)) || podman_args+=(--init)
# The profile's configuration variable names the effective directory in the
# session; the host value is never forwarded.
podman_args+=(--env "PI_CONTAINER_CONFIG_DIR=$CONTAINER_HOME/.pi")
if ((trust_host_ca)); then
    podman_args+=(--volume "$ca_bundle:$CONTAINER_HOME/ca/bundle.pem:ro")
    for variable in SSL_CERT_FILE REQUESTS_CA_BUNDLE CURL_CA_BUNDLE NODE_EXTRA_CA_CERTS; do
        podman_args+=(--env "$variable=$CONTAINER_HOME/ca/bundle.pem")
    done
fi
((run_timeout == 0)) || podman_args+=(--timeout "$run_timeout")
# Values for credentials remain in the creating client's environment, never argv.
# Restricted modes forward no host proxy or CA value and only the profile's key.
if ((restricted)); then
    forward_base=()
    [[ -z "$profile_credential" ]] || forward_base=("$profile_credential")
else
    forward_base=(ANTHROPIC_API_KEY OPENAI_API_KEY GOOGLE_API_KEY HTTP_PROXY HTTPS_PROXY NO_PROXY)
fi
for variable in "${forward_base[@]}"; do
    [[ -z "${!variable:-}" ]] || podman_args+=(--env "$variable")
done
extra_vars=()
read -r -a extra_vars <<< "${PI_ENV_VARS:-}"
for variable in "${extra_vars[@]}"; do
    [[ "$variable" =~ ^[a-zA-Z_][a-zA-Z0-9_]*$ ]] || die "Invalid environment variable name: $variable"
    case "$variable" in
        HOME|TERM|EDITOR|VISUAL|CONTAINER_NAME|CONTAINER_HOST|CONTAINER_CONNECTION|ANTHROPIC_API_KEY|OPENAI_API_KEY|GOOGLE_API_KEY|HTTP_PROXY|HTTPS_PROXY|NO_PROXY|PI_CONTAINER_CONFIG_DIR) continue ;;
    esac
    if ((restricted)); then
        case "$variable" in
            HTTP_PROXY|HTTPS_PROXY|ALL_PROXY|NO_PROXY|http_proxy|https_proxy|all_proxy|no_proxy|SSL_CERT_FILE|REQUESTS_CA_BUNDLE|CURL_CA_BUNDLE|NODE_EXTRA_CA_CERTS|PI_OFFLINE|PI_SKIP_VERSION_CHECK|PI_TELEMETRY)
                printf 'pi-container: PI_ENV_VARS: skipping %s, which restricted modes set themselves\n' "$variable" >&2
                continue ;;
        esac
    fi
    [[ -z "${!variable:-}" ]] || podman_args+=(--env "$variable")
done
# Protected literals follow forwarding; writable Pi settings cannot re-enable
# startup network operations (measured on Pi 0.80.8, see docs/validation.md).
((restricted == 0)) || podman_args+=(--env PI_OFFLINE=1 --env PI_SKIP_VERSION_CHECK=1 --env PI_TELEMETRY=0)
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
if ((qualification_probe)); then
    args=()  # The shared helper supplies the fixed probe command.
elif ((shell_mode)); then
    ((restricted)) || podman_args+=(--entrypoint /bin/bash)
    args=()
fi
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
qualification_check_pid=''
session_start_pid=''
diagnostics_pid=''
diagnostics_fd=''

# shellcheck disable=SC2329 # Invoked through signal/EXIT cleanup.
record_signal() {
    if ((pending_status == 0)); then
        pending_signal=$1
        pending_status=$2
    fi
    if { ((attached || creating)) && [[ -n "$client_pid" ]]; } \
        || [[ -n "$qualification_check_pid" || -n "$session_start_pid" ]]; then
        exit "$pending_status"
    fi
}

# Restricted helpers: TERM, a bounded grace period, then KILL and reap.
# shellcheck disable=SC2329 # Invoked through signal/EXIT cleanup.
child_running() {
    local child=$1 running
    [[ -n "$child" ]] || return 1
    while IFS= read -r running; do
        [[ "$running" != "$child" ]] || return 0
    done < <(jobs -p)
    return 1
}
# shellcheck disable=SC2329 # Invoked through signal/EXIT cleanup.
reap_helper() {
    local child=$1 grace=$2 until
    child_running "$child" || { wait "$child" 2>/dev/null || true; return 0; }
    kill -TERM "$child" 2>/dev/null || true
    until=$((SECONDS + grace))
    while child_running "$child" && ((SECONDS < until)); do sleep 0.05; done
    if child_running "$child"; then
        printf 'pi-container: restricted helper %s did not confirm cleanup before the deadline\n' "$child" >&2
        kill -KILL "$child" 2>/dev/null || true
    fi
    until=$((SECONDS + 1))
    while child_running "$child" && ((SECONDS < until)); do sleep 0.05; done
    if child_running "$child"; then
        printf 'pi-container: Cannot reap restricted helper %s within deadline; inspect it explicitly\n' "$child" >&2
    else
        wait "$child" 2>/dev/null || true
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
    local status=$? control_status shutdown_deadline
    trap '' TERM INT HUP
    ((pending_status == 0)) || status=$pending_status
    shutdown_deadline=$((SECONDS + 20))
    if [[ -n "$qualification_check_pid" ]]; then
        reap_helper "$qualification_check_pid" 13
        qualification_check_pid=''
    fi
    if [[ -n "$session_start_pid" ]]; then
        # The session helper owns a separate process group. Reap the whole
        # group before its leader, including an engine client that ignores TERM.
        kill -TERM -- "-$session_start_pid" 2>/dev/null || true
        sleep 0.1
        kill -KILL -- "-$session_start_pid" 2>/dev/null || true
        reap_helper "$session_start_pid" 1
        session_start_pid=''
    fi
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
    if [[ -n "$diagnostics_fd" ]]; then
        exec {diagnostics_fd}>&-
        diagnostics_fd=''
    fi
    if [[ -n "$diagnostics_pid" ]]; then
        # Drain the final client output before reaping the stderr filter.
        drain_until=$((SECONDS + 1))
        while child_running "$diagnostics_pid" && ((SECONDS < drain_until)); do sleep 0.01; done
        reap_helper "$diagnostics_pid" 1
        diagnostics_pid=''
    fi
    if [[ "$network_mode" == provider && -n "$session_tmp" ]]; then
        # Owned proxy recovery/removal and diagnostics share the remaining budget.
        "${session_helper[@]}" stop --session "$session_tmp" --deadline "$((shutdown_deadline - SECONDS))" \
            --container "${container_id:-unknown}" || true
    fi
    [[ -z "$session_tmp" ]] || rm -rf -- "$session_tmp"
    return "$status"
}

trap cleanup EXIT
trap 'record_signal TERM 143' TERM
trap 'record_signal INT 130' INT
trap 'record_signal HUP 129' HUP
if [[ "$network_mode" == provider ]]; then
    session_tmp=$(umask 077; mktemp -d -- "$PI_CONTAINER_NETWORK_RUNTIME_DIR/session.XXXXXXXXXXXX") \
        || die "Cannot create private session directory in PI_CONTAINER_NETWORK_RUNTIME_DIR"
else
    session_tmp=$(umask 077; mktemp -d) || die "Cannot create private session bookkeeping directory"
fi
((pending_status == 0)) || exit "$pending_status"
printf 'pi-container: network mode=%s\n' "$network_mode" >&2
if ((restricted && qualification_probe == 0)); then
    PI_CONTAINER_IMAGE="$session_image" python3 -I "$script_dir/network/qualify.py" check &
    qualification_check_pid=$!
    qualification_status=0
    wait "$qualification_check_pid" || qualification_status=$?
    qualification_check_pid=''
    ((pending_status == 0)) || exit "$pending_status"
    ((qualification_status == 0)) || exit "$qualification_status"
fi
if [[ "$network_mode" == provider ]]; then
    "${session_helper[@]}" start "${network_inputs[@]}" "${qualification_inputs[@]}" --session "$session_tmp" \
        --guard-digest "$guard_digest" >"$session_tmp/policy.identity" &
    session_start_pid=$!
    start_status=0
    wait "$session_start_pid" || start_status=$?
    session_start_pid=''
    ((pending_status == 0)) || exit "$pending_status"
    ((start_status == 0)) || exit "$start_status"
fi
if ((restricted)); then
    application=()
    if ((shell_mode)); then
        application=(/bin/bash)
    elif ((qualification_probe == 0)); then
        application=(/usr/local/bin/pi "${args[@]}")
    fi
    "${session_helper[@]}" agent-args --installation "$script_dir" --mode "$network_mode" \
        --session "$session_tmp" --guard-digest "$guard_digest" "${qualification_inputs[@]}" \
        -- "${application[@]}" >"$session_tmp/agent.args"
    mapfile -d '' -t restricted_args <"$session_tmp/agent.args"
    [[ "${restricted_args[0]:-}" =~ ^[0-9]+$ ]] || die 'invalid restricted session arguments'
    podman_args+=("${restricted_args[@]:1:${restricted_args[0]}}")
    args=("${restricted_args[@]:$((1 + restricted_args[0]))}")
fi
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
    podman create --name "$name" --cidfile "$session_tmp/cid" --label "io.pi-container.session=${session_tmp##*/}" "${podman_args[@]}" --env "CONTAINER_NAME=$name" "$session_image" "${args[@]}" \
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

# Engine flags alone are not evidence: require the created configuration to
# carry every enforced budget and no unenforced one before the application starts.
configured_budgets=$(timeout --kill-after=1s 10s podman inspect --type container \
    --format '{{.HostConfig.Memory}} {{.HostConfig.NanoCpus}} {{.HostConfig.PidsLimit}}' "$container_id") \
    || die 'Cannot inspect session resource budgets; session not started'
((pending_status == 0)) || exit "$pending_status"
read -r configured_memory configured_cpu configured_pids extra <<< "$configured_budgets"
budgets_applied=0
if [[ -z "${extra:-}" && "$configured_budgets" != *$'\n'* && "$configured_memory" == "$expected_memory" && "$configured_cpu" == "$expected_cpu" ]]; then
    if ((pids_enforced)); then
        [[ "$configured_pids" == "$pids_limit" ]] && budgets_applied=1
    else
        [[ "$configured_pids" =~ ^(0|-1)$ ]] && budgets_applied=1
    fi
fi
((budgets_applied)) \
    || die "Session resource budgets were not applied as expected (memory=$expected_memory nano_cpus=$expected_cpu pids=$( ((pids_enforced)) && printf '%s' "$pids_limit" || printf 'unenforced')); engine reports controllers $cgroup_controllers; check rootless cgroup v2 controller delegation; session not started"

# Explicit redirection retains redirected stdin for the background client.
attached=1
started_at=$SECONDS
if [[ -f "$script_dir/setup/diagnostics.py" ]] && command -v python3 >/dev/null; then
    # Optional for unrestricted installs without host Python. Only the exact
    # successful Podman 4.3 restart-check line changes level; errors pass.
    mkfifo -- "$session_tmp/diagnostics.pipe"
    python3 -I "$script_dir/setup/diagnostics.py" <"$session_tmp/diagnostics.pipe" >&2 &
    diagnostics_pid=$!
    exec {diagnostics_fd}>"$session_tmp/diagnostics.pipe"
    podman start --attach --interactive --sig-proxy=false "$container_id" <&0 2>&"$diagnostics_fd" {diagnostics_fd}>&- &
    client_pid=$!
    exec {diagnostics_fd}>&-
    diagnostics_fd=''
else
    podman start --attach --interactive --sig-proxy=false "$container_id" <&0 &
    client_pid=$!
fi
if ((pending_status)); then
    exit "$pending_status"
fi
status=0
wait "$client_pid" || status=$?
((pending_status == 0)) || exit "$pending_status"
client_pid=''
if ((run_timeout > 0 && status != 0 && SECONDS - started_at >= run_timeout)); then
    printf 'pi-container: session lifetime limit reached (%s s); exit status %s\n' "$run_timeout" "$status" >&2
fi
exit "$status"

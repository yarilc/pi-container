# shellcheck shell=bash
# Shared launcher core, sourced by every wrapper's thin entry script as
#   source launcher/core.sh agent/launcher.sh "$@"
# The entry script sets the shell options, WRAPPER_INVOKED (the invoked path),
# WRAPPER_PATH (its physical path, empty without GNU readlink) and wrapper_dir.
# Everything agent-specific comes from agent/launcher.sh; see
# docs/launcher-contract.md for the contract.
agent_file=$1
shift
# shellcheck source=/dev/null
source "$agent_file"
P=$AGENT_ENV_PREFIX
# Settings are read once from <P>_* into cfg_<SUFFIX>; an unset variable stays
# unset, so ${cfg_X-default} keeps the "only unset selects the default" rule.
for core_suffix in NETWORK NETWORK_PROFILE NETWORK_POLICY NETWORK_RUNTIME_DIR EGRESS_IMAGE IMAGE \
    STATE_DIR PODMAN TRUST_HOST_CA CA_BUNDLE MAINTENANCE QUALIFICATION_INPUT \
    MEMORY_LIMIT CPU_LIMIT PIDS_LIMIT RUN_TIMEOUT TOOLCHAINS TOOLCHAINS_DIR ENV_VARS READONLY_STATE \
    ALLOW_UNSAFE_WORKSPACE ENGINE_IMAGE; do
    core_name=${P}_$core_suffix
    if [[ -v $core_name ]]; then
        printf -v "cfg_$core_suffix" '%s' "${!core_name}"
    fi
done
if [[ -v $AGENT_CONFIG_DIR_ENV ]]; then
    cfg_CONFIG_DIR=${!AGENT_CONFIG_DIR_ENV}
fi
unset core_suffix core_name

die() { printf '%s: %s\n' "$AGENT_NAME" "$*" >&2; exit 1; }

# Every read-only engine query is bounded, so a stalled service cannot hang a
# launch; create, start, build and pull are not (docs/launcher-contract.md M8).
engine() {
    timeout --kill-after=1s 10s podman "$@"
}

# One engine record: strip one final LF; refuse CR and further records.
single_record() {
    local name=$1 message=$2 value
    value=${!name%$'\n'}
    [[ "$value" != *[$'\n'$'\r']* ]] || die "$message"
    printf -v "$name" '%s' "$value"
}

# Keep final LF bytes while retaining the query's own exit status and stderr.
# ShellCheck cannot see this assignment: a variable it sets is read with a
# SC2154 directive naming capture_response.
capture_response() {
    local destination=$1 captured query_status
    shift
    if captured=$("$@"; query_status=$?; printf '\034'; exit "$query_status"); then
        printf -v "$destination" '%s' "${captured%$'\034'}"
    else
        return "$?"
    fi
}

usage() {
    # Builtins only: help works without sed or any other host tool.
    local text
    IFS= read -r -d '' text <<'EOF' || true
Usage: @WRAPPER@ [container option] [arguments...]

Runs @DISPLAY@ (@COMMAND@) in a read-only Podman container. The current
directory (or its parent with --container-git-worktree) and the @DISPLAY@
configuration and shared directories are mounted read/write. Sessions default
to @DEFAULT_MODE@ mode.

Container options:
  --container-setup      interactively prepare a complete user installation
  --container-qualify    verify a prepared restricted installation with fixed local controls
  --container-build      build or refresh the container image; without other
                         arguments it builds and exits
  --container-shell      start a Bash shell instead of @COMMAND@ (always Bash
                         when @COMMAND@ is the shell)
  --container-git-worktree mount the parent of the current directory read/write
                         for Git worktrees; the container starts in the current directory
  --container-toolchain  manage the shared read-only toolchain library; must be first:
                         add <recipe.json|name> | list | remove <name> | verify [<name>];
                         add pulls pinned images and downloads pinned archives itself
  --container-help       show this wrapper help

All other arguments are passed to @COMMAND@ (or to Bash in shell mode) unchanged.

Environment:
@NETWORK_HELP@  @P@_MAINTENANCE authorize image preparation only with exact value 1
  @P@_IMAGE  image name (default: @IMAGE@:latest)
  @CONFIG_ENV@ configuration directory (default: ~/@CONFIG_HOME@)
  @P@_STATE_DIR optional isolated home; unset keeps shared configuration
                           (must not be, contain or lie inside the workspace)
  @P@_TRUST_HOST_CA  trust a host CA bundle: 1, true, or yes (default: disabled)
  @P@_CA_BUNDLE      CA bundle file to trust (default: first of
                                   /etc/ssl/certs/ca-certificates.crt and
                                   /etc/pki/tls/certs/ca-bundle.crt)
  @P@_MEMORY_LIMIT   shell memory, integer with k/m/g unit (default: 4g)
  @P@_CPU_LIMIT      shell CPUs, up to 3 decimals (default: 2)
  @P@_PIDS_LIMIT     shell process limit (default: 512)
                                   Budgets cannot be disabled; managed launches use
                                   the values saved by setup unless exported
  @P@_RUN_TIMEOUT    container lifetime in whole seconds
                                   (default: 0, disabled by default)
  @P@_ALLOW_UNSAFE_WORKSPACE  exact 1 permits a refused sensitive
                                   workspace with a warning (default: disabled)
  @P@_TOOLCHAINS     0, false, or no omits the read-only /toolchains
                                   library mount (default: mounted)
  @P@_TOOLCHAINS_DIR toolchain library shared by the wrappers (default:
                                   ${XDG_DATA_HOME:-~/.local/share}/sandbox-toolchains)
  @P@_ENV_VARS       whitespace-separated host variable names to forward by
                                   name, never by value; an invalid name stops
                                   the launch and reserved names are skipped
  @P@_READONLY_STATE 1, true, or yes mounts the existing configuration and
                                   shared directories read-only (default: disabled)
@PROVIDER_HELP@@AGENT_HELP@
Restricted use needs a protected installation: new users first run
  bash ./@WRAPPER@ --container-setup
and then use the managed launch command printed by setup from a workspace. A
restricted launch, including the default mode, from a location without a
protected installation stops with this guidance before engine queries or state
creation.
Direct use from a checkout needs explicit unrestricted networking, for example:
  @P@_NETWORK=unrestricted bash ./@WRAPPER@
  @P@_NETWORK=unrestricted @P@_MAINTENANCE=1 bash ./@WRAPPER@ --container-build
Offline sessions have no external network. Restricted failures never retry
unrestricted.

Configured launch requires a verified Linux rootless engine, locally or via an explicit
same-host Unix CONTAINER_HOST with an absolute socket pathname beyond /.
Named connections and TCP/SSH are unsupported.
Host Podman delegation was removed: @P@_PODMAN=1 stops startup. Worktree mode
exposes the entire parent read/write.
State directories must belong to the caller and deny group/other access.
Unset @CONFIG_ENV@ when selecting an isolated home; no state is imported.
Temporary /tmp, /run and /var/tmp mounts, and the ephemeral home of sessions
without a writable isolated home, are limited to 512/32/512/512 MiB and noexec;
a profile may allow execution in /tmp and the home for native runtime parts.
Host GNU timeout is required. Shutdown is bounded to 20 seconds, with at most
5 seconds for graceful exit before forced owned-container removal. Cleanup
failures are reported without changing the session or first signal status.
Engine verification replies must contain one record, with no terminator or a
single final LF; extra blank or nonblank records stop startup before builds.
Network restriction requires a protected
installation outside writable workspace/state trees and host Python 3. Eligible
Linux/WSL2 x86_64 installations require a same-host Unix rootless Netavark
service, Podman >= 4.9, standard OCI seccomp and usable Landlock ABI >= 3.
Unsupported setups fail closed. Image pulls/build RUN steps remain outside
runtime filtering and require separate maintenance authorization.
Restricted startup requires a protected static guard and SHA-256 manifest in
network/bin plus a current protected local qualification report. Run setup or
--container-qualify alone after preparation or relevant updates. Kernel/server
exact pins and upper bounds do not determine support. SELinux/AppArmor remains
active when enabled; compatibility is not guaranteed and denials stop startup.
The guard adds
unprivileged Landlock and restrictive seccomp, preserving the OCI profile.
New Unix services are unavailable; fixed-peer pairs may have private inert names.
See network/README.md for packaging and docs/validation.md for measured evidence.
Every session container, in all network modes, drops all
capabilities, enables no-new-privileges and receives the memory, CPU and process
budgets whose cgroup v2 controller the rootless engine delegates (only with the
systemd cgroup manager; cgroupfs delegates none); a budget whose controller is
not delegated is not enforced and a notice names why. Without pids, the
process budget falls back to a per-session process rlimit, set by the session's
first process, when the engine kernel is Linux 5.14 or later. Memory and
CPU have no fallback. The created configuration is checked before the session
starts; a delegated limit or fallback that is ignored stops startup. Without
memory or process budgets a session can exhaust host memory or processes for
your user.
Budgets and tmpfs sizes do not limit workspace or state storage growth.
The workspace mount (the parent in worktree mode) must not be /, your home,
/home, /root, /etc, /usr, /var, /bin, /sbin, /lib, /lib64, /boot, /opt, /srv,
/mnt, /media, /proc, /sys, /dev, /run, /tmp or a WSL drive root such as /mnt/c.
On a drive mount it must not be Users, a profile Users/<name>, its Documents,
OneDrive or OneDrive/Documents, anything in its AppData, Windows, Program Files,
Program Files (x86) or ProgramData, in any letter case.
A reached lifetime limit is reported; the exit status is preserved.
Qualification is credential-free, uses disposable fixed controls and never grants
image maintenance or forwards a command. ABI queries alone do not qualify an
installation. Changed boot, engine/backend/security, code/images, policy/profile,
CA trust or hardening, including budgets and lifetime, invalidates evidence.
Unknown active LSM policy identity requires the gate each launch.
Locally-qualified installations are visibly distinguished from exact
release-measured acceptance records.
EOF
    local network provider='' item hosts agent_text=''
    if ((${#AGENT_CREDENTIALS[@]})); then
        network="  @P@_NETWORK offline, provider (default when unset or empty), or
                           unrestricted
"
        provider="  @P@_NETWORK_PROFILE protected provider policy profile name
  @P@_NETWORK_POLICY  absolute operator policy JSON path
  @P@_NETWORK_RUNTIME_DIR private native directory at its host path
  @P@_EGRESS_IMAGE    immutable proxy image ID or registry digest

Provider mode allows only the hosts of the selected policy profile. Destination
and SNI binding cannot tell your credentials from attacker-supplied ones, so
each allowed host can receive workspace data sent with a foreign key or
account. Only offline mode removes this channel. Allowed hosts:
"
        for item in "${AGENT_POLICY_HOSTS[@]}"; do
            hosts=${item#*=}
            provider+="  ${item%%=*}: ${hosts// /, }
"
        done
    else
        network="  @P@_NETWORK offline (default when unset or empty) or unrestricted;
                           provider is unavailable: the profile declares no
                           authentication method
"
    fi
    if declare -F agent_help >/dev/null; then
        agent_text=$(agent_help) || die 'hook agent_help failed'
        agent_text+=$'\n'
    fi
    text=${text//@NETWORK_HELP@/$network}
    text=${text//@PROVIDER_HELP@/$provider}
    text=${text//@AGENT_HELP@/$agent_text}
    text=${text//@P@/$P}
    text=${text//@WRAPPER@/$AGENT_WRAPPER}
    text=${text//@IMAGE@/$AGENT_IMAGE}
    text=${text//@CONFIG_HOME@/$AGENT_CONFIG_HOME}
    text=${text//@CONFIG_ENV@/$AGENT_CONFIG_DIR_ENV}
    text=${text//@DISPLAY@/$AGENT_DISPLAY_NAME}
    text=${text//@COMMAND@/$AGENT_COMMAND}
    text=${text//@DEFAULT_MODE@/$(default_mode)}
    printf '%s' "$text"
}

# A profile with authentication methods defaults to provider mode (U1); the
# shell reference, without methods, to offline.
default_mode() {
    if ((${#AGENT_CREDENTIALS[@]})); then printf provider; else printf offline; fi
}

# Phase 1: help, toolchain, qualify and setup dispatch, option parsing.
core_arguments() {
    # Setup must diagnose prerequisites before normal runtime configuration exists.
    # Help takes precedence regardless of option order and never loads setup code.
    for arg in "$@"; do
        [[ "$arg" != --container-help ]] || { usage; exit 0; }
    done
    # Toolchain management runs on the host and never starts a session.
    if [[ "${1:-}" == --container-toolchain ]]; then
        [[ "${2:-}" != launch-env ]] || die 'usage: --container-toolchain add <recipe.json|name> | list | remove <name> | verify [<name>]'
        command -v python3 >/dev/null || die 'host Python 3 is required for the toolchain library'
        # shellcheck disable=SC2154 # wrapper_dir is set by the entry script.
        exec python3 -I "$wrapper_dir/setup/toolchains.py" "${@:2}"
    fi
    for arg in "$@"; do
        if [[ "$arg" == --container-qualify ]]; then
            [[ $# == 1 ]] || die '--container-qualify must be used alone'
            command -v python3 >/dev/null || die 'host Python 3 is required for qualification'
            exec python3 -I "$wrapper_dir/network/qualify.py" qualify
        fi
    done
    for arg in "$@"; do
        if [[ "$arg" == --container-setup ]]; then
            [[ $# == 1 ]] || die '--container-setup must be used alone'
            [[ -t 0 && -t 1 ]] || die '--container-setup requires an interactive terminal'
            command -v python3 >/dev/null || die 'host Python 3 is required for interactive setup'
            exec python3 -I "$wrapper_dir/setup/setup.py"
        fi
    done

    build_image=0
    qualification_probe=0
    git_worktree=0
    # A profile whose command is a shell always runs in shell mode (H-c).
    shell_mode=0
    [[ "$AGENT_COMMAND" != bash && "$AGENT_COMMAND" != sh ]] || shell_mode=1
    args=()
    for arg in "$@"; do
        case "$arg" in
            --container-qualify-probe)
                [[ $# == 1 ]] || die 'the fixed qualification probe must be used alone'
                qualification_probe=1 ;;
            --container-help) usage; exit 0 ;;
            --container-build) build_image=1 ;;
            --container-shell) shell_mode=1 ;;
            --container-git-worktree) git_worktree=1 ;;
            --container-toolchain) die '--container-toolchain must be the first argument' ;;
            *) args+=("$arg") ;;
        esac
    done
    # --container-build without application arguments builds and exits (U3, U17);
    # --container-git-worktree and --container-shell do not count. Setup uses it.
    build_only=0
    ((build_image == 0 || ${#args[@]} > 0)) || build_only=1
}

# Phase 2: network mode, switches, budgets and lifetime.
core_settings() {
    # The default mode is the profile's (U1); unrestricted applies only when explicit.
    network_mode=${cfg_NETWORK:-$(default_mode)}
    if ((${#AGENT_CREDENTIALS[@]})); then
        case "$network_mode" in
            offline|provider|unrestricted) ;;
            *) die "${P}_NETWORK must be offline, provider, or unrestricted" ;;
        esac
    else
        case "$network_mode" in
            offline|unrestricted) ;;
            provider) die "${P}_NETWORK=provider is unavailable: the profile declares no authentication method; use offline or unrestricted" ;;
            *) die "${P}_NETWORK must be offline or unrestricted" ;;
        esac
    fi
    restricted=0
    [[ "$network_mode" == unrestricted ]] || restricted=1
    # Host tools are diagnosed later, so a missing readlink leaves the path empty here.
    script_path=$WRAPPER_PATH
    script_dir=${script_path%/*}
    # A launch from the Windows entry (WRAPPER_WINDOWS_ENTRY, set by the
    # bootstrap) prepares the machine with setup from Windows.
    if [[ -n "${WRAPPER_WINDOWS_ENTRY:-}" ]]; then
        setup_step="run $AGENT_NAME.ps1 --container-setup from Windows"
    else
        setup_wrapper=$WRAPPER_INVOKED
        [[ "$setup_wrapper" == /* ]] || setup_wrapper="$PWD/$setup_wrapper"
        printf -v setup_step 'run bash %q --container-setup and use the managed launcher' "$setup_wrapper"
    fi
    # A restricted session needs a protected installation with the built guard and
    # its manifest. Without one, give setup guidance before any engine or state
    # operation; session.py prepare still validates the installation fully.
    if ((restricted)) \
        && { [[ -z "$script_path" ]] || ! compgen -G "$script_dir/network/bin/*.sha256" >/dev/null; }; then
        die "setup required: $network_mode sessions need a protected installation; $setup_step, or set ${P}_NETWORK=unrestricted for a direct session"
    fi
    # Provider mode needs the settings setup saves; a default provider launch
    # without them is a missing setup, an explicit one a configuration error.
    network_profile=''
    if [[ "$network_mode" == provider ]]; then
        if [[ -z "${cfg_NETWORK:-}" ]] && [[ -z "${cfg_NETWORK_PROFILE:-}" || -z "${cfg_NETWORK_POLICY:-}" \
            || -z "${cfg_NETWORK_RUNTIME_DIR:-}" || -z "${cfg_EGRESS_IMAGE:-}" ]]; then
            die "setup required: provider sessions, the default for $AGENT_DISPLAY_NAME, need the settings setup saves; $setup_step"
        fi
        [[ -n "${cfg_NETWORK_PROFILE:-}" && -n "${cfg_NETWORK_POLICY:-}" ]] \
            || die "provider mode requires ${P}_NETWORK_PROFILE and ${P}_NETWORK_POLICY"
        [[ -n "${cfg_NETWORK_RUNTIME_DIR:-}" && -n "${cfg_EGRESS_IMAGE:-}" ]] \
            || die "provider mode requires a private host-path ${P}_NETWORK_RUNTIME_DIR and immutable ${P}_EGRESS_IMAGE"
        network_profile=$cfg_NETWORK_PROFILE
    fi

    boolean() {
        case "${2,,}" in
            1|true|yes) printf 1 ;;
            ''|0|false|no) printf 0 ;;
            *) die "$1 must be 0, 1, true, false, yes, or no" ;;
        esac
    }
    toolchains_enabled=$(boolean "${P}_TOOLCHAINS" "${cfg_TOOLCHAINS:-1}")
    # Host Podman delegation was removed (session-container-engine): a leftover
    # exact opt-in stops every launch instead of silently starting without it.
    [[ "${cfg_PODMAN:-}" != 1 ]] \
        || die "${P}_PODMAN=1: host Podman delegation was removed; add the images your tests need with --container-toolchain add, so that sessions get their own container engine (README: Container tests), then unset ${P}_PODMAN"
    trust_host_ca=$(boolean "${P}_TRUST_HOST_CA" "${cfg_TRUST_HOST_CA:-}")
    [[ -z "${cfg_STATE_DIR:-}" || -z "${cfg_CONFIG_DIR:-}" ]] \
        || die "${P}_STATE_DIR conflicts with $AGENT_CONFIG_DIR_ENV; unset $AGENT_CONFIG_DIR_ENV to isolate state"
    if [[ -n "${cfg_STATE_DIR:-}" ]]; then
        [[ "$cfg_STATE_DIR" == /* && "$cfg_STATE_DIR" != *[:$'\n'$'\r']* ]] \
            || die "${P}_STATE_DIR must be an absolute path without colon, CR or LF: $cfg_STATE_DIR"
    fi
    if [[ -n "${cfg_CONFIG_DIR:-}" ]]; then
        [[ "$cfg_CONFIG_DIR" == /* && "$cfg_CONFIG_DIR" != *[:$'\n'$'\r']* ]] \
            || die "$AGENT_CONFIG_DIR_ENV must be an absolute path without colon, CR or LF: $cfg_CONFIG_DIR"
    fi
    [[ "${cfg_IMAGE:-}" != *[[:space:][:cntrl:]]* ]] \
        || die "${P}_IMAGE must not contain whitespace or control characters"
    readonly_state=$(boolean "${P}_READONLY_STATE" "${cfg_READONLY_STATE:-}")
    # Extra variables are forwarded by name only (U5, U18).
    env_var_names=()
    if [[ -n "${cfg_ENV_VARS:-}" ]]; then
        read -r -d '' -a env_var_names <<<"$cfg_ENV_VARS" || true
    fi
    for core_name in "${env_var_names[@]}"; do
        [[ "$core_name" =~ ^[A-Za-z_][A-Za-z0-9_]*$ ]] \
            || die "${P}_ENV_VARS contains an invalid variable name: $core_name"
    done
    # The profile's approval bypass switch is validated here; its effect is the
    # agent's (agent_approval_bypass) and never applies in shell mode.
    approval_bypass=0
    if [[ -n "$AGENT_APPROVAL_BYPASS_ENV" ]]; then
        approval_bypass=$(boolean "$AGENT_APPROVAL_BYPASS_ENV" "${!AGENT_APPROVAL_BYPASS_ENV:-}")
    fi

    # Agent budgets and lifetime. network/agent_budgets.py implements the same
    # rules for setup and qualification; unrestricted installs may lack host Python.
    # Only an unset budget selects its default; no value disables a budget.
    memory_text=${cfg_MEMORY_LIMIT-4g}
    cpu_text=${cfg_CPU_LIMIT-2}
    pids_text=${cfg_PIDS_LIMIT-512}
    timeout_text=${cfg_RUN_TIMEOUT:-0}
    memory_bytes=0
    if [[ "$memory_text" =~ ^([1-9][0-9]{0,15})([kmgKMG])$ ]]; then
        case "${BASH_REMATCH[2],,}" in
            k) unit=1024 ;;
            m) unit=1048576 ;;
            *) unit=1073741824 ;;
        esac
        ((10#${BASH_REMATCH[1]} > (1 << 50) / unit)) || memory_bytes=$((10#${BASH_REMATCH[1]} * unit))
    fi
    ((memory_bytes > 0)) || die "${P}_MEMORY_LIMIT must be a positive integer with unit k, m or g, for example 4g"
    cpu_nano=0
    if [[ "$cpu_text" =~ ^([0-9]{1,4})(\.([0-9]{1,3}))?$ ]]; then
        fraction=${BASH_REMATCH[3]}000
        cpu_nano=$((10#${BASH_REMATCH[1]} * 1000000000 + 10#${fraction:0:3} * 1000000))
        ((cpu_nano <= 1024000000000)) || cpu_nano=0
    fi
    ((cpu_nano > 0)) || die "${P}_CPU_LIMIT must be a positive number of CPUs with at most 3 decimals, for example 2 or 1.5"
    [[ "$pids_text" =~ ^(0|[1-9][0-9]{0,9})$ ]] && ((pids_text > 0 && pids_text <= 4194304)) \
        || die "${P}_PIDS_LIMIT must be a positive integer process count up to 4194304"
    [[ "$timeout_text" =~ ^(0|[1-9][0-9]{0,9})$ ]] && ((timeout_text <= 2147483647)) \
        || die "${P}_RUN_TIMEOUT must be whole seconds; 0 disables the lifetime limit"
    pids_limit=$((10#$pids_text))
    run_timeout=$((10#$timeout_text))
    call_hook agent_validate "$network_mode"
}

# Phase 3: workspace refusal, host tools and state overlap.
core_workspace() {
    # The build-only operation mounts no workspace: no refusal applies (U16).
    ((build_only)) || core_workspace_refusal
    # One check of every host tool the core uses, in the reference's order.
    command -v podman >/dev/null || die 'Podman is required on the host'
    command -v timeout >/dev/null && [[ $(timeout --version 2>/dev/null) == *'GNU coreutils'* ]] \
        || die 'GNU timeout is required on the host; install GNU coreutils'
    [[ -n "$script_path" ]] || die 'GNU readlink is required on the host; install GNU coreutils'
    command -v stat >/dev/null || die 'GNU stat is required on the host; install GNU coreutils'
    command -v sha256sum >/dev/null || die 'GNU sha256sum is required on the host; install GNU coreutils'
    # Isolated credentials and history must never land in, or contain, the workspace.
    # Compare physical paths; readlink -m also resolves a directory not created yet.
    if [[ -n "${cfg_STATE_DIR:-}" ]] && ((build_only == 0)); then
        state_physical=$(readlink -m -- "$cfg_STATE_DIR")
        [[ "$state_physical/" != "$workspace_mount/"* && "$workspace_mount/" != "$state_physical/"* ]] \
            || die "${P}_STATE_DIR must not overlap the workspace: $cfg_STATE_DIR"
    fi
}

core_workspace_refusal() {
    # Refuse sensitive writable workspaces before any engine or state operation.
    workspace=$(pwd -P)
    workspace_mount=$workspace
    ((git_worktree == 0)) || workspace_mount=$(dirname -- "$workspace")
    [[ "${HOME:-}" == /* ]] || die 'HOME must be an absolute path'
    # Builtins only: tool prerequisites are diagnosed later. A missing home cannot
    # be a workspace, so its lexical path is sufficient then.
    physical_home=$(cd -- "$HOME" 2>/dev/null && pwd -P) || physical_home=$HOME
    unsafe_workspace=0
    case "$workspace_mount" in
        /|/home|/root|/etc|/usr|/var|/bin|/sbin|/lib|/lib64|/boot|/opt|/srv|/mnt|/media|/proc|/sys|/dev|/run|/tmp)
            unsafe_workspace=1 ;;
    esac
    [[ "$workspace_mount" != "$physical_home" && ! "$workspace_mount" =~ ^/mnt/[A-Za-z]$ ]] || unsafe_workspace=1
    # Windows system and profile folders on a WSL drive mount, compared without
    # case like drvfs does. Projects below them stay accepted.
    # Documents and OneDrive hold the PowerShell profile and modules, and AppData
    # the startup folder: code written there runs on Windows outside the sandbox.
    windows_roots='^/mnt/[a-z](/users(/[^/]+(/documents|/onedrive( - [^/]+)?(/documents)?|/appdata(/.*)?)?)?'
    windows_roots+='|/windows|/program files( \(x86\))?|/programdata)$'
    [[ ! "${workspace_mount,,}" =~ $windows_roots ]] || unsafe_workspace=1
    if ((unsafe_workspace)); then
        [[ "${cfg_ALLOW_UNSAFE_WORKSPACE:-}" == 1 ]] \
            || die "refusing sensitive workspace $workspace_mount; launch from a project subdirectory or set exact ${P}_ALLOW_UNSAFE_WORKSPACE=1"
        printf '%s: WARNING: sensitive workspace explicitly exposed read/write: %s\n' "$AGENT_NAME" "$workspace_mount" >&2
    fi
}

# Phase 4: launch engine, cgroup controllers, restricted queries.
core_engine() {
    # Unix service access also supports running this wrapper inside another container
    # on the same host. TCP/SSH transports and the Podman machine's remote connection
    # are not supported; inside the machine's own distribution the local engine is.
    # Empty means the local engine here, but Podman treats a set CONTAINER_HOST
    # or CONTAINER_CONNECTION as a remote context even when it is empty.
    [[ -n "${CONTAINER_HOST:-}" ]] || unset CONTAINER_HOST
    [[ -n "${CONTAINER_CONNECTION:-}" ]] || unset CONTAINER_CONNECTION
    [[ -z "${CONTAINER_CONNECTION:-}" ]] || die 'named remote connections are not supported; use local Podman or a local Unix CONTAINER_HOST'
    case "${CONTAINER_HOST:-}" in
        '') ;;
        unix://*)
            launch_socket=${CONTAINER_HOST#unix://}
            [[ "$launch_socket" == /* && -n "${launch_socket//\//}" ]] \
                || die 'CONTAINER_HOST requires an absolute Unix socket path beyond /'
            ;;
        *) die 'remote TCP/SSH Podman contexts are not supported; use a local Unix socket' ;;
    esac
    capture_response runtime_info engine info --format '{{.Host.Security.Rootless}} {{.Host.OS}} {{.Host.ServiceIsRemote}}' \
        || die 'cannot query Podman; check the local rootless service'
    single_record runtime_info 'invalid Podman engine response: expected one record with at most one final LF'
    local rootless runtime_os extra
    # shellcheck disable=SC2154 # set by capture_response
    read -r rootless runtime_os remote extra <<< "$runtime_info"
    [[ "$rootless" == true && "$runtime_os" == linux && "$remote" =~ ^(true|false)$ && -z "$extra" ]] \
        || die 'a verified Linux rootless Podman engine is required (unexpected engine response)'
    if [[ "$remote" == true && "${CONTAINER_HOST:-}" != unix:///* ]]; then
        die 'remote Podman contexts are not supported; set CONTAINER_HOST to a local Unix socket'
    fi

    ((build_only)) || core_engine_session
    caller_uid=$(id -u)
    caller_gid=$(id -g)
}

# Mechanism enforcing a process budget: the pids cgroup controller, the process
# rlimit (Linux 5.14 and later count it per user namespace), or none. Sets
# process_budget and, for none, process_reason. network/agent_budgets.py
# (process_mechanism, fallback_reason) is the same rule.
#
# The rlimit is set inside each container by its first process
# (core_process_step), never with --ulimit: a new user namespace records its
# creator's limit, and every container of the user counts against it one level
# up, so a limit that the engine applies at creation is shared by all of them.
process_budget_rule() {
    local controllers=$1 kernel=$2
    local pattern='^([0-9]{1,4})\.([0-9]{1,4})([-.+_~][0-9A-Za-z._+~-]*)?$'
    process_reason=''
    if [[ " ${controllers:1:${#controllers}-2} " == *" pids "* ]]; then
        process_budget=cgroup
    elif [[ "$kernel" =~ $pattern ]]; then
        if ((10#${BASH_REMATCH[1]} > 5 || (10#${BASH_REMATCH[1]} == 5 && 10#${BASH_REMATCH[2]} >= 14))); then
            process_budget=rlimit
        else
            process_budget=none
            process_reason="kernel $kernel counts the process rlimit per user, not per container (Linux 5.14 or later is required)"
        fi
    else
        process_budget=none
        process_reason='unrecognized kernel version'
    fi
}

# The process rlimit step: the container's first process sets its soft and hard
# process rlimit to the budget, then executes the entry program in its place,
# or stops the container before the program runs. The script is fixed apart
# from the validated budget, and calls nothing else. Bash and BusyBox name the
# limit -u; dash, the /bin/sh of the agent and proxy images, names it -p (in
# Bash, -p is the read-only pipe size, so it never sets anything there).
process_step_script() {
    # shellcheck disable=SC2016 # expanded by the container's shell
    printf '{ ulimit -u %s 2>/dev/null || ulimit -p %s; } && exec "$0" "$@"' "$1" "$1"
}

# Podman runs a container created with --init through this program.
init_program=/run/podman-init

# On the process rlimit fallback, the session's entry program runs through the
# step: the guard in restricted modes, /bin/bash in an unrestricted shell, and
# the profile's agent program in place of the image entrypoint otherwise. Sets
# process_command to the created command that budgets_applied requires.
core_process_step() {
    local index entry='' found=0
    process_command=()
    [[ "$process_budget" == rlimit ]] || return 0
    for index in "${!container_args[@]}"; do
        [[ "${container_args[$index]}" == --entrypoint ]] || continue
        ((found == 0)) || die 'more than one entrypoint in the session options'
        found=1
        entry=${container_args[index + 1]:-}
        container_args[index + 1]=/bin/sh
    done
    if ((found == 0)); then
        entry=$AGENT_EXEC
        container_args+=(--entrypoint /bin/sh)
    fi
    [[ "$entry" == /* ]] || die "invalid entry program for the process rlimit step: $entry"
    process_command=(/bin/sh -c "$(process_step_script "$pids_limit")" "$entry")
    args=("${process_command[@]:1}" "${args[@]}")
    [[ "$network_mode" != unrestricted ]] || process_command=("$init_program" -- "${process_command[@]}")
}

core_engine_session() {
    # A budget is enforced only when the verified engine reports its cgroup v2
    # controller as delegated. Unenforced budgets are not requested, are announced,
    # and must be absent from the created configuration (see network/agent_budgets.py).
    capture_response cgroup_controllers engine info --format '{{.Host.CgroupControllers}}' \
        || die 'cannot query the rootless cgroup controllers'
    single_record cgroup_controllers 'unverifiable cgroup controller list from the Podman engine'
    # shellcheck disable=SC2154 # set by capture_response
    [[ "$cgroup_controllers" =~ ^\[([a-z_]+( [a-z_]+)*)?\]$ ]] \
        || die 'unverifiable cgroup controller list from the Podman engine'
    # A rootless engine applies cgroup limits only through the systemd manager:
    # cgroupfs may report every controller and ignore the limits (Podman machine
    # on WSL), so it delegates none (network/agent_budgets.py delegated()).
    capture_response cgroup_manager engine info --format '{{.Host.CgroupManager}}' \
        || die 'cannot query the rootless cgroup manager'
    single_record cgroup_manager 'unverifiable cgroup manager from the Podman engine'
    # shellcheck disable=SC2154 # set by capture_response
    [[ "$cgroup_manager" =~ ^[a-z]{1,32}$ ]] || die 'unverifiable cgroup manager from the Podman engine'
    delegated_controllers=$cgroup_controllers
    [[ "$cgroup_manager" == systemd ]] || delegated_controllers='[]'
    controller_delegated() {
        [[ " ${delegated_controllers:1:${#delegated_controllers}-2} " == *" $1 "* ]]
    }
    cgroup_reason() {
        if [[ "$cgroup_manager" == systemd ]]; then
            printf 'cgroup controller %s is not delegated to the rootless engine' "$1"
        else
            printf 'the rootless engine uses the %s cgroup manager, which applies no cgroup limits' "$cgroup_manager"
        fi
    }
    budget_args=()
    expected_memory=0
    expected_cpu=0
    pids_enforced=0
    if controller_delegated memory; then
        budget_args+=("--memory=$memory_bytes")
        expected_memory=$memory_bytes
    else
        printf '%s: agent memory budget not enforced: %s\n' "$AGENT_NAME" "$(cgroup_reason memory)" >&2
    fi
    if controller_delegated cpu; then
        budget_args+=("--cpus=$cpu_text")
        expected_cpu=$cpu_nano
    else
        printf '%s: agent CPU budget not enforced: %s\n' "$AGENT_NAME" "$(cgroup_reason cpu)" >&2
    fi
    # The counting semantics of the process rlimit belong to the engine host's kernel.
    capture_response engine_kernel engine info --format '{{.Host.Kernel}}' \
        || die 'cannot query the engine kernel version'
    single_record engine_kernel 'invalid engine kernel version response'
    # shellcheck disable=SC2154 # set by capture_response
    process_budget_rule "$delegated_controllers" "$engine_kernel"
    case "$process_budget" in
        cgroup)
            budget_args+=("--pids-limit=$pids_limit")
            pids_enforced=1
            ;;
        rlimit)
            # Override any containers.conf default that would request the missing
            # controller. The limit itself is set inside the container
            # (core_process_step), never with --ulimit.
            budget_args+=(--pids-limit=-1)
            printf '%s: agent process budget enforced through the process rlimit (%s tasks of the session user, threads included): %s\n' "$AGENT_NAME" "$pids_limit" "$(cgroup_reason pids)" >&2
            ;;
        *)
            budget_args+=(--pids-limit=-1)
            printf '%s: agent process budget not enforced: %s; %s\n' "$AGENT_NAME" "$(cgroup_reason pids)" "$process_reason" >&2
            ;;
    esac
    if [[ "$network_mode" != unrestricted ]]; then
        command -v python3 >/dev/null || die 'host Python 3 is required for restricted network policy validation'
        [[ "$remote" == true ]] || die 'restricted networking currently requires the tested same-host Unix service; local-engine enforcement is unverified'
        capture_response network_backend engine info --format '{{.Host.NetworkBackend}}' \
            || die 'cannot verify restricted network backend'
        single_record network_backend 'invalid restricted network backend response'
        capture_response network_version engine version --format '{{.Server.Version}}' \
            || die 'cannot verify restricted network server version'
        single_record network_version 'invalid restricted network server version response'
        capture_response network_platform engine info --format '{{json .Host}}' \
            || die 'cannot verify restricted platform security policy'
        single_record network_platform 'invalid restricted platform security policy response'
    elif ((qualification_probe)); then
        die 'qualification probes require restricted networking'
    fi
}

# Phase 3 (after the engine): state directories and CA bundle.
core_state() {
    image="${cfg_IMAGE:-$AGENT_IMAGE:latest}"
    state_dir="${cfg_STATE_DIR:-}"

    private_directory() {
        local path=$1 mode
        [[ -d "$path" && -r "$path" && -w "$path" && -x "$path" ]] \
            || die "state directory is not accessible: $path (grant your user access, or choose another directory)"
        [[ $(stat -c '%u' -- "$path") == "$caller_uid" ]] \
            || die "state directory must belong to the calling user: $path"
        mode=$(stat -c '%a' -- "$path")
        (( (8#$mode & 077) == 0 )) \
            || die "state directory must be private: $path (chmod 700; use native Linux storage if permissions are not enforced)"
    }

    # The umask stays inside the subshell; the caller reports a failure.
    create_private_directory() {
        (umask 077; mkdir -p -- "$1") 2>/dev/null \
            || die "cannot create state directory: $1 (check its parent's permissions, or choose another directory)"
    }

    # Resolve a state directory only after checking that the caller can enter
    # it, so a failed cd never replaces the wrapper's diagnostic.
    resolve_state_directory() {
        [[ -d "$1" && -r "$1" && -x "$1" ]] \
            || die "state directory is not accessible: $1 (grant your user read and search access, or choose another directory)"
        (cd -- "$1" && pwd -P)
    }

    # The build-only operation creates no state; it only selects the CA bundle.
    state_mounts=()
    writable_state=()
    ((build_only)) || core_state_directories
    core_ca_bundle
}

core_state_directories() {
    # Host directories the session can write: the toolchain library must avoid
    # them and restricted preparation declares them writable.
    if ((readonly_state)); then
        core_readonly_state
        return
    fi
    if [[ -n "$state_dir" ]]; then
        create_private_directory "$state_dir"
        state_dir=$(resolve_state_directory "$state_dir")
        private_directory "$state_dir"
        # Resolve before creating children so an existing parent symlink cannot
        # redirect configuration creation outside the dedicated application home;
        # every child, and the CA mount parent, stays inside it and private (M4).
        local children=("$AGENT_CONFIG_HOME" "${AGENT_SHARED_DIRS[@]}")
        ((trust_host_ca == 0)) || children+=(ca)
        for relative in "${children[@]}"; do
            resolved=$(readlink -m -- "$state_dir/$relative")
            [[ "$resolved" == "$state_dir/"* ]] \
                || die "isolated configuration escapes state home: $state_dir/$relative"
            create_private_directory "$state_dir/$relative"
            private_directory "$state_dir/$relative"
        done
        state_mounts+=(--volume "$state_dir:$AGENT_HOME:rw")
        writable_state+=("$state_dir")
    else
        config_dir="${cfg_CONFIG_DIR:-$HOME/$AGENT_CONFIG_HOME}"
        create_private_directory "$config_dir"
        config_dir=$(resolve_state_directory "$config_dir")
        private_directory "$config_dir"
        state_mounts+=(--volume "$config_dir:$AGENT_HOME/$AGENT_CONFIG_HOME:rw")
        writable_state+=("$config_dir")
        for relative in "${AGENT_SHARED_DIRS[@]}"; do
            create_private_directory "$HOME/$relative"
            shared_path=$(resolve_state_directory "$HOME/$relative")
            ((AGENT_PRIVATE_SHARED_DIRS == 0)) || private_directory "$shared_path"
            state_mounts+=(--volume "$shared_path:$AGENT_HOME/$relative:rw")
            writable_state+=("$shared_path")
        done
    fi
}

# Read-only state (U6, M9): existing configuration and shared directories are
# mounted read-only below the home, from shared state or the isolated home; the
# isolated home itself is not mounted. Nothing is created, owner and privacy are
# not checked, and none of them is a writable input of restricted preparation.
core_readonly_state() {
    local root=$HOME config relative source
    config=${cfg_CONFIG_DIR:-$HOME/$AGENT_CONFIG_HOME}
    if [[ -n "$state_dir" ]]; then
        root=$state_dir
        config=$state_dir/$AGENT_CONFIG_HOME
    fi
    for relative in "$AGENT_CONFIG_HOME" "${AGENT_SHARED_DIRS[@]}"; do
        source=$root/$relative
        [[ "$relative" != "$AGENT_CONFIG_HOME" ]] || source=$config
        [[ -d "$source" ]] || die "read-only state needs an existing directory: $source"
        source=$(resolve_state_directory "$source")
        state_mounts+=(--volume "$source:$AGENT_HOME/$relative:ro")
    done
}

core_ca_bundle() {
    ca_bundle=""
    if ((trust_host_ca)); then
        if [[ -n "${cfg_CA_BUNDLE:-}" ]]; then
            [[ -f "$cfg_CA_BUNDLE" ]] || die "${P}_CA_BUNDLE is not a file: $cfg_CA_BUNDLE"
            ca_bundle=$(readlink -f -- "$cfg_CA_BUNDLE")
        else
            for candidate in /etc/ssl/certs/ca-certificates.crt /etc/pki/tls/certs/ca-bundle.crt; do
                if [[ -f "$candidate" ]]; then
                    ca_bundle=$candidate
                    break
                fi
            done
            [[ -n "$ca_bundle" ]] || die "no default CA bundle found; set ${P}_CA_BUNDLE to a bundle file"
        fi
    fi
}

# The image (U8, U12, H6, M12): built on --container-build or when absent, only
# with maintenance, from exact bases pulled first, with --pull=never and the
# docker format, without a timeout. Every image carries build-inputs-hash; an
# image built from other inputs is refused until it is rebuilt. The opted-in
# host CA bundle is a build secret: mounted only for its RUN step, never stored.
core_build_inputs_hash() {
    local relative sum lines='' seen=$'\n'
    call_hook agent_build_args
    for relative in "${agent_build_args[@]}"; do
        [[ "$relative" =~ ^[A-Za-z_][A-Za-z0-9_]*=[^$'\n'$'\r']*$ ]] \
            || die "hook agent_build_args returned an invalid build argument: $relative"
    done
    for relative in Containerfile .containerignore network/relay.py network/mux.py \
        "${AGENT_INSTALL_FILES[@]}" "${agent_build_inputs[@]}"; do
        [[ "$seen" != *$'\n'"$relative"$'\n'* ]] || continue
        seen+="$relative"$'\n'
        [[ "$relative" != /* && "/$relative/" != */../* && -f "$script_dir/$relative" ]] \
            || die "build input is not a file inside the installation: $relative"
        sum=$(sha256sum -- "$script_dir/$relative") || die "cannot hash build input: $relative"
        lines+="$relative ${sum%% *}"$'\n'
    done
    sum=$(printf '%s' "$lines" | sha256sum) || die 'cannot hash the build inputs'
    build_hash=${sum%% *}
}

core_build_image() {
    local keyword base stage stages=' ' build_args=()
    core_build_inputs_hash
    build_secret=()
    if [[ -n "$ca_bundle" ]]; then
        build_secret=(--secret "id=build-ca,src=$ca_bundle")
    fi
    if ((build_image == 0)); then
        if engine image exists "$image"; then
            capture_response image_hash engine image inspect --format '{{index .Labels "build-inputs-hash"}}' "$image" \
                || die "cannot inspect image: $image"
            single_record image_hash "invalid image label response: $image"
            # shellcheck disable=SC2154 # set by capture_response
            [[ "$image_hash" == "$build_hash" ]] \
                || die "image $image is stale for the current build inputs (image ${image_hash:-unlabeled}, inputs $build_hash); rebuild it with exact ${P}_MAINTENANCE=1 and --container-build"
            return
        else
            image_status=$?
            [[ "$image_status" == 1 ]] || die "cannot inspect image: $image"
            [[ "${cfg_MAINTENANCE:-}" == 1 ]] || die "image is absent; prepare it with exact ${P}_MAINTENANCE=1 (build traffic is outside runtime filtering)"
        fi
    else
        [[ "${cfg_MAINTENANCE:-}" == 1 ]] || die "image refresh requires exact ${P}_MAINTENANCE=1; host pulls/build RUN steps are outside runtime filtering"
    fi
    # Pull each exact external base once; later stages may name earlier ones.
    while read -r keyword base _ stage _; do
        [[ "${keyword^^}" == FROM && -n "$base" ]] || continue
        if [[ "$stages" != *" $base "* ]] && ! engine image exists "$base"; then
            podman pull "$base" </dev/null || die "cannot pull build base: $base"
        fi
        [[ -z "$stage" ]] || stages+="$stage "
    done <"$script_dir/Containerfile"
    for keyword in "${agent_build_args[@]}"; do
        build_args+=(--build-arg "$keyword")
    done
    build_status=0
    podman build --pull=never --format docker "${build_secret[@]}" "${build_args[@]}" \
        --label "build-inputs-hash=$build_hash" --tag "$image" --file "$script_dir/Containerfile" "$script_dir" \
        </dev/null || build_status=$?
    if ((build_status)); then
        printf '%s: image build failed: %s (status %s)\n' "$AGENT_NAME" "$image" "$build_status" >&2
        exit "$build_status"
    fi
}

# Agent mounts (agent_mounts): read-only binds of existing host paths and small
# private tmpfs mounts. Destinations may lie below the home but never equal or
# contain the temporary mounts, the workspace, the toolchains, the home, the CA
# file or another mount (M7); a tmpfs size is a plain amount with a unit.
core_agent_mounts() {
    local spec kind rest source destination size reserved
    agent_mount_args=()
    agent_mount_targets=()
    call_hook agent_mounts "$network_mode" "$AGENT_HOME"
    for spec in "${agent_mount_specs[@]}"; do
        kind=${spec%%:*}
        rest=${spec#*:}
        case "$kind" in
            ro) source=${rest%%:*}; destination=${rest#*:} ;;
            tmpfs) destination=${rest%%:*}; size=${rest#*:} ;;
            *) die "hook agent_mounts returned an unsupported mount: $spec" ;;
        esac
        [[ "$destination" == /?* && "$destination" != */ && "$destination" != *//* \
            && "$destination" != *[:$'\n'$'\r']* && "/$destination/" != */../* ]] \
            || die "hook agent_mounts returned an invalid destination: $spec"
        for reserved in /tmp /var/tmp /run "$workspace_mount" /toolchains "$AGENT_HOME" "$AGENT_HOME/ca" \
            "${agent_mount_targets[@]}"; do
            [[ "$reserved/" != "$destination/"* ]] \
                || die "hook agent_mounts returned a mount over $reserved: $spec"
        done
        if [[ "$kind" == ro ]]; then
            [[ "$source" == /* && -e "$source" ]] || die "hook agent_mounts returned a missing source: $spec"
            source=$(readlink -f -- "$source")
            [[ "$source" != *[:$'\n'$'\r']* ]] || die "hook agent_mounts returned an invalid source: $spec"
            agent_mount_args+=(--volume "$source:$destination:ro")
        else
            [[ "$size" =~ ^[1-9][0-9]{0,5}[kmgKMG]$ ]] || die "hook agent_mounts returned an invalid tmpfs size: $spec"
            agent_mount_args+=(--tmpfs "$destination:rw,noexec,nosuid,nodev,mode=0700,U,size=$size")
        fi
        agent_mount_targets+=("$destination")
    done
}

# Names the core sets itself; neither agent_environment nor <P>_ENV_VARS may.
core_set_names() {
    printf '%s\n' HOME USER TERM COLORTERM LANG LC_ALL EDITOR VISUAL PATH CONTAINER_HOST DOCKER_HOST CONTAINER_NAME \
        CONTAINER_CONNECTION SSL_CERT_FILE REQUESTS_CA_BUNDLE CURL_CA_BUNDLE NODE_EXTRA_CA_CERTS "$AGENT_CONFIG_DIR_ENV"
}
proxy_names=(HTTP_PROXY HTTPS_PROXY ALL_PROXY NO_PROXY http_proxy https_proxy all_proxy no_proxy)

# The credential variable of the selected policy profile, if any (U10).
selected_credential() {
    local item
    for item in "${AGENT_CREDENTIALS[@]}"; do
        [[ "${item%%=*}" != "$network_profile" ]] || { printf '%s' "${item#*=}"; return; }
    done
}

# Whether a variable name is reserved for this session (M5, U13): set by the
# core or the agent part, a proxy, CA or restricted setting in restricted modes,
# or in provider mode another method's credential.
reserved_name() {
    local name=$1 item
    [[ $'\n'"$core_reserved"$'\n' != *$'\n'"$name"$'\n'* ]] || return 0
    if ((restricted)); then
        [[ " ${proxy_names[*]} " != *" $name "* ]] || return 0
        for item in "${AGENT_RESTRICTED_ENV[@]}" "${AGENT_PROVIDER_ENV[@]}"; do
            [[ "${item%%=*}" != "$name" ]] || return 0
        done
    fi
    if [[ "$network_mode" == provider ]]; then
        for item in "${AGENT_CREDENTIALS[@]}"; do
            [[ -z "${item#*=}" || "${item#*=}" != "$name" || "${item%%=*}" == "$network_profile" ]] || return 0
        done
    fi
    return 1
}

# Session environment in the contract's order; Podman keeps the last value of a
# name, so later groups win (M6): toolchains, core forwarding, agent_environment,
# <P>_ENV_VARS, the approval bypass, core-set values, fixed agent settings, unsets.
core_session_environment() {
    local name entry credential item
    core_reserved=$(core_set_names)
    for item in "${AGENT_RESERVED_ENV[@]}" "${AGENT_UNSET_ENV[@]}"; do
        core_reserved+=$'\n'"$item"
    done
    for name in TERM COLORTERM LANG LC_ALL; do
        [[ -z "${!name:-}" ]] || container_args+=(--env "$name")
    done
    if ((restricted == 0)); then
        for name in "${proxy_names[@]}"; do
            [[ -z "${!name:-}" ]] || container_args+=(--env "$name")
        done
    fi
    if [[ "$network_mode" == provider ]]; then
        credential=$(selected_credential)
        [[ -z "$credential" || -z "${!credential:-}" ]] || container_args+=(--env "$credential")
    fi
    call_hook agent_environment "$network_mode"
    for entry in "${agent_env[@]}"; do
        name=${entry%%=*}
        [[ "$name" =~ ^[A-Za-z_][A-Za-z0-9_]*$ ]] || die "hook agent_environment returned an invalid entry: $entry"
        ! reserved_name "$name" || [[ " ${AGENT_RESERVED_ENV[*]} " == *" $name "* && "$entry" == *=* ]] \
            || die "hook agent_environment returned a reserved name: $name"
        if [[ "$entry" == *=* || -n "${!name:-}" ]]; then
            container_args+=(--env "$entry")
        fi
    done
    ((qualification_probe == 0)) || env_var_names=()
    for name in "${env_var_names[@]}"; do
        if reserved_name "$name"; then
            printf '%s: %s_ENV_VARS: skipping %s, which this session sets itself\n' "$AGENT_NAME" "$P" "$name" >&2
            continue
        fi
        [[ -z "${!name:-}" ]] || container_args+=(--env "$name")
    done
    agent_bypass_args=()
    # The probe runs fixed controls: no bypass, agent arguments or extra variables (M1).
    if ((approval_bypass && ! shell_mode && ! qualification_probe)); then
        if declare -F agent_approval_bypass >/dev/null; then
            call_hook agent_approval_bypass "$network_mode"
            for entry in "${agent_bypass_env[@]}"; do
                [[ "$entry" == *=* ]] && ! reserved_name "${entry%%=*}" \
                    || die "hook agent_approval_bypass returned a reserved or invalid entry: $entry"
                container_args+=(--env "$entry")
            done
        else
            printf '%s: %s is set but %s has no approval bypass\n' "$AGENT_NAME" "$AGENT_APPROVAL_BYPASS_ENV" \
                "$AGENT_DISPLAY_NAME" >&2
        fi
    fi
    container_args+=(--env "HOME=$AGENT_HOME" --env "USER=$(id -un)"
        --env "EDITOR=nano" --env "VISUAL=nano"
        --env "$AGENT_CONFIG_DIR_ENV=$AGENT_HOME/$AGENT_CONFIG_HOME")
    if ((trust_host_ca)); then
        for name in SSL_CERT_FILE REQUESTS_CA_BUNDLE CURL_CA_BUNDLE NODE_EXTRA_CA_CERTS; do
            container_args+=(--env "$name=$AGENT_HOME/ca/bundle.pem")
        done
    fi
    for entry in "${AGENT_SESSION_ENV[@]}"; do
        container_args+=(--env "$entry")
    done
    if ((restricted)); then
        for entry in "${AGENT_RESTRICTED_ENV[@]}"; do
            container_args+=(--env "$entry")
        done
    fi
    if [[ "$network_mode" == provider ]]; then
        for entry in "${AGENT_PROVIDER_ENV[@]}"; do
            container_args+=(--env "$entry")
        done
    fi
    for name in "${AGENT_UNSET_ENV[@]}" CONTAINER_CONNECTION; do
        container_args+=(--unsetenv "$name")
    done
    if [[ -n "$engine_store" ]]; then
        container_args+=(--env "CONTAINER_HOST=tcp://127.0.0.1:2375" --env "DOCKER_HOST=tcp://127.0.0.1:2375")
    else
        container_args+=(--unsetenv CONTAINER_HOST --unsetenv DOCKER_HOST)
    fi
}

# The application: Bash in shell mode, otherwise the agent with its mode and
# bypass arguments before the user's. Unrestricted agent sessions run the image
# entrypoint; restricted ones run AGENT_EXEC through the guard (H2).
core_application() {
    if ((qualification_probe)); then
        args=()  # The shared helper supplies the fixed probe command.
        return
    fi
    if ((shell_mode)); then
        ((restricted)) || container_args+=(--entrypoint /bin/bash)
        return
    fi
    call_hook agent_command_args "$network_mode"
    args=("${agent_mode_args[@]}" "${agent_bypass_args[@]}" "${args[@]}")
}

# Phase 5: toolchains, restricted preparation, image, container arguments, names.
core_mounts_image() {
    temporary_exec='noexec'
    ((AGENT_EXEC_TMP == 0)) || temporary_exec='exec'
    # A session without a writable isolated home gets an ephemeral tmpfs home
    # below its shared or read-only state directories (U7).
    home_mount=()
    if [[ -z "$state_dir" ]] || ((readonly_state)); then
        home_mount=(--tmpfs "$AGENT_HOME:rw,nosuid,nodev,$temporary_exec,size=512m,mode=1777")
    fi
    core_agent_mounts
    # The operator's toolchain library is mounted read-only; the shared module
    # checks it stays private and outside every writable mount and the installation,
    # and lists the default toolchains verified for this runtime recipe.
    toolchain_library=''
    toolchain_path=''
    toolchain_env=()
    engine_store=''
    if ((toolchains_enabled && ! qualification_probe)); then
        command -v python3 >/dev/null \
            || die "host Python 3 is required for the toolchain library; set ${P}_TOOLCHAINS=0 to omit it"
        toolchain_avoid=(--avoid "$workspace_mount")
        for core_path in "${writable_state[@]}"; do
            toolchain_avoid+=(--avoid "$core_path")
        done
        toolchain_output=$(python3 -I "$script_dir/setup/toolchains.py" launch-env "${toolchain_avoid[@]}") \
            || die "toolchain library check failed; set ${P}_TOOLCHAINS=0 to start without it"
        while IFS=$'\t' read -r toolchain_kind toolchain_first toolchain_second; do
            case "$toolchain_kind" in
                library) toolchain_library=$toolchain_first ;;
                path) toolchain_path+=":$toolchain_first" ;;
                env) toolchain_env+=(--env "$toolchain_first=$toolchain_second") ;;
                store) engine_store=$toolchain_first ;;
                *) die 'unexpected toolchain library output' ;;
            esac
        done <<<"$toolchain_output"
        [[ "$toolchain_library" == /* ]] || die 'toolchain library check returned no library'
    fi
    # A library with images gives the session a private container engine
    # (session-container-engine); its image is named after the agent image.
    engine_image_name=''
    engine_mounts=()
    if [[ -n "$engine_store" ]]; then
        [[ "$engine_store" == "$toolchain_library/.images" ]] || die 'unexpected image store from the toolchain library'
        engine_image_name=${cfg_ENGINE_IMAGE:-$AGENT_IMAGE-engine:latest}
        engine image exists "$engine_image_name" \
            || die "the container engine image $engine_image_name is missing; rerun --container-setup to prepare it, or set ${P}_TOOLCHAINS=0"
        engine_mounts=(--mount "$workspace_mount")
        ((trust_host_ca == 0)) || engine_mounts+=(--ca-bundle "$ca_bundle")
    fi

    # Restricted sessions use the shared helper; this wrapper keeps only the
    # agent-specific command, environment, state and credentials.
    session_helper=(python3 -I "$script_dir/network/session.py")
    network_inputs=()
    qualification_inputs=()
    guard_digest=''
    if [[ "$network_mode" != unrestricted ]]; then
        network_inputs=(--installation "$script_dir" --writable "$workspace_mount"
            --mount-target "$workspace_mount" --mount-target "$AGENT_HOME")
        [[ -z "$toolchain_library" ]] || network_inputs+=(--mount-target /toolchains)
        for core_path in "${agent_mount_targets[@]}"; do
            network_inputs+=(--mount-target "$core_path")
        done
        for core_path in "${writable_state[@]}"; do
            network_inputs+=(--writable "$core_path")
        done
        if [[ "$network_mode" == provider ]]; then
            network_inputs+=(--policy "$cfg_NETWORK_POLICY" --profile "$cfg_NETWORK_PROFILE"
                --proxy-image "$cfg_EGRESS_IMAGE" --runtime "$cfg_NETWORK_RUNTIME_DIR")
        fi
        # shellcheck disable=SC2154 # set by capture_response
        prepare_inputs=(--mode "$network_mode" --server-version "${network_version%$'\n'}"
            --backend "${network_backend%$'\n'}" --endpoint "${CONTAINER_HOST:-}" --engine "$runtime_info")
        if ((qualification_probe)); then
            prepare_inputs+=(--probe --qualification-input "${cfg_QUALIFICATION_INPUT:-}"
                --workspace "$workspace")
        fi
        # shellcheck disable=SC2154 # set by capture_response
        prepared=$(printf '%s' "$network_platform" | "${session_helper[@]}" prepare "${network_inputs[@]}" "${prepare_inputs[@]}")
        read -r guard_digest qualification_token qualification_tls <<< "$prepared"
        if ((qualification_probe)); then
            qualification_inputs=(--probe --token "$qualification_token" --workspace "$workspace"
                --qualification-input "${cfg_QUALIFICATION_INPUT:-}")
            [[ "$qualification_tls" != 1 ]] || qualification_inputs+=(--tls)
        fi
    fi

    core_build_image
    if [[ "$network_mode" == provider ]]; then
        # The proxy image is an immutable artifact: present, or pulled by digest
        # only under explicit maintenance.
        if engine image exists "$cfg_EGRESS_IMAGE"; then
            :
        else
            proxy_status=$?
            [[ "$proxy_status" == 1 ]] || die "cannot inspect proxy image: $cfg_EGRESS_IMAGE"
            [[ "${cfg_MAINTENANCE:-}" == 1 && "$cfg_EGRESS_IMAGE" == *@sha256:* ]] \
                || die "proxy image is absent; prepare the pinned artifact under explicit operator maintenance authorization (${P}_MAINTENANCE=1 and a registry digest)"
            podman pull "$cfg_EGRESS_IMAGE" </dev/null || die "cannot pull proxy image: $cfg_EGRESS_IMAGE"
        fi
    fi

    if [[ "$network_mode" != unrestricted ]]; then
        capture_response runtime_image_id engine image inspect --format '{{.Id}}' "$image" \
            || die 'cannot resolve restricted runtime image identity'
        single_record runtime_image_id 'invalid restricted runtime image identity'
        # shellcheck disable=SC2154 # set by capture_response
        [[ "$runtime_image_id" =~ ^(sha256:)?[a-f0-9]{64}$ ]] || die 'invalid restricted runtime image identity'
        image=$runtime_image_id
    fi
    # Default toolchain entries follow the image PATH, so they never replace the
    # runtime's own node or python3; env.sh puts a toolchain first explicitly.
    if [[ -n "$toolchain_path" ]]; then
        capture_response image_environment engine image inspect --format '{{range .Config.Env}}{{println .}}{{end}}' "$image" \
            || die 'cannot inspect the runtime image environment'
        image_path=''
        # shellcheck disable=SC2154 # set by capture_response
        while IFS= read -r image_variable; do
            [[ "$image_variable" != PATH=* ]] || { image_path=${image_variable#PATH=}; break; }
        done <<<"$image_environment"
        [[ -n "$image_path" ]] || image_path=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
        toolchain_env=(--env "PATH=$image_path$toolchain_path" "${toolchain_env[@]}")
    fi

    # Every core bind passes the same path rule as agent mounts (M7).
    for core_path in "$workspace_mount" "${writable_state[@]}" ${toolchain_library:+"$toolchain_library"} \
        ${ca_bundle:+"$ca_bundle"}; do
        [[ "$core_path" == /* && "$core_path" != *[:$'\n'$'\r']* ]] \
            || die "bind paths must be absolute and contain no colon, CR or LF: $core_path"
    done
    container_args=(
        --rm --interactive --read-only
        --userns=keep-id --user "$caller_uid:$caller_gid"
        --cap-drop=all --security-opt=no-new-privileges
        "${budget_args[@]}"
        --workdir "$workspace"
        # One temporary-storage layout (U7): /tmp and the ephemeral home allow
        # execution only when the profile declares it; /var/tmp and /run never.
        --tmpfs "/tmp:rw,nosuid,nodev,$temporary_exec,size=512m,mode=1777"
        --tmpfs '/run:rw,nosuid,nodev,noexec,size=32m'
        --tmpfs '/var/tmp:rw,nosuid,nodev,noexec,size=512m,mode=1777'
        # Mask engine default mounts at /run/secrets (RHEL subscription secrets from
        # mounts.conf): Podman skips its own mount there, leaving an empty read-only
        # tmpfs that the guard accepts and that exposes no host material.
        --mount 'type=tmpfs,destination=/run/secrets,ro=true'
        # Podman forces /dev read-only with --read-only-tmpfs=false, and crun >= 1.27
        # must replace /dev/console to attach a terminal, so automatic provisioning
        # stays on. /dev and /dev/pts are left to the engine: an explicit /dev/pts mount
        # gets ptmxmode=000 (Podman rejects the option), so no pseudo-terminal could
        # be opened. Only /dev/shm is overridden, with an empty read-only tmpfs.
        --mount 'type=tmpfs,destination=/dev/shm,ro=true'
        --volume "$workspace_mount:$workspace_mount:rw"
        "${home_mount[@]}"
        "${state_mounts[@]}"
        "${agent_mount_args[@]}"
    )
    if [[ -n "$toolchain_library" ]]; then
        container_args+=(--volume "$toolchain_library:/toolchains:ro,nosuid,nodev" "${toolchain_env[@]}")
    fi
    ((run_timeout == 0)) || container_args+=(--timeout "$run_timeout")
    [[ ! -t 0 || ! -t 1 ]] || container_args+=(--tty)
    ((trust_host_ca == 0)) || container_args+=(--volume "$ca_bundle:$AGENT_HOME/ca/bundle.pem:ro")
    # Unrestricted sessions run the image entrypoint, so --init reaps orphans;
    # the guard rejects its mount below /run, so restricted sessions cannot (U12).
    ((restricted)) || container_args+=(--init)
    core_session_environment
    core_application
    prefix=${workspace##*/}
    prefix=$(printf '%s' "$prefix" | sed -E 's/[^a-zA-Z0-9_.-]+/-/g; s/^[.-]+//; s/[.-]+$//')
    prefix=${prefix:-$AGENT_NAME}
    names=$(engine ps --all --format '{{.Names}}') || die 'cannot list Podman containers'
    [[ "$names" != *$'\r'* ]] || die 'invalid Podman container list'

    next_index=0
    while IFS= read -r name; do
        [[ "$name" == "$prefix-"* ]] || continue
        suffix=${name#"$prefix-"}
        [[ "$suffix" =~ ^[0-9]+$ && ${#suffix} -lt 10 ]] || continue
        numeric=$((10#$suffix))
        ((numeric < next_index)) || next_index=$((numeric + 1))
    done <<< "$names"
}

# Reserve the name with create, so an actual process exit code 125 is never
# confused with a create-time naming collision. Remove only our own container.
container_id=''
engine_id=''
engine_name=''
client_pid=''
diagnostics_pid=''
diagnostics_fd=''
create_pid=''
session_dir=''
session_token=''
cid_file=''
create_output=''
creation_pending=0
shutdown_deadline=0
ownership_label=$AGENT_LABEL_NAMESPACE.session
session_start_pid=''
owned_collision=0
cid_value=
qualification_check_pid=''

cleanup_warning() {
    local proxy_id=unknown
    [[ -z "$session_dir" || ! -s "$session_dir/proxy.id" ]] || proxy_id=$(<"$session_dir/proxy.id")
    printf '%s: cleanup %s (container=%s proxy=%s session=%s); inspect the Podman engine for remaining session containers\n' \
        "$AGENT_NAME" "$*" "${container_id:-unknown}" "$proxy_id" "${session_token:-unknown}" >&2
}

# A private creation record: one 64-hex ID, an optional final LF, no NUL (X).
read_cid() {
    local value=''
    if IFS= read -r -d '' value <"$1"; then
        return 1  # A NUL byte is itself invalid record data.
    fi
    value=${value%$'\n'}
    [[ "$value" =~ ^[a-f0-9]{64}$ ]] || return 1
    cid_value=$value
}

# All shutdown engine calls share a deadline and reserve time for local clients.
control() {
    local remaining=$((shutdown_deadline - SECONDS - 2)) duration status
    if ((remaining < 2)); then
        cleanup_warning "deadline exhausted before $1"
        return 124
    fi
    duration=$((remaining - 1))
    ((duration <= 2)) || duration=2
    if timeout --kill-after=1s "${duration}s" podman "$@"; then
        return 0
    else
        status=$?
        cleanup_warning "$1 failed or timed out (status $status)"
        return "$status"
    fi
}

# Consult Bash's child table, so a recycled PID cannot select another process.
child_running() {
    local child=$1 running
    [[ -n "$child" ]] || return 1
    while IFS= read -r running; do
        [[ "$running" != "$child" ]] || return 0
    done < <(jobs -pr)
    return 1
}

reap_client() {
    local child=$1 until
    [[ -n "$child" ]] || return 0
    if child_running "$child"; then
        kill -TERM "$child" 2>/dev/null || true
        until=$((SECONDS + 1))
        while child_running "$child" && ((SECONDS < until && SECONDS < shutdown_deadline - 1)); do
            sleep 0.05
        done
        if child_running "$child"; then
            kill -KILL "$child" 2>/dev/null || true
        fi
    fi
    while child_running "$child" && ((SECONDS < shutdown_deadline)); do
        sleep 0.05
    done
    if child_running "$child"; then
        cleanup_warning "local client $child did not terminate within the deadline"
    else
        wait "$child" 2>/dev/null || true
    fi
}

recover_container() {
    local candidate='' owner ids
    [[ -z "$container_id" && "$creation_pending" == 1 ]] || return 0
    # The CID record first (validated, X), then the create output, which must
    # agree with it (O); only without either, the ownership label.
    if [[ -s "$cid_file" ]]; then
        read_cid "$cid_file" || { cleanup_warning 'invalid container ID in the private creation record'; return 1; }
        candidate=$cid_value
        if [[ -s "$create_output" && "$(<"$create_output")" != "$candidate" ]]; then
            cleanup_warning 'inconsistent creation IDs'
            return 1
        fi
    elif [[ -s "$create_output" ]]; then
        candidate=$(<"$create_output")
    fi
    if [[ ! "$candidate" =~ ^[a-f0-9]{64}$ ]]; then
        if ! ids=$(control ps --all --no-trunc --filter "label=$ownership_label=$session_token" --format '{{.ID}}'); then
            return 1
        fi
        candidate=$ids
    fi
    [[ -n "$candidate" ]] || return 0
    [[ "$candidate" =~ ^[a-f0-9]{64}$ ]] || { cleanup_warning 'invalid recovered container identity'; return 1; }
    if owner=$(control inspect --type container --format "{{index .Config.Labels \"$ownership_label\"}}" "$candidate") \
        && [[ "$owner" == "$session_token" ]]; then
        container_id=$candidate
    else
        cleanup_warning 'could not confirm recovered container ownership'
        return 1
    fi
}

# Keep collision reconciliation interruptible just like the create request.
# The engine client is a direct child, so shutdown can reap it, and the query is
# bounded here rather than by timeout(1), whose child would survive a reap.
creation_lookup() {
    local lookup_status=0 until=$((SECONDS + 10))
    podman "$@" >"$session_dir/lookup" &
    create_pid=$!
    while child_running "$create_pid" && ((SECONDS < until)); do
        sleep 0.05
    done
    if child_running "$create_pid"; then
        kill -KILL "$create_pid" 2>/dev/null || true
        wait "$create_pid" 2>/dev/null || true
        lookup_status=124
    else
        wait "$create_pid" || lookup_status=$?
    fi
    create_pid=''
    return "$lookup_status"
}

# shellcheck disable=SC2329 # Invoked by EXIT and signal traps.
shutdown() {
    local primary_status=$1 signal=${2:-} graceful_until diagnostics_until
    trap - EXIT
    trap '' TERM INT HUP
    set +e
    shutdown_deadline=$((SECONDS + 20))
    if [[ -n "$qualification_check_pid" ]]; then
        kill -TERM "$qualification_check_pid" 2>/dev/null || true
        graceful_until=$((SECONDS + 13))
        while child_running "$qualification_check_pid" && ((SECONDS < graceful_until && SECONDS < shutdown_deadline - 4)); do
            sleep 0.05
        done
        if child_running "$qualification_check_pid"; then
            cleanup_warning 'qualification helper did not confirm cleanup before the deadline'
            kill -KILL "$qualification_check_pid" 2>/dev/null || true
        fi
        reap_client "$qualification_check_pid"
    fi
    if [[ -n "$diagnostics_fd" ]]; then
        exec {diagnostics_fd}>&-
        diagnostics_fd=''
    fi
    if [[ -n "$session_dir" ]]; then
        recover_container
        if [[ -n "$signal" && -n "$container_id" && -n "$client_pid" ]]; then
            control kill --signal "$signal" "$container_id" >/dev/null
            graceful_until=$((SECONDS + 5))
            while child_running "$client_pid" && ((SECONDS < graceful_until && SECONDS < shutdown_deadline - 6)); do
                sleep 0.05
            done
        fi
        [[ -z "$container_id" ]] || control rm --force --time 0 --ignore "$container_id" >/dev/null
        [[ -z "$engine_id" ]] || control rm --force --volumes --time 0 --ignore "$engine_id" >/dev/null
        if [[ -n "$session_start_pid" ]]; then
            # The session helper owns a separate process group. Reap the whole
            # group before its leader, including an engine client that ignores TERM.
            kill -TERM -- "-$session_start_pid" 2>/dev/null || true
            sleep 0.1
            kill -KILL -- "-$session_start_pid" 2>/dev/null || true
            reap_client "$session_start_pid"
        fi
        reap_client "$create_pid"
        reap_client "$client_pid"
        # Drain the final client log before reaping its owned stderr adapter.
        diagnostics_until=$((SECONDS + 1))
        while child_running "$diagnostics_pid" && ((SECONDS < diagnostics_until && SECONDS < shutdown_deadline - 1)); do
            sleep 0.01
        done
        reap_client "$diagnostics_pid"
        # Cancellation can race with the server publishing its create result.
        if ((creation_pending)) && [[ -z "$container_id" ]]; then
            recover_container
            if [[ -n "$container_id" ]]; then
                control rm --force --time 0 --ignore "$container_id" >/dev/null
            elif [[ -n "$signal" ]] || ((owned_collision)); then
                cleanup_warning 'creation outcome unresolved: no verified owned container ID'
            fi
        fi
        if [[ "$network_mode" == provider ]]; then
            # Owned proxy recovery/removal and diagnostics share the remaining budget.
            "${session_helper[@]}" stop --session "$session_dir" --deadline "$((shutdown_deadline - SECONDS))" \
                --container "${container_id:-unknown}" || true
        fi
        rm -rf -- "$session_dir"
    fi
    exit "$primary_status"
}
# Whether a created container carries exactly the session budgets: every enforced
# one and no unenforced one (the agent's, and the engine's, design D7). The
# rlimits are listed by name in brackets, so the field is never empty. On the
# process rlimit fallback, the remaining arguments are the start of the created
# command, which must set the limit inside the container.
budgets_applied() {
    local id=$1 description=$2 configured_budgets configured_memory configured_cpu configured_pids
    local configured_rlimits extra entry value
    shift 2
    capture_response configured_budgets engine inspect --type container \
        --format '{{.HostConfig.Memory}} {{.HostConfig.NanoCpus}} {{.HostConfig.PidsLimit}} [{{range .HostConfig.Ulimits}}{{.Name}}={{.Soft}}:{{.Hard}},{{end}}]' "$id" \
        || die "cannot inspect $description resource budgets; agent not started"
    # shellcheck disable=SC2154 # set by capture_response
    read -r configured_memory configured_cpu configured_pids configured_rlimits extra <<< "${configured_budgets%$'\n'}"
    [[ -z "${extra:-}" && "$configured_memory" == "$expected_memory" && "$configured_cpu" == "$expected_cpu" \
        && "${configured_rlimits:-}" =~ ^\[([A-Z_]+=[0-9]+:[0-9]+,)*\]$ ]] || return 1
    if ((pids_enforced)); then
        [[ "$configured_pids" == "$pids_limit" ]]
        return
    fi
    [[ "$configured_pids" =~ ^(0|-1)$ ]] || return 1
    [[ "$process_budget" == rlimit ]] || return 0
    # A process rlimit the engine applies at creation is shared by every
    # container of the user. One above the budget is the engine's default from
    # the user's own limits; one at or below it is refused.
    configured_rlimits=${configured_rlimits#[}
    while [[ "$configured_rlimits" == *,* ]]; do
        entry=${configured_rlimits%%,*}
        configured_rlimits=${configured_rlimits#*,}
        [[ "$entry" == RLIMIT_NPROC=* ]] || continue
        entry=${entry#*=}
        for value in "${entry%:*}" "${entry#*:}"; do
            # More than 18 digits is above any budget (and outside Bash arithmetic).
            ((${#value} > 18 || 10#$value > pids_limit)) || return 1
        done
    done
    created_command_starts "$id" "$@"
}

# Whether a created container's command starts with the given values: .Path,
# then each .Args entry read alone with index, which reads the same on Podman
# 4.3 and 6.2. A container created with --init reports the init program.
created_command_starts() {
    local id=$1 value expected index=0
    shift
    (($#)) || return 1
    capture_response value engine inspect --type container --format '{{.Path}}' "$id" || return 1
    # shellcheck disable=SC2154 # set by capture_response
    [[ "${value%$'\n'}" == "$1" ]] || return 1
    shift
    for expected in "$@"; do
        capture_response value engine inspect --type container --format "{{index .Args $index}}" "$id" || return 1
        [[ "${value%$'\n'}" == "$expected" ]] || return 1
        index=$((index + 1))
    done
}

# This launcher as <pid>-<start time>: unique while it runs, never reused after.
launcher_identity() {
    local stat fields
    { read -r stat <"/proc/$1/stat"; } 2>/dev/null || return 1
    read -r -a fields <<<"${stat##*) }"
    [[ "${fields[19]:-}" =~ ^[0-9]+$ ]] || return 1
    printf '%s-%s' "$1" "${fields[19]}"
}

# Remove the engines, of any wrapper, whose launcher no longer runs: an
# interrupted launch could not remove its own (session-owned engine storage).
engine_reconcile() {
    local listing id owner
    # The owner comes from inspect: in `ps` templates `.Labels` is a map in
    # Podman 4.3 and a string in Podman 6.2, and no label template works on both.
    listing=$(engine ps --filter "label=sandbox-engine.owner" --format '{{.ID}}' 2>/dev/null) || return 0
    while read -r id; do
        [[ "$id" =~ ^[a-f0-9]{12,64}$ ]] || continue
        owner=$(engine container inspect --format '{{index .Config.Labels "sandbox-engine.owner"}}' "$id" \
            2>/dev/null) || continue
        [[ "$owner" =~ ^[0-9]+-[0-9]+$ ]] || continue
        [[ "$(launcher_identity "${owner%%-*}" || true)" != "$owner" ]] || continue
        engine rm --force --volumes --time 0 --ignore "$id" >/dev/null 2>&1 || true
    done <<<"$listing"
}

# The session's private container engine (session-container-engine). It is
# created first with the session's network options, and the session joins its
# network namespace (design D1). Shutdown removes it with its storage.
core_engine_start() {
    local seccomp="$script_dir/launcher/engine/seccomp.json" default_profile index ready='' attempt owner
    local engine_limit engine_soft engine_hard engine_cgroup network_args=() engine_args=() engine_command=()
    engine_reconcile
    if [[ ! -f "$seccomp" ]]; then
        # A checkout has no prepared profile: derive one from the engine host's default.
        capture_response default_profile engine info --format '{{.Host.Security.SECCOMPProfilePath}}' \
            || die 'cannot query the default seccomp profile of the Podman engine'
        single_record default_profile 'unverifiable default seccomp profile path from the Podman engine'
        seccomp=$session_dir/engine-seccomp.json
        python3 -I "$script_dir/setup/engine.py" seccomp "$default_profile" "$seccomp" >/dev/null \
            || die 'cannot derive the container engine seccomp profile'
    fi
    for index in "${!container_args[@]}"; do
        if [[ "${container_args[$index]}" == --network=* ]]; then
            network_args+=("${container_args[$index]}")
            unset 'container_args[index]'
        fi
    done
    container_args=("${container_args[@]}")
    owner=$(launcher_identity "$$") || die 'cannot identify this launcher for its container engine'
    engine_name=$prefix-engine-$session_token
    python3 -I "$script_dir/setup/engine.py" options --name "$engine_name" --seccomp "$seccomp" \
        --store "$engine_store" "${engine_mounts[@]}" --label "$ownership_label=$session_token" \
        --label "sandbox-engine.owner=$owner" >"$session_dir/engine.args" || die 'invalid container engine options'
    mapfile -d '' -t engine_args <"$session_dir/engine.args"
    ((${#engine_args[@]})) || die 'invalid container engine options'
    # The engine's first process is its startup program (no --init): it sets the
    # process limit given after the port, delegates the engine's cgroup subtree
    # when eligible, and hands over to the services as the engine user.
    engine_command=(/usr/local/bin/sandbox-engine-start 2375)
    [[ "$process_budget" != rlimit ]] || engine_command+=("$pids_limit")
    engine_id=$(podman run --detach "${engine_args[@]}" "${network_args[@]}" "${budget_args[@]}" \
        "$engine_image_name" "${engine_command[@]:1}" </dev/null) || die "cannot start the container engine $engine_name"
    [[ "$engine_id" =~ ^[a-f0-9]{64}$ ]] || die 'invalid container engine ID returned by Podman'
    budgets_applied "$engine_id" 'container engine' "${engine_command[@]}" \
        || die "container engine resource budgets were not applied as expected; engine reports controllers $cgroup_controllers with the $cgroup_manager cgroup manager; agent not started"
    printf '%s: container engine %s: the session budgets apply to it as well\n' "$AGENT_NAME" "$engine_name" >&2
    for ((attempt = 0; attempt < 30; attempt++)); do
        # Commands in the engine run as its user, never as its startup root.
        ready=$(engine exec --user podman "$engine_id" podman --remote --url tcp://127.0.0.1:2375 info \
            --format '{{.Host.Security.Rootless}}' 2>/dev/null) && [[ "$ready" == true ]] && break
        ready=''
        sleep 1
    done
    [[ "$ready" == true ]] || die "the container engine $engine_name did not answer as a rootless engine within 30 seconds; agent not started"
    # The engine's cgroup delegation (support-nested-systemd-containers): a
    # delegated engine is silent, an ineligible one is announced with its reason,
    # and any other state stops the launch.
    capture_response engine_cgroup engine exec --user podman "$engine_id" /usr/local/bin/sandbox-engine-cgroup \
        || die "cannot read the cgroup delegation state of the container engine $engine_name; agent not started"
    single_record engine_cgroup "invalid cgroup delegation state from the container engine $engine_name; agent not started"
    # shellcheck disable=SC2154 # set by capture_response
    case $engine_cgroup in
        delegated) ;;
        'ineligible: '*)
            [[ "${engine_cgroup#ineligible: }" =~ ^[[:print:]]{1,200}$ ]] \
                || die "invalid cgroup delegation state from the container engine $engine_name; agent not started"
            printf '%s: container engine %s: systemd containers and explicit limits for nested containers are unavailable: %s\n' \
                "$AGENT_NAME" "$engine_name" "${engine_cgroup#ineligible: }" >&2
            ;;
        *) die "the container engine $engine_name reports an unexpected cgroup delegation state; agent not started" ;;
    esac
    if [[ "$process_budget" == rlimit ]]; then
        # The startup program is PID 1 and keeps the limit through its exec calls.
        # A process started with exec gets the engine-applied limits instead, so
        # only PID 1's reading is evidence.
        capture_response engine_limit engine exec --user podman "$engine_id" grep '^Max processes ' /proc/1/limits \
            || die "cannot read the process rlimit of the container engine $engine_name; agent not started"
        # shellcheck disable=SC2154 # set by capture_response
        read -r _ _ engine_soft engine_hard _ <<<"${engine_limit%$'\n'}"
        [[ "${engine_soft:-}" == "$pids_limit" && "${engine_hard:-}" == "$pids_limit" ]] \
            || die "the container engine $engine_name does not run with the process rlimit fallback (soft and hard $pids_limit); agent not started"
    fi
    : >"$session_dir/hosts"
    container_args+=(--network "container:$engine_id" --volume "$session_dir/hosts:/etc/hosts:ro")
}

# Phases 6-7: session directory, qualification check, creation, budget
# verification, start and lifetime notice; shutdown runs from the traps.
core_create_start() {
    trap 'shutdown "$?"' EXIT
    trap 'shutdown 143 TERM' TERM
    trap 'shutdown 130 INT' INT
    trap 'shutdown 129 HUP' HUP
    if [[ "$network_mode" == provider ]]; then
        session_dir=$(umask 077; mktemp -d -- "$cfg_NETWORK_RUNTIME_DIR/session.XXXXXXXXXXXX") \
            || die "cannot create a private session directory in ${P}_NETWORK_RUNTIME_DIR"
    else
        session_dir=$(umask 077; mktemp -d)
    fi
    session_token=${session_dir##*/}
    printf '%s: network mode=%s\n' "$AGENT_NAME" "$network_mode" >&2
    if [[ "$network_mode" != unrestricted ]] && ((qualification_probe == 0)); then
        # A session with a container engine also needs the engine's qualification.
        qualification_check=(check)
        [[ -z "$engine_store" ]] || qualification_check+=(--engine)
        env "${P}_IMAGE=$image" python3 -I "$script_dir/network/qualify.py" "${qualification_check[@]}" &
        qualification_check_pid=$!
        if wait "$qualification_check_pid"; then
            qualification_check_pid=''
        else
            qualification_status=$?
            qualification_check_pid=''
            exit "$qualification_status"
        fi
    fi
    if [[ "$network_mode" == provider ]]; then
        # The helper starts the session's proxy in its own process group.
        "${session_helper[@]}" start "${network_inputs[@]}" "${qualification_inputs[@]}" --session "$session_dir" \
            --guard-digest "$guard_digest" >"$session_dir/policy.identity" &
        session_start_pid=$!
        wait "$session_start_pid"
        session_start_pid=''
    fi
    if [[ "$network_mode" != unrestricted ]]; then
        application=()
        if ((qualification_probe == 0)); then
            if ((shell_mode)); then
                application=(/bin/bash "${args[@]}")
            else
                application=("$AGENT_EXEC" "${args[@]}")
            fi
        fi
        "${session_helper[@]}" agent-args --installation "$script_dir" --mode "$network_mode" \
            --session "$session_dir" --guard-digest "$guard_digest" "${qualification_inputs[@]}" \
            -- "${application[@]}" >"$session_dir/agent.args"
        mapfile -d '' -t restricted <"$session_dir/agent.args"
        [[ "${restricted[0]:-}" =~ ^[0-9]+$ ]] || die 'invalid restricted session arguments'
        container_args+=("${restricted[@]:1:${restricted[0]}}")
        args=("${restricted[@]:$((1 + restricted[0]))}")
    fi
    core_process_step
    [[ -z "$engine_store" ]] || core_engine_start
    # Measure the session from just before the container is created, so the
    # engine's lifetime limit cannot have started earlier, with a monotonic clock:
    # WSL2 steps the wall clock to resynchronise with the host, which moves
    # EPOCHREALTIME and SECONDS by seconds at a time, and whole-second SECONDS would
    # also report a short failing session crossing a second boundary as a reached
    # limit. /proc/uptime counts centiseconds since boot.
    elapsed_centiseconds() {
        local now=''
        read -r now _ 2>/dev/null </proc/uptime || now=''
        now=${now//[!0-9]/}
        [[ -n "$now" ]] || now=$((SECONDS * 100))
        printf '%s' "$((10#$now - ${1:-0}))"
    }
    started_at=$(elapsed_centiseconds)
    for ((attempt=0; attempt<20; attempt++)); do
        name="$prefix-$next_index"
        cid_file=$session_dir/$attempt.cid
        create_output=$session_dir/$attempt.stdout
        create_error=$session_dir/$attempt.stderr
        creation_pending=1
        # Each attempt names itself in the session (CONTAINER_NAME, U12); stdin stays
        # with the session, so create reads none (L9).
        podman create --name "$name" --cidfile "$cid_file" --label "$ownership_label=$session_token" \
            "${container_args[@]}" --env "CONTAINER_NAME=$name" "$image" "${args[@]}" \
            </dev/null >"$create_output" 2>"$create_error" &
        create_pid=$!
        if wait "$create_pid"; then
            create_pid=''
            container_id=$(<"$create_output")
            [[ "$container_id" =~ ^[a-f0-9]{64}$ ]] || die 'invalid container ID returned by Podman create'
            if [[ -s "$cid_file" ]]; then
                read_cid "$cid_file" && [[ "$cid_value" == "$container_id" ]] \
                    || die 'inconsistent creation IDs from Podman create'
            fi
            creation_pending=0
            break
        else
            create_status=$?
            create_pid=''
            if [[ ! -s "$cid_file" && ! -s "$create_output" ]] && creation_lookup container exists "$name" \
                && creation_lookup inspect --type container --format "{{index .Config.Labels \"$ownership_label\"}}" "$name"; then
                if [[ $(<"$session_dir/lookup") != "$session_token" ]]; then
                    creation_pending=0
                    next_index=$((next_index + 1))
                    continue
                fi
                # This session's own container behind a failed create is never a
                # collision: shutdown removes it, or reports it unresolved.
                owned_collision=1
                cat -- "$create_error" >&2
                exit "$create_status"
            else
                cat -- "$create_error" >&2
                exit "$create_status"
            fi
        fi
    done
    [[ -n "$container_id" ]] || die 'could not reserve a container name after 20 attempts'
    if [[ -n "$engine_id" ]]; then
        # A container joined to another's network gets no entry of its own, and
        # Podman refuses --add-host there; the private file restores it (design D1).
        printf '127.0.0.1\tlocalhost\n::1\tlocalhost ip6-localhost ip6-loopback\n127.0.0.1\t%s %s\n' \
            "${container_id:0:12}" "$name" >"$session_dir/hosts"
    fi

    # Engine flags alone are not evidence: require the created configuration to
    # carry every enforced budget and no unenforced one, and on the process
    # rlimit fallback the step that sets it. Setup smoke and qualification
    # measure the effective limits.
    if ! budgets_applied "$container_id" agent "${process_command[@]}"; then
        [[ "$process_budget" != rlimit ]] \
            || die "agent resource budgets were not applied as expected (memory=$expected_memory nano_cpus=$expected_cpu process rlimit fallback: the container must start with the step that sets the process rlimit to $pids_limit, and no engine process rlimit at or below it); engine reports controllers $cgroup_controllers with the $cgroup_manager cgroup manager; check the process rlimit fallback and rootless cgroup v2 controller delegation; agent not started"
        die "agent resource budgets were not applied as expected (memory=$expected_memory nano_cpus=$expected_cpu pids=$( ((pids_enforced)) && printf '%s' "$pids_limit" || printf 'unenforced')); engine reports controllers $cgroup_controllers with the $cgroup_manager cgroup manager; check rootless cgroup v2 controller delegation; agent not started"
    fi

    # Explicit stdin redirection prevents Bash from replacing stdin with /dev/null
    # for the background client; traps can forward signals while wait is active.
    if [[ -f "$script_dir/setup/diagnostics.py" ]] && command -v python3 >/dev/null; then
        # Optional for legacy unrestricted installs without host Python. Only the
        # exact successful Podman 4.3 restart-check line changes level; errors pass.
        mkfifo -- "$session_dir/diagnostics.pipe"
        python3 -I "$script_dir/setup/diagnostics.py" <"$session_dir/diagnostics.pipe" >&2 &
        diagnostics_pid=$!
        exec {diagnostics_fd}>"$session_dir/diagnostics.pipe"
        podman start --attach --interactive --sig-proxy=false "$container_id" <&0 2>&"$diagnostics_fd" {diagnostics_fd}>&- &
        client_pid=$!
        exec {diagnostics_fd}>&-
        diagnostics_fd=''
    else
        podman start --attach --interactive --sig-proxy=false "$container_id" <&0 &
        client_pid=$!
    fi
    status=0
    wait "$client_pid" || status=$?
    if ((run_timeout > 0 && status != 0 && $(elapsed_centiseconds "$started_at") >= run_timeout * 100)); then
        printf '%s: session lifetime limit reached (%s s); exit status %s\n' "$AGENT_NAME" "$run_timeout" "$status" >&2
    fi
    exit "$status"
}

# Calls an optional agent hook: empties its output arrays, runs it when the
# agent part defines it, and stops with the hook's name when it fails. Each
# hook's outputs are validated by the phase that reads them.
call_hook() {
    local hook=$1
    shift
    case "$hook" in
        agent_approval_bypass) agent_bypass_args=(); agent_bypass_env=() ;;
        agent_command_args) agent_mode_args=() ;;
        agent_environment) agent_env=() ;;
        agent_mounts) agent_mount_specs=() ;;
        agent_build_args) agent_build_args=(); agent_build_inputs=() ;;
    esac
    declare -F "$hook" >/dev/null || return 0
    "$hook" "$@" || die "hook $hook failed"
}

core_arguments "$@"
core_settings
core_workspace
core_engine
core_state
if ((build_only)); then
    core_build_image
    exit 0
fi
core_mounts_image
core_create_start

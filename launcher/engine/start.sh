#!/bin/sh
# The engine container's first process (support-nested-systemd-containers,
# design D1 and D3). The launcher starts it as the root of the engine's user
# namespace with the ownership-change capability besides the engine's own. It:
#   1. sets the session's process limit after the port, before anything else,
#      so that every later engine process inherits it;
#   2. delegates the engine's own cgroup subtree to the engine user when the
#      engine is eligible (sandbox-engine-cgroup), and fails otherwise;
#   3. hands over: catatonit, as the engine user with only the engine's
#      capabilities as ambient ones, runs the services. Through exec this
#      process stays PID 1, and no root process remains.
set -eu

engine_cgroup=/usr/local/bin/sandbox-engine-cgroup
catatonit=/usr/libexec/podman/catatonit
services=/usr/local/bin/sandbox-engine

usage() {
    echo 'usage: sandbox-engine-start [port [process limit]]' >&2
    exit 2
}

fail() {
    echo "sandbox-engine-start: $*" >&2
    exit 1
}

[ "$#" -le 2 ] || usage
port=${1:-2375}
case $port in
    ''|*[!0-9]*) usage ;;
esac
if [ "$#" -eq 2 ]; then
    case $2 in
        ''|0|0*|*[!0-9]*) usage ;;
    esac
    # shellcheck disable=SC3045 # -u in Bash (the engine image's sh) and BusyBox, -p in dash
    ulimit -u "$2" 2>/dev/null || ulimit -p "$2"
fi

if [ "$(id -u)" != 0 ]; then
    echo 'sandbox-engine-start: not started as root; nothing delegated' >&2
    exec "$catatonit" -- "$services" "$port"
fi

cg=/sys/fs/cgroup
state=$("$engine_cgroup")
case $state in
    eligible)
        # Root-side writes come first: after the ownership change root has no
        # DAC override. Every process, this one included, moves into the leaf,
        # then the root enables its controllers for nested containers. A
        # launcher command may enter the root meanwhile, and a controller
        # cannot be enabled while a process is there: move again and retry.
        mkdir -- "$cg/engine" || fail 'cannot create the engine leaf cgroup'
        attempt=0
        while :; do
            for pid in $(cat -- "$cg/cgroup.procs"); do
                echo "$pid" >"$cg/engine/cgroup.procs" 2>/dev/null || :
            done
            enabled=1
            for controller in $(cat -- "$cg/cgroup.controllers"); do
                echo "+$controller" >"$cg/cgroup.subtree_control" 2>/dev/null || enabled=0
            done
            [ "$enabled" = 0 ] || break
            attempt=$((attempt + 1))
            [ "$attempt" -lt 20 ] || fail 'cannot enable the cgroup controllers for nested containers'
        done
        chown 1000:1000 -- "$cg" "$cg/cgroup.procs" "$cg/cgroup.subtree_control" "$cg/cgroup.threads" \
            "$cg/engine" "$cg/engine/cgroup.procs" "$cg/engine/cgroup.subtree_control" "$cg/engine/cgroup.threads" \
            || fail 'cannot delegate the engine cgroup subtree'
        state=$("$engine_cgroup")
        [ "$state" = delegated ] || fail "the delegation did not take effect: $state"
        ;;
    'ineligible: '*)
        echo "sandbox-engine-start: $state; nothing delegated" >&2
        ;;
    *)
        fail "unexpected cgroup state: $state"
        ;;
esac

# capsh keeps the permitted set across the user change, narrows it to the
# engine's capabilities and raises them as ambient ones; no-new-privileges
# stays on. The ownership-change capability stays only in the bounding set.
export HOME=/home/podman USER=podman LOGNAME=podman
exec capsh --user=podman \
    --caps='cap_setuid,cap_setgid,cap_sys_chroot+eip' \
    --addamb=cap_setuid,cap_setgid,cap_sys_chroot \
    -- -c 'exec "$1" -- "$2" "$3"' sandbox-engine-start "$catatonit" "$services" "$port"

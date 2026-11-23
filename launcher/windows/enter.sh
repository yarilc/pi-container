#!/usr/bin/env bash
# shellcheck shell=bash
# Windows namespace helper. The Podman machine runs systemd, its user manager
# and the Podman service in PID and mount namespaces of their own (unshare
# --pid --mount), and its login shells enter them with /usr/local/bin/enterns:
# sudo nsenter, then sudo -u back to the user. wsl.exe --exec sessions stay
# outside, where podman would start a second rootless user namespace on the
# same storage. The release bootstrap and the shim's setup and help therefore
# run their command through this helper:
#   bash enter.sh <prefix> <command> [args...]
# <prefix> names the messages. The command runs as the calling user inside
# systemd's namespaces, with this environment, working directory, standard
# streams and exit status, and XDG_RUNTIME_DIR=/run/user/<uid>. The
# environment crosses sudo in a private file of the runtime directory, which
# the inner part reads and removes. See docs/launcher-contract.md (Windows
# entry).
set -Eeuo pipefail

proc=/proc
root_uid=0
runtime=/run/user/$(id -u)
transport=$runtime/windows-entry

# Inner part, as the user inside the namespaces: restore the environment.
if [[ "${1:-}" == --inner ]]; then
    prefix=$2
    file=$3
    shift 3
    [[ "$file" == "$transport"/env.* && -f "$file" && ! -L "$file" && -O "$file" ]] \
        || { printf '%s: the environment transport %s is missing\n' "$prefix" "$file" >&2; exit 1; }
    saved=()
    while IFS= read -r -d '' entry; do
        saved+=("$entry")
    done < "$file"
    rm -f -- "$file"
    exec env -i -- "${saved[@]}" XDG_RUNTIME_DIR="$runtime" "$@"
fi

prefix=${1:-}
[[ "$prefix" =~ ^[a-z][a-z0-9]*(-[a-z0-9]+)*$ && $# -ge 2 ]] \
    || { printf 'usage: bash enter.sh <prefix> <command> [args...]\n' >&2; exit 2; }
shift
die() { printf '%s: %s\n' "$prefix" "$*" >&2; exit 1; }
distro=${WSL_DISTRO_NAME:-<distro>}
helper=$(readlink -f -- "${BASH_SOURCE[0]}")

# A distribution whose PID 1 is systemd needs no namespace change.
if [[ "$(cat "$proc/1/comm" 2>/dev/null)" == systemd ]]; then
    export XDG_RUNTIME_DIR=$runtime
    exec "$@"
fi

# The machine's systemd: a root process named systemd that is PID 1 of a child
# PID namespace ("NSpid: <pid> 1"). The lowest such PID wins.
target=''
for directory in "$proc"/[0-9]*; do
    pid=${directory##*/}
    [[ "$(cat "$directory/comm" 2>/dev/null)" == systemd ]] || continue
    [[ "$(stat -c %u -- "$directory" 2>/dev/null)" == "$root_uid" ]] || continue
    [[ "$(sed -n 's/^NSpid:[[:space:]]*//p' "$directory/status" 2>/dev/null)" =~ ^${pid}[[:space:]]+1$ ]] || continue
    if [[ -z "$target" ]] || ((pid < target)); then
        target=$pid
    fi
done
[[ -n "$target" ]] \
    || die "the Podman machine's systemd is not running in the WSL distribution $distro. Run wsl --terminate" \
        "$distro, then start the machine with Podman Desktop or podman machine start, and retry."
for tool in sudo nsenter; do
    command -v "$tool" >/dev/null || die "$tool is required in the distribution"
done
user=$(id -un)
sudo -n true 2>/dev/null \
    || die "entering the Podman machine's systemd namespaces needs sudo without a password for $user in" \
        "$distro, as the machine's own login shells use; restore it or recreate the machine with Podman Desktop."

# The transport directory is private; a file whose creator (now sudo) has
# exited belongs to a start that failed before the inner part read it.
[[ -d "$runtime" && -w "$runtime" ]] || die "$runtime is missing; start the machine with podman machine start"
if [[ ! -e "$transport" ]]; then
    mkdir -m 0700 -- "$transport"
fi
[[ -d "$transport" && ! -L "$transport" && -O "$transport" ]] || die "$transport is not a private directory"
chmod 0700 -- "$transport"
for stale in "$transport"/env.*; do
    [[ -e "$stale" ]] || continue
    owner=${stale#"$transport"/env.}
    owner=${owner%%.*}
    [[ "$owner" =~ ^[0-9]+$ && -e "$proc/$owner" ]] || rm -f -- "$stale"
done
file=$(mktemp -p "$transport" "env.$$.XXXXXXXXXX")
env -0 > "$file"
# This process becomes sudo, so the file name keeps naming a live process.
exec sudo -n -- nsenter --target "$target" --mount --pid --wd="$PWD" -- \
    sudo -n -u "$user" -- /bin/bash "$helper" --inner "$prefix" "$file" "$@"

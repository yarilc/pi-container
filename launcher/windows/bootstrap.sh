#!/usr/bin/env bash
# shellcheck shell=bash
# Windows bootstrap: the first code of an ordinary Windows launch inside the
# Podman machine's WSL distribution. The shared PowerShell shim
# (launcher/windows/core.ps1) runs it from the protected release, never from a
# checkout, with every user value in the environment, because the wsl.exe
# command line cannot carry them unchanged:
#   WRAPPER_WINDOWS_ARGS   base64 of the UTF-8 arguments, each followed by NUL;
#                          unset when there are none
#   WRAPPER_WINDOWS_CWD    raw Windows path of the PowerShell location
#   WRAPPER_WINDOWS_ENTRY  raw Windows path of the entry's directory
# It decodes the arguments, translates both paths, changes to the workspace and
# runs the release's managed command with WRAPPER_WINDOWS_ENTRY translated, so
# setup/launch.py keeps every writable mount away from the entry. The command
# runs in the PID and mount namespaces of the machine's systemd, where the
# launch service and Podman's own connections run (launcher/windows/enter.sh).
# See docs/launcher-contract.md (Windows entry).
set -Eeuo pipefail

prefix=bootstrap
die() { printf '%s: %s\n' "$prefix" "$*" >&2; exit 1; }

# mapfile -d needs Bash 4.4.
((BASH_VERSINFO[0] > 4 || (BASH_VERSINFO[0] == 4 && BASH_VERSINFO[1] >= 4))) \
    || die "Bash 4.4 or later is required in the distribution; found $BASH_VERSION"
for tool in base64 od tail wslpath python3 readlink id; do
    command -v "$tool" >/dev/null || die "$tool is required in the distribution"
done

script=$(readlink -f -- "${BASH_SOURCE[0]}")
release=${script%/launcher/windows/bootstrap.sh}
[[ "$release" != "$script" ]] || die "the bootstrap must run from launcher/windows in a release"
# One read of the release: the profile name for messages, the managed command,
# and whether the saved preferences still enable the removed host Podman
# delegation (schema 2); schema 3 preferences no longer have the setting.
read_release='import json, sys
release = sys.argv[1]
name = json.load(open(release + "/agent/profile.json"))["name"]
saved = json.load(open(release + "/setup.json"))
command = saved["command"]
assert command.startswith("/") and "\n" not in command and "\r" not in command
print(name)
print(command)
print("supported" if saved.get("podman", False) is False else "unsupported")'
details=$(python3 -I -c "$read_release" "$release" 2>/dev/null) \
    || die "the installation in $release is incomplete; rerun setup from Windows with --container-setup"
prefix=${details%%$'\n'*}
details=${details#*$'\n'}
managed_command=${details%%$'\n'*}
# Saved delegation would apply to every launch without a Windows variable; the
# shim refuses only the variable. Saved network modes are the launcher's to check.
[[ "${details#*$'\n'}" == supported ]] \
    || die "the installation in $release saved host Podman delegation, which was removed; rerun setup from" \
        "Windows with --container-setup, which removes the setting"

# Only a distribution that Podman started has the user's runtime directory;
# after a start by wsl.exe alone no podman command works (design D6).
runtime_dir=/run/user/$(id -u)
distro=${WSL_DISTRO_NAME:-<distro>}
[[ -d "$runtime_dir" && -w "$runtime_dir" ]] \
    || die "the WSL distribution $distro runs without the Podman machine: $runtime_dir is missing, so podman" \
        "cannot work. Run wsl --terminate $distro, then start the machine with Podman Desktop or podman machine" \
        "start, and retry."

[[ -v WRAPPER_WINDOWS_CWD && -v WRAPPER_WINDOWS_ENTRY ]] \
    || die 'WRAPPER_WINDOWS_CWD and WRAPPER_WINDOWS_ENTRY are missing; start sessions with the Windows entry'

# Arguments: validated base64 of NUL-terminated UTF-8 records.
args=()
payload=${WRAPPER_WINDOWS_ARGS-}
if [[ -n "$payload" ]]; then
    [[ "$payload" =~ ^[A-Za-z0-9+/]*={0,2}$ ]] && ((${#payload} % 4 == 0)) \
        || die 'malformed argument transport: not base64'
    printf '%s' "$payload" | base64 -d >/dev/null 2>&1 || die 'malformed argument transport: not base64'
    last=$(printf '%s' "$payload" | base64 -d | tail -c 1 | od -An -tx1)
    [[ "${last// /}" == 00 ]] || die 'malformed argument transport: the last argument is not terminated'
    mapfile -d '' -t args < <(printf '%s' "$payload" | base64 -d)
fi

# Translate a raw Windows path into its drive mount; refuse every other kind.
translate() {
    local raw=$1 what=$2 lower=${1,,} drive
    case "$lower" in
        '\\wsl$\'* | '\\wsl.localhost\'* | '//wsl$/'* | '//wsl.localhost/'*)
            die "$what is inside a WSL distribution: $raw; use a directory on a Windows drive such as C:" ;;
        '\\'* | '//'*)
            die "$what is a network or device path: $raw; use a directory on a local Windows drive" ;;
        [a-z]:'\'* | [a-z]:/*) ;;
        *) die "$what is not a Windows file system path: $raw" ;;
    esac
    drive=${raw:0:2}
    translated=$(wslpath -a -u "$raw" 2>/dev/null) || translated=''
    [[ "$translated" == /* && -d "$translated" ]] \
        || die "$what is on drive ${drive^^}, which this distribution does not mount, or does not exist: $raw"
}

translate "$WRAPPER_WINDOWS_ENTRY" 'the Windows entry directory'
entry=$translated
translate "$WRAPPER_WINDOWS_CWD" 'the current directory'
cd -- "$translated" || die "cannot enter the current directory: $translated"

export WRAPPER_WINDOWS_ENTRY="$entry"
unset WRAPPER_WINDOWS_ARGS WRAPPER_WINDOWS_CWD WSLENV
exec /bin/bash "$release/launcher/windows/enter.sh" "$prefix" "$managed_command" "${args[@]}"

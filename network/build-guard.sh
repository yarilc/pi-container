#!/usr/bin/env bash
# Operator-only packaging. No network or host package installation is required.
set -Eeuo pipefail
project_root=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)
# Agent-specific names come only from the profile next to this checkout or release.
profile_query() { python3 -I "$project_root/network/agent_profile.py" "$@"; }
maintenance_name=$(profile_query env MAINTENANCE) || exit 1
[[ ${!maintenance_name:-} == 1 ]] || { printf 'Guard packaging requires exact %s=1.\n' "$maintenance_name" >&2; exit 1; }
[[ $# == 1 && $1 == /* ]] || { printf 'Usage: build-guard.sh /absolute/native/output-directory\n' >&2; exit 64; }
output_dir=$(realpath -e -- "$1")
[[ -d $output_dir && -O $output_dir && -w $output_dir ]] || { printf 'Output must be an existing caller-owned writable native directory.\n' >&2; exit 1; }
default_toolchain=$(profile_query image toolchain development) || exit 1
toolchain=$(podman image inspect --format '{{.Id}}' "${SANDBOX_GUARD_TOOLCHAIN:-$default_toolchain}")
[[ $toolchain =~ ^(sha256:)?[a-f0-9]{64}$ ]] || { printf 'A prepared immutable toolchain image ID is required.\n' >&2; exit 1; }
compiler_args=()
compiler_cidfile=${SANDBOX_GUARD_SETUP_CIDFILE:-}
if [[ -n "$compiler_cidfile" ]]; then
    [[ "$compiler_cidfile" == "$output_dir/"* && ${compiler_cidfile#"$output_dir/"} =~ ^\.setup-guard\.[a-f0-9]{32}$ && ! -e "$compiler_cidfile" && ! -L "$compiler_cidfile" ]] \
        || { printf 'Invalid setup-owned compiler cidfile.\n' >&2; exit 1; }
    compiler_args=(--cidfile "$compiler_cidfile")
fi
artifact=$(mktemp -- "$output_dir/.guard.XXXXXXXXXXXX")
cleanup() {
    local compiler_id=''
    if [[ -n "$compiler_cidfile" && -f "$compiler_cidfile" ]]; then
        compiler_id=$(<"$compiler_cidfile")
        if [[ "$compiler_id" =~ ^[a-f0-9]{64}$ ]]; then
            timeout --kill-after=1s 5s podman rm --force --ignore --time 0 "$compiler_id" >/dev/null \
                || printf 'Setup compiler cleanup could not be confirmed: %s\n' "$compiler_id" >&2
        fi
        rm -f -- "$compiler_cidfile"
    fi
    rm -f -- "$artifact"
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM
trap 'exit 129' HUP
podman run --rm "${compiler_args[@]}" --network=none --read-only --userns=keep-id --user "$(id -u):$(id -g)" \
    --volume "$project_root:$project_root:ro" --volume "$output_dir:$output_dir:rw" \
    --workdir "$project_root" --env LC_ALL=C --env SOURCE_DATE_EPOCH=0 \
    "$toolchain" -std=c11 -O2 -static -Wall -Wextra -Werror -D_FORTIFY_SOURCE=2 \
    -fstack-protector-strong -fno-ident -Wl,--build-id=none \
    -I "$project_root/network" "$project_root/network/guard.c" -o "$artifact"
chmod 0555 -- "$artifact"
"$artifact" --version
mv -f -- "$artifact" "$output_dir/sandbox-egress-guard"
(cd -- "$output_dir" && sha256sum sandbox-egress-guard > sandbox-egress-guard.sha256)
printf 'Packaged guard with toolchain %s\n' "$toolchain" >&2

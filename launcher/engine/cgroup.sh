#!/bin/sh
# The engine's cgroup delegation state (support-nested-systemd-containers,
# design D2): the one eligibility rule, shared by the engine's startup program
# and the launcher. Read-only. Prints one line:
#   eligible               the startup program may delegate the subtree;
#   delegated              the engine user owns the subtree, the init is in its leaf;
#   ineligible: <reason>   nothing is or can be delegated.
# The arguments exist for tests; the engine and the launcher use the defaults.
set -eu

usage() {
    echo 'usage: sandbox-engine-cgroup [init-cgroup mountinfo cgroup-root]' >&2
    exit 2
}

case $# in
    0)
        init_cgroup=/proc/1/cgroup
        mountinfo=/proc/self/mountinfo
        root=/sys/fs/cgroup
        ;;
    3)
        init_cgroup=$1
        mountinfo=$2
        root=$3
        ;;
    *) usage ;;
esac

ineligible() {
    echo "ineligible: $*"
    exit 0
}

has_option() {
    case ,$1, in
        *,"$2",*) return 0 ;;
    esac
    return 1
}

# The init's membership: one cgroup v2 line, none of a v1 hierarchy.
membership=$(cat -- "$init_cgroup" 2>/dev/null) || ineligible 'the engine init cgroup is unreadable'
newline='
'
case $membership in
    *"$newline"*|'') ineligible 'cgroup v1 hierarchies are present' ;;
    0::/*) ;;
    *) ineligible 'cgroup v1 hierarchies are present' ;;
esac

# The last mount at the root wins: mount root, its own options, type and
# superblock options (after the "-" separator).
found=''
set -f
while IFS= read -r line; do
    # shellcheck disable=SC2086 # mountinfo fields are space-separated and never empty
    set -- $line
    [ "$#" -ge 9 ] && [ "$5" = "$root" ] || continue
    mount_root=$4
    mount_options=$6
    shift 6
    while [ "$#" -gt 0 ] && [ "$1" != - ]; do
        shift
    done
    [ "$#" -ge 4 ] || continue
    found=1
    fstype=$2
    super_options=$4
done <"$mountinfo"
set +f
[ -n "$found" ] || ineligible "no cgroup file system at $root"
[ "$fstype" = cgroup2 ] || ineligible "$root is not a cgroup v2 hierarchy"
[ "$mount_root" = / ] || ineligible 'the engine has no private cgroup namespace'
has_option "$mount_options" rw || ineligible "$root is mounted read-only"
has_option "$super_options" nsdelegate || ineligible "$root is mounted without nsdelegate"

owner=$(stat -c %u:%g -- "$root" 2>/dev/null) || ineligible "$root is unreadable"
if [ "$owner" = 0:0 ] && [ "$membership" = 0::/ ]; then
    echo eligible
elif [ "$owner" = 1000:1000 ] && [ "$membership" = 0::/engine ] \
        && [ "$(stat -c %u:%g -- "$root/engine" 2>/dev/null)" = 1000:1000 ]; then
    echo delegated
else
    ineligible "the cgroup root belongs to $owner with the engine init in ${membership#0::}"
fi

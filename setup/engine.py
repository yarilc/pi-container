"""Session container engine helpers (session-container-engine), standard library only.

Shared by setup, the toolchain library and the launcher: the engine's seccomp
profile, its fixed endpoint and the read-only image store of the library.
"""
import hashlib
import json
import os
from pathlib import Path
import sys

# The engine's API service on loopback in the session's network namespace (design D2).
PORT = 2375
ENDPOINT = f'tcp://127.0.0.1:{PORT}'
# The library's image store and where every engine mounts it read-only (design D5).
STORE = '.images'
STORE_MOUNT = '/var/lib/shared'
# Engine build inputs in a release, and the seccomp profile setup writes beside them.
INPUTS = ('launcher/engine/Containerfile', 'launcher/engine/.containerignore', 'launcher/engine/cgroup.sh',
          'launcher/engine/containers.conf', 'launcher/engine/entrypoint.sh', 'launcher/engine/resolv.conf',
          'launcher/engine/start.sh', 'launcher/engine/storage.conf')
SECCOMP = 'launcher/engine/seccomp.json'
# Every session engine carries this label with its store path, for every wrapper:
# the toolchain command finds the engines that use the shared library's store.
STORE_LABEL = 'sandbox-engine.store'
# The launcher that owns an engine, as <pid>-<start time>: a later launch removes
# engines whose launcher no longer runs (session-owned engine storage).
OWNER_LABEL = 'sandbox-engine.owner'
# The engine runs as its image's unprivileged podman user, mapped to the caller,
# so nested containers' root writes caller-owned files (design D4).
USERNS = '--userns=keep-id:uid=1000,gid=1000'
# The engine's first process, its startup program, runs as the root of the
# engine's user namespace, never the caller (support-nested-systemd-containers,
# design D1); every later process runs as ENGINE_USER.
START_USER = '0:0'
START_PROGRAM = '/usr/local/bin/sandbox-engine-start'
# The engine's cgroup delegation state: delegated, eligible or "ineligible: <reason>".
CGROUP_PROGRAM = '/usr/local/bin/sandbox-engine-cgroup'
ENGINE_USER = 'podman'
# The engine's graph root lives below a neutral path (launcher/engine/storage.conf)
# that no workspace mount at the same path can shadow.
STORAGE = '/var/lib/sandbox-engine'
CA = '/etc/pki/ca-trust/extracted/pem/tls-ca-bundle.pem'
# The engine image's skeleton root file system for nested probes, run with the
# engine's /usr bound read-only (design D10).
PROBE_ROOTFS = '/opt/sandbox-engine/probe-rootfs'
# Engine API readiness: the services start within a few seconds.
READY_SECONDS = 30
# The only change from the engine host's default profile: nested containers need
# a private UTS namespace, so the engine may name them without CAP_SYS_ADMIN.
# The kernel still requires CAP_SYS_ADMIN over the owning UTS namespace (design D4).
HOSTNAME_CALLS = ('sethostname', 'setdomainname')


class EngineError(Exception):
    pass


def seccomp_profile(default):
    """The engine profile: the default profile with the hostname calls always allowed."""
    if not isinstance(default, dict) or not isinstance(default.get('syscalls'), list):
        raise EngineError('the default seccomp profile has no syscalls list')
    kept = []
    for rule in default['syscalls']:
        if not isinstance(rule, dict) or not isinstance(rule.get('names'), list):
            raise EngineError('the default seccomp profile has a rule without names')
        names = [name for name in rule['names'] if name not in HOSTNAME_CALLS]
        if names:
            kept.append(dict(rule, names=names))
    return dict(default, syscalls=[*kept, {'names': list(HOSTNAME_CALLS), 'action': 'SCMP_ACT_ALLOW'}])


def write_seccomp(source, destination):
    """Derive the engine profile from the default at source; return its SHA-256."""
    try:
        default = json.loads(Path(source).read_text())
    except (OSError, ValueError) as error:
        raise EngineError(f'cannot read the default seccomp profile {source}: {error}') from None
    data = (json.dumps(seccomp_profile(default), indent=1, sort_keys=True) + '\n').encode()
    destination = Path(destination)
    temporary = destination.with_name('.' + destination.name + '.new')
    temporary.unlink(missing_ok=True)
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, 'wb') as output:
        output.write(data)
    temporary.replace(destination)
    return hashlib.sha256(data).hexdigest()


def container_options(*, name, seccomp, store, mounts=(), ca_bundle='', labels=()):
    """podman run options of an engine container (design D2, D4, D5, D6).

    SETUID and SETGID serve the user-namespace helpers; SYS_CHROOT serves layer
    extraction (pull, load) and image builds, whose helpers chroot. The engine
    starts as the root of its user namespace with CHOWN as well: its startup
    program delegates the engine's own cgroup subtree, then runs catatonit and
    the services as the podman user with the other three capabilities only
    (support-nested-systemd-containers, design D1). No --init: catatonit is the
    startup program's own last exec, so no root process remains.

    The caller adds the network and budget options, then the image and PORT. The
    engine mounts only an anonymous storage volume, which --rm removes with the
    engine, the library's store read-only, the given workspace paths at the same
    paths, and the CA bundle when trusted.
    """
    options = ['--name', name, '--rm', '--user', START_USER, USERNS,
               '--cap-drop=all', '--cap-add=SETUID,SETGID,SYS_CHROOT,CHOWN', '--security-opt=no-new-privileges',
               '--security-opt=unmask=ALL', '--security-opt=label=disable', '--security-opt=seccomp=' + str(seccomp),
               '--device=/dev/fuse', '--device=/dev/net/tun', '--http-proxy=false',
               '--mount', 'type=tmpfs,destination=/run/secrets,ro=true',
               '--volume', STORAGE,
               '--volume', str(Path(store) / 'storage') + ':' + STORE_MOUNT + ':ro',
               '--label', STORE_LABEL + '=' + str(store)]
    for label in labels:
        options += ['--label', label]
    for path in mounts:
        options += ['--volume', f'{path}:{path}:rw']
    if ca_bundle:
        options += ['--volume', f'{ca_bundle}:{CA}:ro']
    for value in options:
        if '\0' in value or '\n' in value:
            raise EngineError('engine options cannot contain NUL or newline characters')
    return options


def inputs_identity(root):
    """SHA-256 over the engine build inputs of a release or checkout."""
    digest = hashlib.sha256()
    for name in INPUTS:
        digest.update(name.encode() + b'\0' + (Path(root) / name).read_bytes() + b'\0')
    return digest.hexdigest()


def parse_options(argv):
    """engine.py options --name N --seccomp P --store S [--mount PATH]... [--ca-bundle F] [--label L]..."""
    values = {'mounts': [], 'labels': [], 'ca_bundle': ''}
    single = {'--name': 'name', '--seccomp': 'seccomp', '--store': 'store', '--ca-bundle': 'ca_bundle'}
    repeated = {'--mount': 'mounts', '--label': 'labels'}
    while argv:
        if len(argv) < 2 or argv[0] not in {**single, **repeated}:
            raise EngineError('invalid engine option: ' + (argv[0] if argv else ''))
        key, value = argv[0], argv[1]
        if key in single:
            values[single[key]] = value
        else:
            values[repeated[key]].append(value)
        argv = argv[2:]
    missing = [key for key in ('name', 'seccomp', 'store') if not values.get(key)]
    if missing:
        raise EngineError('missing engine option: ' + ', '.join(missing))
    return values


def main(argv):
    if len(argv) == 3 and argv[0] == 'seccomp':
        print(write_seccomp(argv[1], argv[2]))
        return 0
    if argv[:1] == ['options']:
        # NUL-separated for the launcher's mapfile -d ''.
        sys.stdout.write(''.join(value + '\0' for value in container_options(**parse_options(argv[1:]))))
        return 0
    print('usage: engine.py seccomp <default-profile> <destination> | options --name N --seccomp P '
          '--store S [--mount PATH]... [--ca-bundle FILE] [--label LABEL]...', file=sys.stderr)
    return 2


if __name__ == '__main__':
    try:
        sys.exit(main(sys.argv[1:]))
    except EngineError as error:
        print(str(error), file=sys.stderr)
        sys.exit(1)

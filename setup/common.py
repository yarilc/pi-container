"""Declarative managed preferences and protected host paths (standard library only)."""
import hashlib
import json
import os
from pathlib import Path
import re
import stat
from collections import deque
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'network'))
import agent_budgets  # noqa: E402
import agent_profile  # noqa: E402

# The checkout or release that contains this file selects its own profile.
PROFILE = agent_profile.load()


class SetupError(ValueError):
    pass


class EntryOverlap(SetupError):
    """A writable mount reaches the Windows entry; the message is safe to show as is."""


# Set by the Windows bootstrap to the entry's directory, translated into the distribution.
WINDOWS_ENTRY = 'WRAPPER_WINDOWS_ENTRY'
# WSL drive mounts (drvfs) ignore letter case.
DRIVE_MOUNT = re.compile(r'/mnt/[A-Za-z](?:/|$)')


# Reviewed toolchain recipes that every release installs (`--container-toolchain add <name>`).
TOOLCHAIN_CATALOG = tuple('setup/toolchain-catalog/' + name + '.json'
                          for name in ('go', 'java21', 'maven3.9', 'node24', 'python3.13', 'rust'))
MANIFEST = (
    PROFILE.wrapper, 'launcher/core.sh', 'launcher/windows/bootstrap.sh', 'launcher/windows/enter.sh',
    'agent/launcher.sh', 'Containerfile', '.containerignore', agent_profile.PROFILE, agent_profile.POLICY,
    'setup/common.py', 'setup/setup.py', 'setup/launch.py', 'setup/smoke.py', 'setup/diagnostics.py',
    'setup/toolchains.py', 'setup/engine.py', *TOOLCHAIN_CATALOG,
    'network/Containerfile', 'network/.containerignore',
    'launcher/engine/Containerfile', 'launcher/engine/.containerignore', 'launcher/engine/cgroup.sh',
    'launcher/engine/containers.conf', 'launcher/engine/entrypoint.sh', 'launcher/engine/resolv.conf',
    'launcher/engine/start.sh', 'launcher/engine/storage.conf',
    'network/guard-build.Containerfile', 'network/build-guard.sh',
    'network/guard.c', 'network/guard_landlock.h', 'network/guard_seccomp.h',
    'network/control.py', 'network/policy.py', 'network/agent_profile.py', 'network/session.py',
    'network/proxy.py', 'network/proxy_hardening.py', 'network/agent_budgets.py',
    'network/tls_client_hello.py', 'network/revisions.py', 'network/relay.py', 'network/mux.py', 'network/resolv.conf',
    'network/platform_check.py', 'network/qualify.py', 'network/qualification_records.py',
    'network/qualification_probe.py', 'network/qualification_runtime.py',
    'network/qualification_peer.py', 'network/qualification_proxy.py',
    'network/release_acceptance.json',
    *PROFILE.install_files,
)
GUARD_INPUTS = ('network/guard.c', 'network/guard_landlock.h',
                'network/guard_seccomp.h', 'network/build-guard.sh',
                'network/guard-build.Containerfile')
IMAGE_ID = re.compile(r'(?:sha256:)?[a-f0-9]{64}')
FIELDS = {
    'schema_version', 'installation', 'command', 'network', 'auth',
    'state_dir', 'config_dir', 'runtime_dir', 'endpoint',
    'yolo', 'worktree', 'trust_ca', 'ca_bundle', 'image', 'image_id',
    'proxy_image', 'toolchain_image', 'guard_sources_sha256',
    'engine_image', 'engine_sources_sha256', 'engine_seccomp_sha256',
    'memory_limit', 'cpu_limit', 'pids_limit', 'run_timeout',
}
# Saved agent budgets/lifetime and the wrapper variable suffix each one supplies.
BUDGETS = {'memory_limit': 'MEMORY_LIMIT', 'cpu_limit': 'CPU_LIMIT',
           'pids_limit': 'PIDS_LIMIT', 'run_timeout': 'RUN_TIMEOUT'}
SCHEMA_VERSION = 3
# Schema 2 preferences may still hold the removed host Podman delegation
# settings, and schema 1 also predates budgets; upgrade() migrates both.
DELEGATION = ('podman', 'delegation_socket')
# Schema 3 adds the session container engine image and seccomp profile.
ENGINE_FIELDS = ('engine_image', 'engine_sources_sha256', 'engine_seccomp_sha256')
FIELDS_V2 = (FIELDS - set(ENGINE_FIELDS)) | set(DELEGATION)
FIELDS_V1 = FIELDS_V2 - set(BUDGETS)
BOOLS = ('yolo', 'worktree', 'trust_ca')
PATHS = ('installation', 'command', 'state_dir', 'config_dir', 'runtime_dir', 'ca_bundle')


def overlap(left, right):
    left, right = Path(left).resolve(), Path(right).resolve()
    return left == right or left in right.parents or right in left.parents


def absolute(value):
    if value == '~' or value.startswith('~/'):
        value = os.environ['HOME'] + value[1:]
    if not value.startswith('/') or any(c in value for c in '\r\n\0:'):
        raise SetupError('Use an absolute Linux path without colons or control characters.')
    return str(Path(value).absolute())


def trusted(path, *, missing=False):
    """Check lexical and physical ancestors, including paths not yet created."""
    path = Path(absolute(str(path)))
    resolved = path.resolve(strict=not missing)
    for item in set((path, *path.parents, resolved, *resolved.parents)):
        if not item.exists():
            if item.is_symlink() or not missing:
                raise SetupError(f'Invalid protected path: {item}')
            continue
        info = item.stat()
        if info.st_uid not in (0, os.getuid()) or info.st_mode & 0o022:
            raise SetupError(f'Unsafe protected path: {item}; use native storage with caller/root-owned, non-writable ancestors.')
    return resolved


def private(path, *, create=False):
    path = Path(path)
    trusted(path, missing=not path.exists())
    if create:
        old = os.umask(0o077)
        try:
            path.mkdir(mode=0o700, parents=True, exist_ok=True)
        finally:
            os.umask(old)
    if path.exists():
        info = path.stat()
        reason = None
        if not path.is_dir():
            reason = 'it is not a directory'
        elif info.st_uid != os.getuid():
            reason = f'it belongs to UID {info.st_uid}, not the calling user'
        elif info.st_mode & 0o077:
            reason = (f'mode {info.st_mode & 0o777:o} grants group/other access; run chmod 700 {path} '
                      'or use native Linux storage that enforces Unix permissions')
        elif not os.access(path, os.R_OK | os.W_OK | os.X_OK):
            reason = 'the calling user lacks read, write or traverse access'
        if reason:
            raise SetupError(f'Private caller-owned directory required: {path} ({reason}); '
                             'existing permissions were not changed.')
    return path.resolve()


def installation_directory(path, *, create=False):
    """Installation code needs write protection; credential state needs privacy."""
    path = Path(path)
    trusted(path, missing=True)
    if create:
        old = os.umask(0o077)
        try:
            path.mkdir(mode=0o700, parents=True, exist_ok=True)
        finally:
            os.umask(old)
    if path.exists():
        trusted(path)
        if not path.is_dir() or path.stat().st_uid != os.getuid() or not os.access(path, os.R_OK | os.W_OK | os.X_OK):
            raise SetupError(f'Installation directory must be caller-owned and readable/writable/searchable: {path}; choose another path or correct its ownership/access explicitly.')
    return path.resolve()


def endpoint_url(endpoint):
    if endpoint == 'local':
        return ''
    if endpoint == 'default':
        runtime = os.environ.get('XDG_RUNTIME_DIR') or f'/run/user/{os.getuid()}'
        endpoint = 'unix://' + runtime + '/podman/podman.sock'
    if not endpoint.startswith('unix:///') or not endpoint[7:].strip('/') or any(c in endpoint for c in '\r\n\0'):
        raise SetupError('Use local, default, or an absolute same-host unix:///path/to/podman.sock endpoint.')
    return endpoint


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise SetupError('Duplicate preference field.')
        result[key] = value
    return result


def validate(value):
    if not isinstance(value, dict) or set(value) != FIELDS:
        raise SetupError('Invalid managed preference fields; no credentials or arbitrary environment variables are accepted.')
    if type(value['schema_version']) is not int or value['schema_version'] != SCHEMA_VERSION:
        raise SetupError('Unsupported managed preference schema.')
    for name in BOOLS:
        if type(value[name]) is not bool:
            raise SetupError('Invalid preference boolean.')
    for name in FIELDS - set(BOOLS) - {'schema_version'}:
        if not isinstance(value[name], str) or len(value[name]) > 4096 or any(c in value[name] for c in '\0\r\n'):
            raise SetupError('Invalid preference string.')
    for name in PATHS:
        if value[name]:
            absolute(value[name])
    if not value['installation'] or not value['command']:
        raise SetupError('Installation and command paths are required.')
    if value['network'] not in ('offline', 'provider', 'unrestricted') or value['auth'] not in ('none', *PROFILE.auth):
        raise SetupError('Invalid network/authentication choice.')
    if value['network'] == 'provider' and value['auth'] == 'none':
        raise SetupError('Provider mode requires an authentication profile.')
    if value['yolo'] and not PROFILE.approval_bypass_env:
        raise SetupError('The agent profile declares no permission bypass.')
    if value['network'] != 'unrestricted' and value['endpoint'] == 'local':
        raise SetupError('Restricted modes require a Unix service.')
    if value['state_dir'] and value['config_dir']:
        raise SetupError('Isolated state conflicts with a shared ' + PROFILE.display_name + ' configuration directory.')
    endpoint_url(value['endpoint'])
    if not re.fullmatch(r'[a-zA-Z0-9][a-zA-Z0-9./:_-]{0,254}', value['image']):
        raise SetupError('Invalid runtime image name.')
    for name in ('image_id', 'proxy_image', 'toolchain_image', 'guard_sources_sha256', *ENGINE_FIELDS):
        if value[name] and not IMAGE_ID.fullmatch(value[name]):
            raise SetupError('Invalid immutable image or source identity.')
    if value['network'] == 'provider' and (not value['runtime_dir'] or not value['proxy_image']):
        raise SetupError('Provider preferences require a runtime directory and immutable proxy image.')
    for name, suffix in BUDGETS.items():
        try:
            if agent_budgets.canonical(suffix, value[name]) != value[name]:
                raise agent_budgets.BudgetError(suffix)
        except agent_budgets.BudgetError:
            raise SetupError('Invalid saved agent budget or lifetime.') from None
    return value


def upgrade(value):
    """Accept exactly the older field sets: schema 1 gains the default budgets,
    and schema 1 and 2 lose the removed host Podman delegation settings."""
    if not isinstance(value, dict) or type(value.get('schema_version')) is not int:
        return value
    if value['schema_version'] == 1 and set(value) == FIELDS_V1:
        value = dict(value, schema_version=2)
        for name, suffix in BUDGETS.items():
            value[name] = agent_budgets.DEFAULTS[suffix]
    if value['schema_version'] == 2 and set(value) == FIELDS_V2:
        value = {key: item for key, item in value.items() if key not in DELEGATION}
        value.update(dict.fromkeys(ENGINE_FIELDS, ''), schema_version=SCHEMA_VERSION)
    return value


def saved_delegation(value):
    """Whether raw saved preferences enable the removed host Podman delegation."""
    return isinstance(value, dict) and value.get('podman') is True


def read_preferences(path):
    path = trusted(path)
    info = path.stat()
    if not path.is_file() or info.st_uid != os.getuid() or info.st_mode & 0o077:
        raise SetupError('Managed preferences must be a private caller-owned regular file.')
    if info.st_size > 65536:
        raise SetupError('Managed preferences exceed 64 KiB.')
    return json.loads(path.read_text(), object_pairs_hook=unique_object)


def load(path, *, migrate=False):
    """Validated preferences. Saved delegation stops launches; setup migrates it away."""
    value = read_preferences(path)
    if saved_delegation(value) and not migrate:
        raise SetupError('The saved preferences enable host Podman delegation, which was removed; rerun '
                         '--container-setup to migrate them. Sessions get a private container engine when '
                         'the toolchain library holds images.')
    return validate(upgrade(value))


def save(path, value):
    validate(value)
    with open(path, 'x', opener=lambda p, flags: os.open(p, flags, 0o600)) as output:
        json.dump(value, output, sort_keys=True, indent=2)
        output.write('\n')


def defaults(root=None):
    home = Path(os.environ['HOME'])
    return dict(schema_version=SCHEMA_VERSION, installation=str(root or home / '.local/lib' / PROFILE.name),
                command=str(home / '.local/bin' / PROFILE.name),
                network='provider' if PROFILE.auth else 'offline', auth=next(iter(PROFILE.auth), 'none'),
                state_dir='', config_dir='', runtime_dir=str(home / '.local/state' / PROFILE.state_name),
                endpoint='default', yolo=False,
                worktree=False, trust_ca=False, ca_bundle='',
                image=PROFILE.image('agent', 'latest'), image_id='', proxy_image='',
                toolchain_image='', guard_sources_sha256='',
                **dict.fromkeys(ENGINE_FIELDS, ''),
                **{name: agent_budgets.DEFAULTS[suffix] for name, suffix in BUDGETS.items()})


def source_identity(root):
    digest = hashlib.sha256()
    for name in GUARD_INPUTS:
        digest.update(name.encode() + b'\0' + (root / name).read_bytes())
    return digest.hexdigest()


def runtime_environment(value, release, *, overrides=True):
    env = os.environ.copy()
    name = PROFILE.env
    selected = {
        name('NETWORK'): value['network'],
        name('STATE_DIR'): value['state_dir'], PROFILE.config_dir_env: value['config_dir'],
        name('IMAGE'): value['image'], name('ENGINE_IMAGE'): value['engine_image'],
        name('TRUST_HOST_CA'): '1' if value['trust_ca'] else '0',
        name('CA_BUNDLE'): value['ca_bundle'],
        'CONTAINER_HOST': endpoint_url(value['endpoint']),
        **{name(suffix): value[key] for key, suffix in BUDGETS.items()},
    }
    if PROFILE.approval_bypass_env:
        selected[PROFILE.approval_bypass_env] = '1' if value['yolo'] else '0'
    # Provider inputs exist only for a profile with authentication methods.
    if PROFILE.auth:
        selected.update({
            name('NETWORK_RUNTIME_DIR'): value['runtime_dir'],
            name('NETWORK_PROFILE'): PROFILE.policy_profile(value['auth']) if value['auth'] != 'none' else '',
            name('NETWORK_POLICY'): str(release / agent_profile.POLICY),
            name('EGRESS_IMAGE'): value['proxy_image'],
        })
    if not overrides:
        # Setup and smoke never inherit the launch-only forwarding and read-only switches.
        for name in (*selected, 'CONTAINER_CONNECTION', PROFILE.env('MAINTENANCE'), PROFILE.env('ENV_VARS'),
                     PROFILE.env('READONLY_STATE'), *PROFILE.credential_envs):
            env.pop(name, None)
    for name, item in selected.items():
        # Podman treats a set CONTAINER_HOST as a remote context even when it
        # is empty, so the local endpoint leaves the variable unset.
        if name not in env and (item or name != 'CONTAINER_HOST'):
            env[name] = item
    return env


def writable_mounts(env, args=(), worktree=False, workspace=None):
    workspace = Path(workspace or Path.cwd()).resolve()
    if worktree or '--container-git-worktree' in args:
        workspace = workspace.parent
    mounts = [workspace]
    state_name, config_name = PROFILE.env('STATE_DIR'), PROFILE.config_dir_env
    if env.get(state_name):
        if env.get(config_name):
            raise SetupError(state_name + ' conflicts with ' + config_name + '; unset the shared override.')
        state = Path(env[state_name]).resolve()
        # Isolated credentials and history must never land in, or contain, the workspace.
        if overlap(state, workspace):
            raise SetupError(state_name + ' must not overlap the workspace: ' + str(state) + ' and ' + str(workspace))
        for relative in (PROFILE.config_home, *PROFILE.shared_dirs):
            child = (state / relative).resolve()
            if child != state and state not in child.parents:
                raise SetupError('Isolated configuration escapes the selected state home.')
        mounts.append(state)
    else:
        mounts += [Path(env.get(config_name) or Path(env['HOME']) / PROFILE.config_home).resolve(),
                   *((Path(env['HOME']) / shared).resolve() for shared in PROFILE.shared_dirs)]
    return mounts


def launcher_paths(path):
    """Resolve like the kernel while retaining every mutable symlink entry."""
    remaining = deque(Path(path).absolute().parts[1:])
    current = Path('/')
    links = []
    while remaining:
        component = remaining.popleft()
        if component == '..':
            current = current.parent
            continue
        if component == '.':
            continue
        entry = current / component
        if entry.is_symlink():
            links.append(entry)
            if len(links) > 40:
                raise SetupError('Too many symlinks in the invoked managed launcher path.')
            target = Path(os.readlink(entry))
            if target.is_absolute():
                current = Path('/')
                remaining.extendleft(reversed(target.parts[1:]))
            else:
                remaining.extendleft(reversed(target.parts))
        else:
            current = entry
    return current, links


def same_or_inside(inner, outer):
    inner, outer = str(inner), str(outer)
    if DRIVE_MOUNT.match(inner) and DRIVE_MOUNT.match(outer):
        inner, outer = inner.lower(), outer.lower()
    return inner == outer or inner.startswith(outer.rstrip('/') + '/')


def protect_windows_entry(entry, mounts):
    """The session must never write the Windows entry that starts the next launch."""
    if not entry.startswith('/'):
        raise SetupError(WINDOWS_ENTRY + ' must be an absolute path.')
    # drvfs paths cannot pass trusted(): the protection is that no mount reaches them.
    entry = Path(entry).resolve()
    for mount in mounts:
        if same_or_inside(entry, mount) or same_or_inside(mount, entry):
            raise EntryOverlap('The Windows entry directory ' + str(entry) + ' overlaps the writable mount '
                               + str(mount) + '; launch from a project outside it, or move the entry.')


def protect_mounts(value, env, args=(), *, launcher=None, workspace=None):
    mounts = writable_mounts(env, args, value['worktree'], workspace)
    if env.get(WINDOWS_ENTRY):
        protect_windows_entry(env[WINDOWS_ENTRY], mounts)
    paths = [value['installation'], value['command']]
    if launcher is not None:
        resolved, links = launcher_paths(launcher)
        paths.append(resolved)
        for entry in links:
            trusted(entry)
            # Do not resolve this entry away: even a link whose target is safe
            # can be replaced through a writable parent on the next invocation.
            if any(entry == mount or mount in entry.parents for mount in mounts):
                raise SetupError('Invoked managed launcher alias overlaps a writable workspace or state mount.')
    for path in paths:
        trusted(path, missing=True)
        lexical = Path(os.path.abspath(path))
        if any(overlap(path, mount) or lexical == mount or mount in lexical.parents
               or lexical in mount.parents for mount in mounts):
            raise SetupError('Managed installation/command overlaps a writable workspace or state mount; relocate it or choose another workspace.')
    if (env.get(PROFILE.env('NETWORK')) or PROFILE.default_mode) == 'provider':
        for name in (PROFILE.env('NETWORK_POLICY'), PROFILE.env('NETWORK_RUNTIME_DIR')):
            path = env.get(name, '')
            if not path or any(overlap(path, mount) for mount in mounts):
                raise SetupError('Protected provider policy/runtime overlaps a writable mount or is missing.')
    return mounts


def prepare_state(env, *, create=False):
    """Preserve the wrapper's private-configuration/shared-directory permission contract.

    Returns (path, private) pairs; private is true only for paths that passed private().
    """
    paths = writable_mounts(env)[1:]
    isolated = env.get(PROFILE.env('STATE_DIR'))
    checked = []
    for index, path in enumerate(paths):
        if isolated or index == 0 or PROFILE.private_shared_dirs:
            private(path, create=create)
            checked.append((path, True))
        else:
            checked.append((path, False))
            # Shared tool settings are writable state, not a credential home.
            trusted(path, missing=True)
            if create:
                old = os.umask(0o077)
                try:
                    path.mkdir(mode=0o700, parents=True, exist_ok=True)
                finally:
                    os.umask(old)
            if path.exists() and (not path.is_dir() or not os.access(path, os.R_OK | os.W_OK | os.X_OK)):
                raise SetupError('Shared configuration directory is inaccessible: ' + str(path))
    if isolated:
        child = Path(isolated) / PROFILE.config_home
        if child.exists():
            private(child)
    return checked


if __name__ == '__main__':
    # The Windows installer copies these files into its per-user folder
    # (launcher/windows/install.ps1); one NUL-terminated record per file.
    if sys.argv[1:] != ['--manifest']:
        print('usage: python3 -I setup/common.py --manifest', file=sys.stderr)
        sys.exit(2)
    sys.stdout.write(''.join(name + '\0' for name in MANIFEST))

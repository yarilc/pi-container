"""Operator-managed toolchain library shared by the wrappers (standard library only).

Toolchains are relocatable prefixes extracted from digest-pinned image paths or
checksummed local archives. Sessions see the library read-only at /toolchains.
"""
import contextlib
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import stat
import subprocess
import sys
import tarfile
import tempfile
import time

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import PROFILE, SetupError, absolute, overlap, private  # noqa: E402

INSTALLATION = Path(__file__).resolve().parents[1]
LIBRARY_NAME = 'sandbox-toolchains'
MOUNT = '/toolchains'
SCHEMA = 1
NAME = re.compile(r'[a-z0-9][a-z0-9._-]{0,63}')
VERSION = re.compile(r'[A-Za-z0-9][A-Za-z0-9._+-]{0,63}')
ENV_NAME = re.compile(r'[A-Za-z_][A-Za-z0-9_]{0,63}')
RELATIVE = re.compile(r'(?:[A-Za-z0-9._+-]+(?:/[A-Za-z0-9._+-]+)*)?')
IMAGE = re.compile(r'[a-z0-9][a-z0-9._/:-]*@sha256:[a-f0-9]{64}')
SHA256 = re.compile(r'[a-f0-9]{64}')
FROM = re.compile(r'^\s*FROM\s+(\S+)', re.IGNORECASE | re.MULTILINE)
BASE = re.compile(r'\S+@sha256:[a-f0-9]{64}')
RECIPE_REQUIRED = {'schema', 'name', 'version', 'source', 'check', 'default'}
RECIPE_OPTIONAL = {'path', 'env', 'requires', 'notes'}
# Session variables that a toolchain must never replace: identity, shell
# startup, the agent's own runtimes, wrapper settings, proxies and CA trust.
PROTECTED = {name.lower() for name in (
    'HOME', 'PATH', 'USER', 'LOGNAME', 'SHELL', 'TERM', 'EDITOR', 'VISUAL', 'PWD', 'OLDPWD', 'TMPDIR',
    'BASH_ENV', 'ENV', 'IFS', 'CONTAINER_HOST', 'CONTAINER_CONNECTION', 'NODE_OPTIONS', 'NODE_PATH',
    'PYTHONPATH', 'PYTHONHOME', 'PYTHONSTARTUP', 'HTTP_PROXY', 'HTTPS_PROXY', 'ALL_PROXY', 'NO_PROXY',
    'SSL_CERT_FILE', 'SSL_CERT_DIR', 'REQUESTS_CA_BUNDLE', 'CURL_CA_BUNDLE', 'NODE_EXTRA_CA_CERTS',
    PROFILE.config_dir_env, PROFILE.approval_bypass_env, *PROFILE.credential_envs)}
# XDG base-directory variables can place a wrapper's state (a wrapper may set them).
PROTECTED_PREFIXES = ('ld_', 'xdg_', PROFILE.env_prefix.lower() + '_', 'sandbox_')
CHECK_TIMEOUT = 300
PREFIX = PROFILE.message_prefix


def run(args, timeout=None):
    """Run one engine command and capture its text output."""
    try:
        return subprocess.run(['podman', *args], capture_output=True, text=True, timeout=timeout)
    except (OSError, subprocess.TimeoutExpired) as error:
        raise SetupError('podman ' + ' '.join(args[:2]) + ' failed: ' + str(error)) from None


@contextlib.contextmanager
def stream(args):
    """Yield the binary standard output of one engine command."""
    try:
        process = subprocess.Popen(['podman', *args], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    except OSError as error:
        raise SetupError('podman ' + args[0] + ' failed: ' + str(error)) from None
    try:
        yield process.stdout
        process.stdout.read()
    finally:
        process.stdout.close()
        error = process.stderr.read().decode(errors='replace')
        process.stderr.close()
        if process.wait() != 0:
            raise SetupError('podman ' + args[0] + ' failed: ' + error.strip()[-400:])


# Library location and safety

def library_path(env):
    value = env.get(PROFILE.env('TOOLCHAINS_DIR'), '')
    if value:
        if '\t' in value or not value.startswith('/'):
            raise SetupError(PROFILE.env('TOOLCHAINS_DIR') + ' must be an absolute path without tabs.')
        return Path(absolute(value))
    data = env.get('XDG_DATA_HOME', '')
    if not data.startswith('/'):
        data = str(Path(env['HOME']) / '.local/share')
    return Path(absolute(data)) / LIBRARY_NAME


def prepare_library(path, avoid):
    path = Path(path)
    if any(c in str(path) for c in '\t\r\n\0:'):
        raise SetupError(f'Toolchain library path must not contain tabs, colons or control characters: {path}')
    for other in avoid:
        if overlap(path, other):
            raise SetupError(f'Toolchain library {path} overlaps {other}; it must stay outside the workspace, '
                             'state directories and installation.')
    try:
        return private(path, create=True)
    except SetupError as error:
        raise SetupError(f'Toolchain library {path}: {error}') from None


def state_directories(env):
    """Host state directories the toolchain command can derive without a session."""
    state = env.get(PROFILE.env('STATE_DIR'), '')
    if state:
        return [Path(state)]
    home = Path(env['HOME'])
    config = env.get(PROFILE.config_dir_env, '') or str(home / PROFILE.config_home)
    return [Path(config), *(home / shared for shared in PROFILE.shared_dirs)]


@contextlib.contextmanager
def locked(library):
    descriptor = os.open(library / '.lock', os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    try:
        fcntl.flock(descriptor, fcntl.LOCK_EX)
        yield
    finally:
        os.close(descriptor)


def write_atomic(path, text):
    descriptor, temporary = tempfile.mkstemp(prefix='.write-', dir=path.parent)
    try:
        with os.fdopen(descriptor, 'w') as handle:
            handle.write(text)
        os.chmod(temporary, 0o644)
        os.replace(temporary, path)
    except BaseException:
        with contextlib.suppress(FileNotFoundError):
            os.unlink(temporary)
        raise


def base_reference(installation):
    """The single digest-pinned base named by the installed runtime recipe."""
    try:
        text = (Path(installation) / 'Containerfile').read_text()
    except OSError as error:
        raise SetupError('Cannot read the runtime Containerfile: ' + str(error)) from None
    bases = FROM.findall(text)
    if len(bases) != 1 or not BASE.fullmatch(bases[0]):
        raise SetupError('The runtime Containerfile must have exactly one digest-pinned FROM line.')
    return bases[0]


# Recipes

def control_free(value):
    return isinstance(value, str) and not any(ord(c) < 0x20 or ord(c) == 0x7f for c in value)


def relative(value, where):
    if not isinstance(value, str) or not RELATIVE.fullmatch(value) or \
            any(part in ('.', '..') for part in value.split('/')):
        raise SetupError(f'toolchain recipe: {where} must be a relative path inside the toolchain')
    return value


def protected(variable):
    lowered = variable.lower()
    return lowered in PROTECTED or lowered.startswith(PROTECTED_PREFIXES)


def validate_recipe(value):
    if not isinstance(value, dict):
        raise SetupError('toolchain recipe must be a JSON object')
    unknown = set(value) - RECIPE_REQUIRED - RECIPE_OPTIONAL
    if unknown:
        raise SetupError('toolchain recipe: unknown key ' + ', '.join(sorted(unknown)))
    missing = RECIPE_REQUIRED - set(value)
    if missing:
        raise SetupError('toolchain recipe: missing key ' + ', '.join(sorted(missing)))
    if value['schema'] != SCHEMA:
        raise SetupError('toolchain recipe: schema must be 1')
    if not isinstance(value['name'], str) or not NAME.fullmatch(value['name']):
        raise SetupError('toolchain recipe: invalid toolchain name; use [a-z0-9][a-z0-9._-]{0,63}')
    if not isinstance(value['version'], str) or not VERSION.fullmatch(value['version']):
        raise SetupError('toolchain recipe: invalid version')
    source = value['source']
    if not isinstance(source, dict):
        raise SetupError('toolchain recipe: source must be an object')
    if 'image' in source:
        if set(source) != {'image', 'path'}:
            raise SetupError('toolchain recipe: an image source has exactly image and path (unknown keys rejected)')
        if not isinstance(source['image'], str) or not IMAGE.fullmatch(source['image']):
            raise SetupError('toolchain recipe: the image must be referenced by @sha256: digest')
        path = source['path']
        if not isinstance(path, str) or not path.startswith('/') or path == '/' or not control_free(path) or \
                any(part in ('.', '..') for part in path.split('/')):
            raise SetupError('toolchain recipe: the image path must be an absolute path below /')
    elif 'archive' in source:
        if not set(source) <= {'archive', 'sha256', 'strip_components'} or 'sha256' not in source:
            raise SetupError('toolchain recipe: an archive source has archive, sha256 and optional strip_components '
                             '(unknown keys rejected)')
        if not isinstance(source['archive'], str) or not source['archive'].startswith('/'):
            raise SetupError('toolchain recipe: the archive must be an absolute local file path')
        absolute(source['archive'])
        if not isinstance(source['sha256'], str) or not SHA256.fullmatch(source['sha256']):
            raise SetupError('toolchain recipe: the archive SHA-256 must be 64 lowercase hex digits')
        strip = source.get('strip_components', 0)
        if not isinstance(strip, int) or isinstance(strip, bool) or not 0 <= strip <= 8:
            raise SetupError('toolchain recipe: strip_components must be an integer from 0 to 8')
    else:
        raise SetupError('toolchain recipe: source needs image and path, or archive and sha256')
    paths = value.get('path', ['bin'])
    if not isinstance(paths, list) or len(paths) > 8:
        raise SetupError('toolchain recipe: path must be a list of at most 8 relative paths')
    for entry in paths:
        relative(entry, 'path entry')
    environment = value.get('env', {})
    if not isinstance(environment, dict) or len(environment) > 32:
        raise SetupError('toolchain recipe: env must be an object with at most 32 variables')
    for variable, item in environment.items():
        if not ENV_NAME.fullmatch(variable):
            raise SetupError('toolchain recipe: invalid env variable name ' + repr(variable))
        if protected(variable):
            raise SetupError('toolchain recipe: env variable ' + variable + ' is protected by the session')
        if not isinstance(item, dict) or len(item) != 1 or not set(item) <= {'toolchain', 'value'}:
            raise SetupError('toolchain recipe: env value for ' + variable + ' must be {"toolchain": path} or {"value": text}')
        if 'toolchain' in item:
            relative(item['toolchain'], 'env ' + variable)
        elif not control_free(item['value']) or len(item['value']) > 1024:
            raise SetupError('toolchain recipe: env literal for ' + variable + ' must be text without control characters')
    requires = value.get('requires', [])
    if not isinstance(requires, list) or len(requires) > 16 or len(set(requires)) != len(requires) or \
            not all(isinstance(item, str) and NAME.fullmatch(item) for item in requires) or value['name'] in requires:
        raise SetupError('toolchain recipe: requires must list other toolchain names once each')
    notes = value.get('notes', [])
    if not isinstance(notes, list) or len(notes) > 10 or \
            not all(control_free(item) and 0 < len(item) <= 300 for item in notes):
        raise SetupError('toolchain recipe: notes must be at most 10 single-line texts')
    check = value['check']
    if not isinstance(check, list) or not 0 < len(check) <= 32 or \
            not all(control_free(item) and item for item in check):
        raise SetupError('toolchain recipe: check must be a non-empty command list without control characters')
    if not isinstance(value['default'], bool):
        raise SetupError('toolchain recipe: default must be true or false')
    return {'schema': SCHEMA, 'name': value['name'], 'version': value['version'], 'source': dict(source),
            'path': list(paths), 'env': {k: dict(v) for k, v in environment.items()}, 'requires': list(requires),
            'notes': list(notes), 'check': list(check), 'default': value['default']}


def load_recipe(path):
    try:
        value = json.loads(Path(path).read_text())
    except (OSError, ValueError) as error:
        raise SetupError('Cannot read toolchain recipe ' + str(path) + ': ' + str(error)) from None
    return validate_recipe(value)


# Installed toolchains

def installed(library):
    found = {}
    for entry in sorted(Path(library).iterdir()):
        manifest = entry / 'toolchain.json'
        if entry.name.startswith('.') or not entry.is_dir() or entry.is_symlink() or not manifest.is_file():
            continue
        try:
            value = json.loads(manifest.read_text())
        except ValueError:
            raise SetupError('Invalid toolchain manifest: ' + entry.name + '; remove and add it again.') from None
        if value.get('name') != entry.name:
            raise SetupError('Toolchain manifest name mismatch: ' + entry.name)
        found[entry.name] = value
    return found


def container_value(name, item):
    if 'toolchain' in item:
        return MOUNT + '/' + name + ('/' + item['toolchain'] if item['toolchain'] else '')
    return item['value']


def container_paths(name, value):
    return [MOUNT + '/' + name + ('/' + entry if entry else '') for entry in value['path']]


def commands(root, paths):
    found = set()
    for entry in paths:
        directory = root / entry if entry else root
        if not directory.is_dir() or directory.is_symlink():
            continue
        for item in directory.iterdir():
            target = item.resolve()
            if (target == root or root in target.parents) and target.is_file() and os.access(target, os.X_OK):
                found.add(item.name)
    return sorted(found)


def quoted(value):
    """Always single-quote, so env.sh never expands or runs anything."""
    return "'" + value.replace("'", "'\"'\"'") + "'"


def env_script(name, value):
    lines = ['# Generated by the toolchain library; do not edit.']
    for required in value['requires']:
        lines.append('. ' + MOUNT + '/' + required + '/env.sh')
    for variable, item in sorted(value['env'].items()):
        lines.append('export ' + variable + '=' + quoted(container_value(name, item)))
    for entry in reversed(container_paths(name, value)):
        lines.append('export PATH=' + quoted(entry) + ':"$PATH"')
    return '\n'.join(lines) + '\n'


def closure(names, toolchains):
    """Required toolchains in dependency order, each once."""
    ordered = []

    def visit(name, path):
        if name in path:
            raise SetupError('toolchain requires form a cycle: ' + ' -> '.join((*path, name)))
        if name in ordered:
            return
        if name not in toolchains:
            raise SetupError('required toolchain is missing: ' + name)
        for required in toolchains[name]['requires']:
            visit(required, (*path, name))
        ordered.append(name)
    for name in sorted(names):
        visit(name, ())
    return ordered


# Extraction

def extract(archive, destination, strip):
    """Extract a tar stream member by member without leaving the destination."""
    destination = Path(destination)
    root = destination.resolve()

    def inside(path):
        resolved = Path(os.path.realpath(path))
        return resolved == root or root in resolved.parents

    def target_of(member_name):
        name = member_name
        while name.startswith('./'):
            name = name[2:]
        parts = [part for part in name.split('/') if part not in ('', '.')]
        if member_name.startswith('/') or '..' in parts:
            raise SetupError('unsafe toolchain member: ' + member_name)
        parts = parts[strip:]
        return destination.joinpath(*parts) if parts else None

    for member in archive:
        target = target_of(member.name)
        if target is None:
            continue
        if not inside(target.parent) or target.is_symlink():
            raise SetupError('unsafe toolchain member: ' + member.name)
        if member.isdir():
            target.mkdir(mode=0o700, parents=True, exist_ok=True)
            os.chmod(target, 0o755)
        elif member.isreg():
            target.parent.mkdir(mode=0o755, parents=True, exist_ok=True)
            source = archive.extractfile(member)
            with open(target, 'xb') as handle:
                shutil.copyfileobj(source, handle)
            os.chmod(target, member.mode & 0o755 | 0o400)
        elif member.issym():
            link = member.linkname
            if link.startswith('/') or not inside(target.parent / link):
                raise SetupError('unsafe toolchain member: ' + member.name + ' -> ' + link)
            target.parent.mkdir(mode=0o755, parents=True, exist_ok=True)
            os.symlink(link, target)
        elif member.islnk():
            linked = target_of(member.linkname)
            if linked is None or not linked.is_file() or linked.is_symlink() or not inside(linked):
                raise SetupError('unsafe toolchain member: ' + member.name + ' links to ' + member.linkname)
            target.parent.mkdir(mode=0o755, parents=True, exist_ok=True)
            os.link(linked, target)
        else:
            raise SetupError('unsafe toolchain member type: ' + member.name)


def extract_source(recipe, staging, env):
    source = recipe['source']
    if 'archive' in source:
        archive = Path(source['archive'])
        digest = hashlib.sha256()
        try:
            with open(archive, 'rb') as handle:
                for block in iter(lambda: handle.read(1 << 20), b''):
                    digest.update(block)
            if digest.hexdigest() != source['sha256']:
                raise SetupError('archive SHA-256 mismatch for ' + archive.name + ': ' + digest.hexdigest())
            with tarfile.open(archive, 'r:*') as members:
                extract(members, staging, source.get('strip_components', 0))
        except (OSError, tarfile.TarError) as error:
            raise SetupError('Cannot extract ' + archive.name + ': ' + str(error)) from None
        return {'archive': archive.name, 'sha256': source['sha256']}, {}
    image = source['image']
    present = run(['image', 'exists', image])
    if present.returncode == 1:
        if env.get(PROFILE.env('MAINTENANCE')) != '1':
            raise SetupError('Pulling ' + image + ' requires exact ' + PROFILE.env('MAINTENANCE') +
                             '=1; host pulls are outside runtime filtering.')
        if run(['pull', image]).returncode != 0:
            raise SetupError('Cannot pull ' + image)
    elif present.returncode != 0:
        raise SetupError('Cannot inspect ' + image)
    inspected = run(['image', 'inspect', '--format', '{{.Id}}', image])
    if inspected.returncode != 0:
        raise SetupError('Cannot inspect ' + image)
    created = run(['create', '--network=none', '--pull=never', '--entrypoint', '/sandbox-toolchain-copy', image])
    container = created.stdout.strip()
    if created.returncode != 0 or not SHA256.fullmatch(container):
        raise SetupError('Cannot create a copy container for ' + image)
    try:
        with stream(['cp', container + ':' + source['path'], '-']) as output:
            try:
                with tarfile.open(fileobj=output, mode='r|*') as members:
                    extract(members, staging, 1)
            except tarfile.TarError as error:
                raise SetupError('Cannot extract ' + source['path'] + ' from ' + image + ': ' + str(error)) from None
    finally:
        run(['rm', '--force', container])
    return {'image': image, 'path': source['path']}, {'image_id': inspected.stdout.strip()}


# Verification

def runtime_image(env):
    image = env.get(PROFILE.env('IMAGE')) or PROFILE.image('agent', 'latest')
    present = run(['image', 'exists', image])
    if present.returncode != 0:
        raise SetupError('The runtime image ' + image + ' is missing; prepare it with --container-setup '
                         'or --container-build first.')
    inspected = run(['image', 'inspect', '--format', '{{.Id}}', image])
    return image, inspected.stdout.strip()


def check(library, name, root, value, toolchains, image):
    mounts = []
    for required in closure(value['requires'], toolchains):
        mounts += ['--volume', str(Path(library) / required) + ':' + MOUNT + '/' + required + ':ro,nosuid,nodev']
    mounts += ['--volume', str(root) + ':' + MOUNT + '/' + name + ':ro,nosuid,nodev']
    result = run(['run', '--rm', '--network=none', '--read-only', '--pull=never', '--userns=keep-id',
                  '--user', f'{os.getuid()}:{os.getgid()}', '--cap-drop=all', '--security-opt=no-new-privileges',
                  '--tmpfs', '/tmp:rw,nosuid,nodev,noexec,size=256m',
                  '--mount', 'type=tmpfs,destination=' + MOUNT + ',tmpfs-size=1m', *mounts,
                  '--entrypoint', '/bin/sh', image, '-c', '. ' + MOUNT + '/' + name + '/env.sh && exec "$@"', 'sh',
                  *value['check']], timeout=CHECK_TIMEOUT)
    if result.returncode != 0:
        output = (result.stdout + result.stderr).strip()[-4000:]
        raise SetupError(f'toolchain check failed for {name} (status {result.returncode}): ' + shlex.join(value['check']) +
                         ('\n' + output if output else ''))


def verified_record(image_id):
    return {'base': base_reference(INSTALLATION), 'date': time.strftime('%Y-%m-%d', time.gmtime()),
            'runtime_image': image_id}


# Library operations

def publish(library, name, staging):
    final = library / name
    old = None
    if final.exists():
        old = Path(tempfile.mkdtemp(prefix='.old-' + name + '-', dir=library))
        os.rmdir(old)
        os.rename(final, old)
    os.rename(staging, final)
    render(library)
    if old:
        shutil.rmtree(old)


def add(library, recipe_path, env):
    recipe = load_recipe(recipe_path)
    name = recipe['name']
    library = prepare_library(library, avoid=(INSTALLATION, *state_directories(env)))
    with locked(library):
        toolchains = installed(library)
        others = {key: item for key, item in toolchains.items() if key != name}
        for required in recipe['requires']:
            if required not in others:
                raise SetupError('required toolchain is missing: ' + required)
        closure(recipe['requires'], {**others, name: recipe})
        for key in others:
            try:
                closure([key], {**others, name: recipe})
            except SetupError as error:
                raise SetupError('toolchain requires form a cycle through ' + key + ': ' + str(error)) from None
        if recipe['default']:
            for required in closure(recipe['requires'], others):
                if not others[required]['default']:
                    raise SetupError('default toolchain ' + name + ' requires non-default ' + required +
                                     '; set default to false or make ' + required + ' a default toolchain')
        staging = Path(tempfile.mkdtemp(prefix='.staging-' + name + '-', dir=library))
        try:
            source, identity = extract_source(recipe, staging, env)
            provided = commands(staging, recipe['path'])
            if recipe['default']:
                for key, other in others.items():
                    if not other['default']:
                        continue
                    shared = sorted(set(provided) & set(other['commands']))
                    variables = sorted(set(recipe['env']) & set(other['env']))
                    if shared or variables:
                        raise SetupError('default toolchain ' + name + ' conflicts with default ' + key + ' on ' +
                                         ', '.join(shared + variables) + '; set default to false in one of them')
            image, image_id = runtime_image(env)
            (staging / 'env.sh').write_text(env_script(name, recipe))
            os.chmod(staging / 'env.sh', 0o644)
            check(library, name, staging, recipe, others, image)
            manifest = {**recipe, 'source': source, 'identity': identity, 'commands': provided,
                        'verified': verified_record(image_id)}
            write_atomic(staging / 'toolchain.json', json.dumps(manifest, indent=2, sort_keys=True) + '\n')
            os.chmod(staging, 0o755)
            publish(library, name, staging)
        finally:
            if staging.exists():
                shutil.rmtree(staging)
    return library / name


def remove(library, name, env=None):
    library = prepare_library(library, avoid=(INSTALLATION, *state_directories(env or os.environ)))
    with locked(library):
        toolchains = installed(library)
        if name not in toolchains:
            raise SetupError('toolchain is not installed: ' + name)
        dependents = sorted(key for key, item in toolchains.items() if name in item['requires'])
        if dependents:
            raise SetupError('toolchain ' + name + ' is required by ' + ', '.join(dependents) + '; remove them first')
        old = Path(tempfile.mkdtemp(prefix='.old-' + name + '-', dir=library))
        os.rmdir(old)
        os.rename(library / name, old)
        render(library)
        shutil.rmtree(old)


def verify(library, name, env):
    library = prepare_library(library, avoid=(INSTALLATION, *state_directories(env)))
    with locked(library):
        toolchains = installed(library)
        if name and name not in toolchains:
            raise SetupError('toolchain is not installed: ' + name)
        image, image_id = runtime_image(env)
        for key in ([name] if name else sorted(toolchains)):
            value = toolchains[key]
            others = {other: item for other, item in toolchains.items() if other != key}
            check(library, key, library / key, value, others, image)
            value['verified'] = verified_record(image_id)
            write_atomic(library / key / 'toolchain.json', json.dumps(value, indent=2, sort_keys=True) + '\n')
        render(library)


def entry(name, value):
    return {'name': name, 'version': value['version'], 'default': value['default'], 'commands': value['commands'],
            'path': container_paths(name, value),
            'env': {variable: container_value(name, item) for variable, item in sorted(value['env'].items())},
            'requires': value['requires'], 'notes': value['notes'], 'check': value['check'],
            'source': value['source'], 'verified': {'base': value['verified']['base'],
                                                    'date': value['verified']['date']}}


GUIDE = """# Toolchains

The toolchains under /toolchains are provided by the operator and are read-only.
Do not install toolchains or system packages yourself. If a needed toolchain is
missing, ask the operator to add it. Package downloads (for example Maven, npm,
pip, Cargo or Go modules) may be blocked by the network policy.

To use a toolchain in one command, source its env.sh first:

    . /toolchains/<name>/env.sh && <command>

Default toolchains are also on PATH, after the system tools, in sessions started
after they were added. Toolchains added during a session are available only
through their env.sh or full paths until the next session.
"""


def render(library):
    library = Path(library)
    entries = [entry(name, value) for name, value in installed(library).items()]
    lines = [GUIDE]
    if not entries:
        lines.append('No toolchains are installed.\n')
    for item in entries:
        env_text = ', '.join(variable + '=' + value for variable, value in item['env'].items()) or 'none'
        lines.append('## ' + item['name'] + ' ' + item['version'] + '\n')
        lines.append('- Use: `. /toolchains/' + item['name'] + '/env.sh && ' + shlex.join(item['check']) + '`')
        lines.append('- Commands: ' + (', '.join(item['commands']) or 'none'))
        lines.append('- Environment: ' + env_text)
        lines.append('- Requires: ' + (', '.join(item['requires']) or 'none'))
        lines.append('- Default on PATH in new sessions: ' + ('yes' if item['default'] else 'no'))
        for note in item['notes']:
            lines.append('- Note: ' + note)
        lines.append('- Verified on ' + item['verified']['base'] + ' (' + item['verified']['date'] + ')\n')
    write_atomic(library / 'toolchains.md', '\n'.join(lines))
    write_atomic(library / 'index.json', json.dumps({'schema': SCHEMA, 'toolchains': entries}, indent=2) + '\n')


def launch_env(library, base):
    """Default toolchains verified on base: PATH entries first, then variables."""
    index = json.loads((Path(library) / 'index.json').read_text())
    if index.get('schema') != SCHEMA or not isinstance(index.get('toolchains'), list):
        raise SetupError('Invalid toolchain index; run --container-toolchain verify.')
    by_name = {item['name']: item for item in index['toolchains']}
    selected, warnings = [], []
    for item in index['toolchains']:
        if not item['default']:
            continue
        if item['verified']['base'] != base:
            warnings.append('toolchain ' + item['name'] + ' was verified on another base image; it gets no default '
                            'environment until --container-toolchain verify ' + item['name'] + ' succeeds')
            continue
        selected.append(item['name'])
    ordered = [name for name in closure(selected, by_name) if name in selected]
    lines = []
    for name in ordered:
        lines += [('path', path) for path in by_name[name]['path']]
    for name in ordered:
        for variable, value in by_name[name]['env'].items():
            if not ENV_NAME.fullmatch(variable) or protected(variable) or not control_free(value) or '\t' in value:
                raise SetupError('Invalid toolchain environment in the index: ' + variable)
            lines.append(('env', variable, value))
    return lines, warnings


def size(path):
    return sum(item.lstat().st_size for item in Path(path).rglob('*'))


def main(argv):
    env = os.environ
    if not argv:
        raise SetupError('usage: --container-toolchain add <recipe.json> | list | remove <name> | verify [<name>]')
    operation, args = argv[0], argv[1:]
    if operation == 'launch-env':
        library, avoid = None, []
        while args:
            if len(args) < 2 or args[0] not in ('--library', '--avoid'):
                raise SetupError('launch-env takes --library PATH and --avoid PATH options')
            if args[0] == '--library':
                library = Path(args[1])
            else:
                avoid.append(Path(args[1]))
            args = args[2:]
        library = prepare_library(library or library_path(env), avoid=(INSTALLATION, *avoid))
        if not (library / 'index.json').exists():
            with locked(library):
                if not (library / 'index.json').exists():
                    render(library)
        lines, warnings = launch_env(library, base_reference(INSTALLATION))
        for warning in warnings:
            print(PREFIX + warning, file=sys.stderr)
        print('library\t' + str(library))
        for line in lines:
            print('\t'.join(line))
        return 0
    library = library_path(env)
    if operation == 'add' and len(args) == 1:
        path = add(library, args[0], env)
        print('Added toolchain ' + path.name + ' to ' + str(library))
    elif operation == 'remove' and len(args) == 1:
        remove(library, args[0], env)
        print('Removed toolchain ' + args[0])
    elif operation == 'verify' and len(args) <= 1:
        verify(library, args[0] if args else None, env)
        print('Verified ' + (args[0] if args else 'all toolchains'))
    elif operation == 'list' and not args:
        library = prepare_library(library, avoid=(INSTALLATION, *state_directories(env)))
        toolchains = installed(library)
        print('Toolchain library: ' + str(library))
        if not toolchains:
            print('No toolchains are installed.')
        for name, value in toolchains.items():
            print(f"{name}\t{value['version']}\tdefault={'yes' if value['default'] else 'no'}\t"
                  f"{size(library / name) // (1 << 20)} MiB\trequires={','.join(value['requires']) or '-'}\t"
                  f"verified={value['verified']['base']} {value['verified']['date']}")
    else:
        raise SetupError('usage: --container-toolchain add <recipe.json> | list | remove <name> | verify [<name>]')
    return 0


if __name__ == '__main__':
    try:
        sys.exit(main(sys.argv[1:]))
    except SetupError as error:
        print(PREFIX + str(error), file=sys.stderr)
        sys.exit(1)

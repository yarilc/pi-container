"""Strict loader for the agent profile, the single source of agent-specific values.

Shared network and setup code contains no agent identifiers. Every wrapper,
variable, image, label, installation and native-application name is declared
in ``agent/profile.json`` and derived here. The profile is data only.
"""
import json
from pathlib import Path
import re
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from policy import PolicyError, hostname, trusted_path, unique_object

ROOT = Path(__file__).resolve().parents[1]
PROFILE = 'agent/profile.json'
POLICY = 'agent/policies/default.json'
SCHEMA = 1
# Variables derived from the prefix. Keep this list closed and explicit.
SUFFIXES = (
    'NETWORK', 'NETWORK_PROFILE', 'NETWORK_POLICY', 'NETWORK_RUNTIME_DIR', 'EGRESS_IMAGE',
    'IMAGE', 'STATE_DIR', 'PODMAN', 'PODMAN_SOCKET', 'TRUST_HOST_CA', 'CA_BUNDLE',
    'MAINTENANCE', 'QUALIFICATION_INPUT', 'MEMORY_LIMIT', 'CPU_LIMIT', 'PIDS_LIMIT', 'RUN_TIMEOUT',
    'TOOLCHAINS', 'TOOLCHAINS_DIR',
)
LABELS = ('session', 'egress', 'qualification')
NAME = re.compile(r'[a-z][a-z0-9]*(?:-[a-z0-9]+)*')
ENV = re.compile(r'[A-Z][A-Z0-9]*(?:_[A-Z0-9]+)*')
IMAGE = re.compile(r'localhost/[a-z0-9][a-z0-9.-]*[a-z0-9]')
RELATIVE = re.compile(r'\.?[a-z0-9][a-z0-9._-]*(?:/[a-z0-9][a-z0-9._-]*)*')
ARGUMENT = re.compile(r'[A-Za-z0-9][A-Za-z0-9._=-]{0,63}|--?[a-z][a-z0-9-]{0,62}')
TEXT = re.compile(r'[A-Za-z0-9 ,.()/-]{1,120}')


class ProfileError(PolicyError):
    pass


def fail(message):
    raise ProfileError('invalid agent profile: ' + message)


def fields(value, required, optional=(), where='profile'):
    if type(value) is not dict:
        fail(where + ' must be an object')
    unknown, missing = set(value) - set(required) - set(optional), set(required) - set(value)
    if unknown or missing:
        fail(where + ' has ' + ('unknown' if unknown else 'missing') + ' fields: '
             + ', '.join(sorted(unknown or missing)))


def string(value, pattern, where):
    if not isinstance(value, str) or not pattern.fullmatch(value):
        fail(where)
    return value


def strings(value, pattern, where, *, minimum=1, maximum=16):
    if not isinstance(value, list) or not minimum <= len(value) <= maximum or len(set(value)) != len(value):
        fail(where)
    return [string(item, pattern, where) for item in value]


class Profile:
    """Validated, read-only view of the profile and the names derived from it."""

    def __init__(self, value):
        self.value = value
        self.name = value['name']
        self.display_name = value['display_name']
        self.wrapper = value['wrapper']
        self.env_prefix = value['env_prefix']
        self.label_namespace = value['label_namespace']
        self.identifiers = tuple(value['identifiers'])
        self.images = dict(value['images'])
        self.state_name = value['install']['state_name']
        # Agent-specific installation inputs read by the wrapper (for example a version file).
        self.install_files = tuple(value['install'].get('files', ()))
        self.runtime_build = value['install'].get('runtime_build', 'recipe')
        native = value['native']
        self.home = native['home']
        self.command = native['command']
        self.config_dir_env = native['config_dir_env']
        self.approval_bypass_env = native['approval_bypass_env']
        self.config_home = native['config_home']
        self.shared_dirs = tuple(native['shared_dirs'])
        # Wrappers that refuse non-private shared directories declare it here.
        self.private_shared_dirs = native.get('private_shared_dirs', False)
        self.auth = {key: dict(item) for key, item in value['auth'].items()}

    def env(self, suffix):
        if suffix not in SUFFIXES:
            raise KeyError(suffix)
        return self.env_prefix + '_' + suffix

    def label(self, kind):
        if kind not in LABELS:
            raise KeyError(kind)
        return self.label_namespace + '.' + kind

    def image(self, kind, tag):
        return self.images[kind] + ':' + tag

    @property
    def credential_envs(self):
        return tuple(item['credential_env'] for item in self.auth.values() if 'credential_env' in item)

    @property
    def message_prefix(self):
        return self.name + ': '

    def policy_profile(self, method):
        return self.auth[method]['policy_profile']

    def policy_rules(self):
        """Agent-specific policy checks applied by trusted host-side code."""
        return {
            'methods': {method: frozenset(item['hosts']) for method, item in self.auth.items()},
            'base_profiles': {item['policy_profile']: (method, frozenset(item['hosts']))
                              for method, item in self.auth.items()},
        }


def validate(value):
    fields(value, ('schema', 'name', 'display_name', 'wrapper', 'env_prefix', 'label_namespace',
                   'identifiers', 'images', 'install', 'native', 'auth'))
    if type(value['schema']) is not int or value['schema'] != SCHEMA:
        fail('unsupported schema')
    name = string(value['name'], NAME, 'name')
    if len(name) > 40:
        fail('name')
    string(value['display_name'], TEXT, 'display_name')
    if value['wrapper'] != name + '.sh':
        fail('wrapper must be <name>.sh')
    string(value['env_prefix'], ENV, 'env_prefix')
    if value['label_namespace'] != 'io.' + name:
        fail('label_namespace must be io.<name>')
    identifiers = strings(value['identifiers'], re.compile(r'[a-z][a-z0-9-]{2,31}'), 'identifiers', maximum=8)
    fields(value['images'], ('agent', 'proxy', 'toolchain'), where='images')
    images = [string(item, IMAGE, 'images.' + key) for key, item in value['images'].items()]
    if len(set(images)) != len(images):
        fail('images must be distinct')
    fields(value['install'], ('state_name',), ('files', 'runtime_build'), where='install')
    if value['install'].get('runtime_build', 'recipe') not in ('recipe', 'wrapper'):
        fail('install.runtime_build must be recipe or wrapper')
    string(value['install']['state_name'], NAME, 'install.state_name')
    files = strings(value['install'].get('files', []), RELATIVE, 'install.files', minimum=0, maximum=8)
    if len(set(files)) != len(files) or any(
            '..' in path.split('/') or path.split('/')[0] in ('network', 'setup', 'agent')
            or path in (value['wrapper'], 'Containerfile', '.containerignore') for path in files):
        fail('install.files must be distinct agent files outside network/, setup/ and agent/')
    native = value['native']
    fields(native, ('home', 'command', 'config_dir_env', 'approval_bypass_env', 'config_home', 'shared_dirs'),
           ('private_shared_dirs',), where='native')
    if type(native.get('private_shared_dirs', False)) is not bool:
        fail('native.private_shared_dirs must be a boolean')
    string(native['home'], re.compile(r'/[a-z0-9][a-z0-9._-]*'), 'native.home')
    string(native['command'], NAME, 'native.command')
    for key in ('config_dir_env', 'approval_bypass_env'):
        string(native[key], ENV, 'native.' + key)
    for path in (native['config_home'], *strings(native['shared_dirs'], RELATIVE, 'native.shared_dirs', minimum=0)):
        string(path, RELATIVE, 'native paths')
        if '..' in path.split('/'):
            fail('native paths must stay inside the home')
    if native['config_home'] in native['shared_dirs']:
        fail('native.config_home is private and cannot also be shared')
    auth = value['auth']
    if type(auth) is not dict or not 1 <= len(auth) <= 8:
        fail('auth')
    policies = set()
    for method, item in auth.items():
        if not NAME.fullmatch(method) or method in ('none', 'custom'):
            fail('auth method name')
        fields(item, ('description', 'policy_profile', 'hosts'), ('login_args', 'credential_env'),
               where='auth.' + method)
        string(item['description'], TEXT, 'auth.' + method + '.description')
        string(item['policy_profile'], re.compile(r'[a-z][a-z0-9-]{0,63}'), 'auth.' + method + '.policy_profile')
        if item['policy_profile'] in policies:
            fail('policy profiles must be distinct')
        policies.add(item['policy_profile'])
        if not isinstance(item['hosts'], list) or not 1 <= len(item['hosts']) <= 32:
            fail('auth.' + method + '.hosts')
        try:
            hosts = [hostname(host) for host in item['hosts']]
        except PolicyError:
            fail('auth.' + method + '.hosts')
        if hosts != item['hosts'] or len(set(hosts)) != len(hosts):
            fail('auth.' + method + '.hosts must be unique normalized hostnames')
        if 'login_args' in item:
            # An empty list means sign-in happens inside the interactive agent.
            strings(item['login_args'], ARGUMENT, 'auth.' + method + '.login_args', minimum=0, maximum=8)
        if 'credential_env' in item:
            string(item['credential_env'], ENV, 'auth.' + method + '.credential_env')
    derived = {value['env_prefix'] + '_' + suffix for suffix in SUFFIXES}
    native_env = {native['config_dir_env'], native['approval_bypass_env'],
                  *(item['credential_env'] for item in auth.values() if 'credential_env' in item)}
    if derived & native_env or len(native_env) != 2 + sum('credential_env' in item for item in auth.values()):
        fail('environment names must be distinct')
    lowered = name + ' ' + value['env_prefix'].lower() + ' ' + ' '.join(images)
    if not any(identifier in lowered for identifier in identifiers):
        fail('identifiers must cover the agent names')
    return Profile(value)


def load(path=None, *, writable=None):
    """Load and validate a profile; with ``writable`` also require a protected path."""
    path = Path(path) if path is not None else ROOT / PROFILE
    if writable is not None:
        path = trusted_path(path, writable)
    try:
        data = path.read_bytes()
    except OSError:
        fail('missing or unreadable ' + PROFILE)
    if len(data) > 16384:
        fail('exceeds 16 KiB')
    try:
        value = json.loads(data, object_pairs_hook=unique_object)
    except PolicyError:
        fail('duplicate JSON key')
    except (ValueError, UnicodeError):
        fail('malformed JSON')
    return validate(value)


def message_prefix(default='sandbox-egress: '):
    """Best-effort diagnostic prefix; never raises."""
    try:
        return load().message_prefix
    except (PolicyError, OSError, ValueError):
        return default


if __name__ == '__main__':
    # Fixed queries for shell callers; no arbitrary attribute access.
    try:
        profile = load(writable=[] if sys.argv[1:2] == ['--protected'] else None)
        query = sys.argv[2:] if sys.argv[1:2] == ['--protected'] else sys.argv[1:]
        if query[:1] == ['env'] and len(query) == 2:
            print(profile.env(query[1]))
        elif query[:1] == ['image'] and len(query) == 3:
            print(profile.image(query[1], query[2]))
        elif query[:1] == ['label'] and len(query) == 2:
            print(profile.label(query[1]))
        else:
            raise ProfileError('unsupported profile query')
    except (PolicyError, KeyError, OSError) as error:
        print('sandbox-egress: ' + (str(error) if isinstance(error, PolicyError) else 'unsupported profile query'),
              file=sys.stderr)
        sys.exit(1)

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
    'TOOLCHAINS', 'TOOLCHAINS_DIR', 'ENV_VARS', 'READONLY_STATE',
)
LABELS = ('session', 'egress', 'qualification')
# The one diagnostic for provider mode with a profile that declares no method.
NO_METHODS = 'provider mode is unavailable: the agent profile declares no authentication method'
# Session variables that a toolchain must never replace, the same for every
# wrapper: identity, shell startup, the agent's own runtimes, proxies, CA trust
# and the (absent) session bus, which --unsetenv cannot remove once --env sets
# it. XDG base-directory variables can place a wrapper's state (a wrapper may
# set them). A profile's protected_env may not repeat them.
NEUTRAL_ENV = frozenset((
    'HOME', 'PATH', 'USER', 'LOGNAME', 'SHELL', 'TERM', 'EDITOR', 'VISUAL', 'PWD', 'OLDPWD', 'TMPDIR',
    'BASH_ENV', 'ENV', 'IFS', 'CONTAINER_HOST', 'CONTAINER_CONNECTION', 'NODE_OPTIONS', 'NODE_PATH',
    'PYTHONPATH', 'PYTHONHOME', 'PYTHONSTARTUP', 'HTTP_PROXY', 'HTTPS_PROXY', 'ALL_PROXY', 'NO_PROXY',
    'SSL_CERT_FILE', 'SSL_CERT_DIR', 'REQUESTS_CA_BUNDLE', 'CURL_CA_BUNDLE', 'NODE_EXTRA_CA_CERTS',
    'DBUS_SESSION_BUS_ADDRESS'))
NEUTRAL_ENV_PREFIXES = ('LD_', 'XDG_', 'SANDBOX_')
NAME = re.compile(r'[a-z][a-z0-9]*(?:-[a-z0-9]+)*')
ENV = re.compile(r'[A-Z][A-Z0-9]*(?:_[A-Z0-9]+)*')
# An agent variable, or a prefix when it ends in '_'.
AGENT_ENV = re.compile(r'[A-Z][A-Z0-9]*(?:_[A-Z0-9]+)*_?')
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
        native = value['native']
        self.home = native['home']
        self.command = native['command']
        # Absolute in-container path of the application for restricted agent sessions.
        self.exec = native.get('exec', '/usr/local/bin/' + self.command)
        # Whether /tmp and the ephemeral home must allow execution (native runtime parts).
        self.exec_tmp = native.get('exec_tmp', False)
        self.config_dir_env = native['config_dir_env']
        # Absent when the application has no approval system (for example a plain shell).
        self.approval_bypass_env = native.get('approval_bypass_env')
        self.config_home = native['config_home']
        self.shared_dirs = tuple(native['shared_dirs'])
        # Wrappers that refuse non-private shared directories declare it here.
        self.private_shared_dirs = native.get('private_shared_dirs', False)
        # Variables (and '_'-terminated prefixes) the agent itself reads; toolchains cannot set them.
        self.protected_env = tuple(native.get('protected_env', ()))
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
    def default_mode(self):
        """Network mode of a launch without one: provider for an agent with methods."""
        return 'provider' if self.auth else 'offline'

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
    fields(value['install'], ('state_name',), ('files',), where='install')
    string(value['install']['state_name'], NAME, 'install.state_name')
    files = strings(value['install'].get('files', []), RELATIVE, 'install.files', minimum=0, maximum=8)
    if len(set(files)) != len(files) or any(
            '..' in path.split('/') or path.split('/')[0] in ('network', 'setup', 'agent')
            or path in (value['wrapper'], 'Containerfile', '.containerignore') for path in files):
        fail('install.files must be distinct agent files outside network/, setup/ and agent/')
    native = value['native']
    fields(native, ('home', 'command', 'config_dir_env', 'config_home', 'shared_dirs'),
           ('approval_bypass_env', 'private_shared_dirs', 'protected_env', 'exec', 'exec_tmp'), where='native')
    for key in ('private_shared_dirs', 'exec_tmp'):
        if type(native.get(key, False)) is not bool:
            fail('native.' + key + ' must be a boolean')
    if 'exec' in native:
        string(native['exec'], re.compile(r'(/[A-Za-z0-9._-]+)+'), 'native.exec')
        if '..' in native['exec'].split('/'):
            fail('native.exec must be an absolute path without ..')
    for entry in strings(native.get('protected_env', []), AGENT_ENV, 'native.protected_env', minimum=0, maximum=32):
        if entry.endswith('_') and len(entry) < 3:
            fail('native.protected_env prefixes need at least three characters')
        if entry in NEUTRAL_ENV or entry.startswith(NEUTRAL_ENV_PREFIXES):
            fail('native.protected_env repeats a neutral protected variable: ' + entry)
    string(native['home'], re.compile(r'/[a-z0-9][a-z0-9._-]*'), 'native.home')
    string(native['command'], NAME, 'native.command')
    for key in ('config_dir_env', 'approval_bypass_env'):
        if key in native:
            string(native[key], ENV, 'native.' + key)
    for path in (native['config_home'], *strings(native['shared_dirs'], RELATIVE, 'native.shared_dirs', minimum=0)):
        string(path, RELATIVE, 'native paths')
        if '..' in path.split('/'):
            fail('native paths must stay inside the home')
    if native['config_home'] in native['shared_dirs']:
        fail('native.config_home is private and cannot also be shared')
    auth = value['auth']
    # No method means no provider mode: offline and unrestricted only.
    if type(auth) is not dict or len(auth) > 8:
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
    named = [native['config_dir_env'], *([native['approval_bypass_env']] if 'approval_bypass_env' in native else []),
             *(item['credential_env'] for item in auth.values() if 'credential_env' in item)]
    native_env = set(named)
    if derived & native_env or len(native_env) != len(named):
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

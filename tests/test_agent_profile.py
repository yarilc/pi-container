"""Agent profile loader: closed schema, derived names and protected paths."""
import copy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from sandbox_profile import AGENT_FIXTURE, NETWORK, SHELL_FIXTURE, NO_METHODS, PROFILE, REAL_POLICY_FILE, REAL_ROOT, ROOT, test_setting
import agent_profile
import policy


def protected_parent():
    native = Path(test_setting('TEST_STATE_ROOT', str(Path.home())))
    if not native.is_dir() or any(p.stat().st_mode & 0o022 for p in (native, *native.parents)):
        return None
    return native


class ProfileSchemaTests(unittest.TestCase):
    def setUp(self):
        self.value = json.loads((ROOT / agent_profile.PROFILE).read_text())

    def test_repository_profile_and_derived_names(self):
        profile = agent_profile.load()
        self.assertEqual(profile.wrapper, profile.name + '.sh')
        self.assertEqual(profile.env('NETWORK'), profile.env_prefix + '_NETWORK')
        self.assertEqual(profile.label('egress'), profile.label_namespace + '.egress')
        self.assertTrue(profile.image('agent', 'latest').startswith('localhost/'))
        self.assertEqual(profile.message_prefix, profile.name + ': ')
        rules = profile.policy_rules()
        self.assertEqual(set(rules['methods']), set(profile.auth))
        for method, item in profile.auth.items():
            self.assertEqual(rules['base_profiles'][item['policy_profile']], (method, frozenset(item['hosts'])))
        with self.assertRaises(KeyError):
            profile.env('ARBITRARY')
        with self.assertRaises(KeyError):
            profile.label('arbitrary')

    def test_invalid_profiles_fail_closed(self):
        method = next(iter(self.value['auth']))
        for mutate in (
            lambda v: v.update(unknown=True),
            lambda v: v.pop('images'),
            lambda v: v.update(schema=2),
            lambda v: v.update(schema=True),
            lambda v: v.update(name='Bad Name'),
            lambda v: v.update(wrapper='other.sh'),
            lambda v: v.update(env_prefix='lower_case'),
            lambda v: v.update(label_namespace='io.other'),
            lambda v: v.update(identifiers=[]),
            lambda v: v.update(identifiers=['unrelated']),
            lambda v: v['images'].update(agent='docker.io/library/other'),
            lambda v: v['images'].update(proxy=v['images']['agent']),
            lambda v: v['images'].update(extra='localhost/extra'),
            lambda v: v['native'].update(home='relative'),
            lambda v: v['native'].update(command='/usr/bin/escape'),
            lambda v: v['native'].update(config_home='../escape'),
            lambda v: v['native'].update(shared_dirs=['/absolute']),
            lambda v: v['native'].update(shared_dirs=[v['native']['config_home']]),
            lambda v: v['native'].update(config_dir_env=v['env_prefix'] + '_NETWORK'),
            lambda v: v['native'].update(approval_bypass_env=v['native']['config_dir_env']),
            lambda v: v['auth'].update(none=copy.deepcopy(v['auth'][method])),
            lambda v: v['auth'].update(custom=copy.deepcopy(v['auth'][method])),
            lambda v: v['auth'][method].update(unknown=True),
            lambda v: v['auth'][method].update(hosts=[]),
            lambda v: v['auth'][method].update(hosts=['127.0.0.1']),
            lambda v: v['auth'][method].update(hosts=['UPPER.example.com']),
            lambda v: v['auth'][method].update(hosts=['a.example.com', 'a.example.com']),
            lambda v: v['auth'][method].update(login_args=['$(touch /tmp/x)']),
            lambda v: v['auth'][method].update(credential_env='lower'),
            lambda v: v['auth'].update(duplicate=dict(v['auth'][method])),
            lambda v: v['install'].update(files='.version'),
            lambda v: v['install'].update(files=['../escape']),
            lambda v: v['install'].update(runtime_build='podman'),
            lambda v: v['install'].update(runtime_build=['wrapper']),
            lambda v: v['install'].update(runtime_build=''),
            lambda v: v['install'].update(files=['/absolute']),
            lambda v: v['install'].update(files=['network/relay.py']),
            lambda v: v['install'].update(files=['agent/profile.json']),
            lambda v: v['install'].update(files=['Containerfile']),
            lambda v: v['install'].update(files=['.version', '.version']),
            lambda v: v['install'].update(unknown=True),
            lambda v: v['native'].update(private_shared_dirs=1),
            lambda v: v['native'].update(private_shared_dirs='true'),
            lambda v: v['native'].update(private_shared_dirs=None),
            lambda v: v['native'].update(protected_env='AGENT_'),
            lambda v: v['native'].update(protected_env=['agent_flag']),
            lambda v: v['native'].update(protected_env=['AGENT FLAG']),
            lambda v: v['native'].update(protected_env=['AGENT_FLAG', 'AGENT_FLAG']),
            lambda v: v['native'].update(protected_env=['A_']),
            lambda v: v['native'].update(protected_env=['PATH']),
            lambda v: v['native'].update(protected_env=['XDG_']),
            lambda v: v['native'].update(protected_env=['SANDBOX_AGENT']),
            lambda v: v['native'].update(protected_env=[1]),
            lambda v: v['native'].update(unknown=True),
        ):
            value = copy.deepcopy(self.value)
            mutate(value)
            with self.subTest(value=value), self.assertRaises(agent_profile.ProfileError):
                agent_profile.validate(value)

    def test_optional_install_files(self):
        self.assertEqual(agent_profile.validate(self.value).install_files,
                         tuple(self.value['install'].get('files', ())))
        value = copy.deepcopy(self.value)
        value['install']['files'] = ['.version', 'docs/agent-version']
        self.assertEqual(agent_profile.validate(value).install_files, ('.version', 'docs/agent-version'))

    def test_optional_private_shared_dirs(self):
        self.assertIs(agent_profile.validate(self.value).private_shared_dirs,
                      self.value['native'].get('private_shared_dirs', False))
        value = copy.deepcopy(self.value)
        value['native'].pop('private_shared_dirs', None)
        self.assertIs(agent_profile.validate(value).private_shared_dirs, False)
        for flag in (True, False):
            value['native']['private_shared_dirs'] = flag
            self.assertIs(agent_profile.validate(value).private_shared_dirs, flag)

    def test_optional_protected_env(self):
        self.assertEqual(agent_profile.validate(self.value).protected_env,
                         tuple(self.value['native'].get('protected_env', ())))
        value = copy.deepcopy(self.value)
        value['native'].pop('protected_env', None)
        self.assertEqual(agent_profile.validate(value).protected_env, ())
        value['native']['protected_env'] = ['AGENT_CODE_', 'DISABLE_TELEMETRY']
        self.assertEqual(agent_profile.validate(value).protected_env, ('AGENT_CODE_', 'DISABLE_TELEMETRY'))

    def test_optional_runtime_build(self):
        self.assertEqual(agent_profile.validate(self.value).runtime_build,
                         self.value['install'].get('runtime_build', 'recipe'))
        for mode in ('recipe', 'wrapper'):
            value = copy.deepcopy(self.value)
            value['install']['runtime_build'] = mode
            self.assertEqual(agent_profile.validate(value).runtime_build, mode)

    def test_login_arguments_may_be_empty(self):
        # An empty list selects sign-in inside the interactive agent.
        value = copy.deepcopy(self.value)
        method = next(iter(value['auth']))
        value['auth'][method]['login_args'] = []
        self.assertEqual(agent_profile.validate(value).auth[method]['login_args'], [])
        for arguments in ([str(index) for index in range(9)], ['login', 'login'], 'login'):
            value['auth'][method]['login_args'] = arguments
            with self.subTest(arguments=arguments), self.assertRaises(agent_profile.ProfileError):
                agent_profile.validate(value)

    def test_malformed_duplicate_oversized_and_missing_files(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'profile.json'
            for data in (b'{', b'{"schema":1,"schema":1}', b'[]', b'\xff', b' ' * 16385):
                path.write_bytes(data)
                with self.subTest(data=data[:20]), self.assertRaises(agent_profile.ProfileError):
                    agent_profile.load(path)
            with self.assertRaises(agent_profile.ProfileError):
                agent_profile.load(Path(directory) / 'missing.json')

    def test_profile_error_is_a_policy_error(self):
        self.assertTrue(issubclass(agent_profile.ProfileError, policy.PolicyError))

    def test_unprotected_path_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'profile.json'
            path.write_text(json.dumps(self.value))
            path.chmod(0o666)
            with self.assertRaises(policy.PolicyError):
                agent_profile.load(path, writable=[])

    def test_protected_path_and_writable_overlap(self):
        native = protected_parent()
        if native is None:
            self.skipTest('native protected ancestors required; set SANDBOX_TEST_STATE_ROOT')
        with tempfile.TemporaryDirectory(prefix='profile-test-', dir=native) as directory:
            root = Path(directory)
            path = root / 'profile.json'
            path.write_text(json.dumps(self.value))
            path.chmod(0o600)
            self.assertEqual(agent_profile.load(path, writable=[]).name, PROFILE.name)
            with self.assertRaises(policy.PolicyError):
                agent_profile.load(path, writable=[root])
            alias = root / 'workspace'
            alias.mkdir()
            (alias / 'profile.json').symlink_to(path)
            with self.assertRaises(policy.PolicyError):
                agent_profile.load(alias / 'profile.json', writable=[alias])

    def test_current_directory_decoy_is_ignored(self):
        with tempfile.TemporaryDirectory() as directory:
            decoy = Path(directory)
            (decoy / 'agent').mkdir()
            value = json.loads((ROOT / agent_profile.PROFILE).read_text()) | {'env_prefix': 'DECOY_CONTAINER'}
            (decoy / 'agent/profile.json').write_text(json.dumps(value))
            (decoy / 'policy.py').write_text('raise SystemExit("decoy module executed")\n')
            result = subprocess.run([sys.executable, '-I', str(NETWORK / 'agent_profile.py'), 'env', 'NETWORK'],
                                    cwd=decoy, capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(result.stdout.strip(), PROFILE.env('NETWORK'))

    def test_fixed_shell_queries(self):
        script = str(NETWORK / 'agent_profile.py')
        run = lambda *args: subprocess.run([sys.executable, '-I', script, *args], capture_output=True, text=True)
        self.assertEqual(run('env', 'MAINTENANCE').stdout.strip(), PROFILE.env('MAINTENANCE'))
        self.assertEqual(run('image', 'toolchain', 'development').stdout.strip(),
                         PROFILE.image('toolchain', 'development'))
        self.assertEqual(run('label', 'session').stdout.strip(), PROFILE.label('session'))
        for args in (('env', 'ARBITRARY'), ('value',), ('image', 'agent'), ()):
            result = run(*args)
            self.assertNotEqual(result.returncode, 0, args)
            self.assertEqual(result.stdout, '')


def missing_base_profiles(profile, value):
    """Methods whose exact base policy profile is absent or differs from the profile's hosts."""
    missing = []
    for method, item in profile.auth.items():
        selected = value['profiles'].get(item['policy_profile'])
        if (selected is None or selected['authentication'] != method
                or {(d['host'], d['port']) for d in selected['destinations']} != {(h, 443) for h in item['hosts']}):
            missing.append(method)
    return missing


class RealProfileTests(unittest.TestCase):
    """The checkout's own profile and policy; every other test uses the fixture."""
    def setUp(self):
        self.profile = agent_profile.load(REAL_ROOT / agent_profile.PROFILE)
        self.policy = json.loads(REAL_POLICY_FILE.read_text())

    def test_schema_identifiers_and_distinct_names(self):
        # load() validates the schema, the identifier coverage and the distinct names.
        self.assertEqual(self.profile.wrapper, self.profile.name + '.sh')
        self.assertTrue((REAL_ROOT / self.profile.wrapper).is_file())
        policy.validate(copy.deepcopy(self.policy), self.profile.policy_rules())

    def test_every_method_has_its_exact_base_profile(self):
        if not self.profile.auth:
            self.assertEqual(self.policy['profiles'], {})
            self.skipTest(NO_METHODS)
        self.assertEqual(missing_base_profiles(self.profile, self.policy), [])

    def test_missing_base_profile_is_detected(self):
        if not self.profile.auth:
            self.skipTest(NO_METHODS)
        method, item = next(iter(self.profile.auth.items()))
        value = copy.deepcopy(self.policy)
        value['profiles'].pop(item['policy_profile'])
        self.assertEqual(missing_base_profiles(self.profile, value), [method])


class ProfileWithoutMethodsTests(unittest.TestCase):
    """A profile may declare no authentication method and no approval bypass."""
    def setUp(self):
        self.value = json.loads((SHELL_FIXTURE / 'profile.json').read_text())
        self.policy = json.loads((SHELL_FIXTURE / 'policies/default.json').read_text())

    def test_profile_and_empty_policy_load(self):
        profile = agent_profile.validate(copy.deepcopy(self.value))
        self.assertEqual(profile.auth, {})
        self.assertIsNone(profile.approval_bypass_env)
        self.assertEqual(profile.credential_envs, ())
        self.assertEqual(profile.policy_rules(), {'methods': {}, 'base_profiles': {}})
        policy.validate(copy.deepcopy(self.policy), profile.policy_rules())

    def test_empty_policy_is_refused_when_methods_exist(self):
        value = copy.deepcopy(self.policy)
        with self.assertRaises(policy.PolicyError):
            policy.validate(value, PROFILE.policy_rules())
        with self.assertRaises(policy.PolicyError):
            policy.validate(copy.deepcopy(self.policy))

    def test_approval_bypass_name_is_still_validated(self):
        for bad in ('lower', self.value['native']['config_dir_env'], self.value['env_prefix'] + '_NETWORK'):
            value = copy.deepcopy(self.value)
            value['native']['approval_bypass_env'] = bad
            with self.subTest(bad=bad), self.assertRaises(agent_profile.ProfileError):
                agent_profile.validate(value)


class FixtureProfileTests(unittest.TestCase):
    def test_fixture_profile_and_policy_are_valid(self):
        self.assertEqual(PROFILE.value, json.loads((AGENT_FIXTURE / 'profile.json').read_text()))
        self.assertGreaterEqual(len(PROFILE.auth), 2)
        self.assertTrue(PROFILE.approval_bypass_env)
        self.assertTrue(any(entry.endswith('_') for entry in PROFILE.protected_env))
        value = json.loads((ROOT / agent_profile.POLICY).read_text())
        policy.validate(value, PROFILE.policy_rules())
        hosts = {host for item in PROFILE.auth.values() for host in item['hosts']}
        self.assertTrue(all(host.endswith('.test') for host in hosts), hosts)


if __name__ == '__main__':
    unittest.main()

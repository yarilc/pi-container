"""Agent profile loader: closed schema, derived names and protected paths."""
import copy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from sandbox_profile import NETWORK, PROFILE, ROOT, test_setting
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
            lambda v: v['auth'].clear(),
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


if __name__ == '__main__':
    unittest.main()

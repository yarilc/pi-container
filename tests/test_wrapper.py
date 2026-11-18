"""Pi-specific launcher checks: the real entry script with Pi's agent part.

The launcher behavior is tested once, for every wrapper, by the shared
tests/test_launcher.py against fixture agent parts. These cases cover what only
Pi's own profile and agent part show: the hooks (help, YOLO notice, gitconfig,
npm cache, PI_VERSION), the fixed restricted settings and the provider key that
follows the selected policy profile.
"""
import itertools
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
WRAPPER = ROOT / 'pi-container.sh'
FAKE = (ROOT / 'tests/fake_podman.py').read_text()
sys.path.insert(0, str(ROOT / 'tests'))
from test_launcher import build_inputs_hash, synthetic_install  # noqa: E402

EXEC = '/usr/local/bin/pi'
RELAY = ['/usr/bin/python3', '-I', '/opt/sandbox-egress/relay.py']
VERSION = (ROOT / '.version').read_text().splitlines()[0].strip()
LABEL_HASH = build_inputs_hash(ROOT, ('.version',))
NOTICE = 'PI_CONTAINER_YOLO has no effect: Pi has no tool-approval layer'
TRUE = ('1', 'true', 'TrUe', 'yes', 'YES')
FALSE = ('', '0', 'false', 'FaLsE', 'no', 'nO')
KEYS = {'anthropic-api': 'ANTHROPIC_API_KEY', 'openai-api': 'OPENAI_API_KEY',
        'gemini-api': 'GEMINI_API_KEY', 'openrouter-api': 'OPENROUTER_API_KEY'}
HOSTS = {'anthropic-api': 'api.anthropic.com', 'openai-api': 'api.openai.com',
         'gemini-api': 'generativelanguage.googleapis.com', 'openrouter-api': 'openrouter.ai'}
RESTRICTED = ('PI_OFFLINE=1', 'PI_SKIP_VERSION_CHECK=1', 'PI_TELEMETRY=0')


class WrapperTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='pi-wrapper-', dir=os.environ.get('SANDBOX_TEST_TMPDIR'))
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        self.bin = self.base / 'bin'
        self.bin.mkdir()
        podman = self.bin / 'podman'
        podman.write_text(FAKE)
        podman.chmod(0o755)
        self.project = self.base / 'parent with spaces' / 'my project'
        self.project.mkdir(parents=True)
        self.log = self.base / 'calls.jsonl'
        self.home = self.base / 'host-home'
        self.home.mkdir()
        self.library = self.home / '.local/share/sandbox-toolchains'
        self.env = {'PATH': str(self.bin) + ':' + os.environ['PATH'], 'HOME': str(self.home),
                    'PI_CONTAINER_NETWORK': 'unrestricted', 'PI_CONTAINER_MAINTENANCE': '1',
                    'FAKE_LABEL_HASH': LABEL_HASH, 'FAKE_LOG': str(self.log)}
        self.socket = socket.socket(socket.AF_UNIX)
        self.socket_path = self.base / 'podman.sock'
        self.socket.bind(str(self.socket_path))
        self.addCleanup(self.socket.close)
        self.env['PI_CONTAINER_PODMAN_SOCKET'] = str(self.socket_path)

    def run_wrapper(self, *args, wrapper=WRAPPER, **env):
        self.log.unlink(missing_ok=True)
        return subprocess.run([str(wrapper), *args], cwd=self.project, env=self.env | env, input='input payload',
                              text=True, capture_output=True, timeout=30)

    def calls(self):
        return [json.loads(s) for s in self.log.read_text().splitlines()] if self.log.exists() else []

    def engine_calls(self):
        return [c for c in self.calls() if not c[0].endswith('.py')]

    def agent_create(self):
        return next(c for c in self.calls() if c[0] == 'create' and not any('.egress=' in a for a in c))

    @staticmethod
    def environment(create):
        return [create[i + 1] for i, arg in enumerate(create) if arg == '--env']

    @staticmethod
    def options(create, flag):
        return [create[i + 1] for i, arg in enumerate(create) if arg == flag]

    @staticmethod
    def stable(create):
        return [a for a in create if '.cid' not in a and '.session=' not in a]

    def toolchain_index(self, entries):
        sys.path.insert(0, str(ROOT / 'setup'))
        import toolchains
        base = toolchains.base_reference(ROOT)
        self.library.mkdir(parents=True, mode=0o700, exist_ok=True)
        entry = {'version': '1', 'default': True, 'commands': ['tool'], 'requires': [], 'notes': [],
                 'check': ['tool'], 'source': {}, 'verified': {'base': base, 'date': '2026-11-14'}}
        (self.library / 'index.json').write_text(json.dumps(
            {'schema': 1, 'toolchains': [{**entry, **value} for value in entries]}))

    def run_fresh(self, **env):
        """A launch with an empty home, to show that a refusal creates no state."""
        home = Path(tempfile.mkdtemp(dir=self.base))
        result = self.run_wrapper(HOME=str(home), **env)
        self.assertEqual(list(home.iterdir()), [])
        return result

    def assert_refused_before_engine(self, result, *texts):
        self.assertEqual(result.returncode, 1, result.stderr)
        for text in texts:
            self.assertIn(text, result.stderr)
        self.assertEqual(self.engine_calls(), [])

    def test_help_documents_the_agent_variables_and_the_provider_hosts(self):
        # No Podman on PATH and no .version next to the entry script.
        install = self.base / 'help-install'
        for name in ('pi-container.sh', 'launcher/core.sh', 'agent/launcher.sh'):
            (install / name).parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(ROOT / name, install / name)
        result = subprocess.run(['/bin/bash', str(install / 'pi-container.sh'), '--container-help'],
                                cwd=self.project, env={'PATH': '/usr/bin:/bin', 'HOME': str(self.home)},
                                text=True, capture_output=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)
        for text in ('PI_CONTAINER_YOLO', 'no tool-approval', 'container is the only boundary',
                     "Pi's --approve trusts project-local files", 'PI_CONTAINER_GITCONFIG', 'PI_NPM_CACHE_SIZE',
                     'default: 256M', *KEYS.values(), 'PI_CONTAINER_ENV_VARS lists them',
                     'PI_OFFLINE=1, PI_SKIP_VERSION_CHECK=1', *(f'{p}: {h}' for p, h in HOSTS.items())):
            self.assertIn(text, result.stdout)
        self.assertLess(result.stdout.index('PI_CONTAINER_NETWORK'), result.stdout.index('PI_CONTAINER_YOLO'))
        self.assertFalse(self.log.exists())
        self.assertEqual(sorted(p.name for p in self.home.iterdir()), [])

    def test_yolo_notice_only_for_enabled_values(self):
        self.assertEqual(self.run_wrapper('-p', 'x').returncode, 0)
        baseline = self.stable(self.agent_create())
        for shell, value in itertools.product((False, True), TRUE + FALSE):
            with self.subTest(shell=shell, value=value):
                options = ['--container-shell'] if shell else []
                result = self.run_wrapper(*options, '-p', 'x', PI_CONTAINER_YOLO=value)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(result.stderr.count(NOTICE), 1 if value in TRUE and not shell else 0)
                if not shell:
                    self.assertEqual(self.stable(self.agent_create()), baseline)
        for value in ('2', 'on', ' 1'):
            with self.subTest(invalid=value):
                result = self.run_fresh(PI_CONTAINER_YOLO=value)
                self.assert_refused_before_engine(result, 'PI_CONTAINER_YOLO')

    def test_gitconfig_requires_the_exact_opt_in(self):
        target = self.base / 'dotfiles' / 'gitconfig'
        target.parent.mkdir()
        target.write_text('[user]\n name = Test\n')
        (self.home / '.gitconfig').symlink_to(target)
        for value in (None, 'true', 'yes', '', '0', '01'):
            with self.subTest(value=value):
                result = self.run_wrapper(**({} if value is None else {'PI_CONTAINER_GITCONFIG': value}))
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertFalse(any('.gitconfig' in a for a in self.agent_create()))
                self.assertNotIn('gitconfig', result.stderr)
        result = self.run_wrapper(PI_CONTAINER_GITCONFIG='1')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(f'{target}:/pi-home/.gitconfig:ro', self.options(self.agent_create(), '--volume'))

    def test_gitconfig_opt_in_without_a_regular_file(self):
        result = self.run_wrapper(PI_CONTAINER_GITCONFIG='1')
        self.assert_refused_before_engine(result, 'PI_CONTAINER_GITCONFIG=1', f'{self.home}/.gitconfig')
        (self.home / '.gitconfig').mkdir()
        result = self.run_wrapper(PI_CONTAINER_GITCONFIG='1')
        self.assert_refused_before_engine(result, 'PI_CONTAINER_GITCONFIG=1')
        (self.home / '.gitconfig').rmdir()
        (self.home / '.gitconfig').symlink_to(self.base / 'missing')
        result = self.run_wrapper(PI_CONTAINER_GITCONFIG='1')
        self.assert_refused_before_engine(result, 'PI_CONTAINER_GITCONFIG=1')
        (self.home / '.gitconfig').unlink()
        colon = self.base / 'dot:files'
        colon.write_text('[user]\n name = Test\n')
        (self.home / '.gitconfig').symlink_to(colon)
        result = self.run_wrapper(PI_CONTAINER_GITCONFIG='1')
        self.assert_refused_before_engine(result, 'PI_CONTAINER_GITCONFIG=1', 'colon', str(colon))

    def test_npm_cache_tmpfs(self):
        for size, expected in ((None, '256M'), ('', '256M'), ('1g', '1g'), ('64k', '64k')):
            with self.subTest(size=size):
                result = self.run_wrapper(**({} if size is None else {'PI_NPM_CACHE_SIZE': size}))
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertIn(f'/pi-home/.npm:rw,noexec,nosuid,nodev,mode=0700,U,size={expected}',
                              self.options(self.agent_create(), '--tmpfs'))
        for size in ('lots', '0M', '256', '-1g', '1t', '1000000m'):
            with self.subTest(invalid=size):
                result = self.run_fresh(PI_NPM_CACHE_SIZE=size)
                self.assert_refused_before_engine(result, 'PI_NPM_CACHE_SIZE')

    def test_npm_cache_below_an_isolated_home(self):
        state = self.base / 'isolated'
        result = self.run_wrapper(PI_CONTAINER_STATE_DIR=str(state))
        self.assertEqual(result.returncode, 0, result.stderr)
        create = self.agent_create()
        self.assertIn(f'{state}:/pi-home:rw', self.options(create, '--volume'))
        self.assertIn('/pi-home/.npm:rw,noexec,nosuid,nodev,mode=0700,U,size=256M', self.options(create, '--tmpfs'))

    def test_pi_version_from_the_installation(self):
        # Former Bun variables change nothing: PI_VERSION is the only build argument.
        for former in ({}, {'PI_ENABLE_BUN': '1', 'PI_BUN_VERSION': 'bun-v1.2.0'}):
            with self.subTest(former=former):
                result = self.run_wrapper('--container-build', **former)
                self.assertEqual(result.returncode, 0, result.stderr)
                build = next(c for c in self.calls() if c[0] == 'build')
                self.assertEqual(self.options(build, '--build-arg'), ['PI_VERSION=' + VERSION])
                self.assertIn('build-inputs-hash=' + LABEL_HASH, build)
        install = synthetic_install(self.base, ROOT, WRAPPER.name).parent
        for content in (None, '', '\n', '  \n'):
            with self.subTest(version=content):
                version = install / '.version'
                version.unlink(missing_ok=True)
                if content is not None:
                    version.write_text(content)
                for args in (('--container-build',), ('-p', 'x')):
                    result = self.run_wrapper(*args, wrapper=install / WRAPPER.name)
                    self.assertEqual(result.returncode, 1, result.stderr)
                    self.assertIn('.version is missing or empty', result.stderr)
                    self.assertFalse(any(c[0] in ('build', 'create') or c[:2] == ['image', 'inspect']
                                         for c in self.calls()))

    def test_unrestricted_sessions_get_no_restricted_settings_or_unlisted_keys(self):
        keys = {name: 'host-' + name for name in KEYS.values()}
        result = self.run_wrapper('-p', 'x', **keys)
        self.assertEqual(result.returncode, 0, result.stderr)
        environment = self.environment(self.agent_create())
        for name in (*KEYS.values(), *RESTRICTED):
            self.assertNotIn(name, environment)
        self.assertFalse(any(e.startswith(('PI_OFFLINE', 'PI_TELEMETRY', 'PI_SKIP_VERSION_CHECK'))
                             for e in environment))
        result = self.run_wrapper('-p', 'x', PI_CONTAINER_ENV_VARS='ANTHROPIC_API_KEY PI_TELEMETRY',
                                  PI_TELEMETRY='1', **keys)
        self.assertEqual(result.returncode, 0, result.stderr)
        create = self.agent_create()
        environment = self.environment(create)
        self.assertIn('ANTHROPIC_API_KEY', environment)
        self.assertIn('PI_TELEMETRY', environment)
        self.assertNotIn('OPENAI_API_KEY', environment)
        self.assertFalse(any(value in ' '.join(create) for value in keys.values()))


class RestrictedTests(WrapperTests):
    """Offline and provider sessions through a synthetic installation (argument instrumentation only)."""
    def setUp(self):
        super().setUp()
        self.wrapper = synthetic_install(self.base, ROOT, WRAPPER.name)
        shutil.copyfile(ROOT / '.version', self.wrapper.parent / '.version')
        self.policy = self.wrapper.parent / 'agent/policies/default.json'
        self.policy.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / 'agent/policies/default.json', self.policy)
        self.runtime = self.base / 'runtime'
        self.runtime.mkdir(mode=0o700)
        self.keys = {name: 'host-' + name for name in KEYS.values()}
        self.restricted = {'PI_CONTAINER_PODMAN': '', 'FAKE_NETWORK': '1', 'FAKE_INFO': 'true linux true',
                           'CONTAINER_HOST': 'unix:///run/service.sock', **self.keys}

    def run_offline(self, *args, **env):
        return self.run_wrapper(*args, wrapper=self.wrapper, PI_CONTAINER_NETWORK='offline',
                                **(self.restricted | env))

    def run_provider(self, *args, profile='anthropic-api', **env):
        return self.run_wrapper(*args, wrapper=self.wrapper, PI_CONTAINER_NETWORK='provider',
                                PI_CONTAINER_NETWORK_PROFILE=profile,
                                PI_CONTAINER_NETWORK_POLICY=str(self.policy),
                                PI_CONTAINER_NETWORK_RUNTIME_DIR=str(self.runtime),
                                PI_CONTAINER_EGRESS_IMAGE='sha256:' + 'e' * 64, **(self.restricted | env))

    def tail(self, create):
        """The application after the guard's mode separator and, in provider mode, the relay."""
        command = create[create.index('--') + 1:]
        return command[len(RELAY):] if command[:len(RELAY)] == RELAY else command

    def test_restricted_application_and_settings(self):
        for run in (self.run_offline, self.run_provider):
            with self.subTest(mode=run.__name__):
                result = run('-p', 'hello world', '')
                self.assertEqual(result.returncode, 0, result.stderr)
                create = self.agent_create()
                self.assertEqual(self.tail(create), [EXEC, '-p', 'hello world', ''])
                environment = self.environment(create)
                for setting in RESTRICTED:
                    self.assertEqual([e for e in environment if e.startswith(setting.split('=')[0] + '=')],
                                     [setting])

    def test_restricted_settings_win_over_toolchain_and_forwarded_variables(self):
        self.toolchain_index([{'name': 'noisy', 'path': ['/toolchains/noisy/bin'],
                               'env': {'PI_TELEMETRY': '1', 'PI_OFFLINE': '0'}}])
        for run in (self.run_offline, self.run_provider):
            with self.subTest(mode=run.__name__):
                result = run('-p', 'x', PI_OFFLINE='0', PI_TELEMETRY='1',
                             PI_CONTAINER_ENV_VARS='PI_OFFLINE PI_SKIP_VERSION_CHECK PI_TELEMETRY')
                self.assertEqual(result.returncode, 0, result.stderr)
                create = self.agent_create()
                self.assertIn(f'{self.library}:/toolchains:ro,nosuid,nodev', self.options(create, '--volume'))
                environment = self.environment(create)
                for setting in RESTRICTED:
                    name = setting.split('=')[0]
                    self.assertEqual([e for e in environment if e == name or e.startswith(name + '=')], [setting])
                    self.assertIn(f'skipping {name}', result.stderr)

    def test_offline_forwards_no_provider_key(self):
        result = self.run_offline('-p', 'x')
        self.assertEqual(result.returncode, 0, result.stderr)
        create = self.agent_create()
        environment = self.environment(create)
        for name in KEYS.values():
            self.assertNotIn(name, environment)
        self.assertFalse(any(value in ' '.join(create) for value in self.keys.values()))

    def test_provider_key_per_profile(self):
        for profile, key in KEYS.items():
            with self.subTest(profile=profile):
                # Another profile's key listed for forwarding is skipped with a notice.
                other = next(name for name in KEYS.values() if name != key)
                result = self.run_provider('-p', 'x', profile=profile, PI_CONTAINER_ENV_VARS=other)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertIn(f'network profile={profile}', result.stderr)
                create = self.agent_create()
                environment = self.environment(create)
                self.assertEqual([e for e in environment if e in KEYS.values()], [key])
                self.assertIn(f'skipping {other}', result.stderr)
                self.assertFalse(any(value in ' '.join(create) for value in self.keys.values()))

    def test_restricted_shell_and_probe_receive_no_yolo_notice(self):
        for run in (self.run_offline, self.run_provider):
            with self.subTest(mode=run.__name__):
                result = run('--container-shell', '-c', 'echo ok', PI_CONTAINER_YOLO='1')
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(self.tail(self.agent_create()), ['/bin/bash', '-c', 'echo ok'])
                self.assertNotIn(NOTICE, result.stderr)
                result = run('-p', 'x', PI_CONTAINER_YOLO='1')
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(result.stderr.count(NOTICE), 1)
        control = self.wrapper.parent / 'network/control.py'
        control.write_text(control.read_text() + "if args[0]=='qualification-input': print('f'*32+' 0')\n")
        result = self.run_offline('--container-qualify-probe', PI_CONTAINER_YOLO='1')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.tail(self.agent_create()), ['/usr/bin/python3', '-I',
                                                          '/opt/sandbox-egress/qualification_probe.py', 'probe'])
        self.assertNotIn(NOTICE, result.stderr)

    # The unrestricted cases of the parent class run once, there.
    test_help_documents_the_agent_variables_and_the_provider_hosts = None
    test_yolo_notice_only_for_enabled_values = None
    test_gitconfig_requires_the_exact_opt_in = None
    test_gitconfig_opt_in_without_a_regular_file = None
    test_npm_cache_tmpfs = None
    test_npm_cache_below_an_isolated_home = None
    test_pi_version_from_the_installation = None
    test_unrestricted_sessions_get_no_restricted_settings_or_unlisted_keys = None


if __name__ == '__main__':
    unittest.main()

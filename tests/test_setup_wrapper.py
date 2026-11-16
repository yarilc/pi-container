"""Per-agent setup checks through this checkout's own wrapper.

These tests launch the wrapper or its managed launcher, so they use the
checkout's real profile and variable names. Wrappers differ in how they admit a
missing network mode (this wrapper refuses an ordinary launch without one), so
this file is per-agent and not part of the shared set; module-level setup
checks live in the shared tests/test_setup.py.
"""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from sandbox_profile import REAL_PROFILE as PROFILE, REAL_ROOT as ROOT, REAL_WRAPPER as WRAPPER, \
    real_env as name, test_setting
from test_setup import FAKE_PODMAN_TEMPLATE, pty_run

COMMAND = PROFILE.name
CONFIG_HOME = PROFILE.config_home
PROVIDER_METHOD = next(iter(PROFILE.auth), 'none')
FAKE_PODMAN = FAKE_PODMAN_TEMPLATE.replace('@MAINTENANCE@', name('MAINTENANCE'))
# The checkout's own setup modules run in a separate process: this test process
# has already imported the shared modules of the fixture profile.
HARNESS = r'''
import importlib.util, json, sys
from pathlib import Path
root = Path(sys.argv[1])
sys.path.insert(0, str(root / 'setup'))
import common
spec = importlib.util.spec_from_file_location('sandbox_setup', root / 'setup/setup.py')
setup = importlib.util.module_from_spec(spec)
spec.loader.exec_module(setup)
request = json.loads(sys.argv[2])
if request['op'] == 'defaults':
    print(json.dumps(common.defaults(Path(request['installation']))))
else:
    value = request['value']
    install = Path(value['installation'])
    (install / 'releases').mkdir(mode=0o700, parents=True, exist_ok=True)
    release = install / 'releases' / request['name']
    release.mkdir(mode=0o700)
    setup.copy_inputs(release)
    common.save(release / 'setup.json', value)
    setup.activate(install, release, Path(value['command']))
    print(json.dumps(str(release)))
'''


class SetupWrapperTests(unittest.TestCase):
    def setUp(self):
        parent = test_setting('TEST_TMPDIR') or test_setting('TEST_STATE_ROOT')
        if not parent:
            parent = '/home/node' if Path('/home/node').is_dir() else str(Path.home())
        self.tmp = tempfile.TemporaryDirectory(prefix='sandbox-setup-wrapper-', dir=parent)
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        self.home = self.base / 'home'
        self.home.mkdir(mode=0o700)
        self.workspace = self.base / 'workspace with spaces'
        self.workspace.mkdir()
        self.bin = self.base / 'bin'
        self.bin.mkdir()
        self.log = self.base / 'calls.jsonl'
        self.env = {'PATH': str(self.bin) + ':' + os.environ['PATH'], 'HOME': str(self.home),
                    'SETUP_TEST_LOG': str(self.log)}
        fake = self.bin / 'podman'
        fake.write_text(FAKE_PODMAN)
        fake.chmod(0o700)
        self.value = self.harness(op='defaults', installation=str(self.base / 'installed'))
        self.value.update(network='unrestricted', auth=PROVIDER_METHOD, endpoint='local',
                          command=str(self.bin / COMMAND))

    def harness(self, **request):
        result = subprocess.run([sys.executable, '-I', '-c', HARNESS, str(ROOT), json.dumps(request)],
                                env=self.env, capture_output=True, text=True, timeout=60)
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout)

    def calls(self):
        return [json.loads(line) for line in self.log.read_text().splitlines()] if self.log.exists() else []

    def release(self, name='first'):
        """Install and activate a release of this checkout with the current preferences."""
        return Path(self.harness(op='release', name=name, value=self.value))

    def answers(self, **changes):
        value = self.value | changes
        result = [('Protected native installation directory', value['installation']),
                  ('Network mode', value['network'])]
        if value['network'] == 'provider':
            result += [('Acknowledge that allowed provider hosts', 'yes')]
        if value['network'] != 'offline' and PROFILE.auth:
            result += [('Authentication method', value['auth'])]
        result += [('State mode', 'isolated'), ('Private isolated state directory', str(self.base / 'state')),
                   ('Delegate the host Podman API', 'no')]
        if PROFILE.approval_bypass_env:
            result += [('Enable ' + PROFILE.display_name + ' permission bypass', 'no')]
        result += [('Use parent-directory worktree scope', 'no'), ('Agent memory limit', ''),
                   ('Agent CPU limit', ''), ('Agent process limit', ''), ('Session lifetime in seconds', ''),
                   ('Trust a host CA bundle', 'no'),
                   ('Managed launch command path', value['command']), ('Podman launch endpoint', value['endpoint'])]
        if value['network'] == 'provider':
            result += [('Private native egress runtime directory', str(self.base / 'egress'))]
        return result

    def test_setup_entry_rejects_pipes_and_mixed_arguments_but_help_is_independent(self):
        for args in (['--container-setup'], ['--container-setup', '--version'],
                     ['--container-shell', '--container-setup']):
            result = subprocess.run(['bash', str(WRAPPER), *args],
                                    env=self.env, capture_output=True, text=True, cwd=self.workspace)
            self.assertNotEqual(result.returncode, 0)
        for args in (['--container-setup', '--container-help'], ['--container-help', '--container-setup']):
            result = subprocess.run(['bash', str(WRAPPER), *args], env=self.env | {
                name('NETWORK'): 'invalid'}, capture_output=True, text=True)
            self.assertEqual(result.returncode, 0)
            self.assertIn('--container-setup', result.stdout)
        self.assertFalse(self.calls())
        self.assertEqual(list(self.home.iterdir()), [])

    def test_missing_mode_keeps_help_setup_and_fixed_qualification_dispatch(self):
        cases = (
            (['--container-setup'], 'requires an interactive terminal'),
            (['--container-setup', '--version'], 'must be used alone'),
            (['--container-qualify'], 'qualification requires an explicit same-host Unix endpoint'),
            (['--container-qualify', 'application'], 'must be used alone'),
            (['--container-qualify-probe', 'application'], 'must be used alone'),
            (['--container-qualify-probe'], 'setup required:'),
        )
        for mode in (None, ''):
            env = self.env.copy()
            if mode is not None:
                env[name('NETWORK')] = mode
            for args, message in cases:
                with self.subTest(mode=mode, args=args):
                    result = subprocess.run(['/bin/bash', str(WRAPPER), *args],
                                            cwd=self.workspace, env=env, text=True,
                                            capture_output=True, timeout=10)
                    self.assertNotEqual(result.returncode, 0)
                    self.assertIn(message, result.stderr)
                    self.assertEqual(result.stdout, '')
                    if args != ['--container-qualify-probe']:
                        self.assertNotIn('setup required:', result.stderr)
            result = subprocess.run(['/bin/bash', str(WRAPPER),
                                     '--container-setup', '--container-qualify', '--container-help'],
                                    cwd=self.workspace, env=env | {PROFILE.approval_bypass_env: 'invalid'},
                                    text=True, capture_output=True, timeout=5)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn('Container options:', result.stdout)
            code, output = pty_run(['/bin/bash', str(WRAPPER)],
                                   env, self.workspace, [])
            self.assertEqual(code, 1, output)
            self.assertIn('setup required:', output)
        self.assertFalse(self.calls())
        self.assertEqual(list(self.home.iterdir()), [])

    def test_pty_questionnaire_before_invalid_provider_runtime_and_missing_image(self):
        env = self.env | {name('NETWORK'): 'provider', 'SETUP_TEST_MISSING': '1',
                          'SETUP_TEST_ENGINE': 'true linux false'}
        answers = self.answers() + [('Refresh prepared images', 'no'), ('Apply this installation', 'no')]
        code, output = pty_run(['bash', str(WRAPPER), '--container-setup'], env,
                               self.workspace, answers)
        self.assertEqual(code, 1, output)
        self.assertIn('prepare/build missing image', output)
        self.assertIn('cancelled before', output)
        self.assertFalse(Path(self.value['installation']).exists())
        self.assertFalse(any(c['args'][0] in ('build', 'pull', 'tag') for c in self.calls()))

    def test_setup_plan_names_unenforced_budgets_without_a_question(self):
        for controllers, notices in (('[memory pids]', ['agent CPU budget not enforced: cgroup controller cpu']),
                                     ('[cpu pids]', ['agent memory budget not enforced: cgroup controller memory']),
                                     ('[cpu memory pids]', [])):
            with self.subTest(controllers=controllers):
                env = self.env | {name('NETWORK'): 'provider', 'SETUP_TEST_MISSING': '1',
                                  'SETUP_TEST_ENGINE': 'true linux false', 'SETUP_TEST_CONTROLLERS': controllers}
                answers = self.answers() + [('Refresh prepared images', 'no'), ('Apply this installation', 'no')]
                code, output = pty_run(['bash', str(WRAPPER), '--container-setup'], env,
                                       self.workspace, answers)
                self.assertEqual(code, 1, output)
                self.assertIn('enforced agent budgets: ' + ', '.join(controllers[1:-1].split()), output)
                for notice in notices:
                    self.assertIn(notice, output)
                if not notices:
                    self.assertNotIn('budget not enforced', output)
                # This questionnaire selects unrestricted mode, which has no proxy.
                self.assertNotIn('proxy memory budget', output)
                self.assertIn('cancelled before', output)

    def test_questionnaire_cancellation_has_no_mutation(self):
        code, output = pty_run(['bash', str(WRAPPER), '--container-setup'],
                               self.env, self.workspace, [('Protected native installation directory', None)])
        self.assertEqual(code, 130, output)
        self.assertFalse(self.calls())
        self.assertEqual(list(self.home.iterdir()), [])

    def test_managed_real_wrapper_admits_saved_modes_and_preserves_network_overrides(self):
        release = self.release()
        command = Path(self.value['command'])
        for mode in ('offline', 'provider', 'unrestricted'):
            saved = self.value | {'network': mode, 'auth': 'none' if mode == 'offline' else PROVIDER_METHOD,
                                 'endpoint': 'default' if mode != 'unrestricted' else 'local',
                                 'state_dir': str(self.base / 'state'),
                                 'runtime_dir': str(self.base / 'egress'),
                                 'proxy_image': 'sha256:' + 'b' * 64}
            (release / 'setup.json').write_text(json.dumps(saved))
            for override in (None, '', 'unrestricted', 'invalid'):
                with self.subTest(saved_mode=mode, override=override):
                    self.log.unlink(missing_ok=True)
                    env = self.env | {'SETUP_TEST_FAIL': 'query'}
                    if override is not None:
                        env[name('NETWORK')] = override
                    result = subprocess.run([str(command), '--version'], cwd=self.workspace,
                                            env=env, capture_output=True, text=True, timeout=10)
                    self.assertEqual(result.returncode, 1, result.stderr)
                    self.assertEqual(result.stdout, '')
                    if override == '':
                        self.assertIn('setup required:', result.stderr)
                        self.assertFalse(self.calls())
                    elif override == 'invalid':
                        self.assertIn('must be offline, provider, or unrestricted', result.stderr)
                        self.assertFalse(self.calls())
                    else:
                        # Deliberately fail the first engine query: reaching it
                        # proves admission without faking restricted readiness.
                        self.assertIn('cannot query Podman', result.stderr)
                        self.assertEqual(len(self.calls()), 1)
                        self.assertEqual(self.calls()[0]['args'][0], 'info')
                        endpoint = self.calls()[0]['endpoint']
                        self.assertEqual(bool(endpoint), mode != 'unrestricted')
                    self.assertFalse((self.base / 'state').exists())
                    self.assertFalse((self.home / CONFIG_HOME).exists())

    def test_managed_help_bypasses_corrupt_json_python_and_podman(self):
        release = self.release()
        command = Path(self.value['command'])
        (release / 'setup.json').write_text('invalid preferences')
        help_bin = self.base / 'help-bin'
        help_bin.mkdir()
        (help_bin / 'cat').symlink_to(shutil.which('cat'))
        result = subprocess.run(['/bin/bash', str(command), '--container-setup', '--container-help'],
                                env={'PATH': str(help_bin), 'HOME': str(self.home)}, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('--container-setup', result.stdout)
        self.assertFalse(self.calls())

    def test_managed_rerun_reviews_saved_defaults_without_inheriting_launch_values(self):
        release = self.release()
        command = Path(self.value['command'])
        for mode in ('unrestricted', 'offline'):
            with self.subTest(mode=mode):
                saved = self.value | {'network': mode, 'auth': 'none' if mode == 'offline' else PROVIDER_METHOD,
                                      'endpoint': 'default' if mode == 'offline' else 'local'}
                (release / 'setup.json').write_text(json.dumps(saved))
                code, output = pty_run([str(command), '--container-setup'],
                                       self.env | {name('NETWORK'): 'invalid'}, self.workspace,
                                       [('Protected native installation directory', ''), ('Network mode', None)])
                self.assertEqual(code, 130, output)
                self.assertIn('Network mode [' + mode + ']', output)
        self.assertFalse(self.calls())


if __name__ == '__main__':
    unittest.main()

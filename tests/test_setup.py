"""Synthetic setup tests: native disposable state, fake engines, no credentials."""
import importlib.util
import io
import json
import os
from pathlib import Path
import pty
import select
import shlex
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
from sandbox_profile import GUARD, PROFILE, ROOT, env as name, test_setting
sys.path.insert(0, str(ROOT / 'setup'))
import common
import diagnostics

WRAPPER = PROFILE.wrapper
COMMAND = PROFILE.name
CONFIG_HOME = PROFILE.config_home
CONFIG_ENV = PROFILE.config_dir_env
YOLO_ENV = PROFILE.approval_bypass_env
MAINTENANCE = name('MAINTENANCE')
# Setup proposes the profile's first method. Profiles may have only API-key
# methods, so the interactive login method is optional.
PROVIDER_METHOD = next(iter(PROFILE.auth))
LOGIN_METHOD = next((method for method, item in PROFILE.auth.items() if 'login_args' in item), None)
KEY_METHOD = next(method for method, item in PROFILE.auth.items() if 'credential_env' in item)
LOGIN_ARGS = PROFILE.auth[LOGIN_METHOD]['login_args'] if LOGIN_METHOD else None
CREDENTIAL = PROFILE.auth[KEY_METHOD]['credential_env']

spec = importlib.util.spec_from_file_location('sandbox_setup', ROOT / 'setup/setup.py')
setup = importlib.util.module_from_spec(spec)
spec.loader.exec_module(setup)


def pty_run(command, env, cwd, answers, timeout=30):
    """Wait for prompts before sending answers; never leave an interactive child."""
    master, slave = pty.openpty()
    proc = subprocess.Popen(command, env=env, cwd=cwd, stdin=slave, stdout=slave, stderr=slave,
                            start_new_session=True)
    os.close(slave)
    output = b''
    offset = 0
    deadline = time.monotonic() + timeout
    try:
        for prompt, answer in answers:
            while prompt.encode() not in output[offset:]:
                if time.monotonic() >= deadline:
                    raise AssertionError('PTY prompt timeout: ' + prompt + '\n' + output.decode(errors='replace'))
                ready, _, _ = select.select([master], [], [], 0.1)
                if ready:
                    try:
                        chunk = os.read(master, 65536)
                    except OSError:
                        chunk = b''
                    if not chunk:
                        raise AssertionError('PTY closed before: ' + prompt + '\n' + output.decode(errors='replace'))
                    output += chunk
            offset = len(output)
            if answer is None:
                proc.send_signal(signal.SIGTERM)
            else:
                os.write(master, answer.encode() + b'\n')
        while True:
            if time.monotonic() >= deadline:
                raise AssertionError('PTY completion timeout\n' + output.decode(errors='replace'))
            ready, _, _ = select.select([master], [], [], 0.1)
            if ready:
                try:
                    chunk = os.read(master, 65536)
                except OSError:
                    chunk = b''
                if not chunk:
                    break
                output += chunk
            elif proc.poll() is not None:
                break
        return proc.wait(timeout=2), output.decode(errors='replace')
    finally:
        if proc.poll() is None:
            os.killpg(proc.pid, signal.SIGKILL)
        proc.wait()
        os.close(master)


FAKE_PODMAN = r'''#!/usr/bin/env python3
import json, os, sys
args=sys.argv[1:]
with open(os.environ['SETUP_TEST_LOG'], 'a') as output:
    output.write(json.dumps({'args':args, 'maintenance':os.environ.get('@MAINTENANCE@'),
                            'endpoint':os.environ.get('CONTAINER_HOST')})+'\n')
if os.environ.get('SETUP_TEST_FAIL') == 'query' and 'info' in args: sys.exit(125)
if 'info' in args:
    template=args[-1]
    if 'RemoteSocket.Path' in template: print('true '+os.environ.get('SETUP_TEST_SOCKET','/run/user/1000/podman/podman.sock'))
    elif 'NetworkBackend' in template: print('netavark')
    elif 'json .Host' in template:
        print(json.dumps({'kernel':'6.6.87.2-microsoft-standard-WSL2','arch':'amd64',
           'security':{'seccompEnabled':True,'selinuxEnabled':False,'apparmorEnabled':False}}))
    else: print(os.environ.get('SETUP_TEST_ENGINE','true linux '+('true' if os.environ.get('CONTAINER_HOST') else 'false')))
elif args[0]=='version': print('4.9.3')
elif args[:2]==['image','exists']:
    sys.exit(125 if os.environ.get('SETUP_TEST_FAIL')=='inspect' else 1 if os.environ.get('SETUP_TEST_MISSING')=='1' else 0)
elif args[:2]==['image','inspect']: print('sha256:'+'a'*64)
elif args[0] in ('build','pull','tag'):
    if os.environ.get('SETUP_TEST_FAIL')==args[0]: sys.exit(125)
elif args[0]=='run' and '--cidfile' in args:
    with open(args[args.index('--cidfile')+1], 'w') as output: output.write('d'*64+'\n')
    sys.exit(17)
elif args[0]=='rm': sys.exit(0)
else: sys.exit(125)
'''.replace('@MAINTENANCE@', MAINTENANCE)


class SetupTests(unittest.TestCase):
    def setUp(self):
        parent = test_setting('TEST_TMPDIR') or test_setting('TEST_STATE_ROOT')
        if not parent:
            parent = '/home/node' if Path('/home/node').is_dir() else str(Path.home())
        self.tmp = tempfile.TemporaryDirectory(prefix='sandbox-setup-', dir=parent)
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
        self.value = common.defaults(self.base / 'installed')
        self.value.update(network='unrestricted', auth=PROVIDER_METHOD, endpoint='local',
                          command=str(self.bin / COMMAND))

    def calls(self):
        return [json.loads(line) for line in self.log.read_text().splitlines()] if self.log.exists() else []

    def release(self, name='first'):
        root = Path(self.value['installation'])
        (root / 'releases').mkdir(mode=0o700, parents=True, exist_ok=True)
        release = root / 'releases' / name
        release.mkdir(mode=0o700)
        setup.copy_inputs(release)
        common.save(release / 'setup.json', self.value)
        return root, release

    def answers(self, **changes):
        value = self.value | changes
        result = [('Protected native installation directory', value['installation']),
                  ('Network mode', value['network'])]
        if value['network'] == 'provider':
            result += [('Acknowledge that allowed provider hosts', 'yes')]
        if value['network'] != 'offline':
            result += [('Authentication method', value['auth'])]
        result += [('State mode', 'isolated'), ('Private isolated state directory', str(self.base / 'state')),
                   ('Delegate the host Podman API', 'no'), ('Enable ' + PROFILE.display_name + ' permission bypass', 'no'),
                   ('Use parent-directory worktree scope', 'no'), ('Agent memory limit', ''),
                   ('Agent CPU limit', ''), ('Agent process limit', ''), ('Session lifetime in seconds', ''),
                   ('Trust a host CA bundle', 'no'),
                   ('Managed launch command path', value['command']), ('Podman launch endpoint', value['endpoint'])]
        if value['network'] == 'provider':
            result += [('Private native egress runtime directory', str(self.base / 'egress'))]
        return result

    def test_setup_entry_rejects_pipes_and_mixed_arguments_but_help_is_independent(self):
        for args in (['--container-setup'], ['--container-setup', '--version'],
                     ['--container-shell', '--container-setup']):
            result = subprocess.run(['bash', str(ROOT / WRAPPER), *args],
                                    env=self.env, capture_output=True, text=True, cwd=self.workspace)
            self.assertNotEqual(result.returncode, 0)
        for args in (['--container-setup', '--container-help'], ['--container-help', '--container-setup']):
            result = subprocess.run(['bash', str(ROOT / WRAPPER), *args], env=self.env | {
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
                    result = subprocess.run(['/bin/bash', str(ROOT / WRAPPER), *args],
                                            cwd=self.workspace, env=env, text=True,
                                            capture_output=True, timeout=10)
                    self.assertNotEqual(result.returncode, 0)
                    self.assertIn(message, result.stderr)
                    self.assertEqual(result.stdout, '')
                    if args != ['--container-qualify-probe']:
                        self.assertNotIn('setup required:', result.stderr)
            result = subprocess.run(['/bin/bash', str(ROOT / WRAPPER),
                                     '--container-setup', '--container-qualify', '--container-help'],
                                    cwd=self.workspace, env=env | {YOLO_ENV: 'invalid'},
                                    text=True, capture_output=True, timeout=5)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn('Container options:', result.stdout)
            code, output = pty_run(['/bin/bash', str(ROOT / WRAPPER)],
                                   env, self.workspace, [])
            self.assertEqual(code, 1, output)
            self.assertIn('setup required:', output)
        self.assertFalse(self.calls())
        self.assertEqual(list(self.home.iterdir()), [])

    def test_diagnostics_reclassifies_only_complete_known_lines_at_any_chunk_boundary(self):
        for original, expected in ((b'ERRO[0074] Should restart: false\n', b'INFO[0074] Should restart: false\n'),
                                   (b'time="2026-11-07T12:11:46Z" level=error msg="Should restart: false"\n',
                                    b'time="2026-11-07T12:11:46Z" level=info msg="Should restart: false"\n')):
            for split in range(len(original) + 1):
                stream = diagnostics.Diagnostics()
                result = stream.feed(original[:split]) + stream.feed(original[split:]) + stream.finish()
                self.assertEqual(result, expected)
        stream = diagnostics.Diagnostics()
        message = b'\x1b[31mERRO\x1b[0m[0074] Should restart: false\r\n'
        result = b''.join(stream.feed(bytes([byte])) for byte in message) + stream.finish()
        self.assertEqual(result, b'\x1b[36mINFO\x1b[0m[0074] Should restart: false\r\n')

    def test_diagnostics_preserves_errors_binary_bytes_and_unterminated_records(self):
        for message in (b'ERRO[0074] Should restart: true\n', b'ERRO[0074] Should restart: false extra\n',
                        b'ERRO[0074] Failed to check if container should restart: unavailable\n',
                        b'ERRO[0074] Should restart: false', b'prefix ERRO[0074] Should restart: false\n',
                        b'time="2026-11-07T12:11:46Z" level=error msg="genuine failure"\n',
                        b'time="2026-11-07T12:11:46Z" level=error msg="Should restart: true"\n',
                        b'\0\xff\r\n', b'ERRO[' + b'9' * 10000):
            stream = diagnostics.Diagnostics()
            self.assertEqual(stream.feed(message) + stream.finish(), message)
            self.assertLess(len(stream.pending), 128)

    def test_diagnostics_forwards_interactive_prompts_without_waiting_for_newline(self):
        stream = diagnostics.Diagnostics()
        for chunk in (b'Paste code here > ', b'\xf0\x9f', b'\x98\x80', b'\r', b'prompt\n'):
            self.assertEqual(stream.feed(chunk), chunk)
        self.assertEqual(stream.finish(), b'')

    def test_pty_questionnaire_before_invalid_provider_runtime_and_missing_image(self):
        env = self.env | {name('NETWORK'): 'provider', 'SETUP_TEST_MISSING': '1',
                          'SETUP_TEST_ENGINE': 'true linux false'}
        answers = self.answers() + [('Refresh prepared images', 'no'), ('Apply this installation', 'no')]
        code, output = pty_run(['bash', str(ROOT / WRAPPER), '--container-setup'], env,
                               self.workspace, answers)
        self.assertEqual(code, 1, output)
        self.assertIn('prepare/build missing image', output)
        self.assertIn('cancelled before', output)
        self.assertFalse(Path(self.value['installation']).exists())
        self.assertFalse(any(c['args'][0] in ('build', 'pull', 'tag') for c in self.calls()))

    def test_questionnaire_defaults_retries_and_explicit_delegation_conflict(self):
        with patch.dict(os.environ, self.env, clear=True), patch.object(setup, 'SOURCE', ROOT):
            # Provider/account defaults remain selected through input retries;
            # requesting delegation must not silently broaden the network mode.
            answers = iter([str(self.base / 'installed'), 'invalid', '', 'yes', '', 'shared', '',
                            'yes', '', 'no', 'no', '', '', '', '', 'no', str(self.bin / COMMAND), 'default', ''])
            with patch('builtins.input', side_effect=lambda prompt: next(answers)), patch('builtins.print'):
                value, old = setup.questionnaire()
            self.assertIsNone(old)
            self.assertEqual(value['network'], 'provider')
            self.assertFalse(value['podman'])
            self.assertEqual(value['auth'], PROVIDER_METHOD)

    def questionnaire_output(self, inputs):
        answers, printed = iter(inputs), []
        with patch.dict(os.environ, self.env, clear=True), patch.object(setup, 'SOURCE', ROOT), \
                patch('builtins.input', side_effect=lambda prompt: (printed.append(prompt), next(answers))[1]), \
                patch('builtins.print', side_effect=lambda *a, **k: printed.append(' '.join(map(str, a)))):
            value, _ = setup.questionnaire()
        self.assertRaises(StopIteration, next, answers)
        return value, '\n'.join(printed)

    def test_provider_residual_notice_requires_acknowledgement(self):
        # Declining returns to the mode question; nothing is substituted or saved.
        value, output = self.questionnaire_output([
            str(self.base / 'installed'), 'provider', 'no', 'offline', 'shared', '',
            'no', 'no', 'no', '', '', '', '', 'no', str(self.bin / COMMAND), ''])
        self.assertEqual(value['network'], 'offline')
        self.assertEqual(output.count('Residual exfiltration:'), 1)
        self.assertEqual(output.count('Network mode ['), 2)
        self.assertIn('Provider mode not acknowledged', output)
        for method, item in PROFILE.auth.items():
            self.assertIn(method + ': ' + ', '.join(item['hosts']), output)
        self.assertFalse([key for key in value if 'ack' in key])
        self.assertEqual(set(value), set(common.defaults()))

    def test_delegation_conflict_switch_to_provider_requires_acknowledgement(self):
        value, output = self.questionnaire_output([
            str(self.base / 'installed'), 'offline', 'shared', '', 'yes', 'change-network', 'provider', 'yes', '',
            'disable-delegation', 'no', 'no', '', '', '', '', 'no', str(self.bin / COMMAND), '', ''])
        self.assertEqual((value['network'], value['auth'], value['podman']), ('provider', PROVIDER_METHOD, False))
        self.assertEqual(output.count('Residual exfiltration:'), 1)

    def test_unrestricted_selection_has_no_provider_notice(self):
        value, output = self.questionnaire_output([
            str(self.base / 'installed'), 'unrestricted', '', 'shared', '', 'no', 'no', 'no', '', '', '', '', 'no',
            str(self.bin / COMMAND), ''])
        self.assertEqual(value['network'], 'unrestricted')
        self.assertNotIn('Residual exfiltration', output)

    def test_budget_questions_defaults_retries_and_saved_values(self):
        value, output = self.questionnaire_output([
            str(self.base / 'installed'), 'unrestricted', '', 'shared', '', 'no', 'no', 'no',
            '0', 'max', '4', '8G', '0', '1.5', '-1', '1024', '1.5', '3600', 'no', str(self.bin / COMMAND), ''])
        self.assertEqual((value['memory_limit'], value['cpu_limit'], value['pids_limit'], value['run_timeout']),
                         ('8g', '1.5', '1024', '3600'))
        self.assertEqual(output.count('Invalid value: use a positive integer with unit k, m or g'), 3)
        self.assertEqual(output.count('Invalid value: use a positive number of CPUs'), 1)
        self.assertEqual(output.count('Invalid value: use a positive integer process count'), 1)
        self.assertEqual(output.count('Invalid value: use whole seconds'), 1)
        self.assertIn('Agent memory limit (integer with k, m or g unit) [4g]', output)
        self.assertIn('Session lifetime in seconds, 0 disables [0]', output)
        self.assertIn('do not limit workspace or state storage', output)
        _, release = self.release()
        common.save(release / 'saved.json', self.value | value | {'installation': self.value['installation']})
        rerun = common.load(release / 'saved.json')
        with patch.object(setup, 'current_release', return_value=release), \
                patch.object(common, 'load', return_value=rerun), patch.object(setup, 'load', return_value=rerun):
            _, output = self.questionnaire_output([
                str(self.base / 'installed'), 'unrestricted', '', 'shared', '', 'no', 'no', 'no',
                '', '', '', '', 'no', str(self.bin / COMMAND), ''])
        self.assertIn('Agent memory limit (integer with k, m or g unit) [8g]', output)
        self.assertIn('Session lifetime in seconds, 0 disables [3600]', output)

    def test_questionnaire_cancellation_has_no_mutation(self):
        code, output = pty_run(['bash', str(ROOT / WRAPPER), '--container-setup'],
                               self.env, self.workspace, [('Protected native installation directory', None)])
        self.assertEqual(code, 130, output)
        self.assertFalse(self.calls())
        self.assertEqual(list(self.home.iterdir()), [])

    def test_strict_engine_records_and_failed_query_stop_before_images(self):
        for response in ('false linux false', 'true windows false', '', 'true linux false\n',
                         'true linux false\r', 'true linux false\nextra'):
            with self.subTest(response=response):
                with self.assertRaises(common.SetupError):
                    setup.verify_engine(self.env | {'SETUP_TEST_ENGINE': response}, False)
        with self.assertRaisesRegex(common.SetupError, 'subuid'):
            setup.verify_engine(self.env | {'SETUP_TEST_FAIL': 'query'}, False)
        setup.verify_engine(self.env, False)
        with self.assertRaises(common.SetupError):
            setup.verify_engine(self.env, True)
        setup.verify_engine(self.env | {'CONTAINER_HOST': 'unix:///some/socket'}, True)
        self.assertTrue(all(c['args'][0] in ('info', 'version') for c in self.calls()))

    def test_missing_podman_and_unsupported_context_diagnosis(self):
        with patch.dict(os.environ, self.env, clear=True), patch.object(setup.shutil, 'which', return_value=None):
            with self.assertRaisesRegex(common.SetupError, 'Podman is required'):
                setup.check_prerequisites()
        for control in ({'CONTAINER_CONNECTION': 'named'}, {'CONTAINER_HOST': 'ssh://host'},
                        {'CONTAINER_HOST': 'unix:///'}, {'CONTAINER_HOST': 'unix://relative'}):
            with patch.dict(os.environ, self.env | control, clear=True):
                with self.assertRaises(common.SetupError):
                    setup.check_prerequisites()
        self.assertFalse(self.calls())

    def test_platform_security_mismatch_does_not_fallback(self):
        env = self.env | {'CONTAINER_HOST': 'unix:///some/socket'}
        real_run = setup.run
        def platform(command, *args, **kwargs):
            if command[-1] == '{{json .Host}}':
                return json.dumps({'kernel': 'other', 'arch': 'amd64', 'security': {}})
            return real_run(command, *args, **kwargs)
        with patch.object(setup, 'run', side_effect=platform):
            with self.assertRaisesRegex(common.SetupError, 'Unsupported restricted platform'):
                setup.verify_engine(env, True)
        self.assertFalse(any(c['args'][0] in ('build', 'pull', 'tag') for c in self.calls()))

    def test_shared_platform_rules_admit_native_and_active_lsm_without_version_pins(self):
        env = self.env | {'CONTAINER_HOST':'unix:///some/socket'}
        for kernel, selinux, apparmor in (('6.12-native', True, False), ('6.8-ubuntu', False, True),
                                         ('6.6.99-microsoft-standard-WSL2', False, False)):
            host = dict(kernel=kernel, arch='amd64', security=dict(
                seccompEnabled=True, selinuxEnabled=selinux, apparmorEnabled=apparmor))
            def response(command, *args, **kwargs):
                return {'{{json .Host}}':json.dumps(host), '{{.Server.Version}}':'5.4.0',
                        '{{.Host.NetworkBackend}}':'netavark'}.get(command[-1], 'true linux true')
            with self.subTest(kernel=kernel), patch.object(setup, 'run', side_effect=response):
                setup.verify_engine(env, True)
        self.assertFalse(self.calls())

    def test_user_socket_activation_requires_consent_and_exact_post_verification(self):
        value = self.value | {'network': 'offline', 'endpoint': 'default'}
        changes = []
        with (patch.dict(os.environ, self.env, clear=True), patch.object(setup, 'run', return_value='') as run,
             patch.object(setup.shutil, 'which', return_value='/bin/systemctl'),
             patch.object(setup, 'verify_socket', side_effect=[common.SetupError('missing'), None]) as verify,
             patch.object(setup, 'verify_engine') as engine, patch.object(setup, 'yes', return_value=True)):
            setup.prepare_service(value, changes)
            self.assertEqual(run.call_args_list[-1].args[0], ['systemctl', '--user', 'enable', '--now', 'podman.socket'])
            self.assertEqual(verify.call_count, 2)
            self.assertEqual(verify.call_args_list[0].args[0], verify.call_args_list[1].args[0])
            self.assertTrue(engine.called)
        self.assertFalse(value['podman'])
        self.assertIn('podman.socket', changes[0])

    def test_no_systemd_or_declined_socket_outputs_foreground_recovery(self):
        value = self.value | {'network': 'offline', 'endpoint': 'default'}
        for available in (False, True):
            with (patch.dict(os.environ, self.env, clear=True), patch.object(setup, 'verify_socket', side_effect=common.SetupError('missing')),
                 patch.object(setup.shutil, 'which', return_value='/bin/systemctl' if available else None),
                 patch.object(setup, 'run', return_value='') as run, patch.object(setup, 'yes', return_value=False),
                 patch('builtins.print') as output):
                with self.assertRaisesRegex(common.SetupError, 'Sandbox incomplete'):
                    setup.prepare_service(value, [])
                self.assertFalse(any('enable' in call.args[0] for call in run.call_args_list))
                text = '\n'.join(str(call.args) for call in output.call_args_list)
                self.assertIn('podman system service --time=0', text)
                self.assertIn('foreground', text)

    def test_reuses_exact_endpoint_and_local_needs_no_user_service(self):
        with (patch.dict(os.environ, self.env, clear=True), patch.object(setup, 'verify_socket') as socket_check,
             patch.object(setup, 'verify_engine'), patch.object(setup, 'run') as run):
            setup.prepare_service(self.value, [])
            socket_check.assert_not_called()
            run.assert_not_called()
            value = self.value | {'endpoint': 'unix:///exact/socket', 'podman': True,
                                  'delegation_socket': '/separate/delegated.sock'}
            setup.prepare_service(value, [])
            self.assertEqual([call.args[0] for call in socket_check.call_args_list],
                             ['unix:///exact/socket', 'unix:///separate/delegated.sock'])
            run.assert_not_called()

    def test_socket_validation_rejects_rootful_and_cr_responses(self):
        temporary = tempfile.TemporaryDirectory(prefix='setup-sock-')
        self.addCleanup(temporary.cleanup)
        endpoint = Path(temporary.name) / 'podman.sock'
        with socket.socket(socket.AF_UNIX) as bound:
            bound.bind(str(endpoint))
            for response in ('false /host/socket', 'true relative', 'true /host/socket\r', 'true /host/socket\n\n'):
                with patch.object(setup, 'run', return_value=response):
                    with self.assertRaises(common.SetupError):
                        setup.verify_socket('unix://' + str(endpoint), self.env)
            setup.verify_socket('unix://' + str(endpoint), self.env)

    def test_manifest_copies_complete_native_inputs_without_credentials(self):
        root, release = self.release()
        self.assertEqual(set(common.MANIFEST), {str(p.relative_to(release)) for p in release.rglob('*') if p.is_file()} - {'setup.json'})
        self.assertFalse((release / CONFIG_HOME).exists())
        self.assertFalse((release / '.git').exists())
        self.assertEqual((release / 'network/relay.py').stat().st_mode & 0o777, 0o644)
        self.assertEqual((release / 'network/tls_client_hello.py').read_bytes(), (ROOT / 'network/tls_client_hello.py').read_bytes())
        self.assertEqual((release / WRAPPER).stat().st_mode & 0o777, 0o700)
        self.assertEqual((release / 'agent/policies/default.json').stat().st_mode & 0o777, 0o600)
        with patch.dict(os.environ, self.env, clear=True):
            common.protect_mounts(self.value, common.runtime_environment(self.value, release, overrides=False))

    def test_profile_and_policy_are_installed_validated_and_bound_to_the_release(self):
        root, release = self.release()
        for item in ('agent/profile.json', 'agent/policies/default.json'):
            self.assertEqual((release / item).read_bytes(), (ROOT / item).read_bytes())
        self.assertEqual(common.agent_profile.load(release / 'agent/profile.json', writable=[]).value, PROFILE.value)
        provider = self.value | {'network': 'provider', 'runtime_dir': str(self.base / 'egress')}
        with patch.dict(os.environ, self.env, clear=True):
            env = common.runtime_environment(provider, release, overrides=False)
        self.assertEqual(env[name('NETWORK_POLICY')], str(release / 'agent/policies/default.json'))
        self.assertEqual(env[name('NETWORK_PROFILE')], PROFILE.policy_profile(PROVIDER_METHOD))
        command = Path(self.value['command'])
        setup.activate(root, release, command)
        profile = release / 'agent/profile.json'
        original = profile.read_bytes()
        for damage in ('mode', 'content'):
            with self.subTest(damage=damage):
                self.log.unlink(missing_ok=True)
                if damage == 'mode':
                    profile.chmod(0o666)
                else:
                    profile.write_text('{"schema": 1}')
                result = subprocess.run([str(command), '--version'], cwd=self.workspace, env=self.env,
                                        capture_output=True, text=True, timeout=10)
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(result.stdout, '')
                self.assertRegex(result.stderr, 'invalid or unsafe managed configuration|invalid managed installation')
                self.assertFalse(self.calls())
                profile.chmod(0o644)
                profile.write_bytes(original)

    def test_rollback_keeps_the_profile_of_the_restored_release(self):
        root, first = self.release()
        command = Path(self.value['command'])
        setup.activate(root, first, command)
        _, second = self.release('second')
        changed = json.loads((second / 'agent/profile.json').read_text()) | {'display_name': 'Changed'}
        (second / 'agent/profile.json').write_text(json.dumps(changed))
        real_replace = setup.os.replace
        def interrupted(source, target):
            if Path(target) == root / 'current':
                raise KeyboardInterrupt
            return real_replace(source, target)
        with patch.object(setup.os, 'replace', side_effect=interrupted):
            with self.assertRaises(KeyboardInterrupt):
                setup.activate(root, second, command)
        active = setup.current_release(root)
        self.assertEqual(active, first)
        self.assertEqual((active / 'agent/profile.json').read_bytes(), (ROOT / 'agent/profile.json').read_bytes())
        self.assertEqual((active / 'agent/policies/default.json').read_bytes(), (first / 'agent/policies/default.json').read_bytes())

    def test_workspace_decoy_profile_is_ignored_by_the_managed_launcher(self):
        root, release = self.release()
        command = Path(self.value['command'])
        setup.activate(root, release, command)
        decoy = json.loads((ROOT / 'agent/profile.json').read_text()) | {'env_prefix': 'DECOY_CONTAINER'}
        for base in (self.workspace, self.workspace / 'network'):
            (base / 'agent/policies').mkdir(parents=True, exist_ok=True)
            (base / 'agent/profile.json').write_text(json.dumps(decoy))
        (self.workspace / 'network/agent_profile.py').write_text('raise SystemExit("decoy loader executed")\n')
        (release / WRAPPER).write_text("""#!/bin/bash
exec python3 -c 'import json,os; print(json.dumps(sorted(k for k in os.environ if k.endswith("_NETWORK_POLICY"))))'
""")
        result = subprocess.run([str(command), '--version'], cwd=self.workspace, env=self.env,
                                capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout), [name('NETWORK_POLICY')])
        self.assertNotIn('decoy', result.stderr)

    def test_paths_reject_writable_ancestors_overlap_and_escaped_state(self):
        unsafe = self.base / 'unsafe'
        unsafe.mkdir(mode=0o777)
        unsafe.chmod(0o777)
        with self.assertRaises(common.SetupError):
            common.trusted(unsafe / 'installation', missing=True)
        state = self.base / 'state'
        state.mkdir(mode=0o700)
        (state / CONFIG_HOME).parent.mkdir(parents=True, exist_ok=True)
        (state / CONFIG_HOME).symlink_to(self.base / 'outside')
        with self.assertRaises(common.SetupError):
            common.writable_mounts(self.env | {name('STATE_DIR'): str(state)})
        with self.assertRaises(common.SetupError):
            common.private(self.workspace)
        self.assertEqual(self.workspace.stat().st_mode & 0o777, 0o755)
        value = self.value | {'installation': str(self.workspace / 'installed')}
        with patch.object(Path, 'cwd', return_value=self.workspace):
            with self.assertRaisesRegex(common.SetupError, 'overlaps'):
                common.protect_mounts(value, self.env)

    def test_private_creation_preserves_umask_and_existing_permissions(self):
        before = os.umask(0o027)
        try:
            common.private(self.base / 'private/new', create=True)
            inherited = os.umask(0o027)
            self.assertEqual(inherited, 0o027)
            self.assertEqual((self.base / 'private/new').stat().st_mode & 0o777, 0o700)
            with self.assertRaises(common.SetupError):
                common.private(self.workspace, create=True)
            self.assertEqual(self.workspace.stat().st_mode & 0o777, 0o755)
        finally:
            os.umask(before)

    def test_private_refusal_names_reason_and_fix(self):
        shared = self.base / 'host-tool-dir'
        shared.mkdir(mode=0o755)
        shared.chmod(0o755)
        with self.assertRaises(common.SetupError) as raised:
            common.private(shared)
        message = str(raised.exception)
        for text in (str(shared), 'mode 755', 'chmod 700 ' + str(shared), 'existing permissions were not changed'):
            self.assertIn(text, message)
        self.assertEqual(shared.stat().st_mode & 0o777, 0o755)
        regular = self.base / 'regular-file'
        regular.write_text('')
        with self.assertRaisesRegex(common.SetupError, 'not a directory'):
            common.private(regular)
        locked = self.base / 'locked'
        locked.mkdir(mode=0o700)
        locked.chmod(0o500)
        self.addCleanup(locked.chmod, 0o700)
        if not os.access(locked, os.W_OK):  # a caller that bypasses permission checks cannot observe this case
            with self.assertRaisesRegex(common.SetupError, 'lacks read, write or traverse access'):
                common.private(locked)
        self.assertEqual(locked.stat().st_mode & 0o777, 0o500)
        owned = self.base / 'owned'
        owned.mkdir(mode=0o700)
        with patch.object(common, 'trusted'), patch.object(common.os, 'getuid', return_value=os.getuid() + 1):
            with self.assertRaisesRegex(common.SetupError, 'belongs to UID'):
                common.private(owned)

    def test_missing_source_input_and_reserved_symlinks_are_rejected(self):
        with patch.dict(os.environ, self.env, clear=True), patch.object(setup, 'SOURCE', self.base):
            with self.assertRaisesRegex(common.SetupError, 'Installation input missing'):
                setup.planned_paths(self.value)
        root = Path(self.value['installation'])
        root.mkdir(mode=0o700)
        (root / 'current').symlink_to(self.workspace)
        with self.assertRaisesRegex(common.SetupError, 'outside'):
            setup.current_release(root)

    def test_lock_contention_and_owned_cleanup(self):
        root = Path(self.value['installation'])
        with setup.installation_lock(root):
            with self.assertRaisesRegex(common.SetupError, 'Setup busy'):
                with setup.installation_lock(root):
                    self.fail('competing setup acquired the lock')
            self.assertTrue((root / '.setup.lock').is_dir())
        self.assertFalse((root / '.setup.lock').exists())
        with self.assertRaises(KeyboardInterrupt):
            with setup.installation_lock(root):
                raise KeyboardInterrupt
        self.assertFalse((root / '.setup.lock').exists())

    def test_installation_lock_creates_missing_root_and_command_parent(self):
        root = self.base / 'new/installation'
        self.assertFalse(root.exists())
        with setup.installation_lock(root):
            self.assertEqual(root.stat().st_mode & 0o777, 0o700)
        release = root / 'releases/first'
        release.mkdir(parents=True)
        command = self.base / ('new-bin/nested/' + COMMAND)
        setup.activate(root, release, command)
        self.assertTrue(command.is_file())
        self.assertEqual(command.parent.stat().st_mode & 0o777, 0o700)

    def test_existing_protected_installation_root_does_not_require_private_mode(self):
        root = Path(self.value['installation'])
        root.mkdir(mode=0o755)
        manual = root / WRAPPER
        manual.write_text('existing manual installation')
        with setup.installation_lock(root):
            self.assertEqual(root.stat().st_mode & 0o777, 0o755)
        self.assertEqual(manual.read_text(), 'existing manual installation')
        root.chmod(0o777)
        with self.assertRaises(common.SetupError):
            with setup.installation_lock(root):
                self.fail('unprotected root accepted')
        root.chmod(0o755)
        with self.assertRaises(common.SetupError):
            common.private(root)

    def test_path_guidance_has_executable_export_without_changing_profile(self):
        directory = self.base / 'command with spaces'
        with patch.dict(os.environ, self.env, clear=True), patch('builtins.print') as output:
            setup.path_guidance(str(directory / COMMAND))
        lines = [call.args[0] for call in output.call_args_list]
        export = next(line.strip() for line in lines if line.strip().startswith('export PATH='))
        result = subprocess.run(['bash', '-c', export + '\nprintf "%s" "$PATH"'], env=self.env,
                                capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, str(directory) + ':' + self.env['PATH'])
        self.assertIn('~/.bashrc', '\n'.join(lines))
        self.assertFalse((self.home / '.bashrc').exists())
        with patch.dict(os.environ, self.env | {'PATH': str(directory)}, clear=True), patch('builtins.print') as output:
            setup.path_guidance(str(directory / COMMAND))
            output.assert_not_called()

    def test_activation_preserves_flat_install_and_supports_atomic_rerun(self):
        root, first = self.release()
        manual = root / WRAPPER
        manual.write_text('manual wrapper remains')
        command = Path(self.value['command'])
        setup.activate(root, first, command)
        self.assertEqual(setup.current_release(root), first)
        self.assertEqual(command.read_text(), setup.dispatcher(root))
        self.assertEqual(manual.read_text(), 'manual wrapper remains')
        second = root / 'releases/second'
        second.mkdir(mode=0o700)
        setup.activate(root, second, command)
        self.assertEqual(setup.current_release(root), second)
        self.assertTrue(first.exists())

    def test_failed_first_command_publication_rolls_back_pointer(self):
        root, release = self.release()
        command = Path(self.value['command'])
        with patch.object(setup.os, 'link', side_effect=OSError('publication failed')):
            with self.assertRaises(OSError):
                setup.activate(root, release, command)
        self.assertFalse((root / 'current').exists())
        self.assertFalse(command.exists())
        self.assertFalse(list(root.glob('.current.*')))
        self.assertFalse(list(command.parent.glob('.' + COMMAND + '.*')))

    def test_unrelated_command_and_interrupted_update_leave_previous_release(self):
        root, first = self.release()
        command = Path(self.value['command'])
        setup.activate(root, first, command)
        second = root / 'releases/second'
        second.mkdir(mode=0o700)
        real_replace = setup.os.replace
        def interrupted(source, target):
            if Path(target) == root / 'current':
                raise KeyboardInterrupt
            return real_replace(source, target)
        with patch.object(setup.os, 'replace', side_effect=interrupted):
            with self.assertRaises(KeyboardInterrupt):
                setup.activate(root, second, command)
        self.assertEqual(setup.current_release(root), first)
        command.write_text('unrelated replacement')
        with self.assertRaisesRegex(common.SetupError, 'unrelated file'):
            setup.activate(root, second, command)
        self.assertEqual(command.read_text(), 'unrelated replacement')

    def test_image_inspection_distinguishes_absence_from_engine_errors(self):
        self.assertEqual(setup.image_identity('prepared', self.env), 'sha256:' + 'a' * 64)
        self.assertEqual(setup.image_identity('absent', self.env | {'SETUP_TEST_MISSING': '1'}), '')
        with self.assertRaisesRegex(common.SetupError, 'engine errors'):
            setup.image_identity('error', self.env | {'SETUP_TEST_FAIL': 'inspect'})
        self.assertFalse(any(c['args'][0] in ('build', 'pull') for c in self.calls()))

    def test_recipe_acquisition_preserves_pins_and_build_failure(self):
        _, release = self.release()
        env = self.env | {name('MAINTENANCE'): '1'}
        with patch.object(setup, 'image_identity', side_effect=['', 'sha256:' + 'b' * 64]):
            identity = setup.build_image(release, 'network/guard-build.Containerfile', 'localhost/test:unique', env)
        self.assertEqual(identity, 'sha256:' + 'b' * 64)
        calls = self.calls()
        pull = next(c for c in calls if c['args'][0] == 'pull')
        self.assertEqual(pull['args'][1], 'docker.io/library/alpine@sha256:c64c687cbea9300178b30c95835354e34c4e4febc4badfe27102879de0483b5e')
        build = next(c for c in calls if c['args'][0] == 'build')
        self.assertIn('--pull=never', build['args'])
        self.assertTrue(all(c['maintenance'] == '1' for c in calls))
        with patch.object(setup, 'image_identity', return_value='sha256:' + 'b' * 64):
            with self.assertRaises(common.SetupError):
                setup.build_image(release, 'Containerfile', 'localhost/test:failure', env | {'SETUP_TEST_FAIL': 'build'})

    def test_runtime_build_follows_the_profile(self):
        _, release = self.release()
        env = self.env | {name('MAINTENANCE'): '1'}
        identity = 'sha256:' + 'c' * 64
        with patch.object(setup.PROFILE, 'runtime_build', 'recipe'), \
                patch.object(setup, 'build_image', return_value=identity) as build, \
                patch.object(setup, 'run') as run:
            self.assertEqual(setup.build_runtime(release, 'localhost/test:recipe', env), identity)
        build.assert_called_once_with(release, 'Containerfile', 'localhost/test:recipe', env)
        run.assert_not_called()
        with patch.object(setup.PROFILE, 'runtime_build', 'wrapper'), \
                patch.object(setup, 'build_image') as build, \
                patch.object(setup, 'run') as run, \
                patch.object(setup, 'image_identity', return_value=identity) as inspect:
            self.assertEqual(setup.build_runtime(release, 'localhost/test:wrapper', env), identity)
        build.assert_not_called()
        command, used = run.call_args.args
        self.assertEqual(command, ['bash', release / PROFILE.wrapper, '--container-build'])
        self.assertEqual(used, env | {name('NETWORK'): 'unrestricted', name('IMAGE'): 'localhost/test:wrapper'})
        self.assertEqual(used[name('MAINTENANCE')], '1')
        self.assertEqual(run.call_args.kwargs['input'], '')
        inspect.assert_called_once_with('localhost/test:wrapper', env)
        with patch.object(setup.PROFILE, 'runtime_build', 'wrapper'), patch.object(setup, 'run'), \
                patch.object(setup, 'image_identity', return_value=''):
            with self.assertRaisesRegex(common.SetupError, 'unavailable after preparation'):
                setup.build_runtime(release, 'localhost/test:missing', env)

    def test_mode_specific_artifacts_and_scoped_maintenance(self):
        _, release = self.release()
        value = self.value.copy()
        with patch.object(setup, 'run') as run, patch.object(setup, 'build_image') as build:
            setup.prepare_artifacts(value, None, release, self.env, {'runtime': 'a' * 64}, False, [])
            self.assertIn(':setup-', value['image'])
            self.assertEqual(value['image_id'], 'a' * 64)
            build.assert_not_called()
            self.assertEqual(run.call_args.args[1][name('MAINTENANCE')], '1')
            self.assertEqual(value['proxy_image'], '')
        # Compilation uses the existing packaging script and an immutable toolchain.
        second = release.parent / 'provider'
        second.mkdir(mode=0o700)
        setup.copy_inputs(second)
        value = self.value | {'network': 'provider', 'endpoint': 'default',
                              'runtime_dir': str(self.base / 'egress')}
        with patch.object(setup, 'run') as run, patch.object(setup, 'build_image') as build:
            setup.prepare_artifacts(value, None, second, self.env,
                                    {'runtime': 'a' * 64, 'toolchain': 'b' * 64, 'proxy': 'c' * 64}, False, [])
            build.assert_not_called()
            compile_call = next(call for call in run.call_args_list if call.args[0][0] == 'bash')
            self.assertEqual(compile_call.args[1]['SANDBOX_GUARD_TOOLCHAIN'], 'b' * 64)
            self.assertEqual(compile_call.args[1][name('MAINTENANCE')], '1')
            self.assertEqual(value['proxy_image'], 'c' * 64)
            self.assertEqual(value['guard_sources_sha256'], common.source_identity(second))
        env = common.runtime_environment(value, second, overrides=False)
        self.assertNotIn(name('MAINTENANCE'), env)
        self.assertNotIn(CREDENTIAL, env)
        self.assertFalse('MAINTENANCE' in json.dumps(value))

    def test_fresh_and_refresh_builds_keep_previous_runtime_tag(self):
        _, release = self.release()
        value = self.value.copy()
        original = value['image']
        for refresh, runtime in ((False, ''), (True, 'a' * 64)):
            # The runtime dispatch point covers both recipe and wrapper builds.
            with patch.object(setup, 'build_runtime', return_value='b' * 64) as build:
                setup.prepare_artifacts(value, None, release, self.env, {'runtime': runtime}, refresh, [])
                build.assert_called_once()
                self.assertNotEqual(build.call_args.args[1], original)
                self.assertEqual(value['image_id'], 'b' * 64)
        with patch.object(setup, 'build_runtime', side_effect=common.SetupError('build failed')):
            with self.assertRaises(common.SetupError):
                setup.prepare_artifacts(self.value.copy(), None, release, self.env, {'runtime': ''}, False, [])

    def test_guard_reuse_requires_preflight_and_matching_source_identity(self):
        root, old = self.release()
        (old / 'network/bin').mkdir(mode=0o700)
        for name in (GUARD, GUARD + '.sha256'):
            (old / 'network/bin' / name).write_text('fixture')
        candidate = root / 'releases/candidate'
        candidate.mkdir(mode=0o700)
        setup.copy_inputs(candidate)
        previous = self.value | {'guard_sources_sha256': common.source_identity(old)}
        value = previous | {'network': 'offline', 'endpoint': 'default'}
        images = {'runtime': 'a' * 64, 'toolchain': 'b' * 64, 'guard_release': str(old)}
        with patch.object(setup, 'run', side_effect=[None, common.SetupError('digest mismatch')]):
            with self.assertRaisesRegex(common.SetupError, 'digest mismatch'):
                setup.prepare_artifacts(value, previous, candidate, self.env, images, False, [])
        self.assertFalse((candidate / ('network/bin/' + GUARD)).exists())

    def test_preferences_schema_secrets_duplicates_and_permissions_are_rejected(self):
        _, release = self.release()
        path = release / 'setup.json'
        original = path.read_text()
        for data in (self.value | {'api_key': 'SYNTHETIC_SECRET'}, self.value | {'schema_version': 3},
                     self.value | {'schema_version': 1}, self.value | {'memory_limit': '0'},
                     self.value | {'cpu_limit': 'max'}, self.value | {'pids_limit': '-1'},
                     self.value | {'run_timeout': ''}, self.value | {'memory_limit': '4G'},
                     {k: v for k, v in self.value.items() if k != 'pids_limit'},
                     self.value | {'schema_version': True}, self.value | {'podman': 'yes'},
                     self.value | {'image_id': 'mutable:tag'}):
            path.write_text(json.dumps(data))
            with self.assertRaises(common.SetupError):
                common.load(path)
        path.write_text('{"schema_version":1,"schema_version":1}')
        with self.assertRaises(common.SetupError):
            common.load(path)
        path.write_text(original)
        path.chmod(0o644)
        with self.assertRaisesRegex(common.SetupError, 'private'):
            common.load(path)
        path.chmod(0o600)
        self.assertEqual(common.load(path), self.value)

    def test_schema_one_preferences_upgrade_with_default_budgets(self):
        _, release = self.release()
        path = release / 'setup.json'
        legacy = {k: v for k, v in self.value.items() if k not in common.BUDGETS} | {'schema_version': 1}
        path.write_text(json.dumps(legacy))
        upgraded = common.load(path)
        self.assertEqual(upgraded['schema_version'], 2)
        self.assertEqual({k: upgraded[k] for k in common.BUDGETS},
                         dict(memory_limit='4g', cpu_limit='2', pids_limit='512', run_timeout='0'))
        for data in (legacy | {'memory_limit': '8g'}, legacy | {'unknown': 'x'},
                     {k: v for k, v in legacy.items() if k != 'yolo'}):
            path.write_text(json.dumps(data))
            with self.assertRaises(common.SetupError):
                common.load(path)
        saved = release / 'resaved.json'
        common.save(saved, upgraded)
        self.assertEqual(json.loads(saved.read_text())['schema_version'], 2)

    def test_saved_budgets_supplied_unless_explicitly_present(self):
        value = self.value | {'memory_limit': '8g', 'cpu_limit': '1.5', 'pids_limit': '1024', 'run_timeout': '60'}
        with patch.dict(os.environ, self.env | {name('PIDS_LIMIT'): '2048', name('RUN_TIMEOUT'): ''}, clear=True):
            env = common.runtime_environment(value, self.base)
            stripped = common.runtime_environment(value, self.base, overrides=False)
        self.assertEqual((env[name('MEMORY_LIMIT')], env[name('CPU_LIMIT')]), ('8g', '1.5'))
        self.assertEqual((env[name('PIDS_LIMIT')], env[name('RUN_TIMEOUT')]), ('2048', ''))
        self.assertEqual((stripped[name('PIDS_LIMIT')], stripped[name('RUN_TIMEOUT')]), ('1024', '60'))

    def test_runtime_defaults_respect_present_empty_overrides_and_dynamic_socket(self):
        value = self.value | {'network': 'provider', 'auth': PROVIDER_METHOD, 'endpoint': 'default',
                              'state_dir': str(self.base / 'state'), 'proxy_image': 'b' * 64}
        with patch.dict(os.environ, self.env | {'XDG_RUNTIME_DIR': '/new/session',
                         name('STATE_DIR'): '', YOLO_ENV: '',
                         name('MAINTENANCE'): '1', CREDENTIAL: 'SYNTHETIC_SECRET'}, clear=True):
            env = common.runtime_environment(value, self.base)
            self.assertEqual(env[name('STATE_DIR')], '')
            self.assertEqual(env[YOLO_ENV], '')
            self.assertEqual(env['CONTAINER_HOST'], 'unix:///new/session/podman/podman.sock')
            self.assertEqual(env[name('NETWORK_PROFILE')], PROFILE.policy_profile(PROVIDER_METHOD))
            prepared = common.runtime_environment(value, self.base, overrides=False)
            self.assertEqual(prepared[name('STATE_DIR')], value['state_dir'])
            self.assertNotIn(name('MAINTENANCE'), prepared)
            self.assertNotIn(CREDENTIAL, prepared)

    def test_managed_launcher_preserves_argv_input_cwd_status_and_explicit_build(self):
        root, release = self.release()
        command = Path(self.value['command'])
        setup.activate(root, release, command)
        # A transparent application stand-in; no engine or model is involved.
        wrapper = release / WRAPPER
        wrapper.write_text('''#!/bin/bash
exec python3 -c 'import json,os,sys; print(json.dumps({"argv":sys.argv[1:],"stdin":sys.stdin.read(),"cwd":os.getcwd(),"pid":os.getpid(),"network":os.environ.get("@NETWORK@"),"maintenance":os.environ.get("@MAINTENANCE@")})); sys.exit(int(os.environ.get("SETUP_APP_EXIT","0")))' "$@"
'''.replace('@NETWORK@', name('NETWORK')).replace('@MAINTENANCE@', MAINTENANCE))
        args = ['--container-build', 'space value', '', '--version']
        env = self.env | {name('NETWORK'): '', name('MAINTENANCE'): '1', 'SETUP_APP_EXIT': '17'}
        proc = subprocess.Popen([str(command), *args], cwd=self.workspace, env=env,
                                stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        output, error = proc.communicate('payload\n', timeout=10)
        self.assertEqual(proc.returncode, 17, error)
        message = json.loads(output)
        self.assertEqual(message['argv'], args)
        self.assertEqual(message['stdin'], 'payload\n')
        self.assertEqual(message['cwd'], str(self.workspace))
        self.assertEqual(message['pid'], proc.pid)
        self.assertEqual(message['network'], '')
        self.assertEqual(message['maintenance'], '1')

    def test_managed_real_wrapper_admits_saved_modes_and_preserves_network_overrides(self):
        root, release = self.release()
        command = Path(self.value['command'])
        setup.activate(root, release, command)
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

    def test_managed_launcher_rejects_future_worktree_and_state_conflicts(self):
        root, release = self.release()
        command = Path(self.value['command'])
        setup.activate(root, release, command)
        for cwd, args, controls in ((self.base, [], {}), (self.workspace, ['--container-git-worktree'], {}),
                                   (self.workspace, [], {name('STATE_DIR'): str(self.base),
                                                        CONFIG_ENV: '/some/shared/config'})):
            result = subprocess.run([str(command), *args], cwd=cwd, env=self.env | controls,
                                    capture_output=True, text=True, timeout=10)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn('unsafe managed configuration', result.stderr)
        self.assertFalse(self.calls())

    def test_command_migration_retires_old_dispatcher_and_protects_actual_aliases(self):
        root, first = self.release()
        old_command = Path(self.value['command'])
        setup.activate(root, first, old_command)
        self.value['command'] = str(self.base / ('new-bin/' + COMMAND))
        _, second = self.release('second')
        (second / WRAPPER).write_text('printf REACHED_WRAPPER')
        command = Path(self.value['command'])
        setup.activate(root, second, command)
        self.assertFalse(old_command.exists())
        result = subprocess.run([str(command)], cwd=old_command.parent, env=self.env,
                                capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, 'REACHED_WRAPPER')
        # A copied or aliased entry point must protect its own directory entry,
        # even though setup.json still points at the safe canonical command.
        alias = self.workspace / COMMAND
        alias.symlink_to(command)
        parent_alias = self.base / 'workspace-alias'
        parent_alias.symlink_to(self.workspace, target_is_directory=True)
        for argv in ([str(alias)], ['./' + COMMAND], [str(parent_alias / alias.name)]):
            result = subprocess.run(argv, cwd=self.workspace, env=self.env,
                                    capture_output=True, text=True, timeout=10)
            self.assertNotEqual(result.returncode, 0)
            self.assertNotIn('REACHED_WRAPPER', result.stdout)
        alias.unlink()
        shutil.copyfile(command, alias)
        alias.chmod(0o700)
        result = subprocess.run([str(alias)], cwd=self.workspace, env=self.env,
                                capture_output=True, text=True, timeout=10)
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(self.calls())

    def test_legacy_dispatcher_fails_closed_until_atomically_upgraded(self):
        root, first = self.release()
        command = Path(self.value['command'])
        setup.activate(root, first, command)
        command.write_text(setup.dispatcher(root, legacy=True))
        result = subprocess.run([str(command), '--version'], cwd=self.workspace, env=self.env,
                                capture_output=True, text=True, timeout=10)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('--container-setup', result.stderr)
        _, second = self.release('second')
        (second / WRAPPER).write_text('printf UPGRADED_WRAPPER')
        setup.activate(root, second, command)
        self.assertEqual(command.read_text(), setup.dispatcher(root))
        result = subprocess.run([command.name, '--version'], cwd=self.workspace, env=self.env,
                                capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, 'UPGRADED_WRAPPER')

    def test_launcher_checks_every_symlink_hop_and_kernel_dotdot_semantics(self):
        root, release = self.release()
        command = Path(self.value['command'])
        setup.activate(root, release, command)
        (release / WRAPPER).write_text('printf REACHED_WRAPPER')
        inner = self.workspace / command.name
        inner.symlink_to(command)
        outer = self.base / 'outer'
        outer.symlink_to(inner)
        (self.workspace / 'sub').mkdir()
        child_alias = self.base / 'child-alias'
        child_alias.symlink_to(self.workspace / 'sub', target_is_directory=True)
        # This safe decoy would incorrectly pass if '..' were collapsed before
        # traversing child-alias (the kernel resolves it after the symlink).
        (self.base / command.name).symlink_to(command)
        for path in (outer, child_alias / '..' / command.name):
            result = subprocess.run([str(path)], cwd=self.workspace, env=self.env,
                                    capture_output=True, text=True, timeout=10)
            self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertNotIn('REACHED_WRAPPER', result.stdout)
        safe_inner = self.base / 'safe-inner'
        safe_inner.symlink_to(command)
        safe_outer = self.base / 'safe-outer'
        safe_outer.symlink_to('safe-inner')
        result = subprocess.run([str(safe_outer)], cwd=self.workspace, env=self.env,
                                capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, 'REACHED_WRAPPER')

    def test_command_path_alias_does_not_retire_the_active_directory_entry(self):
        root, first = self.release()
        command = Path(self.value['command'])
        setup.activate(root, first, command)
        (command.parent / 'sub').mkdir()
        parent_alias = self.base / 'bin-alias'
        parent_alias.symlink_to(command.parent, target_is_directory=True)
        for index, alias in enumerate((command.parent / 'sub/..' / command.name, parent_alias / command.name)):
            self.value['command'] = str(alias)
            _, release = self.release('alias-' + str(index))
            (release / WRAPPER).write_text('printf ALIAS_WRAPPER')
            setup.activate(root, release, alias)
            self.assertTrue(command.is_file())
            result = subprocess.run([str(alias)], cwd=self.workspace, env=self.env,
                                    capture_output=True, text=True, timeout=10)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(result.stdout, 'ALIAS_WRAPPER')
        # Hardlinks share an inode but are separate entries: retire the old name
        # while keeping the new command. samefile() would miss this migration.
        linked = self.base / 'hardlinked-command'
        os.link(command, linked)
        self.value['command'] = str(linked)
        _, release = self.release('hardlink')
        (release / WRAPPER).write_text('printf HARDLINK_WRAPPER')
        setup.activate(root, release, linked)
        self.assertFalse(command.exists())
        self.assertTrue(linked.is_file())
        result = subprocess.run([str(linked)], cwd=self.workspace, env=self.env,
                                capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, 'HARDLINK_WRAPPER')

    def test_failed_command_retirement_rolls_back_pointer_and_command_publication(self):
        root, first = self.release()
        old_command = Path(self.value['command'])
        setup.activate(root, first, old_command)
        self.value['command'] = str(self.base / ('new-bin/' + COMMAND))
        _, second = self.release('second')
        command = Path(self.value['command'])
        real_unlink = Path.unlink
        def refuse_retirement(path, *args, **kwargs):
            if path == old_command:
                raise PermissionError('simulated retirement failure')
            return real_unlink(path, *args, **kwargs)
        for existing_legacy in (False, True):
            with self.subTest(existing_legacy=existing_legacy):
                if existing_legacy:
                    command.parent.mkdir(mode=0o700, exist_ok=True)
                    command.write_text(setup.dispatcher(root, legacy=True))
                    command.chmod(0o700)
                with patch.object(Path, 'unlink', new=refuse_retirement):
                    with self.assertRaises(PermissionError):
                        setup.activate(root, second, command)
                self.assertEqual(setup.current_release(root), first)
                self.assertEqual(old_command.read_text(), setup.dispatcher(root))
                if existing_legacy:
                    self.assertEqual(command.read_text(), setup.dispatcher(root, legacy=True))
                else:
                    self.assertFalse(command.exists())
                self.assertFalse(list(command.parent.glob('.' + COMMAND + '.*')))

    def test_managed_help_bypasses_corrupt_json_python_and_podman(self):
        root, release = self.release()
        command = Path(self.value['command'])
        setup.activate(root, release, command)
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
        root, release = self.release()
        command = Path(self.value['command'])
        setup.activate(root, release, command)
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

    def test_saved_worktree_scope_and_tty_are_forwarded_without_a_wrapper_process(self):
        self.value['worktree'] = True
        root, release = self.release()
        command = Path(self.value['command'])
        setup.activate(root, release, command)
        project = self.base / 'projects/project'
        project.mkdir(parents=True)
        (release / WRAPPER).write_text('''#!/bin/bash
terminal=no
if [[ -t 0 && -t 1 ]]; then terminal=yes; fi
printf 'APP_TTY=%s ARGS=%s\\n' "$terminal" "$*"
''')
        code, output = pty_run([str(command), '--version'], self.env, project, [])
        self.assertEqual(code, 0, output)
        self.assertIn('APP_TTY=yes ARGS=--container-git-worktree --version', output)

    def test_smoke_requires_confirmed_success_and_has_no_maintenance_or_key(self):
        _, release = self.release()
        for trust in (False, True):
            value = self.value | {'trust_ca': trust}
            with patch.dict(os.environ, self.env | {name('MAINTENANCE'): '1',
                             CREDENTIAL: 'SYNTHETIC_SECRET'}, clear=True), patch.object(setup, 'run', return_value='SANDBOX_SETUP_SMOKE_OK\n') as run:
                setup.smoke(value, release)
                self.assertEqual(run.call_args.args[0][-1], '--container-shell')
                self.assertNotIn(name('MAINTENANCE'), run.call_args.args[1])
                self.assertNotIn(CREDENTIAL, run.call_args.args[1])
                self.assertIn('unrestricted ' + ('1' if trust else '0'), run.call_args.kwargs['input'])
                self.assertIn(' 4294967296 2000000000 512 <<', run.call_args.kwargs['input'])
                workspace = Path(run.call_args.kwargs['cwd'])
                self.assertNotEqual(workspace, Path.cwd())
                self.assertFalse(workspace.exists())
        value = self.value | {'memory_limit': '8g', 'cpu_limit': '1.5', 'pids_limit': '1024'}
        with patch.dict(os.environ, self.env | {name('MEMORY_LIMIT'): '1g'}, clear=True), \
                patch.object(setup, 'run', return_value='SANDBOX_SETUP_SMOKE_OK\n') as run:
            setup.smoke(value, release)
            self.assertIn(' 8589934592 1500000000 1024 <<', run.call_args.kwargs['input'])
            self.assertEqual(run.call_args.args[1][name('MEMORY_LIMIT')], '8g')
        with patch.object(setup, 'run', return_value='version-only\n'):
            with self.assertRaisesRegex(common.SetupError, 'did not confirm readiness'):
                setup.smoke(self.value, release)
        with patch.object(setup, 'run', side_effect=common.SetupError('guard failed')):
            with self.assertRaises(common.SetupError):
                setup.smoke(self.value, release)

    def test_failed_smoke_shows_a_bounded_sanitized_stderr_excerpt(self):
        refusal = setup.PREFIX + 'State must be private: /home/user/.shared (chmod 700)'
        program = ('printf "notice one\\n\\n%s\\n" ' + shlex.quote(refusal) + ' >&2; exit 1')
        with patch('sys.stderr', new=io.StringIO()) as err:
            with self.assertRaisesRegex(common.SetupError, 'Setup command failed'):
                setup.run(['bash', '-c', program], self.env, capture=True, excerpt=True)
        self.assertIn(setup.PREFIX + 'smoke: ' + refusal, err.getvalue())
        self.assertIn(setup.PREFIX + 'smoke: notice one', err.getvalue())
        # Without the flag, other captured commands keep their previous output.
        with patch('sys.stderr', new=io.StringIO()) as err:
            with self.assertRaises(common.SetupError):
                setup.run(['bash', '-c', program], self.env, capture=True)
        self.assertEqual(err.getvalue(), '')
        hostile = '\x1b[31mred\x1b[0m\x07bell\r\n' + ''.join('line %d\n' % index for index in range(9)) + 'x' * 5000
        excerpt = setup.stderr_excerpt(hostile.encode())
        self.assertEqual(len(excerpt), 5)
        self.assertEqual(excerpt[-1], 'x' * 2048)
        self.assertEqual(setup.stderr_excerpt('\x1b[31mred\x1b[0m\x07bell'), ['[31mred[0mbell'])
        self.assertTrue(all(char.isprintable() for line in excerpt for char in line))
        _, release = self.release()
        missing = setup.Captured('version-only\n')
        missing.stderr = setup.PREFIX + 'warning before exit\n'
        with patch.object(setup, 'run', return_value=missing) as run, patch('sys.stderr', new=io.StringIO()) as err:
            with self.assertRaisesRegex(common.SetupError, 'did not confirm readiness'):
                setup.smoke(self.value, release)
        self.assertTrue(run.call_args.kwargs['excerpt'])
        self.assertIn(setup.PREFIX + 'smoke: ' + setup.PREFIX + 'warning before exit', err.getvalue())
        ready = setup.Captured('SANDBOX_SETUP_SMOKE_OK\n')
        ready.stderr = setup.PREFIX + 'routine notice\n'
        with patch.object(setup, 'run', return_value=ready), patch('sys.stderr', new=io.StringIO()) as err:
            setup.smoke(self.value, release)
        self.assertEqual(err.getvalue(), '')

    def test_restricted_smoke_requires_qualification_and_displays_its_status(self):
        _, release = self.release()
        value = self.value | {'network':'offline','auth':'none'}
        passing='SANDBOX_QUALIFICATION_STATUS=locally-qualified\nSANDBOX_QUALIFICATION_OK\n'
        with patch.dict(os.environ,self.env | {CREDENTIAL:'SYNTHETIC_SECRET',
                        name('MAINTENANCE'):'1'},clear=True), \
                patch.object(setup,'run',side_effect=[passing,'SANDBOX_SETUP_SMOKE_OK\n']) as run, \
                patch('builtins.print') as output:
            setup.smoke(value,release)
            self.assertEqual(run.call_args_list[0].args[0][-1],'--container-qualify')
            self.assertEqual(run.call_args_list[1].args[0][-1],'--container-shell')
            for call in run.call_args_list:
                self.assertNotIn(CREDENTIAL,call.args[1])
                self.assertNotIn(name('MAINTENANCE'),call.args[1])
            self.assertTrue(any('not release-measured' in str(call) for call in output.call_args_list))
        for result in ('version-only\n','SANDBOX_QUALIFICATION_OK\n'):
            with patch.object(setup,'run',return_value=result) as run, self.assertRaises(common.SetupError):
                setup.smoke(value,release)
            self.assertEqual(run.call_count,1)

    def test_authentication_is_optional_direct_terminal_and_no_automatic_model_call(self):
        _, release = self.release()
        # The login checks apply only to profiles with an interactive login method.
        for failure in ((None, common.SetupError('login failed'), KeyboardInterrupt()) if LOGIN_METHOD else ()):
            with patch.dict(os.environ, self.env, clear=True), patch.object(setup, 'yes', return_value=True), patch.object(setup, 'run', side_effect=failure) as run, patch('builtins.print'):
                status = setup.authenticate(self.value | {'auth': LOGIN_METHOD}, release)
                self.assertEqual(run.call_args.args[0][2:], LOGIN_ARGS)
                self.assertNotIn('capture', run.call_args.kwargs)
                self.assertNotIn(CREDENTIAL, run.call_args.args[1])
                self.assertIn('verified' if failure is None else 'pending', status)
        for mode, auth, expected in (('offline', 'none', 'not applicable'), ('provider', KEY_METHOD, 'pending'),
                                     *((('provider', LOGIN_METHOD, 'pending'),) if LOGIN_METHOD else ())):
            with patch.object(setup, 'yes', return_value=False), patch.object(setup, 'run') as run, patch('builtins.print'):
                value = self.value | {'network': mode, 'auth': auth}
                self.assertEqual(setup.authenticate(value, release), expected)
                run.assert_not_called()

    def test_empty_login_arguments_start_the_interactive_agent(self):
        # A profile whose agent has no login command declares empty login_args:
        # setup offers a sign-in session through the installed wrapper itself.
        _, release = self.release()
        method = next(iter(PROFILE.auth))
        item = {'description': 'signs in interactively', 'policy_profile': 'interactive-test',
                'hosts': ['login.example.com'], 'login_args': []}
        value = self.value | {'network': 'provider', 'auth': method}
        with patch.dict(setup.PROFILE.auth, {method: item}):
            for failure in (None, common.SetupError('session failed'), KeyboardInterrupt()):
                with self.subTest(failure=failure), patch.dict(os.environ, self.env, clear=True), \
                        patch.object(setup, 'yes', return_value=True) as ask, \
                        patch.object(setup, 'run', side_effect=failure) as run, patch('builtins.print') as output:
                    status = setup.authenticate(value, release)
                    self.assertIn('interactively', ask.call_args.args[0])
                    self.assertEqual(run.call_args.args[0], ['bash', release / PROFILE.wrapper])
                    self.assertTrue(run.call_args.kwargs['terminal'])
                    self.assertIsNone(run.call_args.kwargs['timeout'])
                    self.assertNotIn('capture', run.call_args.kwargs)
                    printed = ' '.join(str(call) for call in output.call_args_list)
                    if failure is None:
                        self.assertIn('interactive sign-in session exited successfully', status)
                        self.assertNotIn('Next authentication action', printed)
                    else:
                        self.assertEqual(status, 'pending')
                        self.assertIn('sign in inside the interactive session', printed)
            with patch.object(setup, 'yes', return_value=False), patch.object(setup, 'run') as run, \
                    patch('builtins.print') as output:
                self.assertEqual(setup.authenticate(value, release), 'pending')
                run.assert_not_called()
                printed = ' '.join(str(call) for call in output.call_args_list)
                self.assertIn('Next authentication action: ' + shlex.quote(value['command'])
                              + ' (sign in inside the interactive session', printed)
            with patch.object(setup, 'yes', return_value=True), patch.object(setup, 'run') as run, \
                    patch('builtins.print'):
                run.call_args = None
                worktree = value | {'worktree': True}
                setup.authenticate(worktree, release)
                self.assertEqual(run.call_args.args[0], ['bash', release / PROFILE.wrapper, '--container-git-worktree'])

    def test_existing_shared_openspec_permissions_are_preserved(self):
        config = self.home / CONFIG_HOME
        config.parent.mkdir(parents=True, exist_ok=True)
        config.mkdir(mode=0o700)
        openspec = self.home / '.config/openspec'
        openspec.mkdir(mode=0o755, parents=True)
        common.prepare_state(self.env, create=True)
        self.assertEqual(openspec.stat().st_mode & 0o777, 0o755)
        self.assertEqual(config.stat().st_mode & 0o777, 0o700)

    def test_profile_declared_shared_directory_privacy(self):
        config = self.home / CONFIG_HOME
        config.mkdir(mode=0o700, parents=True)
        shared = self.home / '.shared-test-state'
        shared.mkdir(mode=0o755)
        shared.chmod(0o755)
        with patch.object(common.PROFILE, 'shared_dirs', ('.shared-test-state',)):
            with patch.object(common.PROFILE, 'private_shared_dirs', False):
                checked = common.prepare_state(self.env, create=True)
                self.assertEqual(checked, [(config.resolve(), True), (shared.resolve(), False)])
            with patch.object(common.PROFILE, 'private_shared_dirs', True):
                with self.assertRaises(common.SetupError) as raised:
                    common.prepare_state(self.env, create=True)
                self.assertIn(str(shared), str(raised.exception))
                self.assertIn('chmod 700', str(raised.exception))
                shared.chmod(0o700)
                checked = common.prepare_state(self.env, create=True)
                self.assertEqual(checked, [(config.resolve(), True), (shared.resolve(), True)])
        self.assertEqual(shared.stat().st_mode & 0o777, 0o700)
        self.assertEqual(self.calls(), [])

    def test_timeout_allows_owned_child_cleanup_without_killing_setup(self):
        marker = self.base / 'child-cleaned'
        program = 'trap ' + shlex.quote('touch ' + shlex.quote(str(marker)) + '; exit 0') + ' TERM; while :; do sleep 1; done'
        started = time.monotonic()
        with self.assertRaisesRegex(common.SetupError, 'timed out'):
            setup.run(['bash', '-c', program], self.env, capture=True, timeout=0.2)
        self.assertTrue(marker.exists())
        self.assertLess(time.monotonic() - started, 5)

    def assert_timeout_reaps_descendant(self, close_pipes_on_term):
        # Isolate Linux subreaper status in a helper so the test can collect its
        # orphaned descendant without depending on PID 1 or leaving zombies.
        harness = r'''
import ctypes, importlib.util, os, pathlib, shlex, signal, sys, time
assert ctypes.CDLL(None).prctl(36, 1, 0, 0, 0) == 0  # PR_SET_CHILD_SUBREAPER
root, pidfile, ready = map(pathlib.Path, sys.argv[1:4])
sys.path.insert(0, str(root / 'setup'))
spec = importlib.util.spec_from_file_location('sandbox_setup', root / 'setup/setup.py')
setup = importlib.util.module_from_spec(spec)
spec.loader.exec_module(setup)
child = 'import os,signal,time,pathlib,sys\n'
if sys.argv[4] == '1':
    child += 'def terminate(signum, frame):\n    os.close(1)\n    os.close(2)\nsignal.signal(signal.SIGTERM, terminate)\n'
child += 'pathlib.Path(sys.argv[1]).touch()\ntime.sleep(300)\n'
program = (shlex.join([sys.executable, '-I', '-c', child, str(ready)]) +
           ' & descendant=$!; printf "%s %s" "$$" "$descendant" > ' + shlex.quote(str(pidfile)) +
           '; while [[ ! -f ' + shlex.quote(str(ready)) + ' ]]; do sleep 0.01; done; exit 0')
reaped = False
try:
    started = time.monotonic()
    try:
        setup.run(['bash', '-c', program], os.environ.copy(), capture=True, timeout=0.3)
    except setup.SetupError as error:
        assert 'timed out' in str(error), str(error)
    else:
        raise AssertionError('missing timeout')
    assert ready.exists(), 'descendant did not initialize'
    leader, descendant = map(int, pidfile.read_text().split())
    deadline = time.monotonic() + 3
    while time.monotonic() < deadline:
        pid, status = os.waitpid(descendant, os.WNOHANG)
        if pid:
            reaped = True
            assert os.WIFSIGNALED(status), status
            if sys.argv[4] == '1':
                assert os.WTERMSIG(status) == signal.SIGKILL, status
            break
        time.sleep(0.01)
    assert reaped, 'owned descendant survived leader exit and timeout'
    assert time.monotonic() - started < 5
    print('DESCENDANT_REAPED')
finally:
    if not reaped and pidfile.exists():
        leader, descendant = map(int, pidfile.read_text().split())
        try: os.killpg(leader, signal.SIGKILL)
        except ProcessLookupError: pass
        try: os.waitpid(descendant, 0)
        except ChildProcessError: pass
'''
        result = subprocess.run([sys.executable, '-I', '-c', harness, str(ROOT),
                                 str(self.base / 'pids'), str(self.base / 'ready'),
                                 '1' if close_pipes_on_term else '0'],
                                env=self.env, capture_output=True, text=True, timeout=12)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn('DESCENDANT_REAPED', result.stdout)

    def test_timeout_kills_descendant_after_leader_has_already_exited(self):
        self.assert_timeout_reaps_descendant(False)

    def test_timeout_kills_descendant_that_closes_pipes_but_ignores_termination(self):
        self.assert_timeout_reaps_descendant(True)

    def test_managed_launcher_exec_preserves_signal_delivery(self):
        root, release = self.release()
        command = Path(self.value['command'])
        setup.activate(root, release, command)
        (release / WRAPPER).write_text('''#!/bin/bash
exec python3 -c 'import os,signal; print(os.getpid(),flush=True); signal.pause()'
''')
        proc = subprocess.Popen([str(command)], env=self.env, cwd=self.workspace,
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        try:
            self.assertTrue(select.select([proc.stdout], [], [], 5)[0])
            self.assertEqual(int(proc.stdout.readline()), proc.pid)
            proc.send_signal(signal.SIGTERM)
            proc.communicate(timeout=5)
            self.assertEqual(proc.returncode, -signal.SIGTERM)
        finally:
            if proc.poll() is None:
                proc.kill()
            proc.communicate()

    def test_compiler_failure_removes_only_setup_owned_container_and_artifacts(self):
        output = self.base / 'guard-output'
        output.mkdir(mode=0o700)
        cidfile = output / ('.setup-guard.' + 'f' * 32)
        env = self.env | {name('MAINTENANCE'): '1', 'SANDBOX_GUARD_SETUP_CIDFILE': str(cidfile)}
        result = subprocess.run(['bash', str(ROOT / 'network/build-guard.sh'), str(output)],
                                env=env, capture_output=True, text=True, timeout=10)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(list(output.iterdir()), [])
        calls = self.calls()
        compile_call = next(c for c in calls if c['args'][0] == 'run')
        self.assertIn('--network=none', compile_call['args'])
        self.assertEqual([c['args'][-1] for c in calls if c['args'][0] == 'rm'], ['d' * 64])


if __name__ == '__main__':
    unittest.main()

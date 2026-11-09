"""Synthetic Pi wrapper contracts; no engine or provider credentials."""
import itertools
import json
import os
from pathlib import Path
import pty
import signal
import socket
import subprocess
import tempfile
import time
import unittest

ROOT = Path(__file__).resolve().parents[1]
WRAPPER = ROOT / 'pi-container.sh'
FAKE = (ROOT / 'tests/fake_podman.py').read_text()

class WrapperTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='pi-wrapper-')
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        self.bin = self.base / 'bin'
        self.bin.mkdir()
        fake = self.bin / 'podman'
        fake.write_text(FAKE)
        fake.chmod(0o755)
        self.project = self.base / 'parent with spaces' / 'my project'
        self.project.mkdir(parents=True)
        self.home = self.base / 'home'
        self.home.mkdir()
        self.state = self.home / '.pi'
        self.agents = self.home / '.agents'
        self.log = self.base / 'calls.jsonl'
        self.env = {k: v for k, v in os.environ.items()
                    if not k.startswith(('PI_', 'CONTAINER_', 'FAKE_'))
                    and k not in ('ANTHROPIC_API_KEY', 'OPENAI_API_KEY', 'GOOGLE_API_KEY')}
        self.env.update(PATH=str(self.bin) + ':' + self.env['PATH'], HOME=str(self.home),
                        FAKE_LOG=str(self.log), FAKE_ROOT=str(ROOT))
        self.sock = socket.socket(socket.AF_UNIX)
        self.sock_path = self.base / 'service.sock'
        self.sock.bind(str(self.sock_path))
        self.addCleanup(self.sock.close)

    def test_fixture_rejects_unknown_and_preserves_records(self):
        result = subprocess.run([str(self.bin / 'podman'), 'unexpected'], env=self.env,
                                capture_output=True, text=True)
        self.assertEqual(result.returncode, 99)
        self.assertEqual(self.calls(), [['unexpected']])
        result = subprocess.run([str(self.bin / 'podman'), 'info'],
                                env=self.env | {'FAKE_INFO_RAW': 'true linux false\n\n'},
                                capture_output=True, text=True)
        self.assertEqual(result.stdout, 'true linux false\n\n')
    def run_wrapper(self, *args, **env):
        self.log.unlink(missing_ok=True)
        return subprocess.run(['bash', str(WRAPPER), *args], cwd=self.project,
                              env=self.env | env, text=True, capture_output=True,
                              timeout=10, umask=0o022)


    def calls(self):
        return [json.loads(line) for line in self.log.read_text().splitlines()] if self.log.exists() else []


    def assert_rejected(self, result):
        self.assertNotEqual(result.returncode, 0, result.stdout)
        self.assertIn('pi-container:', result.stderr)
        self.assertFalse(any(call[0] in ('image', 'build', 'ps', 'run', 'create', 'start') for call in self.calls()))


    def test_help_without_engine_or_state(self):
        result = self.run_wrapper('--container-help', CONTAINER_CONNECTION='bad')
        self.assertEqual(result.returncode, 0, result.stderr)
        for needle in ('Container options:', 'Environment:', 'Deprecated names',
                       'PI_CONTAINER_GITCONFIG exactly 1 mounts ~/.gitconfig read-only',
                       'PI_CONTAINER_IMAGE     image name (default: pi-container)',
                       'PI_CONTAINER_PODMAN    delegation', 'PI_CONTAINER_PODMAN_SOCKET',
                       'PI_CONTAINER_MEMORY_LIMIT', '(default: 4g)', 'PI_CONTAINER_CPU_LIMIT',
                       '(default: 2)', 'PI_CONTAINER_PIDS_LIMIT', '(default: 512)',
                       'PI_CONTAINER_RUN_TIMEOUT', 'PI_CONTAINER_ALLOW_UNSAFE_WORKSPACE',
                       'PI_IMAGE_NAME, PI_ENABLE_PODMAN, PI_PODMAN_SOCKET, PI_MEMORY_LIMIT',
                       'PI_MOUNT_GITCONFIG', 'Pi has no tool-approval layer', '--approve trusts',
                       'do not limit workspace or state storage', '/mnt/<letter>', '/tmp, the caller',
                       'PI_CONTAINER_STATE_DIR', 'PI_BUN_VERSION and PI_PULL_ALWAYS are ignored',
                       'stops the launch until', 'HOME=/pi-home'):
            self.assertIn(needle, result.stdout)
        self.assertEqual(self.calls(), [])
        self.assertFalse(self.state.exists())


    def test_help_without_podman_installed(self):
        minimal = self.base / 'minimal-bin'
        minimal.mkdir()
        for name in ('dirname', 'sed', 'cat'):
            (minimal / name).symlink_to('/usr/bin/' + name)
        result = subprocess.run(['/bin/bash', str(WRAPPER), '--container-help'],
                                env=self.env | {'PATH': str(minimal)}, cwd=self.project,
                                capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(self.state.exists())
        self.assertEqual(self.calls(), [])


    def test_valid_launch_engine_without_delegation(self):
        result = self.run_wrapper('exec', 'prompt with spaces', '')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.calls()[0][0], 'info')
        self.assertFalse(any(c[0] == '--remote' for c in self.calls()))
        self.assertEqual(self.run_args()[-3:], ['exec', 'prompt with spaces', ''])


    def test_engine_failure_matrix_before_image_operations(self):
        infos = ['false linux false', 'true darwin false', '', 'true linux',
                 'true linux maybe', 'yes linux false', 'true linux false extra',
                 'true linux false\ntrue linux false']
        for shell, build, access, info in itertools.product(
                (False, True), (False, True), ('0', '1'), infos):
            with self.subTest(shell=shell, build=build, access=access, info=info):
                args = (['--container-shell'] if shell else []) + (['--container-build'] if build else [])
                result = self.run_wrapper(*args, FAKE_INFO=info,
                                          PI_CONTAINER_PODMAN=access)
                self.assert_rejected(result)
                self.assertFalse(self.state.exists())
                self.assertFalse(any(c[0] == '--remote' for c in self.calls()))
        self.assert_rejected(self.run_wrapper(FAKE_INFO_STATUS='125'))


    def test_unsupported_contexts(self):
        for env in ({'CONTAINER_CONNECTION': 'named'},
                    {'CONTAINER_HOST': 'ssh://host'},
                    {'CONTAINER_HOST': 'tcp://localhost:1234'},
                    {'CONTAINER_HOST': 'unix://relative'},
                    {'CONTAINER_HOST': 'unix:///'},
                    {'FAKE_INFO': 'true linux true'}):
            with self.subTest(env=env):
                self.assert_rejected(self.run_wrapper(**env))


    def test_explicit_unix_launch_connection(self):
        result = self.run_wrapper(CONTAINER_HOST='unix:///visible/launch.sock', FAKE_INFO='true linux true')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(any(c[0] == '--remote' for c in self.calls()))
        self.assertIn('--unsetenv', self.run_args())


    def test_slash_only_endpoints_rejected_before_podman(self):
        endpoints = ('unix://', 'unix:///', 'unix:////', 'unix:////////', 'unix://relative')
        for shell, build, endpoint in itertools.product((False, True), (False, True), endpoints):
            with self.subTest(shell=shell, build=build, endpoint=endpoint):
                options = (['--container-shell'] if shell else []) + (['--container-build'] if build else [])
                self.assert_rejected(self.run_wrapper(*options, CONTAINER_HOST=endpoint))
                self.assertEqual(self.calls(), [])
                self.assertFalse(self.state.exists())
        for endpoint in ('unix:///run/user/1000/podman/podman.sock', 'unix:////visible/socket with spaces.sock'):
            result = self.run_wrapper(CONTAINER_HOST=endpoint, FAKE_INFO='true linux true')
            self.assertEqual(result.returncode, 0, result.stderr)


    def test_verification_normal_terminators_and_socket_spaces(self):
        for shell, build, launch_end, socket_end in itertools.product((False, True), (False, True), ('', '\n'), ('', '\n')):
            with self.subTest(shell=shell, build=build, launch_end=launch_end, socket_end=socket_end):
                options = (['--container-shell'] if shell else []) + (['--container-build'] if build else [])
                result = self.run_wrapper(*options, PI_CONTAINER_PODMAN='1',
                                          PI_CONTAINER_PODMAN_SOCKET=str(self.sock_path),
                                          FAKE_INFO_RAW='true linux false' + launch_end,
                                          FAKE_SOCKET_INFO_RAW='true\n/host/socket with spaces.sock' + socket_end)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertIn('/host/socket with spaces.sock:/run/podman/podman.sock:rw', self.run_args())


    def test_extra_launch_records_are_not_trimmed(self):
        valid = 'true linux false'
        invalid = [valid + '\n\n', valid + '\n\n\n', '\n' + valid + '\n',
                   valid + '\nextra\n', valid + '\r\n', 'true\nlinux false\n',
                   'true linux false extra\n', '\n', '']
        for shell, build, access, response in itertools.product((False, True), (False, True), ('0', '1'), invalid):
            with self.subTest(shell=shell, build=build, access=access, response=response):
                options = (['--container-shell'] if shell else []) + (['--container-build'] if build else [])
                self.assert_rejected(self.run_wrapper(*options, PI_CONTAINER_PODMAN=access,
                                                      FAKE_INFO_RAW=response))
                self.assertFalse(any(c[0] == '--remote' for c in self.calls()))
                self.assertFalse(self.state.exists())


    def test_extra_delegation_records_are_not_trimmed(self):
        valid = 'true\n/host/podman.sock'
        invalid = [valid + '\n\n', valid + '\n\n\n', '\n' + valid + '\n',
                   'true\n\n/host/podman.sock\n', valid + '\nextra\n', valid + '\r\n',
                   'true\n', 'true\nrelative\n', 'false\n/host/podman.sock\n', '']
        for shell, build, response in itertools.product((False, True), (False, True), invalid):
            with self.subTest(shell=shell, build=build, response=response):
                options = (['--container-shell'] if shell else []) + (['--container-build'] if build else [])
                self.assert_rejected(self.run_wrapper(*options, PI_CONTAINER_PODMAN='1',
                                                      PI_CONTAINER_PODMAN_SOCKET=str(self.sock_path),
                                                      FAKE_SOCKET_INFO_RAW=response))
                self.assertFalse(self.state.exists())


    def test_failed_queries_with_valid_looking_raw_output(self):
        for shell, build, endpoint in itertools.product((False, True), (False, True), ('launch', 'delegation')):
            with self.subTest(shell=shell, build=build, endpoint=endpoint):
                options = (['--container-shell'] if shell else []) + (['--container-build'] if build else [])
                response = {'FAKE_INFO_RAW': 'true linux false\n', 'FAKE_INFO_STATUS': '125'} if endpoint == 'launch' else {
                    'FAKE_SOCKET_INFO_RAW': 'true\n/host/podman.sock\n', 'FAKE_SOCKET_STATUS': '125'}
                self.assert_rejected(self.run_wrapper(*options, PI_CONTAINER_PODMAN='1',
                                                      PI_CONTAINER_PODMAN_SOCKET=str(self.sock_path), **response))


    def run_args(self):
        return next(call for call in self.calls() if call[0] == 'create')


    def creates(self):
        return [c for c in self.calls() if c[0] == 'create']


    def wait_path(self, path, process, timeout=5):
        deadline = time.monotonic() + timeout
        while not path.exists():
            self.assertIsNone(process.poll(), 'wrapper exited before fixture barrier')
            self.assertLess(time.monotonic(), deadline, 'fixture barrier timed out')
            time.sleep(0.01)


    def start_wrapper(self, *args, **env):
        process = subprocess.Popen(['bash', str(WRAPPER), *args], cwd=self.project,
                                   env=self.env | env, stdin=subprocess.DEVNULL,
                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                   text=True, start_new_session=True)
        def stop():
            # Also terminate leaked children when a broken wrapper exits early.
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            process.communicate(timeout=5)
        self.addCleanup(stop)
        return process


    def assert_owned_cleanup(self):
        removals = [c for c in self.calls() if c[0] == 'rm']
        self.assertEqual(len(removals), 1)
        self.assertEqual(removals[0][-1], 'a' * 64)
        self.assertEqual(removals[0][removals[0].index('--time') + 1], '0')
        cidfile = Path(self.run_args()[self.run_args().index('--cidfile') + 1])
        self.assertFalse(cidfile.parent.exists())


    def test_all_names_decimal_bounds_and_listing_error(self):
        names = '\n'.join(['my-project-08', 'my-project-2', 'my-project-no',
                           'my-project-9999999999', 'other-80', 'my-project--1'])
        result = self.run_wrapper(FAKE_NAMES=names)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('--all', next(c for c in self.calls() if c[0] == 'ps'))
        self.assertIn('my-project-9', self.run_args())
        result = self.run_wrapper(FAKE_LIST_STATUS='125')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('Cannot list', result.stderr)
        self.assertEqual(self.creates(), [])


    def test_collision_retries_and_exhaustion(self):
        result = self.run_wrapper(FAKE_COLLISIONS='2')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual([c[c.index('--name') + 1] for c in self.creates()],
                         ['my-project-0', 'my-project-1', 'my-project-2'])
        self.assert_owned_cleanup()
        result = self.run_wrapper(FAKE_COLLISIONS='20')
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(len(self.creates()), 20)
        self.assertIn('20 attempts', result.stderr)
        self.assertFalse(any(c[0] in ('start', 'rm') for c in self.calls()))


    def test_creation_and_collision_query_failures(self):
        for exists in ('1', '125'):
            with self.subTest(exists=exists):
                result = self.run_wrapper(FAKE_CREATE_STATUS='42', FAKE_EXISTS_STATUS=exists)
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(len(self.creates()), 1)
                self.assertIn('synthetic create failure', result.stderr)
                self.assertFalse(any(c[0] in ('start', 'rm') for c in self.calls()))
                if exists == '1':
                    self.assertEqual(result.returncode, 42)
                else:
                    self.assertIn('Cannot verify', result.stderr)


    def test_application_status_and_cleanup_failure(self):
        for status, removal in itertools.product((0, 23, 125), ('0', '125')):
            with self.subTest(status=status, removal=removal):
                result = self.run_wrapper(FAKE_EXIT=str(status), FAKE_RM_STATUS=removal)
                self.assertEqual(result.returncode, status, result.stderr)
                self.assertEqual(len(self.creates()), 1)
                self.assert_owned_cleanup()
                self.assertEqual('Cannot remove owned' in result.stderr, removal != '0')


    def test_signals_during_creation(self):
        for shell, (sig, status) in itertools.product((False, True), (
                (signal.SIGTERM, 143), (signal.SIGINT, 130), (signal.SIGHUP, 129))):
            with self.subTest(shell=shell, sig=sig):
                self.log.unlink(missing_ok=True)
                barrier = self.base / f'create-{shell}-{sig}'
                process = self.start_wrapper(*(['--container-shell'] if shell else []),
                                             FAKE_CREATE_BARRIER=str(barrier))
                self.wait_path(barrier.with_suffix('.ready'), process)
                process.send_signal(sig)
                # The client completes only after the parent has received the signal.
                time.sleep(0.05)
                barrier.with_suffix('.release').touch()
                out, err = process.communicate(timeout=10)
                self.assertEqual(process.returncode, status, out + err)
                self.assertFalse(any(c[0] == 'start' for c in self.calls()))
                self.assert_owned_cleanup()


    def test_permanently_stalled_creation_signal_matrix(self):
        for shell, sig, mode in itertools.product(
                (False, True), (signal.SIGTERM, signal.SIGINT, signal.SIGHUP),
                ('stall', 'stall-owned', 'cid-on-term')):
            with self.subTest(shell=shell, signal=sig, mode=mode):
                self.log.unlink(missing_ok=True)
                barrier = self.base / f'stall-{shell}-{sig}-{mode}'
                process = self.start_wrapper(*(['--container-shell'] if shell else []),
                                             FAKE_CREATE_BARRIER=str(barrier),
                                             FAKE_CREATE_MODE=mode,
                                             FAKE_CLIENT_IGNORE_TERM='1' if mode == 'stall' else '')
                self.wait_path(barrier.with_suffix('.ready'), process)
                child = int(barrier.with_suffix('.pid').read_text())
                started = time.monotonic()
                process.send_signal(sig)
                # Repeated mixed signals must neither replace status nor renew waits.
                for later in (signal.SIGHUP, signal.SIGTERM, signal.SIGINT):
                    time.sleep(0.1)
                    process.send_signal(later)
                out, err = process.communicate(timeout=25)
                elapsed = time.monotonic() - started
                self.assertLess(elapsed, 25, out + err)
                # A permanent stall was cancelled, never released to finish normally.
                self.assertFalse(barrier.with_suffix('.release').exists())
                self.assertGreater(elapsed, 3)
                self.assertEqual(process.returncode, 128 + sig, out + err)
                self.assertFalse(any(c[0] == 'start' for c in self.calls()))
                self.assertEqual(len(self.creates()), 1)
                with self.assertRaises(ProcessLookupError):
                    os.kill(child, 0)
                cidfile = Path(self.run_args()[self.run_args().index('--cidfile') + 1])
                self.assertFalse(cidfile.parent.exists())
                if mode == 'stall':
                    self.assertIn('Creation outcome unresolved', err)
                    self.assertFalse(any(c[0] in ('rm', 'kill') for c in self.calls()))
                else:
                    self.assert_owned_cleanup()
                    self.assertNotIn('Creation outcome unresolved', err)


    def test_interrupted_creation_invalid_identity_and_control_failures(self):
        cases = (
            {'FAKE_CID_NUL': '1'},
            {'FAKE_CID_RAW': 'invalid\n'},
            {'FAKE_CID_RAW': 'a' * 64 + '\n' + 'b' * 64 + '\n'},
            {'FAKE_CID_RAW': 'a' * 64 + '\n\n'},
            {'FAKE_CID_RAW': 'a' * 64 + '\r\n'},
            {'FAKE_RM_STATUS': '125'},
            {'FAKE_CONTROL_STALL': 'rm', 'FAKE_CONTROL_IGNORE_TERM': '1'},
        )
        for index, env in enumerate(cases):
            with self.subTest(env=env):
                self.log.unlink(missing_ok=True)
                barrier = self.base / f'invalid-control-{index}'
                process = self.start_wrapper(FAKE_CREATE_BARRIER=str(barrier),
                                             FAKE_CREATE_MODE='stall-owned', **env)
                self.wait_path(barrier.with_suffix('.ready'), process)
                started = time.monotonic()
                process.send_signal(signal.SIGINT)
                out, err = process.communicate(timeout=25)
                self.assertLess(time.monotonic() - started, 25)
                self.assertEqual(process.returncode, 130, out + err)
                self.assertFalse(any(c[0] == 'start' for c in self.calls()))
                cidfile = Path(self.run_args()[self.run_args().index('--cidfile') + 1])
                self.assertFalse(cidfile.parent.exists())
                if 'FAKE_CID_RAW' in env or 'FAKE_CID_NUL' in env:
                    self.assertIn('Invalid container ID', err)
                    self.assertIn('Creation outcome unresolved', err)
                    self.assertFalse(any(c[0] == 'rm' for c in self.calls()))
                else:
                    self.assert_owned_cleanup()
                    self.assertIn('Cannot remove owned container ' + 'a' * 64, err)


    def test_stopped_creation_client_is_cancelled(self):
        barrier = self.base / 'stopped-create'
        process = self.start_wrapper(FAKE_CREATE_BARRIER=str(barrier),
                                     FAKE_CREATE_MODE='stall-owned')
        self.wait_path(barrier.with_suffix('.ready'), process)
        child = int(barrier.with_suffix('.pid').read_text())
        os.kill(child, signal.SIGSTOP)
        process.send_signal(signal.SIGTERM)
        out, err = process.communicate(timeout=25)
        self.assertEqual(process.returncode, 143, out + err)
        with self.assertRaises(ProcessLookupError):
            os.kill(child, 0)
        self.assert_owned_cleanup()
        self.assertFalse(any(c[0] == 'start' for c in self.calls()))


    def test_unreapable_client_reports_without_waiting(self):
        # Fault injection models a child still present after KILL without leaking
        # a real uninterruptible process. Exercise the production helper verbatim.
        source = WRAPPER.read_text()
        helpers = source[source.index('client_running() {'):source.index('cleanup() {')]
        harness = helpers + '''
client_pid=424242
client_running() { return 0; }
wait_for_client_until() { return 1; }
kill() { printf '%s\\n' "$*"; }
wait() { printf 'unexpected wait\\n'; exit 99; }
reap_client
[[ -z "$client_pid" ]]
'''
        result = subprocess.run(['bash', '-euc', harness], text=True,
                                capture_output=True, timeout=2)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(result.stdout.splitlines(), ['-TERM 424242', '-KILL 424242'])
        self.assertIn('Cannot reap Podman client 424242', result.stderr)


    def test_attached_signals_both_modes(self):
        for shell, sig in itertools.product((False, True),
                                           (signal.SIGTERM, signal.SIGINT, signal.SIGHUP)):
            expected = {signal.SIGTERM: 143, signal.SIGINT: 130, signal.SIGHUP: 129}[sig]
            with self.subTest(shell=shell, sig=sig):
                self.log.unlink(missing_ok=True)
                session = self.base / f'session-{shell}-{sig}'
                process = self.start_wrapper(*(['--container-shell'] if shell else []),
                                             FAKE_SESSION=str(session))
                self.wait_path(session.with_suffix('.ready'), process)
                process.send_signal(sig)
                out, err = process.communicate(timeout=10)
                self.assertEqual(process.returncode, expected, out + err)
                kills = [c for c in self.calls() if c[0] == 'kill']
                self.assertEqual(kills, [['kill', '--signal', signal.Signals(sig).name[3:], 'a' * 64]])
                self.assert_owned_cleanup()
                self.assertIn('--sig-proxy=false', next(c for c in self.calls() if c[0] == 'start'))


    def test_stubborn_application_and_stalled_cleanup_are_bounded(self):
        for stall in ('', 'kill', 'rm', 'failed-kill'):
            with self.subTest(stall=stall):
                self.log.unlink(missing_ok=True)
                session = self.base / ('stubborn-' + (stall or 'application'))
                process = self.start_wrapper(FAKE_SESSION=str(session), FAKE_IGNORE_SIGNAL='1',
                                             FAKE_CONTROL_STALL=stall,
                                             FAKE_KILL_STATUS='125' if stall == 'failed-kill' else '0',
                                             FAKE_CLIENT_IGNORE_TERM='1' if stall == 'rm' else '')
                self.wait_path(session.with_suffix('.ready'), process)
                start = time.monotonic()
                process.send_signal(signal.SIGTERM)
                time.sleep(0.1)
                process.send_signal(signal.SIGHUP)
                out, err = process.communicate(timeout=23)
                self.assertEqual(process.returncode, 143, out + err)
                self.assertLess(time.monotonic() - start, 22)
                self.assert_owned_cleanup()
                if stall == 'rm':
                    self.assertIn('Cannot remove owned', err)


    def test_terminal_matrix(self):
        for terminal_in, terminal_out in itertools.product((False, True), repeat=2):
            with self.subTest(stdin=terminal_in, stdout=terminal_out):
                self.log.unlink(missing_ok=True)
                master, slave = pty.openpty()
                try:
                    process = subprocess.Popen(['bash', str(WRAPPER)], cwd=self.project,
                                               env=self.env, stdin=slave if terminal_in else subprocess.DEVNULL,
                                               stdout=slave if terminal_out else subprocess.PIPE,
                                               stderr=subprocess.PIPE, text=True)
                    out, err = process.communicate(timeout=10)
                    self.assertEqual(process.returncode, 0, (out or '') + err)
                    self.assertEqual('--tty' in self.run_args(), terminal_in and terminal_out)
                finally:
                    os.close(master)
                    os.close(slave)


    def test_pipe_and_file_input_reach_eof(self):
        for shell in (False, True):
            args = ['--container-shell'] if shell else ['exec', 'prompt with spaces', '']
            result = subprocess.run(['bash', str(WRAPPER), *args], cwd=self.project,
                                    env=self.env | {'FAKE_ECHO_INPUT': '1'}, input='payload\n',
                                    text=True, capture_output=True, timeout=10)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn('payload\n', result.stdout)
        source = self.base / 'input'
        source.write_text('file payload\n')
        with source.open() as stream:
            result = subprocess.run(['bash', str(WRAPPER), '--container-shell'], cwd=self.project,
                                    env=self.env | {'FAKE_ECHO_INPUT': '1'}, stdin=stream,
                                    text=True, capture_output=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('file payload\n', result.stdout)


    def test_image_and_build_status_matrix(self):
        for shell, access, image in itertools.product((False, True), ('0', '1'), (0, 1, 125, 42)):
            with self.subTest(shell=shell, access=access, image=image):
                result = self.run_wrapper(*(['--container-shell'] if shell else []),
                                          PI_CONTAINER_PODMAN=access,
                                          PI_CONTAINER_PODMAN_SOCKET=str(self.sock_path),
                                          FAKE_IMAGE_STATUS=str(image))
                self.assertEqual(result.returncode, image if image not in (0, 1) else 0, result.stderr)
                self.assertEqual(any(c[0] == 'build' for c in self.calls()), image == 1)
                self.assertEqual(bool(self.creates()), image in (0, 1))
        result = self.run_wrapper('--container-build', FAKE_IMAGE_STATUS='125')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(any(c[0] == 'image' for c in self.calls()))
        for options in ([], ['--container-build']):
            result = self.run_wrapper(*options, FAKE_IMAGE_STATUS='1', FAKE_BUILD_STATUS='42')
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(self.creates(), [])


    def test_private_state_creation_and_mask(self):
        result = self.run_wrapper()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.state.stat().st_mode & 0o777, 0o700)
        self.assertEqual(self.state.stat().st_uid, os.getuid())
        self.assertIn(f'{self.state}:/pi-home/.pi:rw', self.run_args())
        self.assertIn('mask:0o22', result.stdout)


    def test_invalid_state_before_image_operations(self):
        for mode in (0o755, 0o770, 0o707):
            self.state.mkdir(exist_ok=True)
            self.state.chmod(mode)
            result = self.run_wrapper('--container-build')
            self.assert_rejected(result)
            self.assertEqual(self.state.stat().st_mode & 0o777, mode)
        self.state.rmdir()
        self.state.write_text('untouched')
        self.assert_rejected(self.run_wrapper())
        self.assertEqual(self.state.read_text(), 'untouched')
        self.state.unlink()
        self.state.symlink_to(self.base / 'absent')
        self.assert_rejected(self.run_wrapper())
        self.assertTrue(self.state.is_symlink())


    @unittest.skipIf(os.getuid() == 0, 'root bypasses ordinary access checks')
    def test_inaccessible_state(self):
        self.state.mkdir(mode=0o700)
        for mode in (0o000, 0o500):
            with self.subTest(mode=mode):
                self.state.chmod(mode)
                try:
                    self.assert_rejected(self.run_wrapper())
                finally:
                    self.state.chmod(0o700)


    def install_stat_fixture(self, field, value):
        # Simulate metadata unavailable to an unprivileged test process.
        # This verifies branching, not a real chown or non-Unix filesystem.
        stat = self.bin / 'stat'
        stat.write_text('#!/usr/bin/env python3\n'
                        'import os, sys\n'
                        f'if sys.argv[2] == {field!r}: print({value!r})\n'
                        'else: os.execv("/usr/bin/stat", ["stat", *sys.argv[1:]])\n')
        stat.chmod(0o755)


    def test_wrong_owner_controlled_fixture(self):
        self.install_stat_fixture('%u', str(os.getuid() + 1))
        result = self.run_wrapper()
        self.assert_rejected(result)
        self.assertIn('belong to the calling user', result.stderr)


    def test_non_enforcing_modes_controlled_fixture(self):
        self.install_stat_fixture('%a', '777')
        result = self.run_wrapper()
        self.assert_rejected(result)
        self.assertIn('filesystem that enforces Unix permissions', result.stderr)


    def test_socket_override_and_remapped_source(self):
        result = self.run_wrapper(PI_CONTAINER_PODMAN='1',
                                  PI_CONTAINER_PODMAN_SOCKET=str(self.sock_path),
                                  CONTAINER_HOST='unix:///different/launch.sock',
                                  FAKE_INFO='true linux true',
                                  FAKE_SOCKET_INFO='true\n/host/socket with spaces.sock')
        self.assertEqual(result.returncode, 0, result.stderr)
        query = next(c for c in self.calls() if c[0] == '--remote')
        self.assertEqual(query[2], 'unix://' + str(self.sock_path))
        self.assertIn('/host/socket with spaces.sock:/run/podman/podman.sock:rw', self.run_args())
        self.assertNotIn(f'{self.sock_path}:/run/podman/podman.sock:rw', self.run_args())
        self.assertIn('CONTAINER_HOST=unix:///run/podman/podman.sock', self.run_args())


    def test_socket_fallbacks_and_symlink(self):
        runtime = self.base / 'runtime'
        (runtime / 'podman').mkdir(parents=True)
        link = runtime / 'podman' / 'podman.sock'
        link.symlink_to(self.sock_path)
        cases = [dict(CONTAINER_HOST='unix://' + str(link), FAKE_INFO='true linux true'),
                 dict(XDG_RUNTIME_DIR=str(runtime)),
                 dict(XDG_RUNTIME_DIR=str(runtime), PI_CONTAINER_PODMAN_SOCKET='')]
        for env in cases:
            with self.subTest(env=env):
                result = self.run_wrapper(PI_CONTAINER_PODMAN='1', **env)
                self.assertEqual(result.returncode, 0, result.stderr)
                query = next(c for c in self.calls() if c[0] == '--remote')
                self.assertEqual(query[2], 'unix://' + str(self.sock_path))
        # A controlled resolver records selection without depending on whether
        # the machine running tests happens to have a real UID service socket.
        resolver = self.bin / 'readlink'
        selection = self.base / 'selected-path'
        resolver.write_text('#!/usr/bin/env python3\n'
                            'import os, pathlib, sys\n'
                            'if sys.argv[-1].endswith("pi-container.sh"): os.execv("/usr/bin/readlink", ["readlink", *sys.argv[1:]])\n'
                            f'pathlib.Path({str(selection)!r}).write_text(sys.argv[-1])\n'
                            f'print({str(self.sock_path)!r})\n')
        resolver.chmod(0o755)
        for xdg in ('', None):
            self.env.pop('XDG_RUNTIME_DIR', None)
            env = {} if xdg is None else dict(XDG_RUNTIME_DIR=xdg)
            result = self.run_wrapper(PI_CONTAINER_PODMAN='1', **env)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(selection.read_text(), f'/run/user/{os.getuid()}/podman/podman.sock')


    def test_invalid_socket_paths(self):
        file = self.base / 'ordinary-file'
        file.write_text('not a socket')
        for path in ('relative.sock', str(file), str(self.base / 'missing'),
                     str(self.base / 'absent' / 'missing.sock')):
            with self.subTest(path=path):
                result = self.run_wrapper(PI_CONTAINER_PODMAN='1', PI_CONTAINER_PODMAN_SOCKET=path)
                self.assert_rejected(result)
                self.assertIn(path, result.stderr)


    @unittest.skipIf(os.getuid() == 0, 'root bypasses ordinary socket access checks')
    def test_inaccessible_socket(self):
        self.sock_path.chmod(0)
        try:
            self.assert_rejected(self.run_wrapper(PI_CONTAINER_PODMAN='1',
                                                 PI_CONTAINER_PODMAN_SOCKET=str(self.sock_path)))
        finally:
            self.sock_path.chmod(0o700)


    def test_service_failures_before_image_operations(self):
        infos = ['false\n/host/socket', 'true', 'true\n', 'true\nrelative',
                 '', 'maybe\n/host/socket', 'true\n/host/socket\nextra']
        for shell, build, info in itertools.product((False, True), (False, True), infos):
            with self.subTest(shell=shell, build=build, info=info):
                args = (['--container-shell'] if shell else []) + (['--container-build'] if build else [])
                self.assert_rejected(self.run_wrapper(
                    *args, PI_CONTAINER_PODMAN='1',
                    PI_CONTAINER_PODMAN_SOCKET=str(self.sock_path), FAKE_SOCKET_INFO=info))
        self.assert_rejected(self.run_wrapper(PI_CONTAINER_PODMAN='1',
                                             PI_CONTAINER_PODMAN_SOCKET=str(self.sock_path),
                                             FAKE_SOCKET_STATUS='125'))


    def test_modes_image_override_and_native_help(self):
        result = self.run_wrapper('--container-build', '--container-shell', 'ignored', PI_CONTAINER_IMAGE='test/custom:tag')
        self.assertEqual(result.returncode, 0, result.stderr)
        build = next(c for c in self.calls() if c[0] == 'build')
        self.assertIn('test/custom:tag', build)
        self.assertIn('--entrypoint', self.run_args())
        self.assertNotIn('ignored', self.run_args())
        self.assertEqual(self.run_args()[-1], 'test/custom:tag')
        result = self.run_wrapper('--help', 'prompt with spaces', '')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.run_args()[-3:], ['--help', 'prompt with spaces', ''])
        self.assertNotIn('--container-shell', self.run_args())

    def test_help_missing_version_and_runtime(self):
        wrapper = self.base / 'wrapper.sh'
        wrapper.write_text(WRAPPER.read_text())
        minimal = self.base / 'minimal-help'
        minimal.mkdir()
        (minimal / 'cat').symlink_to('/bin/cat')
        for flag in ('--container-help', '--wrapper-help'):
            result = subprocess.run(['/bin/bash', str(wrapper), flag], cwd=self.project,
                                    env=self.env | {'PATH': str(minimal)}, capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertFalse(self.state.exists())
            self.assertEqual(self.calls(), [])

    def test_exact_delegation_bun_and_connection_forwarding(self):
        for access, bun in itertools.product(('', '0', 'false', 'true', 'yes', '1', 'unexpected'), ('', '1')):
            result=self.run_wrapper('--version', PI_CONTAINER_PODMAN=access, PI_ENABLE_BUN=bun,
                PI_CONTAINER_PODMAN_SOCKET=str(self.sock_path), PI_ENV_VARS='CONTAINER_HOST CONTAINER_CONNECTION CUSTOM_SECRET',
                CONTAINER_HOST='unix:///launch.sock', FAKE_INFO='true linux true', CUSTOM_SECRET='dummy-private-value', PI_DEBUG='1')
            self.assertEqual(result.returncode,0,result.stderr)
            args=self.run_args()
            self.assertEqual(any(c[0]=='--remote' for c in self.calls()),access=='1')
            self.assertEqual('CONTAINER_HOST=unix:///run/podman/podman.sock' in args,access=='1')
            self.assertNotIn('CONTAINER_HOST', [args[j+1] for j,a in enumerate(args[:-1]) if a=='--env'])
            self.assertNotIn('dummy-private-value',json.dumps(self.calls())+result.stderr)
            self.assertIn('CUSTOM_SECRET',args)
            self.assertNotIn('--cap-add',args)
        for value in ('0','1'):
            self.assert_rejected(self.run_wrapper(FAKE_INFO='false linux false',PI_ALLOW_ROOTFUL=value))

    def test_physical_state_both_directories_and_readonly(self):
        for state in (self.state,self.agents):
            if state.exists(): state.rmdir()
            target=self.base/('physical-'+state.name)
            target.mkdir(mode=0o700)
            state.symlink_to(target,target_is_directory=True)
            result=self.run_wrapper()
            self.assertEqual(result.returncode,0,result.stderr)
            self.assertIn(f'{target}:/pi-home/{state.name}:rw',self.run_args())
            state.unlink()
            state.mkdir(mode=0o755)
            self.assert_rejected(self.run_wrapper())
            state.chmod(0o700)
        self.state.chmod(0o500)
        result=self.run_wrapper(PI_READONLY_CONFIG='1')
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertIn(f'{self.state}:/pi-home/.pi:ro',self.run_args())
        self.state.chmod(0o700)
        self.state.rmdir()
        self.assert_rejected(self.run_wrapper(PI_READONLY_CONFIG='1'))
        self.assertFalse(self.state.exists())

    def test_workspace_parent_identity_tmpfs_and_controls(self):
        for flags,mount in (([],self.project),(['--container-git-worktree'],self.project.parent)):
            result=self.run_wrapper('--container-shell',*flags,PI_CONTAINER_RUN_TIMEOUT='12',PI_NPM_CACHE_SIZE='512M',
                PI_CONTAINER_MEMORY_LIMIT='8g',PI_CONTAINER_CPU_LIMIT='3',PI_CONTAINER_PIDS_LIMIT='100',PI_NETWORK='none',
                FAKE_AGENT_BUDGETS='8589934592 3000000000 100')
            self.assertEqual(result.returncode,0,result.stderr)
            args=self.run_args()
            self.assertEqual(args[args.index('--workdir')+1],str(self.project))
            self.assertIn(f'{mount}:{mount}:rw',args)
            self.assertIn(f'{os.getuid()}:{os.getgid()}',args)
            self.assertIn('--userns=keep-id',args)
            self.assertIn('--cap-drop=ALL',args)
            self.assertFalse(any(a.startswith('--cap-add') for a in args))
            self.assertIn('--security-opt=no-new-privileges',args)
            for value in ('--memory=8589934592','--cpus=3','--pids-limit=100','--read-only-tmpfs=false'):
                self.assertIn(value,args)
            self.assertLess(args.index('--timeout'),args.index('pi-container'))
            self.assertEqual(args[args.index('--timeout')+1],'12')
            mounts=[args[j+1] for j,a in enumerate(args[:-1]) if a=='--tmpfs']
            self.assertEqual(len(mounts),5)
            for value in mounts:
                self.assertIn('noexec,nosuid,nodev',value)
                self.assertIn('size=',value)
            self.assertIn('/var/tmp:rw,noexec,nosuid,nodev,mode=1777,size=256M',mounts)
            self.assertTrue(any('mode=0700,U,size=512M' in m for m in mounts))
            self.assertFalse(any(':Z' in a or ':z' in a for a in args))
        alias=self.base/'workspace-alias'
        alias.symlink_to(self.project,target_is_directory=True)
        self.project=alias
        self.assertEqual(self.run_wrapper().returncode,0)
        self.assertIn(f'{alias.resolve()}:{alias.resolve()}:rw',self.run_args())
        self.project=self.home/'project'
        self.project.mkdir()
        self.assert_rejected(self.run_wrapper('--container-git-worktree'))

    def test_hash_inspection_bun_build_inputs_and_failures(self):
        self.assertNotEqual(self.run_wrapper(FAKE_INSPECT_STATUS='125').returncode,0)
        self.assertFalse(any(c[0]=='build' for c in self.calls()))
        # A stale image stops the launch instead of rebuilding silently.
        for env in ({'FAKE_LABEL_HASH':''},{'FAKE_LABEL_HASH':'0'*64},{'PI_ENABLE_BUN':'1','FAKE_LABEL_HASH':'0'*64}):
            with self.subTest(env=env):
                result=self.run_wrapper(**env)
                self.assertEqual(result.returncode,1,result.stderr)
                self.assertIn('is stale for the current inputs',result.stderr)
                self.assertIn('--container-build',result.stderr)
                self.assertFalse(any(c[0] in ('build','create') for c in self.calls()))
        result=self.run_wrapper(FAKE_IMAGE_STATUS='1')
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertTrue(any(c[0]=='build' for c in self.calls()))
        hashes=[]
        for bun in ('','1'):
            result=self.run_wrapper('--container-build',PI_ENABLE_BUN=bun,PI_BUN_VERSION='bun-v1.2.0',PI_PULL_ALWAYS='1')
            self.assertEqual(result.returncode,0,result.stderr)
            for name in ('PI_BUN_VERSION','PI_PULL_ALWAYS'):
                self.assertEqual(result.stderr.count(f'{name} is ignored; image inputs are pinned in Containerfile'),1)
            build=next(c for c in self.calls() if c[0]=='build')
            hashes.append(build[build.index('--label')+1])
            args=[build[i+1] for i,a in enumerate(build) if a=='--build-arg']
            self.assertEqual([a.split('=')[0] for a in args],['PI_VERSION','INSTALL_BUN'])
            self.assertIn('INSTALL_BUN='+('1' if bun else '0'),args)
            self.assertNotIn('--pull=always',build)
        self.assertNotEqual(*hashes)
        result=self.run_wrapper(PI_ENABLE_BUN='1')
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertFalse(any(c[0]=='build' for c in self.calls()))
        result=self.run_wrapper(FAKE_CREATE_STATUS='42',FAKE_FAIL_WITH_CID='1')
        self.assertEqual(result.returncode,42,result.stderr)
        self.assert_owned_cleanup()

    def test_dedicated_home_layout(self):
        (self.home/'.gitconfig').write_text('[user]\n name = Test\n')
        result=self.run_wrapper(PI_CONTAINER_GITCONFIG='1')
        self.assertEqual(result.returncode,0,result.stderr)
        args=self.run_args()
        self.assertEqual(args[args.index('--env', args.index('--workdir'))+1],'HOME=/pi-home')
        tmpfs=[args[i+1] for i,a in enumerate(args) if a=='--tmpfs']
        self.assertIn('/pi-home:rw,noexec,nosuid,nodev,mode=1777,size=64M',tmpfs)
        self.assertTrue(any(v.startswith('/pi-home/.npm:rw,noexec') for v in tmpfs))
        volumes=[args[i+1] for i,a in enumerate(args) if a=='--volume']
        self.assertIn(f'{self.state}:/pi-home/.pi:rw',volumes)
        self.assertIn(f'{self.agents}:/pi-home/.agents:rw',volumes)
        self.assertIn(f'{self.home}/.gitconfig:/pi-home/.gitconfig:ro',volumes)
        self.assertIn(f'{self.project}:{self.project}:rw',volumes)
        self.assertFalse(any(v.split(':')[1].startswith(str(self.home)) for v in volumes))
        self.assertFalse(any(v.startswith(str(self.home)) for v in tmpfs))

    def test_isolated_state_directory(self):
        state=self.base/'isolated'/'state'
        result=self.run_wrapper(PI_CONTAINER_STATE_DIR=str(state))
        self.assertEqual(result.returncode,0,result.stderr)
        for path in (state,state/'.pi',state/'.agents'):
            self.assertEqual(path.stat().st_mode & 0o777,0o700,str(path))
        args=self.run_args()
        volumes=[args[i+1] for i,a in enumerate(args) if a=='--volume']
        self.assertIn(f'{state}:/pi-home:rw',volumes)
        self.assertFalse(any(v.startswith('/pi-home:') for v in [args[i+1] for i,a in enumerate(args) if a=='--tmpfs']))
        self.assertFalse(any('/pi-home/.pi' in v or '/pi-home/.agents' in v for v in volumes))
        self.assertFalse(self.state.exists())
        # Read-only mode mounts the isolated .pi and .agents under an ephemeral home.
        (state/'.pi').chmod(0o500); (state/'.agents').chmod(0o500)
        result=self.run_wrapper(PI_CONTAINER_STATE_DIR=str(state),PI_READONLY_CONFIG='1')
        self.assertEqual(result.returncode,0,result.stderr)
        volumes=[a for i,a in enumerate(self.run_args()) if self.run_args()[i-1]=='--volume']
        self.assertIn(f'{state}/.pi:/pi-home/.pi:ro',volumes)
        self.assertIn(f'{state}/.agents:/pi-home/.agents:ro',volumes)
        (state/'.pi').chmod(0o700); (state/'.agents').chmod(0o700)
        missing=self.base/'missing-ro'
        result=self.run_wrapper(PI_CONTAINER_STATE_DIR=str(missing),PI_READONLY_CONFIG='1')
        self.assertNotEqual(result.returncode,0)
        self.assertFalse(missing.exists())
        shared=self.base/'shared'; shared.mkdir(mode=0o755)
        for value in ('relative/state','',str(shared),str(self.project),str(self.project/'state'),
                      str(self.project.parent),'/bad:colon'):
            with self.subTest(value=value):
                result=self.run_wrapper(PI_CONTAINER_STATE_DIR=value)
                self.assertEqual(result.returncode,1,result.stderr)
                self.assertIn('PI_CONTAINER_STATE_DIR',result.stderr)
                self.assertEqual(self.calls(),[])
        self.assertFalse((self.project/'state').exists())
        self.assertEqual(shared.stat().st_mode & 0o777,0o755)

    def test_prefix_fallback_identity_records_and_attempt_environment(self):
        original=self.project
        self.project=self.base/'...'
        self.project.mkdir()
        result=self.run_wrapper()
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertIn('pi-0',self.run_args())
        self.project=original
        result=self.run_wrapper(FAKE_NAMES='my-project-999999999',FAKE_COLLISIONS='1')
        self.assertEqual(result.returncode,0,result.stderr)
        for c in self.creates():
            name=c[c.index('--name')+1]
            self.assertIn('CONTAINER_NAME='+name,c)
        for value in ('a'*64,'a'*64+'\n'):
            self.assertEqual(self.run_wrapper(FAKE_CID_RAW=value).returncode,0)
        for value in ('abc','a'*64+'\n\n','a'*64+'\r\n','a'*64+'\nextra'):
            result=self.run_wrapper(FAKE_CID_RAW=value)
            self.assertNotEqual(result.returncode,0)
            self.assertFalse(any(c[0] in ('start','rm') for c in self.calls()))

    def test_build_cannot_consume_session_input(self):
        result = subprocess.run(['bash',str(WRAPPER),'--container-build','--container-shell'],
            cwd=self.project,env=self.env|{'FAKE_BUILD_READ_INPUT':'1','FAKE_ECHO_INPUT':'1'},
            input='preserved payload\n',capture_output=True,text=True,timeout=10)
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertEqual(Path(str(self.log)+'.build-stdin').read_text(),'')
        self.assertIn('preserved payload\n',result.stdout)

    def test_missing_successful_cid_reports_unresolved(self):
        result=self.run_wrapper(FAKE_CID_RAW='')
        self.assertNotEqual(result.returncode,0)
        self.assertIn('outcome unresolved',result.stderr)
        self.assertIn('inspect the engine',result.stderr)
        self.assertFalse(any(c[0] in ('start','rm') for c in self.calls()))

    def test_runtime_runner_prerequisites_and_smoke_image_guard(self):
        result=subprocess.run(['bash',str(ROOT/'tests/run-runtime.sh')],env=self.env|{'FAKE_INFO':'false linux'},
            cwd=self.project,capture_output=True,text=True,timeout=10)
        self.assertNotEqual(result.returncode,0)
        self.assertIn('Linux rootless Podman',result.stderr)
        self.assertFalse(any(c[0] in ('build','run','rm') for c in self.calls()))
        self.log.unlink(missing_ok=True)
        result=subprocess.run(['bash',str(ROOT/'test.sh'),'--image','existing-user-image'],env=self.env,
            cwd=self.project,capture_output=True,text=True,timeout=10)
        self.assertNotEqual(result.returncode,0)
        self.assertIn('Refusing to replace',result.stderr)
        self.assertEqual(self.calls(),[['image','exists','existing-user-image']])

    def test_retained_editors_gitconfig_and_secrets(self):
        (self.home/'.gitconfig').write_text('[user]\n name = Test\n')
        result=self.run_wrapper(ANTHROPIC_API_KEY='dummy-secret',HTTP_PROXY='dummy-proxy',EDITOR='vim',VISUAL='code',
            PI_ENV_VARS='ANTHROPIC_API_KEY HTTP_PROXY CUSTOM_SECRET',CUSTOM_SECRET='dummy-custom',PI_DEBUG='1',
            PI_CONTAINER_GITCONFIG='1')
        self.assertEqual(result.returncode,0,result.stderr)
        args=self.run_args()
        for value in ('ANTHROPIC_API_KEY','HTTP_PROXY','CUSTOM_SECRET','EDITOR=vim','VISUAL=code'):
            self.assertIn(value,args)
        self.assertIn(f'{self.home}/.gitconfig:/pi-home/.gitconfig:ro',args)
        for value in ('dummy-secret','dummy-proxy','dummy-custom'):
            self.assertNotIn(value,json.dumps(self.calls())+result.stderr)
        result=self.run_wrapper(PI_CONTAINER_GITCONFIG='0')
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertFalse(any('.gitconfig:' in a for a in self.run_args()))

    def gitconfig_mounts(self):
        return [a for a in self.run_args() if '.gitconfig:' in a]

    def test_gitconfig_requires_exact_opt_in(self):
        target=self.base/'dotfiles'/'gitconfig'; target.parent.mkdir(); target.write_text('[user]\n name = Test\n')
        (self.home/'.gitconfig').symlink_to(target)
        result=self.run_wrapper()
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertEqual(self.gitconfig_mounts(),[])
        self.assertEqual(result.stderr.count('~/.gitconfig is no longer mounted by default'),1)
        self.assertNotIn('name = Test',result.stderr)
        result=self.run_wrapper(PI_CONTAINER_GITCONFIG='1')
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertEqual(self.gitconfig_mounts(),[f'{target}:/pi-home/.gitconfig:ro'])
        self.assertNotIn('no longer mounted',result.stderr)
        for value in ('true','yes','','0','01'):
            with self.subTest(value=value):
                result=self.run_wrapper(PI_CONTAINER_GITCONFIG=value)
                self.assertEqual(result.returncode,0,result.stderr)
                self.assertEqual(self.gitconfig_mounts(),[])
                self.assertNotIn('no longer mounted',result.stderr)

    def test_gitconfig_opt_in_without_regular_file(self):
        result=self.run_wrapper(PI_CONTAINER_GITCONFIG='1')
        self.assert_rejected(result)
        self.assertIn('PI_CONTAINER_GITCONFIG=1',result.stderr)
        self.assertEqual(self.calls(),[]); self.assertFalse(self.state.exists())
        (self.home/'.gitconfig').mkdir()
        result=self.run_wrapper(PI_CONTAINER_GITCONFIG='1')
        self.assert_rejected(result)
        self.assertEqual(self.calls(),[])
        result=self.run_wrapper()
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertIn('no longer mounted',result.stderr)

    def test_gitconfig_deprecated_alias(self):
        (self.home/'.gitconfig').write_text('[user]\n name = Test\n')
        warning='PI_MOUNT_GITCONFIG is deprecated; use PI_CONTAINER_GITCONFIG=1'
        result=self.run_wrapper(PI_MOUNT_GITCONFIG='1')
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertEqual(result.stderr.count(warning),1)
        self.assertEqual(self.gitconfig_mounts(),[f'{self.home}/.gitconfig:/pi-home/.gitconfig:ro'])
        result=self.run_wrapper(PI_MOUNT_GITCONFIG='0')
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertEqual(result.stderr.count(warning),1)
        self.assertNotIn('no longer mounted',result.stderr)
        self.assertEqual(self.gitconfig_mounts(),[])
        for env in ({'PI_MOUNT_GITCONFIG':'1','PI_CONTAINER_GITCONFIG':'1'},
                    {'PI_MOUNT_GITCONFIG':'0','PI_CONTAINER_GITCONFIG':'0'}):
            result=self.run_wrapper(**env)
            self.assertEqual(result.returncode,0,result.stderr)
        for env in ({'PI_MOUNT_GITCONFIG':'0','PI_CONTAINER_GITCONFIG':'1'},
                    {'PI_MOUNT_GITCONFIG':'1','PI_CONTAINER_GITCONFIG':'true'},
                    {'PI_MOUNT_GITCONFIG':'1','PI_CONTAINER_GITCONFIG':''}):
            with self.subTest(env=env):
                result=self.run_wrapper(**env)
                self.assert_rejected(result)
                self.assertIn('PI_MOUNT_GITCONFIG and PI_CONTAINER_GITCONFIG conflict',result.stderr)
                self.assertEqual(self.calls(),[])
        for value in ('2','yes',''):
            with self.subTest(value=value):
                result=self.run_wrapper(PI_MOUNT_GITCONFIG=value)
                self.assert_rejected(result)
                self.assertEqual(self.calls(),[])

    def test_suite_leaves_no_scratch_directories(self):
        # The wrapper suite keeps scratch space in its own temporary directory.
        self.assertTrue(self.base.name.startswith('pi-wrapper-'))
        self.assertFalse(self.base.is_relative_to(ROOT))
        self.assertEqual(sorted(p.name for p in ROOT.glob('.wrapper-test-*')),[])
        probe=tempfile.TemporaryDirectory(prefix='pi-wrapper-')
        path=Path(probe.name)
        probe.cleanup()
        self.assertFalse(path.exists())

    def assert_refused_early(self, result, *needles):
        self.assertEqual(result.returncode, 1, result.stderr)
        for needle in needles:
            self.assertIn(needle, result.stderr)
        self.assertEqual(self.calls(), [])

    ALIASES = (('PI_CONTAINER_IMAGE', 'PI_IMAGE_NAME', 'test/alias:1', 'test/other:1'),
               ('PI_CONTAINER_MEMORY_LIMIT', 'PI_MEMORY_LIMIT', '2g', '3g'),
               ('PI_CONTAINER_CPU_LIMIT', 'PI_CPU_LIMIT', '1.5', '2'),
               ('PI_CONTAINER_PIDS_LIMIT', 'PI_PIDS_LIMIT', '256', '128'),
               ('PI_CONTAINER_RUN_TIMEOUT', 'PI_RUN_TIMEOUT', '30', '40'))

    def test_common_names_and_deprecated_aliases(self):
        budgets = {'PI_CONTAINER_MEMORY_LIMIT': '2147483648 2000000000 512',
                   'PI_CONTAINER_CPU_LIMIT': '4294967296 1500000000 512',
                   'PI_CONTAINER_PIDS_LIMIT': '4294967296 2000000000 256'}
        expected = {'PI_CONTAINER_IMAGE': 'test/alias:1', 'PI_CONTAINER_MEMORY_LIMIT': '--memory=2147483648',
                    'PI_CONTAINER_CPU_LIMIT': '--cpus=1.5', 'PI_CONTAINER_PIDS_LIMIT': '--pids-limit=256',
                    'PI_CONTAINER_RUN_TIMEOUT': '30'}
        for new, old, value, other in self.ALIASES:
            fake = {'FAKE_AGENT_BUDGETS': budgets[new]} if new in budgets else {}
            for env, warned in (({old: value}, 1), ({new: value}, 0), ({new: value, old: value}, 1)):
                with self.subTest(env=env):
                    result = self.run_wrapper(**env, **fake)
                    self.assertEqual(result.returncode, 0, result.stderr)
                    self.assertEqual(result.stderr.count(f'{old} is deprecated; use {new}'), warned)
                    self.assertIn(expected[new], self.run_args())
            with self.subTest(conflict=new):
                result = self.run_wrapper(**{new: value, old: other})
                self.assert_refused_early(result, f'{old} and {new} conflict')
        for env, conflict in (({'PI_ENABLE_PODMAN': '1', 'PI_CONTAINER_PODMAN': '0'}, True),
                              ({'PI_ENABLE_PODMAN': 'yes', 'PI_CONTAINER_PODMAN': '0'}, False),
                              ({'PI_ENABLE_PODMAN': '1', 'PI_CONTAINER_PODMAN': '1'}, False),
                              ({'PI_ALLOW_UNSAFE_PWD': '1', 'PI_CONTAINER_ALLOW_UNSAFE_WORKSPACE': 'true'}, True)):
            with self.subTest(switch=env):
                result = self.run_wrapper(**env, PI_CONTAINER_PODMAN_SOCKET=str(self.sock_path))
                if conflict:
                    self.assert_refused_early(result, 'conflict; set only')
                else:
                    self.assertEqual(result.returncode, 0, result.stderr)
        result = self.run_wrapper(PI_ENABLE_PODMAN='1', PI_PODMAN_SOCKET=str(self.sock_path))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('/host/podman.sock:/run/podman/podman.sock:rw', self.run_args())
        self.assertIn('PI_ENABLE_PODMAN is deprecated; use PI_CONTAINER_PODMAN (only the exact value 1 enables it)', result.stderr)
        self.assertIn('PI_PODMAN_SOCKET is deprecated; use PI_CONTAINER_PODMAN_SOCKET', result.stderr)
        result = self.run_wrapper(PI_CONTAINER_PODMAN_SOCKET=str(self.sock_path), PI_PODMAN_SOCKET='/other.sock')
        self.assert_refused_early(result, 'PI_PODMAN_SOCKET and PI_CONTAINER_PODMAN_SOCKET conflict')

    def test_yolo_has_no_effect(self):
        self.run_wrapper()
        baseline = self.run_args()
        result = self.run_wrapper(PI_CONTAINER_YOLO='1')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('PI_CONTAINER_YOLO has no effect; Pi has no tool-approval layer', result.stderr)
        self.assertEqual(len(self.run_args()), len(baseline))
        self.assertEqual([a for a in self.run_args() if 'cid' not in a], [a for a in baseline if 'cid' not in a])

    def test_budget_validation(self):
        result = self.run_wrapper()
        self.assertEqual(result.returncode, 0, result.stderr)
        for flag in ('--memory=4294967296', '--cpus=2', '--pids-limit=512'):
            self.assertIn(flag, self.run_args())
        self.assertNotIn('--timeout', self.run_args())
        invalid = {'PI_CONTAINER_MEMORY_LIMIT': ('', '  ', '0', '-1', 'max', '4', '4t', '4gb', '1.5g', '2000000g'),
                   'PI_CONTAINER_CPU_LIMIT': ('', '0', '0.0', '-1', '1.2345', '2000', 'max', 'a'),
                   'PI_CONTAINER_PIDS_LIMIT': ('', '0', '-1', 'max', '4194305', '1.5'),
                   'PI_CONTAINER_RUN_TIMEOUT': ('-1', '1.5', 'abc', '0007', '12345678901')}
        for name, values in invalid.items():
            for value in values:
                with self.subTest(name=name, value=value):
                    fresh = self.base / 'fresh-home'
                    fresh.mkdir(exist_ok=True)
                    self.assert_refused_early(self.run_wrapper(HOME=str(fresh), **{name: value}), name)
                    self.assertEqual(list(fresh.iterdir()), [])
        for value, expected in (('', None), ('0', None), ('7', '7')):
            result = self.run_wrapper(PI_CONTAINER_RUN_TIMEOUT=value)
            self.assertEqual(result.returncode, 0, result.stderr)
            args = self.run_args()
            if expected is None:
                self.assertNotIn('--timeout', args)
            else:
                self.assertEqual(args[args.index('--timeout') + 1], expected)
        for env in ({'PI_CONTAINER_PODMAN': '1', 'PI_CONTAINER_PODMAN_SOCKET': str(self.sock_path)}, {'PI_CONTAINER_YOLO': '1'}):
            result = self.run_wrapper('--container-shell', **env)
            self.assertEqual(result.returncode, 0, result.stderr)
            for flag in ('--memory=4294967296', '--cpus=2', '--pids-limit=512', '--cap-drop=ALL'):
                self.assertIn(flag, self.run_args())

    def test_budget_inspection(self):
        result = self.run_wrapper()
        names = [c[0] for c in self.calls()]
        inspect = names.index('inspect')
        self.assertLess(names.index('create'), inspect)
        self.assertLess(inspect, names.index('start'))
        for env in ({'FAKE_AGENT_BUDGETS': '0 0 0'}, {'FAKE_AGENT_BUDGETS': '4294967296 2000000000 -1'},
                    {'FAKE_AGENT_BUDGETS': '1 2000000000 512'}, {'FAKE_BUDGET_INSPECT_STATUS': '125'}):
            with self.subTest(env=env):
                result = self.run_wrapper(**env)
                self.assertEqual(result.returncode, 1, result.stderr)
                self.assertIn('session not started', result.stderr)
                names = [c[0] for c in self.calls()]
                self.assertNotIn('start', names)
                self.assertIn(['rm', '--force', '--ignore', '--time', '0', 'a' * 64], self.calls())
        self.assertIn('cgroup v2', self.run_wrapper(FAKE_AGENT_BUDGETS='0 0 0').stderr)

    def test_lifetime_notice(self):
        result = self.run_wrapper(PI_CONTAINER_RUN_TIMEOUT='2', FAKE_SLOW='2.2')
        self.assertEqual(result.returncode, 255, result.stderr)
        self.assertIn('session lifetime limit reached (2 s); exit status 255', result.stderr)
        result = self.run_wrapper(PI_CONTAINER_RUN_TIMEOUT='30', FAKE_EXIT='3')
        self.assertEqual(result.returncode, 3, result.stderr)
        self.assertNotIn('lifetime', result.stderr)

    def test_sensitive_workspaces(self):
        def launch(cwd, *args, **env):
            self.log.unlink(missing_ok=True)
            return subprocess.run(['bash', str(WRAPPER), *args], cwd=cwd, env=self.env | env, text=True,
                                  capture_output=True, timeout=10, umask=0o022)
        for cwd in (self.home, Path('/'), Path('/etc'), Path('/tmp'), Path('/usr')):
            with self.subTest(cwd=cwd):
                result = launch(cwd)
                self.assertEqual(result.returncode, 1, result.stderr)
                self.assertIn('refusing sensitive workspace', result.stderr)
                self.assertEqual(self.calls(), [])
                self.assertFalse(self.state.exists())
        child = self.home / 'project'; child.mkdir()
        self.assertEqual(launch(child, '--container-git-worktree').returncode, 1)
        link = self.base / 'etc-link'; link.symlink_to('/etc')
        result = launch(link)
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertIn('/etc', result.stderr)
        for env in ({'PI_CONTAINER_ALLOW_UNSAFE_WORKSPACE': 'true'}, {'PI_CONTAINER_ALLOW_UNSAFE_WORKSPACE': ''},
                    {'PI_ALLOW_UNSAFE_PWD': 'yes'}):
            with self.subTest(env=env):
                self.assertEqual(launch(self.home, **env).returncode, 1)
        for env in ({'PI_CONTAINER_ALLOW_UNSAFE_WORKSPACE': '1'}, {'PI_ALLOW_UNSAFE_PWD': '1'}):
            with self.subTest(env=env):
                result = launch(self.home, **env)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertIn('WARNING: sensitive workspace explicitly exposed read/write', result.stderr)
        self.assertEqual(launch(child).returncode, 0)

if __name__ == '__main__':
    unittest.main()

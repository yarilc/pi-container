"""Shared launcher tests: the core (launcher/core.sh) through the thin entry script.

The tests run against a private fixture root (tests/sandbox_profile.py) with a
fixture agent part, never the checkout's own profile, so every wrapper runs the
same cases. The fixture shell profile mirrors the reference shell; agent-only
paths use the fixture agent profile. The engine is the shared fake
(tests/fake_podman.py).
"""
import atexit
import json
import itertools
import os
from pathlib import Path
import socket
import stat
import sys
import subprocess
import tempfile
import time
import signal
import shutil
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from sandbox_profile import SHELL_FIXTURE, fixture_root  # noqa: E402

TESTS = Path(__file__).resolve().parent
# A private fixture root with the shell fixture: shared code, launcher and fixture agent part.
ROOT = fixture_root(SHELL_FIXTURE)
atexit.register(shutil.rmtree, ROOT, True)
WRAPPER = ROOT / 'fixture-shell.sh'
OWNED_ID = 'a' * 64
FAKE = (TESTS / 'fake_podman.py').read_text()


# Shared accept/reject table for the Bash wrapper and network/agent_budgets.py.
BUDGET_REJECTIONS = {
    'MEMORY_LIMIT': ('', ' ', '0', '0g', '-1', '-1g', 'max', '4', '4t', '4gb', '1.5g', '04g', 'abc', '2000000g'),
    'CPU_LIMIT': ('', '0', '0.0', '0.0000', '-1', 'max', '1.5555', '1.', '.5', '1025', 'two', ' 2'),
    'PIDS_LIMIT': ('', '0', '-1', 'max', '4194305', '01', '1.5', 'x'),
    'RUN_TIMEOUT': ('-1', '1.5', 'x', '01', '2147483648', ' 5'),
}
BUDGET_ACCEPTED = {
    'MEMORY_LIMIT': ('1k', '4g', '4G', '512m', '1048576k', '1048576g'),
    'CPU_LIMIT': ('0.001', '2', '1.5', '1024', '02', '3.25'),
    'PIDS_LIMIT': ('1', '512', '4194304'),
    'RUN_TIMEOUT': ('0', '1', '2147483647'),
}


def build_inputs_hash(root, extra=()):
    """The launcher's build-inputs-hash rule (docs/launcher-contract.md, Build hash)."""
    import hashlib
    lines, seen = '', set()
    for relative in ('Containerfile', '.containerignore', 'network/relay.py', 'network/mux.py', *extra):
        if relative in seen:
            continue
        seen.add(relative)
        lines += f'{relative} {hashlib.sha256((root / relative).read_bytes()).hexdigest()}\n'
    return hashlib.sha256(lines.encode()).hexdigest()


def synthetic_install(base, root, wrapper_name):
    """A protected-looking installation with a synthetic guard and control helper."""
    # Argument/lifecycle instrumentation only. Real guard and protected-path
    # acceptance lives in test_network_runtime; no production check is changed.
    install = base / 'synthetic-install'
    (install / 'network/bin').mkdir(parents=True)
    wrapper = install / wrapper_name
    shutil.copyfile(root / wrapper_name, wrapper)
    wrapper.chmod(0o700)
    guard = install / 'network/bin/sandbox-egress-guard'
    guard.write_text('#!/bin/sh\nexit 0\n')
    guard.chmod(0o700)
    (guard.parent / 'sandbox-egress-guard.sha256').write_text('c' * 64 + '  sandbox-egress-guard\n')
    shutil.copyfile(root / 'network/proxy_hardening.py', install / 'network/proxy_hardening.py')
    shutil.copyfile(root / 'network/platform_check.py', install / 'network/platform_check.py')
    for name in ('network/session.py', 'network/agent_profile.py', 'network/agent_budgets.py', 'network/policy.py',
                 'network/revisions.py', 'agent/profile.json', 'setup/common.py', 'setup/toolchains.py',
                 'Containerfile', '.containerignore', 'network/relay.py', 'network/mux.py',
                 'launcher/core.sh', 'agent/launcher.sh'):
        (install / name).parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(root / name, install / name)
    (install / 'network/qualify.py').write_text('# Synthetic argument fixture only.\n')
    (install / 'network/control.py').write_text('''import pathlib,socket,sys
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from revisions import TLS_ENFORCEMENT
args=sys.argv[1:]
import json,os
with open(os.environ['FAKE_LOG']+'.control','a') as log: log.write(json.dumps(args)+'\\n')
if args[0]=='snapshot':
 p=pathlib.Path(args[args.index('--session')+1]); (p/'transport').mkdir()
 (p/'config').mkdir(); (p/'logs').mkdir()
 s=socket.socket(socket.AF_UNIX); s.bind(str(p/'transport/proxy.sock')); s.close()
 (p/'transport/ready').write_text('fixture-policy guard='+ 'c'*64 +' mux=1 tls=' + TLS_ENFORCEMENT + '\\n')
 print('fixture-policy')
''')
    return wrapper


# Every fixture root and synthetic installation shares the same build inputs.
BUILD_HASH = build_inputs_hash(ROOT)


class LauncherTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='sandbox-wrapper-', dir=os.environ.get('SANDBOX_TEST_TMPDIR'))
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
        self.state = self.base / 'state'
        self.env = {'PATH': os.environ['PATH'], 'FIXTURE_SHELL_NETWORK': 'unrestricted',
                    'FAKE_LABEL_HASH': BUILD_HASH,
                    'FIXTURE_SHELL_MAINTENANCE': '1'}
        self.env['HOME'] = str(self.base / 'host-home')
        self.env.pop('FIXTURE_SHELL_CONFIG_DIR', None)
        self.env.update(PATH=str(self.bin) + ':' + self.env['PATH'],
                        FAKE_LOG=str(self.log),
                        FIXTURE_SHELL_STATE_DIR=str(self.state))
        self.socket = socket.socket(socket.AF_UNIX)
        self.socket_path = self.base / 'podman.sock'
        self.socket.bind(str(self.socket_path))
        self.addCleanup(self.socket.close)
        self.env['FIXTURE_SHELL_PODMAN_SOCKET'] = str(self.socket_path)
        self.library = self.base / 'host-home/.local/share/sandbox-toolchains'

    def run_wrapper(self, *args, cwd=None, caller_umask=-1, **env):
        return subprocess.run([str(getattr(self, 'wrapper', WRAPPER)), *args], cwd=cwd or self.project,
                              env=self.env | env, input='input payload',
                              text=True, capture_output=True, timeout=25, umask=caller_umask)

    def calls(self):
        return [json.loads(s) for s in self.log.read_text().splitlines()] if self.log.exists() else []

    def create(self):
        return next(c for c in self.calls() if c[0] == 'create')

    def wait_marker(self, proc, suffix):
        marker = Path(str(self.log) + suffix)
        deadline = time.monotonic() + 5
        while not marker.exists() and time.monotonic() < deadline:
            if proc.poll() is not None:
                self.fail(str(proc.communicate()))
            time.sleep(0.02)
        self.assertTrue(marker.exists(), suffix)

    def start_waiting_wrapper(self, marker='.started', **env):
        diagnostics = self.base / 'diagnostics'
        diagnostics.mkdir(exist_ok=True)
        proc = subprocess.Popen([str(WRAPPER)], cwd=self.project,
                                env=self.env | {'TMPDIR': str(diagnostics)} | env,
                                stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE, text=True)
        def finish():
            if proc.poll() is None:
                proc.kill()
            proc.communicate(timeout=25)
            pid_files = [Path(str(self.log) + suffix) for suffix in ('.pid', '.create-pid')]
            pid_files.extend(self.base.glob('calls.jsonl.stalled-*'))
            for pid in pid_files:
                if pid.exists():
                    try:
                        child = int(pid.read_text())
                        if str(self.bin / 'podman').encode() in Path(f'/proc/{child}/cmdline').read_bytes():
                            os.kill(child, signal.SIGKILL)
                    except (ProcessLookupError, FileNotFoundError):
                        pass
        self.addCleanup(finish)
        self.wait_marker(proc, marker)
        return proc, diagnostics

    def assert_no_fake_client(self):
        for suffix in ('.pid', '.create-pid'):
            path = Path(str(self.log) + suffix)
            if path.exists():
                with self.assertRaises(ProcessLookupError):
                    os.kill(int(path.read_text()), 0)

    def test_help_without_podman_or_side_effects(self):
        help_bin = self.base / 'help-bin'
        help_bin.mkdir()
        (help_bin / 'cat').symlink_to('/bin/cat')
        result = subprocess.run(
            ['/bin/bash', str(WRAPPER), '--container-help'],
            env=self.env | {'PATH': str(help_bin), 'OTHER_AGENT_YOLO': 'invalid'},
            text=True, capture_output=True)
        self.assertEqual(result.returncode, 0)
        self.assertIn('beyond the workspace', result.stdout)
        self.assertFalse(self.calls())
        self.assertFalse(self.state.exists())

    def test_missing_mode_defaults_to_offline_and_needs_an_installation(self):
        for mode in (None, ''):
            with self.subTest(mode=mode):
                env = self.env.copy()
                env.pop('FIXTURE_SHELL_NETWORK')
                if mode is not None:
                    env['FIXTURE_SHELL_NETWORK'] = mode
                result = subprocess.run(['/bin/bash', str(WRAPPER)], cwd=self.project,
                                        env=env, input='input payload', text=True,
                                        capture_output=True, timeout=5)
                self.assertEqual(result.returncode, 1, result.stderr)
                self.assertIn('setup required: offline sessions need a protected installation; run bash ',
                              result.stderr)
                self.assertIn('--container-setup', result.stderr)
                self.assertIn('FIXTURE_SHELL_NETWORK=unrestricted', result.stderr)
                self.assertEqual(result.stdout, '')
                self.assertFalse(self.calls())
                self.assertFalse(self.state.exists())
                self.assertFalse(Path(env['HOME']).exists())

    def test_setup_guidance_from_the_windows_entry_names_the_windows_step(self):
        # A launch from the Windows entry prepares the machine from Windows.
        result = self.run_wrapper(FIXTURE_SHELL_NETWORK='offline', WRAPPER_WINDOWS_ENTRY='/mnt/c/Work')
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertIn('setup required: offline sessions need a protected installation; '
                      'run fixture-shell.ps1 --container-setup from Windows, '
                      'or set FIXTURE_SHELL_NETWORK=unrestricted for a direct session', result.stderr)
        self.assertNotIn('bash ', result.stderr)
        self.assertNotIn(str(WRAPPER), result.stderr)
        self.assertNotIn('managed launcher', result.stderr)
        self.assertFalse(self.calls())
        result = self.run_wrapper(FIXTURE_SHELL_NETWORK='offline', WRAPPER_WINDOWS_ENTRY='')
        self.assertIn('; run bash ', result.stderr)
        self.assertIn('--container-setup and use the managed launcher', result.stderr)

    def test_missing_mode_precedes_options_prerequisites_and_other_configuration(self):
        (self.project / 'setup.json').write_text('{"network":"unrestricted"}')
        (self.project / 'qualification').mkdir()
        (self.project / 'qualification/report.json').write_text('{"checks":"passed"}')
        options = ('--container-shell', '--container-build', '--container-git-worktree')
        for enabled in itertools.product((False, True), repeat=3):
            for missing_tools in (False, True):
                for mode in (None, ''):
                    with self.subTest(enabled=enabled, missing_tools=missing_tools, mode=mode):
                        env = self.env | {'OTHER_AGENT_YOLO': 'invalid',
                            'FIXTURE_SHELL_TRUST_HOST_CA': 'invalid',
                            'FIXTURE_SHELL_MAINTENANCE': '1',
                            'FIXTURE_SHELL_PODMAN': '1', 'CONTAINER_HOST': 'invalid',
                            'FIXTURE_SHELL_NETWORK_POLICY': '/invalid/policy',
                            'FIXTURE_SHELL_CONFIG_DIR': '/conflicting/config'}
                        env.pop('FIXTURE_SHELL_NETWORK')
                        if mode is not None:
                            env['FIXTURE_SHELL_NETWORK'] = mode
                        if missing_tools:
                            env['PATH'] = ''
                        args = [option for option, use in zip(options, enabled) if use]
                        result = subprocess.run(['/bin/bash', str(WRAPPER), *args, '-c', ''],
                                                cwd=self.project, env=env, input='payload',
                                                text=True, capture_output=True, timeout=5)
                        self.assertEqual(result.returncode, 1, result.stderr)
                        self.assertIn('setup required:', result.stderr)
                        self.assertEqual(result.stdout, '')
                        self.assertFalse(self.calls())
                        self.assertFalse(self.state.exists())
                        self.assertFalse(Path(env['HOME']).exists())
        for mode in ('invalid', ' ', '\t', 'provider'):
            with self.subTest(invalid_mode=repr(mode)):
                result = self.run_wrapper(FIXTURE_SHELL_NETWORK=mode)
                self.assertEqual(result.returncode, 1)
                if mode == 'provider':
                    self.assertIn('declares no authentication method', result.stderr)
                else:
                    self.assertIn('must be offline or unrestricted', result.stderr)
                self.assertNotIn('setup required:', result.stderr)
                self.assertFalse(self.calls())

    def test_setup_diagnostic_quotes_invoked_symlink_and_runs_from_other_workspace(self):
        link = self.base / 'wrapper with spaces $(touch injected) `touch injected-too`.sh'
        link.symlink_to(WRAPPER)
        env = self.env.copy()
        env.pop('FIXTURE_SHELL_NETWORK')
        for wrapper in (str(link), os.path.relpath(link, self.project), str(WRAPPER)):
            with self.subTest(wrapper=wrapper):
                result = subprocess.run(['/bin/bash', wrapper], cwd=self.project,
                                        env=env, capture_output=True, text=True, timeout=5)
                self.assertEqual(result.returncode, 1)
                command = result.stderr.split('protected installation; run ', 1)[1].split(
                    ' and use the managed launcher', 1)[0]
                # Execute the suggested command with help taking precedence over
                # setup: this verifies shell quoting without starting a setup.
                help_result = subprocess.run(['/bin/bash', '-c', command + ' --container-help'],
                                             cwd=self.project, env=env, capture_output=True,
                                             text=True, timeout=5)
                self.assertEqual(help_result.returncode, 0, help_result.stderr)
                self.assertIn('Container options:', help_result.stdout)
                if wrapper != str(WRAPPER):
                    self.assertIn('wrapper', command)
                    self.assertNotIn(str(WRAPPER), command)
                self.assertFalse((self.project / 'injected').exists())
                self.assertFalse((self.project / 'injected-too').exists())
                self.assertFalse(self.calls())
                self.assertFalse(self.state.exists())

    def test_network_preflight_rejections_precede_image_operations(self):
        for values in (
            {'FIXTURE_SHELL_NETWORK': 'invalid'},
            {'FIXTURE_SHELL_NETWORK': 'provider'},
            {'FIXTURE_SHELL_NETWORK': 'offline', 'FIXTURE_SHELL_PODMAN': '1'},
            {'FIXTURE_SHELL_NETWORK': 'provider', 'FIXTURE_SHELL_PODMAN': '1'},
        ):
            for flags in ((), ('--container-shell', '--container-build', '--container-git-worktree')):
                with self.subTest(values=values, flags=flags):
                    self.log.unlink(missing_ok=True)
                    result = self.run_wrapper(*flags, **values)
                    self.assertNotEqual(result.returncode, 0)
                    self.assertFalse(self.calls())
        fixture = self.restricted_fixture()
        for values in ({'FAKE_BACKEND': 'cni'}, {'FAKE_SERVER_VERSION': '4.8.0'}):
            self.log.unlink(missing_ok=True)
            result = self.run_wrapper(**(fixture | values | {'FIXTURE_SHELL_NETWORK':'offline'}))
            self.assertNotEqual(result.returncode, 0)
            self.assertIn('ineligible restricted platform', result.stderr)
            self.assertFalse(any(c[0] in ('image', 'build', 'create') for c in self.calls()))

    def test_maintenance_is_separate_from_runtime_mode(self):
        for maintenance in ('', '0', 'true', 'yes', '01'):
            for explicit in (False, True):
                self.log.unlink(missing_ok=True)
                result = self.run_wrapper(*(['--container-build'] if explicit else []),
                    FIXTURE_SHELL_MAINTENANCE=maintenance, FAKE_IMAGE_STATUS='1')
                self.assertNotEqual(result.returncode, 0)
                self.assertIn('MAINTENANCE=1', result.stderr)
                self.assertFalse(any(c[0] in ('build', 'pull', 'create') for c in self.calls()))

    def test_restricted_unprotected_installation_fails_before_image_operations(self):
        result = self.run_wrapper('--container-shell', '--container-build',
                                  FIXTURE_SHELL_NETWORK='offline',
                                  CONTAINER_HOST='unix:///run/service.sock',
                                  FAKE_INFO='true linux true')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('setup required:', result.stderr)
        self.assertFalse(self.calls())

    def test_argument_forwarding_and_defaults(self):
        result = self.run_wrapper('-p', 'hello world', '', '--help')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.create()[-5:], ['localhost/fixture-shell:latest', '-p', 'hello world', '', '--help'])
        self.assertNotIn('--tty', self.create())
        self.assertNotIn('--dangerously-skip-permissions', self.create())
        unsets = [a for i, a in enumerate(self.create()[1:]) if self.create()[i] == '--unsetenv']
        self.assertIn('CONTAINER_HOST', unsets)
        self.assertIn('CONTAINER_CONNECTION', unsets)
        self.assertIn('stdin:input payload', result.stdout)
        self.assertEqual(self.state.stat().st_mode & 0o777, 0o700)

    def test_delegation_only_follows_the_exact_opt_in(self):
        # An agent approval variable has no effect on the shell.
        for yolo in ('0', '1'):
            for service in ('0', '1'):
                with self.subTest(yolo=yolo, service=service):
                    self.log.unlink(missing_ok=True)
                    result = self.run_wrapper('-c', 'test', OTHER_AGENT_YOLO=yolo,
                                              FIXTURE_SHELL_PODMAN=service)
                    self.assertEqual(result.returncode, 0, result.stderr)
                    self.assertNotIn('--dangerously-skip-permissions', self.create())
                    self.assertEqual(self.create()[-2:], ['-c', 'test'])
                    self.assertEqual('CONTAINER_HOST=unix:///run/podman/podman.sock' in self.create(), service == '1')
                    self.assertNotIn('--privileged', self.create())
                    self.assertFalse(any('label=disable' in a for a in self.create()))

    def test_boolean_forms_and_invalid_values(self):
        for value in ('1', 'true', 'TrUe', 'yes', 'YES', '', '0', 'false', 'FALSE', 'no', 'NO'):
            self.assertEqual(self.run_wrapper(FIXTURE_SHELL_TOOLCHAINS=value).returncode, 0)
        for variable in ('FIXTURE_SHELL_TOOLCHAINS', 'FIXTURE_SHELL_TRUST_HOST_CA'):
            self.log.unlink(missing_ok=True)
            result = self.run_wrapper(**{variable: 'maybe'})
            self.assertNotEqual(result.returncode, 0)
            self.assertIn(variable, result.stderr)
            self.assertFalse(self.calls())

    def test_shell_option_is_equivalent(self):
        creates = []
        for flags in ((), ('--container-shell',)):
            self.log.unlink(missing_ok=True)
            result = self.run_wrapper(*flags, '-c', 'echo "$0"', '')
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn('stdin:input payload', result.stdout)
            create = self.create()
            # The cidfile and the ownership label name the per-session directory.
            creates.append([a for i, a in enumerate(create) if i == 0 or create[i - 1] not in ('--cidfile', '--label')])
        self.assertEqual(creates[0], creates[1])
        self.assertEqual(creates[0][creates[0].index('--entrypoint'):creates[0].index('--entrypoint') + 2],
                         ['--entrypoint', '/bin/bash'])
        self.assertIn('CONTAINER_NAME=my-project-0', creates[0])
        self.assertEqual(creates[0][-4:], ['localhost/fixture-shell:latest',
                                           '-c', 'echo "$0"', ''])

    def test_workspace_worktree_and_symlink(self):
        alias = self.base / 'alias'
        alias.symlink_to(self.project, target_is_directory=True)
        self.assertEqual(self.run_wrapper(cwd=alias).returncode, 0)
        self.assertIn(f'{self.project}:{self.project}:rw', self.create())
        self.assertIn(str(self.project), self.create())
        self.log.unlink()
        self.assertEqual(self.run_wrapper('--container-git-worktree', cwd=alias).returncode, 0)
        self.assertIn(f'{self.project.parent}:{self.project.parent}:rw', self.create())
        self.assertIn(str(self.project), self.create())
        self.assertNotIn(f'{self.project}:{self.project}:rw', self.create())

    def test_read_only_identity_and_no_extra_host_mounts(self):
        self.assertEqual(self.run_wrapper().returncode, 0)
        create = self.create()
        for option in ('--read-only', '--userns=keep-id', f'{os.getuid()}:{os.getgid()}'):
            self.assertIn(option, create)
        volumes = [create[i+1] for i, a in enumerate(create) if a == '--volume']
        self.assertEqual(len(volumes), 3)
        self.assertIn(f'{self.state}:/fixture-shell-home:rw', volumes)
        self.assertIn(f'{self.library}:/toolchains:ro,nosuid,nodev', volumes)

    # Toolchain library

    def volumes(self):
        create = self.create()
        return [create[i + 1] for i, a in enumerate(create) if a == '--volume']

    def environment(self):
        create = self.create()
        return [create[i + 1] for i, a in enumerate(create) if a == '--env']

    def test_toolchain_command_dispatch(self):
        env = {k: v for k, v in self.env.items() if k != 'FIXTURE_SHELL_NETWORK'}
        result = subprocess.run([str(WRAPPER), '--container-toolchain', 'list'], cwd=self.project, env=env,
                                text=True, capture_output=True, timeout=25)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('Toolchain library: ' + str(self.library), result.stdout)
        self.assertIn('No toolchains are installed.', result.stdout)
        self.assertEqual(self.calls(), [])
        for args, message in ((('--version', '--container-toolchain', 'list'), 'must be the first argument'),
                              (('--container-toolchain', 'launch-env'), 'usage'),
                              (('--container-toolchain',), 'usage')):
            with self.subTest(args=args):
                result = self.run_wrapper(*args)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn(message, result.stderr)
                self.assertFalse(any(c[0] in ('create', 'build') for c in self.calls()))

    def test_toolchain_library_created_private_and_mounted_read_only(self):
        self.assertFalse(self.library.exists())
        result = self.run_wrapper()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(stat.S_IMODE(self.library.stat().st_mode), 0o700)
        self.assertIn('No toolchains are installed', (self.library / 'toolchains.md').read_text())
        self.assertIn(f'{self.library}:/toolchains:ro,nosuid,nodev', self.volumes())
        self.assertFalse(any(e.startswith('PATH=') for e in self.environment()))

    def test_unsafe_toolchain_library_stops_before_engine_operations(self):
        self.library.mkdir(parents=True, mode=0o700)
        os.chmod(self.library, 0o755)
        cases = [({}, str(self.library))]
        cases += [({'FIXTURE_SHELL_TOOLCHAINS_DIR': str(path)}, str(path))
                  for path in (self.project / 'tools', self.base, self.state / 'tools')]
        for env, path in cases:
            with self.subTest(env=env):
                self.log.unlink(missing_ok=True)
                result = self.run_wrapper(**env)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn(path, result.stderr)
                self.assertFalse(any(c[0] in ('create', 'build', 'image', 'pull') for c in self.calls()))

    def test_toolchain_mount_can_be_disabled(self):
        for value in ('0', 'false', 'no'):
            with self.subTest(value=value):
                result = self.run_wrapper(FIXTURE_SHELL_TOOLCHAINS=value)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertFalse(any(v.endswith(':/toolchains:ro,nosuid,nodev') for v in self.volumes()))
                self.assertFalse(self.library.exists())
        result = self.run_wrapper(FIXTURE_SHELL_TOOLCHAINS='maybe')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('FIXTURE_SHELL_TOOLCHAINS', result.stderr)

    def test_default_toolchain_environment_is_appended(self):
        sys.path.insert(0, str(ROOT / 'setup'))
        import toolchains
        base = toolchains.base_reference(ROOT)
        self.library.mkdir(parents=True, mode=0o700)
        entry = {'version': '1', 'default': True, 'commands': ['tool'], 'requires': [], 'notes': [],
                 'check': ['tool'], 'source': {}}
        index = {'schema': 1, 'toolchains': [
            {**entry, 'name': 'current', 'path': ['/toolchains/current/bin'],
             'env': {'CURRENT_HOME': '/toolchains/current'}, 'verified': {'base': base, 'date': '2026-11-13'}},
            {**entry, 'name': 'stale', 'path': ['/toolchains/stale/bin'], 'env': {},
             'verified': {'base': 'docker.io/library/other@sha256:' + 'e' * 64, 'date': '2026-11-13'}}]}
        (self.library / 'index.json').write_text(json.dumps(index))
        result = self.run_wrapper(FAKE_IMAGE_ENV='PATH=/usr/bin:/bin\nNODE_VERSION=22')
        self.assertEqual(result.returncode, 0, result.stderr)
        environment = self.environment()
        self.assertIn('PATH=/usr/bin:/bin:/toolchains/current/bin', environment)
        self.assertIn('CURRENT_HOME=/toolchains/current', environment)
        self.assertFalse(any('/toolchains/stale' in e for e in environment))
        self.assertEqual(result.stderr.count('toolchain stale was verified on another base image'), 1)
        self.assertIn('verify stale', result.stderr)

    def test_toolchain_variables_and_protected_session_variables(self):
        # The shell profile declares no agent variables, so another agent's
        # variables reach the shell; neutral session variables never do.
        sys.path.insert(0, str(ROOT / 'setup'))
        import toolchains
        self.library.mkdir(parents=True, mode=0o700)
        entry = {'name': 'tools', 'version': '1', 'default': True, 'commands': ['tool'], 'requires': [],
                 'notes': [], 'check': ['tool'], 'source': {}, 'path': ['/toolchains/tools/bin'],
                 'verified': {'base': toolchains.base_reference(ROOT), 'date': '2026-11-15'}}
        index = {'schema': 1, 'toolchains': [entry | {'env': {
            'JAVA_HOME': '/toolchains/tools', 'OTHER_AGENT_BASE_URL': 'https://example.invalid'}}]}
        (self.library / 'index.json').write_text(json.dumps(index))
        result = self.run_wrapper()
        self.assertEqual(result.returncode, 0, result.stderr)
        environment = self.environment()
        self.assertIn('JAVA_HOME=/toolchains/tools', environment)
        self.assertIn('OTHER_AGENT_BASE_URL=https://example.invalid', environment)
        for variable in ('FIXTURE_SHELL_CONFIG_DIR', 'HISTFILE', 'HOME'):
            with self.subTest(variable=variable):
                self.log.unlink(missing_ok=True)
                index['toolchains'][0]['env'] = {variable: '/toolchains/tools'}
                (self.library / 'index.json').write_text(json.dumps(index))
                result = self.run_wrapper()
                if variable == 'HISTFILE':
                    # Not a protected name, but the wrapper sets its own value after the toolchains.
                    self.assertEqual(result.returncode, 0, result.stderr)
                    values = [e.split('=', 1)[1] for e in self.environment() if e.startswith('HISTFILE=')]
                    self.assertEqual(values[-1], '/fixture-shell-home/.config/fixture-shell/bash_history')
                    continue
                if variable == 'FIXTURE_SHELL_CONFIG_DIR':
                    # The profile's own variables are left out with a warning; the core sets its value.
                    self.assertEqual(result.returncode, 0, result.stderr)
                    self.assertIn(variable, result.stderr)
                    values = [e.split('=', 1)[1] for e in self.environment() if e.startswith(variable + '=')]
                    self.assertEqual(values, ['/fixture-shell-home/.config/fixture-shell'])
                    continue
                self.assertNotEqual(result.returncode, 0)
                self.assertIn('toolchain library check failed', result.stderr)
                self.assertFalse(any(c[0] == 'create' for c in self.calls()))

    def test_restricted_sessions_declare_the_toolchain_mount(self):
        values = self.restricted_fixture()
        for mode in ('offline',):
            with self.subTest(mode=mode):
                self.log.unlink(missing_ok=True)
                Path(str(self.log) + '.control').unlink(missing_ok=True)
                result = self.run_wrapper(**(values | {'FIXTURE_SHELL_NETWORK': mode}))
                self.assertEqual(result.returncode, 0, result.stderr)
                agent = next(c for c in self.calls() if c[0] == 'create'
                             and not any(a.startswith('io.fixture-shell.egress=') for a in c))
                volumes = [agent[i + 1] for i, a in enumerate(agent) if a == '--volume']
                self.assertIn(f'{self.library}:/toolchains:ro,nosuid,nodev', volumes)
                control = [json.loads(line) for line in Path(str(self.log) + '.control').read_text().splitlines()]
                self.assertTrue(any(c[i:i + 2] == ['--mount-target', '/toolchains']
                                    for c in control for i in range(len(c) - 1)), control)

    def restricted_fixture(self):
        # Argument/lifecycle instrumentation only. Real guard and protected-path
        # acceptance lives in test_network_runtime; no production check is changed.
        self.wrapper = synthetic_install(self.base, ROOT, 'fixture-shell.sh')
        return dict(FAKE_NETWORK='1', FAKE_INFO='true linux true',
                    CONTAINER_HOST='unix:///run/service.sock',
                    FIXTURE_SHELL_NETWORK='offline')

    def test_hardening_and_budgets_in_every_mode(self):
        values = self.restricted_fixture()
        cases = [(mode, state, flags, {}) for mode in ('offline', 'unrestricted')
                 for state in ('', str(self.state)) for flags in ((), ('--container-shell',))]
        cases += [('unrestricted', str(self.state), flags, {'FIXTURE_SHELL_PODMAN': '1'})
                  for flags in ((), ('--container-shell',))]
        for mode, state, flags, extra in cases:
            with self.subTest(mode=mode, state=state, flags=flags, extra=extra):
                self.log.unlink(missing_ok=True)
                result = self.run_wrapper(*flags, **(values | extra | {
                    'FIXTURE_SHELL_NETWORK': mode, 'FIXTURE_SHELL_STATE_DIR': state}))
                self.assertEqual(result.returncode, 0, result.stderr)
                creates = [c for c in self.calls() if c[0] == 'create']
                self.assertEqual(len(creates), 1)
                for create in creates:
                    for option in ('--cap-drop=all', '--security-opt=no-new-privileges', '--userns=keep-id'):
                        self.assertIn(option, create)
                    self.assertIn(f'{os.getuid()}:{os.getgid()}', create)
                    proxy = any(a.startswith('io.fixture-shell.egress=') for a in create)
                    self.assertEqual('--pids-limit=128' in create, proxy)
                    self.assertEqual('--memory=256m' in create, proxy)
                    agent = ('--memory=4294967296', '--cpus=2', '--pids-limit=512')
                    for option in agent:
                        self.assertEqual(option in create, not proxy)
                    self.assertFalse(any(a == '--timeout' for a in create))
                agent_inspect = [c for c in self.calls() if c[0] == 'inspect' and '{{.HostConfig.Memory}}' in c[-2]]
                self.assertEqual(len(agent_inspect), 1)
                self.assertEqual(agent_inspect[0][-1], OWNED_ID)
                if '--container-shell' not in flags:
                    self.assertNotIn('lifetime limit', result.stderr)

    def test_budget_overrides_and_rejections_precede_engine(self):
        result = self.run_wrapper(FIXTURE_SHELL_MEMORY_LIMIT='8G', FIXTURE_SHELL_CPU_LIMIT='1.5',
                                  FIXTURE_SHELL_PIDS_LIMIT='1024', FIXTURE_SHELL_RUN_TIMEOUT='60')
        self.assertEqual(result.returncode, 0, result.stderr)
        create = self.create()
        for option in ('--memory=8589934592', '--cpus=1.5', '--pids-limit=1024'):
            self.assertIn(option, create)
        self.assertEqual(create[create.index('--timeout') + 1], '60')
        for value in ('', '0', None):
            with self.subTest(timeout=value):
                self.log.unlink(missing_ok=True)
                env = {} if value is None else {'FIXTURE_SHELL_RUN_TIMEOUT': value}
                self.assertEqual(self.run_wrapper(**env).returncode, 0)
                self.assertNotIn('--timeout', self.create())
        for name, cases in BUDGET_REJECTIONS.items():
            for value in cases:
                with self.subTest(name=name, value=value):
                    self.log.unlink(missing_ok=True)
                    fresh = self.base / 'rejected-state'
                    result = self.run_wrapper(**{'FIXTURE_SHELL_' + name: value,
                                                 'FIXTURE_SHELL_STATE_DIR': str(fresh)})
                    self.assertEqual(result.returncode, 1)
                    self.assertIn('FIXTURE_SHELL_' + name + ' must be', result.stderr)
                    self.assertFalse(self.calls())
                    self.assertFalse(fresh.exists())

    def test_budget_rules_match_shared_python_module(self):
        import sys
        sys.path.insert(0, str(ROOT / 'network'))
        import agent_budgets
        keys = {'MEMORY_LIMIT': 'memory', 'CPU_LIMIT': 'nano_cpus', 'PIDS_LIMIT': 'pids', 'RUN_TIMEOUT': 'timeout'}
        for name, values in BUDGET_REJECTIONS.items():
            for value in values:
                with self.subTest(rejected=name, value=value), self.assertRaises(agent_budgets.BudgetError):
                    agent_budgets.normalize({name: value})
        for name, values in BUDGET_ACCEPTED.items():
            for value in values:
                with self.subTest(accepted=name, value=value):
                    self.log.unlink(missing_ok=True)
                    expected = agent_budgets.normalize({name: value})
                    result = self.run_wrapper(**{'FIXTURE_SHELL_' + name: value})
                    self.assertEqual(result.returncode, 0, result.stderr)
                    create = self.create()
                    timeout = int(create[create.index('--timeout') + 1]) if '--timeout' in create else 0
                    configured = Path(str(self.log) + '.budgets').read_text().split()
                    actual = dict(memory=int(configured[0]), nano_cpus=int(configured[1]),
                                  pids=int(configured[2]), timeout=timeout)
                    self.assertEqual(actual, expected)
                    self.assertEqual(actual[keys[name]], expected[keys[name]])
        # The process-budget mechanism: the same kernel rule in Bash and Python.
        for kernel in ('6.6.87.2-microsoft-standard-WSL2', '5.14', '5.14.0-427.13.1.el9_4.x86_64',
                       '5.15.0-91-generic', '6.8.9+deb13', '10.0', '5.140', '5.13.19', '5.10.0-28-amd64',
                       '4.18.0-553.el8_10.x86_64', '5.9', '', '5', '5.', 'x5.14', ' 5.14', '5.14 x',
                       '5.14-\x1b[0m', '5.14/x', '5.x', '12345.1', '5.14.0-é'):
            for controllers in ('[cpu memory]', '[cpu memory pids]'):
                with self.subTest(kernel=kernel, controllers=controllers):
                    self.log.unlink(missing_ok=True)
                    mechanism = agent_budgets.process_mechanism(controllers, kernel)
                    result = self.run_wrapper(FAKE_CONTROLLERS=controllers, FAKE_KERNEL=kernel)
                    self.assertEqual(result.returncode, 0, result.stderr)
                    create = self.create()
                    self.assertEqual('--pids-limit=512' in create, mechanism == 'cgroup')
                    self.assertEqual('nproc=512:512' in create, mechanism == 'rlimit')
                    if mechanism == 'none':
                        self.assertIn(agent_budgets.fallback_reason(kernel), result.stderr)
        # Delegation: the same cgroup manager rule in Bash and Python.
        for manager in ('systemd', 'cgroupfs', 'none', 'other'):
            for controllers in ('[cpu memory pids]', '[memory]', '[]'):
                with self.subTest(manager=manager, controllers=controllers):
                    self.log.unlink(missing_ok=True)
                    delegated = agent_budgets.delegated(controllers, manager)
                    result = self.run_wrapper(FAKE_CONTROLLERS=controllers, FAKE_CGROUP_MANAGER=manager)
                    self.assertEqual(result.returncode, 0, result.stderr)
                    create = self.create()
                    self.assertEqual(any(a.startswith('--memory=') for a in create), 'memory' in delegated)
                    self.assertEqual(any(a.startswith('--cpus=') for a in create), 'cpu' in delegated)
                    self.assertEqual('--pids-limit=512' in create, 'pids' in delegated)
                    self.assertEqual('nproc=512:512' in create,
                                     agent_budgets.process_mechanism(delegated, '6.6.87.2') == 'rlimit')
                    for controller in {'memory', 'cpu', 'pids'} - set(delegated):
                        self.assertIn(agent_budgets.cgroup_reason(controller, manager), result.stderr)
        for manager in ('', 'Systemd', 'system d', 'x' * 33):
            with self.subTest(malformed_manager=manager):
                with self.assertRaises(agent_budgets.ControllerError):
                    agent_budgets.delegated('[cpu memory pids]', manager)
                self.assertEqual(self.run_wrapper(FAKE_CGROUP_MANAGER=manager).returncode, 1)

    def test_budgets_follow_delegated_controllers(self):
        notices = {'memory': 'agent memory budget not enforced: cgroup controller memory',
                   'cpu': 'agent CPU budget not enforced: cgroup controller cpu',
                   'pids': 'agent process budget not enforced: cgroup controller pids'}
        rlimit_notice = ('agent process budget enforced through the process rlimit (512 tasks of the session user, '
                         'threads included): cgroup controller pids is not delegated')
        old_kernel = 'kernel 5.13.19 counts the process rlimit per user, not per container'
        flags = {'memory': '--memory=4294967296', 'cpu': '--cpus=2', 'pids': '--pids-limit=512'}
        # Without pids, a kernel from 5.14 counts the process rlimit per container: the
        # fallback applies. An older or unrecognized kernel leaves the budget unenforced.
        for kernel, fallback, reason in (('6.6.87.2-microsoft-standard-WSL2', True, ''),
                                         ('5.13.19', False, old_kernel),
                                         ('unknown', False, 'unrecognized kernel version')):
            for controllers in ('[cpu memory pids]', '[cpuset cpu io memory pids]', '[memory pids]',
                                '[cpu pids]', '[cpu memory]', '[]'):
                with self.subTest(controllers=controllers, kernel=kernel):
                    self.log.unlink(missing_ok=True)
                    result = self.run_wrapper(FAKE_CONTROLLERS=controllers, FAKE_KERNEL=kernel)
                    self.assertEqual(result.returncode, 0, result.stderr)
                    create = self.create()
                    present = controllers[1:-1].split()
                    missing_pids = 'pids' not in present
                    for name in ('memory', 'cpu'):
                        self.assertEqual(flags[name] in create, name in present)
                        self.assertEqual(notices[name] in result.stderr, name not in present)
                    self.assertEqual(flags['pids'] in create, not missing_pids)
                    self.assertEqual('--pids-limit=-1' in create, missing_pids)
                    self.assertEqual('--ulimit' in create, missing_pids and fallback)
                    if missing_pids and fallback:
                        self.assertEqual(create[create.index('--ulimit') + 1], 'nproc=512:512')
                    self.assertEqual(rlimit_notice in result.stderr, missing_pids and fallback)
                    self.assertEqual(notices['pids'] in result.stderr, missing_pids and not fallback)
                    self.assertEqual(reason != '' and reason in result.stderr, missing_pids and not fallback)
                    self.assertFalse(any(a.startswith('--cpus=') for a in create) and 'cpu' not in present)
                    self.assertTrue(any(c[0] == 'start' for c in self.calls()))
        # cgroupfs reports controllers but applies no limits: nothing is delegated, and the
        # process budget uses the rlimit fallback. The manager is a strict single record.
        self.log.unlink(missing_ok=True)
        result = self.run_wrapper(FAKE_CONTROLLERS='[cpuset cpu io memory hugetlb pids rdma]',
                                  FAKE_CGROUP_MANAGER='cgroupfs')
        self.assertEqual(result.returncode, 0, result.stderr)
        create = self.create()
        self.assertFalse(any(a.startswith(('--memory=', '--cpus=')) for a in create))
        self.assertNotIn('--pids-limit=512', create)
        self.assertIn('--pids-limit=-1', create)
        self.assertEqual(create[create.index('--ulimit') + 1], 'nproc=512:512')
        manager = 'the rootless engine uses the cgroupfs cgroup manager, which applies no cgroup limits'
        for budget in ('memory', 'CPU'):
            self.assertIn(f'agent {budget} budget not enforced: {manager}', result.stderr)
        self.assertIn('agent process budget enforced through the process rlimit (512 tasks of the session user, '
                      'threads included): ' + manager, result.stderr)
        self.log.unlink(missing_ok=True)
        result = self.run_wrapper(FAKE_CONTROLLERS='[cpu memory pids]', FAKE_CGROUP_MANAGER='cgroupfs',
                                  FAKE_KERNEL='5.10.0')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn('--ulimit', self.create())
        self.assertIn(f'agent process budget not enforced: {manager}; kernel 5.10.0 counts', result.stderr)
        for env in (dict(FAKE_CGROUP_MANAGER=''), dict(FAKE_CGROUP_MANAGER='Systemd'),
                    dict(FAKE_CGROUP_MANAGER='system d'), dict(FAKE_CGROUP_MANAGER_RAW='systemd\\nsystemd\\n'),
                    dict(FAKE_CGROUP_MANAGER_RAW='systemd\\r\\n'), dict(FAKE_CGROUP_MANAGER_STATUS='3')):
            with self.subTest(manager_response=env):
                self.log.unlink(missing_ok=True)
                result = self.run_wrapper(**env)
                self.assertEqual(result.returncode, 1)
                self.assertRegex(result.stderr, 'unverifiable cgroup manager|cannot query the rootless cgroup manager')
                self.assertFalse(any(c[0] in ('create', 'build', 'image') for c in self.calls()))
        # The fallback uses the selected process budget.
        self.log.unlink(missing_ok=True)
        result = self.run_wrapper(FAKE_CONTROLLERS='[cpu memory]', FIXTURE_SHELL_PIDS_LIMIT='1024')
        self.assertEqual(result.returncode, 0, result.stderr)
        create = self.create()
        self.assertEqual(create[create.index('--ulimit') + 1], 'nproc=1024:1024')
        self.assertIn('(1024 tasks of the session user', result.stderr)
        # The kernel is an engine query with the same record and failure rules as the others.
        for env in (dict(FAKE_KERNEL_RAW='6.6.87.2\\n5.10\\n'), dict(FAKE_KERNEL_RAW='6.6.87.2\\r\\n'),
                    dict(FAKE_KERNEL_STATUS='3')):
            with self.subTest(kernel_response=env):
                self.log.unlink(missing_ok=True)
                result = self.run_wrapper(FAKE_CONTROLLERS='[cpu memory]', **env)
                self.assertEqual(result.returncode, 1)
                self.assertRegex(result.stderr, 'invalid engine kernel version response|cannot query the engine kernel')
                self.assertFalse(any(c[0] in ('create', 'build', 'image') for c in self.calls()))
        # A delegated controller whose limit the engine drops still stops the launch;
        # an unenforced limit that unexpectedly appears is rejected too.
        for controllers, reported in (('[memory pids]', '0 0 512'), ('[memory pids]', '4294967296 2000000000 512'),
                                      ('[cpu memory]', '4294967296 2000000000 512'),
                                      ('[cpu memory]', '4294967296 2000000000 2048')):
            with self.subTest(controllers=controllers, reported=reported):
                self.log.unlink(missing_ok=True)
                result = self.run_wrapper(FAKE_CONTROLLERS=controllers, FAKE_AGENT_BUDGETS=reported)
                self.assertEqual(result.returncode, 1)
                self.assertIn('agent resource budgets were not applied', result.stderr)
                self.assertFalse(any(c[0] == 'start' for c in self.calls()))
        for controllers in ('cpu memory pids', '[cpu,memory]', '[CPU]', '[ cpu]', ''):
            with self.subTest(malformed=controllers):
                self.log.unlink(missing_ok=True)
                result = self.run_wrapper(FAKE_CONTROLLERS=controllers)
                self.assertEqual(result.returncode, 1)
                self.assertIn('unverifiable cgroup controller list', result.stderr)
                self.assertFalse(any(c[0] == 'create' for c in self.calls()))
        self.log.unlink(missing_ok=True)
        result = self.run_wrapper(FAKE_CONTROLLERS_STATUS='125')
        self.assertEqual(result.returncode, 1)
        self.assertIn('cannot query the rootless cgroup controllers', result.stderr)

    def test_engine_default_secrets_are_masked_in_every_mode(self):
        mask = 'type=tmpfs,destination=/run/secrets,ro=true'
        for args, env in (((), {}), (('--container-shell',), {}), (('--container-git-worktree',), {}),
                          ((), {'FIXTURE_SHELL_PODMAN': '1'})):
            with self.subTest(args=args, env=env):
                self.log.unlink(missing_ok=True)
                result = self.run_wrapper(*args, **env)
                self.assertEqual(result.returncode, 0, result.stderr)
                create = self.create()
                index = create.index(mask)
                self.assertEqual(create[index - 1], '--mount')
                self.assertEqual(create.count(mask), 1)
                self.assertFalse(any(':/run/secrets' in arg for arg in create))

    def assert_agent_dev_layout(self, create):
        self.assertIn('--read-only', create)
        self.assertNotIn('--read-only-tmpfs=false', create)
        # The engine provides /dev and a devpts that allows pseudo-terminals; an
        # explicit devpts would get ptmxmode=000.
        tmpfs = [create[i + 1] for i, arg in enumerate(create) if arg == '--tmpfs']
        self.assertFalse(any(t == '/dev' or t.startswith('/dev:') or t.startswith('/dev/') for t in tmpfs), tmpfs)
        mounts = [create[i + 1] for i, arg in enumerate(create) if arg == '--mount']
        self.assertFalse(any('type=devpts' in m or m.endswith('destination=/dev') or 'destination=/dev,' in m
                             for m in mounts), mounts)
        self.assertIn('type=tmpfs,destination=/dev/shm,ro=true', mounts)
        self.assertIn('type=tmpfs,destination=/run/secrets,ro=true', mounts)

    def test_agent_dev_layout_attaches_terminals_in_every_mode(self):
        values = self.restricted_fixture()
        cases = [(mode, flags, {}) for mode in ('offline', 'unrestricted')
                 for flags in ((), ('--container-shell',), ('--container-git-worktree',))]
        cases.append(('unrestricted', (), {'FIXTURE_SHELL_PODMAN': '1'}))
        for mode, flags, extra in cases:
            with self.subTest(mode=mode, flags=flags, extra=extra):
                self.log.unlink(missing_ok=True)
                result = self.run_wrapper(*flags, **(values | extra | {'FIXTURE_SHELL_NETWORK': mode}))
                self.assertEqual(result.returncode, 0, result.stderr)
                for create in (c for c in self.calls() if c[0] == 'create'):
                    if any(a.startswith('io.fixture-shell.egress=') for a in create):
                        # The proxy never attaches a terminal and keeps /dev read-only.
                        self.assertIn('--read-only-tmpfs=false', create)
                        self.assertFalse(any(a.startswith('/dev') or 'destination=/dev' in a for a in create))
                    else:
                        self.assert_agent_dev_layout(create)

    def test_ignored_budgets_stop_before_start_and_remove_owned_container(self):
        for reported in ('0 0 0', '4294967296 2000000000 0', '4294967296 0 512', '0 2000000000 512',
                         '4294967296 2000000000 513', ''):
            with self.subTest(reported=reported):
                self.log.unlink(missing_ok=True)
                result = self.run_wrapper(FAKE_AGENT_BUDGETS=reported)
                self.assertEqual(result.returncode, 1)
                self.assertIn('agent resource budgets were not applied', result.stderr)
                self.assertIn('controller delegation', result.stderr)
                self.assertFalse(any(c[0] == 'start' for c in self.calls()))
                self.assertTrue(any(c[0] == 'rm' and c[-1] == OWNED_ID for c in self.calls()))
        # The process rlimit fallback: exactly one RLIMIT_NPROC entry at the budget and no cgroup limit.
        configured = '4294967296 2000000000 '
        for reported in (configured + '-1 []', configured + '-1 [RLIMIT_NPROC=512:1024,]',
                         configured + '-1 [RLIMIT_NPROC=256:256,]', configured + '-1 [RLIMIT_NPROC=1024:512,]',
                         configured + '-1 [RLIMIT_NPROC=512:512,RLIMIT_NPROC=512:512,]',
                         configured + '-1 [RLIMIT_NPROC=512:512,RLIMIT_NPROC=4096:4096,]',
                         configured + '512 [RLIMIT_NPROC=512:512,]', configured + '-1 RLIMIT_NPROC=512:512',
                         configured + '-1 [RLIMIT_NPROC=512:512]', configured + '-1', configured + '-1 [] extra'):
            with self.subTest(fallback=reported):
                self.log.unlink(missing_ok=True)
                result = self.run_wrapper(FAKE_CONTROLLERS='[cpu memory]', FAKE_AGENT_BUDGETS=reported)
                self.assertEqual(result.returncode, 1)
                self.assertIn('agent resource budgets were not applied', result.stderr)
                self.assertIn('process rlimit fallback', result.stderr)
                self.assertFalse(any(c[0] == 'start' for c in self.calls()))
                self.assertTrue(any(c[0] == 'rm' and c[-1] == OWNED_ID for c in self.calls()))
        # Accepted: the exact fallback beside other rlimits, and an engine-default process
        # rlimit when the budget uses the cgroup controller or has no enforcement.
        for controllers, kernel, reported in (
                ('[cpu memory]', '6.6.87.2', configured + '-1 [RLIMIT_NOFILE=1024:1024,RLIMIT_NPROC=512:512,]'),
                ('[cpu memory]', '6.6.87.2', configured + '0 [RLIMIT_NPROC=512:512,]'),
                ('[cpu memory pids]', '6.6.87.2', configured + '512 [RLIMIT_NPROC=63948:63948,]'),
                ('[cpu memory]', '5.10.0', configured + '-1 [RLIMIT_NPROC=63948:63948,]')):
            with self.subTest(accepted=reported, controllers=controllers):
                self.log.unlink(missing_ok=True)
                result = self.run_wrapper(FAKE_CONTROLLERS=controllers, FAKE_KERNEL=kernel,
                                          FAKE_AGENT_BUDGETS=reported)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertTrue(any(c[0] == 'start' for c in self.calls()))
        self.log.unlink(missing_ok=True)
        result = self.run_wrapper(FAKE_FAIL='inspect')
        self.assertEqual(result.returncode, 1)
        self.assertIn('cannot inspect agent resource budgets', result.stderr)
        self.assertFalse(any(c[0] == 'start' for c in self.calls()))

    def test_lifetime_notice_preserves_status(self):
        result = self.run_wrapper(FIXTURE_SHELL_RUN_TIMEOUT='1', FAKE_START_DELAY='1.2', FAKE_EXIT='137')
        self.assertEqual(result.returncode, 137)
        self.assertIn('session lifetime limit reached (1 s); exit status 137', result.stderr)
        for env in ({'FAKE_EXIT': '3'}, {'FAKE_START_DELAY': '1.2', 'FAKE_EXIT': '0'}):
            with self.subTest(env=env):
                result = self.run_wrapper(FIXTURE_SHELL_RUN_TIMEOUT='1', **env)
                self.assertEqual(result.returncode, int(env['FAKE_EXIT']))
                self.assertNotIn('lifetime limit', result.stderr)
        # A short failing session that crosses a whole-second boundary is not a
        # reached limit: elapsed time is measured below one second.
        for attempt in range(8):
            with self.subTest(boundary_attempt=attempt):
                result = self.run_wrapper(FIXTURE_SHELL_RUN_TIMEOUT='1', FAKE_START_DELAY='0.3', FAKE_EXIT='3')
                self.assertEqual(result.returncode, 3)
                self.assertNotIn('lifetime limit', result.stderr)

    def test_sensitive_workspaces_refused_before_engine(self):
        home = Path(self.env['HOME'])
        home.mkdir()
        (home / 'project').mkdir()
        etc_link = self.base / 'etc-link'
        etc_link.symlink_to('/etc', target_is_directory=True)
        refused = [(home, ()), (home / 'project', ('--container-git-worktree',)), (etc_link, ()),
                   (Path('/'), ()), (Path('/tmp'), ())]
        if Path('/mnt').is_dir():
            refused.append((Path('/mnt'), ()))
        for cwd, flags in refused:
            for override in (None, 'true', 'yes', '0', ' 1'):
                with self.subTest(cwd=str(cwd), flags=flags, override=override):
                    self.log.unlink(missing_ok=True)
                    env = {} if override is None else {'FIXTURE_SHELL_ALLOW_UNSAFE_WORKSPACE': override}
                    result = self.run_wrapper(*flags, cwd=cwd, **env)
                    self.assertEqual(result.returncode, 1, result.stderr)
                    self.assertIn('refusing sensitive workspace', result.stderr)
                    self.assertIn('project subdirectory', result.stderr)
                    self.assertFalse(self.calls())
                    self.assertFalse(self.state.exists())
        self.log.unlink(missing_ok=True)
        # An exposed home contains the default toolchain library, which must
        # never be writable through the workspace: the launch stops first.
        result = self.run_wrapper(cwd=home, FIXTURE_SHELL_ALLOW_UNSAFE_WORKSPACE='1')
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertIn('overlaps ' + str(home), result.stderr)
        self.assertFalse(any(c[0] in ('create', 'build') for c in self.calls()))
        self.log.unlink(missing_ok=True)
        result = self.run_wrapper(cwd=home, FIXTURE_SHELL_ALLOW_UNSAFE_WORKSPACE='1',
                                  FIXTURE_SHELL_TOOLCHAINS='0')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(f'WARNING: sensitive workspace explicitly exposed read/write: {home}', result.stderr)
        self.assertIn(f'{home}:{home}:rw', self.create())
        self.log.unlink(missing_ok=True)
        self.assertEqual(self.run_wrapper(cwd=home / 'project').returncode, 0)
        self.assertNotIn('WARNING', self.run_wrapper(cwd=home / 'project').stderr)

    def test_wsl_drive_roots_refused_but_subdirectories_accepted(self):
        drives = [p for p in Path('/mnt').glob('?') if p.is_dir()] if Path('/mnt').is_dir() else []
        if not drives:
            self.skipTest('no single-letter drive root under /mnt')
        result = self.run_wrapper(cwd=drives[0])
        self.assertEqual(result.returncode, 1)
        self.assertIn('refusing sensitive workspace ' + str(drives[0]), result.stderr)
        self.assertFalse(self.calls())

    def run_with_windows_drive(self, cwd, *args, **env):
        """Run the entry in a user and mount namespace whose /mnt is a fresh tmpfs."""
        if str(self.base).startswith('/mnt/'):
            self.skipTest('the test directory is under /mnt')
        if subprocess.run(['unshare', '-rm', 'true'], capture_output=True).returncode:
            self.skipTest('unprivileged user and mount namespaces are unavailable')
        script = ('mount -t tmpfs tmpfs /mnt || exit 97\n'
                  'printf "%s\\n" "$TEST_WINDOWS_DIRS" | while IFS= read -r d; do mkdir -p -- "$d"; done\n'
                  'cd -- "$1" || exit 98\nshift\nexec "$@"\n')
        command = ['unshare', '-rm', 'sh', '-c', script, 'sh', str(cwd), str(getattr(self, 'wrapper', WRAPPER)), *args]
        # Unmapped owners make host ancestors look unsafe to the toolchain check, which is not under test.
        env = {'FIXTURE_SHELL_TOOLCHAINS': '0'} | env | {'TEST_WINDOWS_DIRS': str(cwd)}
        return subprocess.run(command, env=self.env | env,
                              input='input payload', text=True, capture_output=True, timeout=25)

    def test_windows_system_and_profile_folders_refused_before_engine(self):
        refused = ['/mnt/c/Users', '/mnt/c/Users/me', '/mnt/c/Users/me/AppData', '/mnt/c/Windows',
                   '/mnt/c/Program Files', '/mnt/c/Program Files (x86)', '/mnt/c/ProgramData', '/mnt/d/Users/Public',
                   '/mnt/c/Users/me/Documents', '/mnt/c/Users/me/OneDrive', '/mnt/c/Users/me/OneDrive/Documents',
                   '/mnt/c/Users/me/OneDrive - Example/Documents', '/mnt/c/Users/me/AppData/Local/project',
                   '/mnt/c/Users/me/AppData/Roaming/Microsoft/Windows/Start Menu/Programs/Startup']
        cases = [(path, ()) for path in refused] + [(path.upper().replace('/MNT/', '/mnt/'), ()) for path in refused]
        cases += [('/mnt/c/users/YARI', ()), ('/mnt/C/PROGRAM FILES', ()),
                  ('/mnt/c/Users/me/app', ('--container-git-worktree',))]
        for cwd, flags in cases:
            with self.subTest(cwd=cwd, flags=flags):
                self.log.unlink(missing_ok=True)
                result = self.run_with_windows_drive(cwd, *flags)
                self.assertEqual(result.returncode, 1, result.stderr)
                expected = str(Path(cwd).parent) if flags else cwd
                self.assertIn('refusing sensitive workspace ' + expected, result.stderr)
                self.assertFalse(self.calls())
                self.assertFalse(self.state.exists())
        self.log.unlink(missing_ok=True)
        result = self.run_with_windows_drive('/mnt/c/Users/me', FIXTURE_SHELL_ALLOW_UNSAFE_WORKSPACE='1')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('WARNING: sensitive workspace explicitly exposed read/write: /mnt/c/Users/me', result.stderr)
        self.assertIn('/mnt/c/Users/me:/mnt/c/Users/me:rw', self.create())
        for cwd in ('/mnt/c/Users/me/projects/app', '/mnt/c/Users/me/Documents/GitHub/app',
                    '/mnt/c/Users/me/OneDrive/Projects/app', '/mnt/c/Users/me/AppDataFiles', '/mnt/c/WindowsApps'):
            with self.subTest(accepted=cwd):
                self.log.unlink(missing_ok=True)
                result = self.run_with_windows_drive(cwd)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertNotIn('WARNING', result.stderr)
                self.assertIn(f'{cwd}:{cwd}:rw', self.create())

    def test_insecure_existing_state_rejected(self):
        self.state.mkdir(mode=0o777)
        self.state.chmod(0o777)
        result = self.run_wrapper()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('must be private', result.stderr)
        self.assertFalse(any(c[0] == 'create' for c in self.calls()))

    def test_tty_allocated_for_terminal(self):
        import pty
        master, slave = pty.openpty()
        proc = subprocess.Popen([str(WRAPPER), '--version'], cwd=self.project,
                                env=self.env | {'FAKE_NO_STDIN': '1'},
                                stdin=slave, stdout=slave, stderr=slave)
        os.close(slave)
        try:
            self.assertEqual(proc.wait(timeout=10), 0)
            self.assertIn('--tty', self.create())
            self.assert_agent_dev_layout(self.create())
        finally:
            os.close(master)
            if proc.poll() is None:
                proc.terminate()
                proc.wait(timeout=5)

    def test_socket_only_required_when_enabled(self):
        missing = str(self.base / 'missing.sock')
        self.assertEqual(self.run_wrapper(FIXTURE_SHELL_PODMAN_SOCKET=missing).returncode, 0)
        self.log.unlink()
        result = self.run_wrapper(FIXTURE_SHELL_PODMAN='1', FIXTURE_SHELL_PODMAN_SOCKET=missing)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('socket', result.stderr)
        self.assertFalse(any(c[0] in ('build', 'create') for c in self.calls()))

    def test_socket_engine_must_be_rootless(self):
        result = self.run_wrapper(FIXTURE_SHELL_PODMAN='1', FAKE_SOCKET_ROOTLESS='false')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('rootless', result.stderr)

    def test_rootful_and_remote_rejected_local_unix_accepted(self):
        cases = ({'FAKE_INFO': 'false linux false'},
                 {'CONTAINER_HOST': 'ssh://other-host'},
                 {'CONTAINER_HOST': 'tcp://127.0.0.1:1234'},
                 {'CONTAINER_CONNECTION': 'machine'},
                 {'FAKE_INFO': 'true linux true'})
        for env in cases:
            self.assertNotEqual(self.run_wrapper(**env).returncode, 0)
        self.assertEqual(self.run_wrapper(FAKE_INFO='true linux true', CONTAINER_HOST='unix:///run/podman/podman.sock').returncode, 0)

    def test_empty_engine_context_reaches_podman_unset(self):
        # Podman treats a set but empty CONTAINER_HOST or CONTAINER_CONNECTION as remote.
        probe = self.bin / 'podman'
        probe.write_text(FAKE.replace("args = sys.argv[1:]",
                         "assert 'CONTAINER_HOST' not in os.environ and 'CONTAINER_CONNECTION' not in os.environ\n"
                         "args = sys.argv[1:]"))
        result = self.run_wrapper('-c', 'true', CONTAINER_HOST='', CONTAINER_CONNECTION='')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('create', [c[0] for c in self.calls()])

    def test_build_location_refresh_and_missing_image(self):
        self.assertEqual(self.run_wrapper('--container-build').returncode, 0)
        build = next(c for c in self.calls() if c[0] == 'build')
        self.assertEqual(build[-3:], ['--file', str(ROOT / 'Containerfile'), str(ROOT)])
        self.log.unlink()
        self.assertEqual(self.run_wrapper(FAKE_IMAGE_STATUS='1').returncode, 0)
        self.assertTrue(any(c[0] == 'build' for c in self.calls()))

    def test_runtime_build_receives_host_ca_only_when_trusted(self):
        ca = self.base / 'bundle.pem'
        ca.write_text('synthetic certificate bundle')
        for trust in ('0', '1'):
            for build in (('--container-build',), ()):
                with self.subTest(trust=trust, build=build):
                    self.log.unlink(missing_ok=True)
                    result = self.run_wrapper(*build, FIXTURE_SHELL_TRUST_HOST_CA=trust,
                                              FIXTURE_SHELL_CA_BUNDLE=str(ca),
                                              **({} if build else {'FAKE_IMAGE_STATUS': '1'}))
                    self.assertEqual(result.returncode, 0, result.stderr)
                    args = next(c for c in self.calls() if c[0] == 'build')
                    secrets = [args[i + 1] for i, arg in enumerate(args) if arg == '--secret']
                    # The wrapper passes the resolved bundle path (readlink -f).
                    self.assertEqual(secrets, [f'id=build-ca,src={ca.resolve()}'] if trust == '1' else [])
                    self.assertEqual(args[-3:], ['--file', str(ROOT / 'Containerfile'), str(ROOT)])

    def test_build_and_image_inspection_errors(self):
        self.assertEqual(self.run_wrapper('--container-build', FAKE_BUILD_STATUS='17').returncode, 17)
        self.assertNotEqual(self.run_wrapper(FAKE_IMAGE_STATUS='125').returncode, 0)
        self.assertFalse(any(c[0] == 'create' for c in self.calls()))

    def test_exit_status_and_owned_cleanup(self):
        for status in ('7', '125'):
            result = self.run_wrapper(FAKE_EXIT=status)
            self.assertEqual(result.returncode, int(status))
            self.assertIn(['rm', '--force', '--time', '0', '--ignore', OWNED_ID], self.calls())

    def test_successful_restart_check_is_informational_and_real_errors_remain(self):
        diagnostics = ('ERRO[0074] Should restart: false\n'
                       'ERRO[0074] Failed to check if container should restart: unavailable\n'
                       'ERRO[0074] Should restart: true\n')
        result = self.run_wrapper('--version', FAKE_START_STDERR=diagnostics, FAKE_EXIT='17')
        self.assertEqual(result.returncode, 17, result.stderr)
        self.assertIn('INFO[0074] Should restart: false\n', result.stderr)
        self.assertNotIn('ERRO[0074] Should restart: false\n', result.stderr)
        self.assertIn('ERRO[0074] Failed to check if container should restart: unavailable\n', result.stderr)
        self.assertIn('ERRO[0074] Should restart: true\n', result.stderr)
        self.assertNotIn('Should restart', result.stdout)

    def test_cleanup_failure_or_stall_preserves_application_status(self):
        for mode in ('FAKE_FAIL', 'FAKE_STALL'):
            for status in (0, 7, 125):
                with self.subTest(mode=mode, status=status):
                    self.log.unlink(missing_ok=True)
                    started = time.monotonic()
                    result = self.run_wrapper(FAKE_EXIT=str(status), **{mode: 'rm'})
                    self.assertEqual(result.returncode, status, result.stderr)
                    self.assertLess(time.monotonic() - started, 22)
                    self.assertIn('cleanup rm failed or timed out', result.stderr)
                    self.assertIn(OWNED_ID, result.stderr)
                    self.assertTrue(all(c[-1] == OWNED_ID for c in self.calls() if c[0] == 'rm'))

    def test_ignored_signals_force_owned_removal(self):
        for name, status in (('TERM', 143), ('INT', 130), ('HUP', 129)):
            with self.subTest(signal=name):
                self.log.unlink(missing_ok=True)
                Path(str(self.log) + '.started').unlink(missing_ok=True)
                proc, diagnostics = self.start_waiting_wrapper(FAKE_WAIT='1', FAKE_IGNORE_SIGNALS='1')
                started = time.monotonic()
                proc.send_signal(getattr(signal, 'SIG' + name))
                _, stderr = proc.communicate(timeout=25)
                self.assertEqual(proc.returncode, status, stderr)
                self.assertGreater(time.monotonic() - started, 3.5)
                self.assertLess(time.monotonic() - started, 22)
                self.assertIn(['kill', '--signal', name, OWNED_ID], self.calls())
                self.assertIn(['rm', '--force', '--time', '0', '--ignore', OWNED_ID], self.calls())
                self.assertEqual(list(diagnostics.iterdir()), [])
                self.assert_no_fake_client()

    def test_stalled_controls_and_repeated_signal_are_bounded(self):
        proc, diagnostics = self.start_waiting_wrapper(FAKE_WAIT='1', FAKE_IGNORE_SIGNALS='1',
                                                       FAKE_STALL='kill,rm')
        started = time.monotonic()
        proc.terminate()
        self.wait_marker(proc, '.stalled-kill')
        proc.send_signal(signal.SIGHUP)
        _, stderr = proc.communicate(timeout=25)
        self.assertEqual(proc.returncode, 143, stderr)
        self.assertLess(time.monotonic() - started, 22)
        self.assertIn('cleanup kill failed or timed out', stderr)
        self.assertIn('cleanup rm failed or timed out', stderr)
        self.assertEqual(len([c for c in self.calls() if c[0] == 'rm']), 1)
        self.assertEqual(list(diagnostics.iterdir()), [])
        self.assert_no_fake_client()

    def test_interrupted_creation_recovers_only_owned_identity(self):
        for phase in ('before', 'after'):
            with self.subTest(phase=phase):
                self.log.unlink(missing_ok=True)
                Path(str(self.log) + '.creating').unlink(missing_ok=True)
                proc, diagnostics = self.start_waiting_wrapper('.creating', FAKE_CREATE_PAUSE=phase)
                create = self.create()
                cid_file = Path(create[create.index('--cidfile') + 1])
                self.assertEqual(cid_file.parent.stat().st_mode & 0o777, 0o700)
                self.assertEqual(cid_file.exists(), phase == 'after')
                proc.terminate()
                _, stderr = proc.communicate(timeout=25)
                self.assertEqual(proc.returncode, 143, stderr)
                self.assertIn(['rm', '--force', '--time', '0', '--ignore', OWNED_ID], self.calls())
                self.assertFalse(any(c[0] == 'start' for c in self.calls()))
                self.assertEqual(list(diagnostics.iterdir()), [])
                self.assert_no_fake_client()

    def test_interrupted_creation_rejects_foreign_recovery_result(self):
        proc, diagnostics = self.start_waiting_wrapper('.creating', FAKE_CREATE_PAUSE='before',
                                                       FAKE_RECOVERY_ID='b' * 64)
        proc.terminate()
        _, stderr = proc.communicate(timeout=25)
        self.assertEqual(proc.returncode, 143, stderr)
        self.assertIn('could not confirm recovered container ownership', stderr)
        self.assertFalse(any(c[0] in ('rm', 'start') for c in self.calls()))
        self.assertEqual(list(diagnostics.iterdir()), [])
        self.assert_no_fake_client()

    def test_interrupted_creation_recovery_calls_are_bounded(self):
        for phase, stalled in (('before', 'ps'), ('after', 'inspect')):
            with self.subTest(phase=phase, stalled=stalled):
                self.log.unlink(missing_ok=True)
                Path(str(self.log) + '.creating').unlink(missing_ok=True)
                proc, diagnostics = self.start_waiting_wrapper('.creating', FAKE_CREATE_PAUSE=phase,
                                                               FAKE_STALL=stalled)
                started = time.monotonic()
                proc.terminate()
                _, stderr = proc.communicate(timeout=25)
                self.assertEqual(proc.returncode, 143, stderr)
                self.assertLess(time.monotonic() - started, 22)
                self.assertIn('failed or timed out', stderr)
                self.assertIn('creation outcome unresolved', stderr)
                self.assertFalse(any(c[0] in ('rm', 'start') for c in self.calls()))
                self.assertEqual(list(diagnostics.iterdir()), [])
                self.assert_no_fake_client()

    def test_signal_matrix_is_bounded_in_creation_and_attachment(self):
        # Family B's signal and stall cases (X, A, P), rewritten for the shared
        # 20 s deadline (U9): every signal, during creation and while attached to
        # an application that ignores it, with a stalled removal.
        for name, status in (('TERM', 143), ('INT', 130), ('HUP', 129)):
            sig = getattr(signal, 'SIG' + name)
            with self.subTest(signal=name, phase='creation'):
                self.log.unlink(missing_ok=True)
                Path(str(self.log) + '.creating').unlink(missing_ok=True)
                proc, diagnostics = self.start_waiting_wrapper('.creating', FAKE_CREATE_PAUSE='after')
                started = time.monotonic()
                proc.send_signal(sig)
                _, stderr = proc.communicate(timeout=25)
                self.assertEqual(proc.returncode, status, stderr)
                self.assertLess(time.monotonic() - started, 22)
                self.assertIn(['rm', '--force', '--time', '0', '--ignore', OWNED_ID], self.calls())
                self.assertFalse(any(c[0] == 'start' for c in self.calls()))
                self.assertEqual(list(diagnostics.iterdir()), [])
                self.assert_no_fake_client()
            with self.subTest(signal=name, phase='attached'):
                self.log.unlink(missing_ok=True)
                for suffix in ('.started', '.pid', '.container'):
                    Path(str(self.log) + suffix).unlink(missing_ok=True)
                proc, diagnostics = self.start_waiting_wrapper(FAKE_WAIT='1', FAKE_IGNORE_SIGNALS='1',
                                                               FAKE_STALL='rm')
                started = time.monotonic()
                proc.send_signal(sig)
                _, stderr = proc.communicate(timeout=25)
                self.assertEqual(proc.returncode, status, stderr)
                self.assertLess(time.monotonic() - started, 22)
                self.assertIn(['kill', '--signal', name, OWNED_ID], self.calls())
                self.assertIn('cleanup rm failed or timed out', stderr)
                self.assertEqual(list(diagnostics.iterdir()), [])
                self.assert_no_fake_client()

    def test_collision_reconciliation_can_be_interrupted(self):
        proc, diagnostics = self.start_waiting_wrapper('.stalled-inspect', FAKE_COLLISION='1',
                                                       FAKE_STALL='inspect')
        proc.terminate()
        _, stderr = proc.communicate(timeout=25)
        self.assertEqual(proc.returncode, 143, stderr)
        self.assertFalse(any(c[0] in ('rm', 'start') for c in self.calls()))
        self.assertEqual(list(diagnostics.iterdir()), [])
        with self.assertRaises(ProcessLookupError):
            os.kill(int(Path(str(self.log) + '.stalled-inspect').read_text()), 0)

    def test_failed_create_after_id_publication_is_cleaned(self):
        result = self.run_wrapper(FAKE_CREATED_STATUS='19')
        self.assertEqual(result.returncode, 19, result.stderr)
        self.assertIn(['rm', '--force', '--time', '0', '--ignore', OWNED_ID], self.calls())
        self.assertFalse(any(c[0] == 'start' for c in self.calls()))

    def test_failed_signal_delivery_still_removes_owned_container(self):
        proc, diagnostics = self.start_waiting_wrapper(FAKE_WAIT='1', FAKE_IGNORE_SIGNALS='1',
                                                       FAKE_FAIL='kill')
        proc.terminate()
        _, stderr = proc.communicate(timeout=25)
        self.assertEqual(proc.returncode, 143, stderr)
        self.assertIn('cleanup kill failed or timed out', stderr)
        self.assertIn(['rm', '--force', '--time', '0', '--ignore', OWNED_ID], self.calls())
        self.assertEqual(list(diagnostics.iterdir()), [])
        self.assert_no_fake_client()

    def test_timeout_prerequisite_and_independent_help(self):
        restricted = self.base / 'prerequisite-bin'
        restricted.mkdir()
        for name, target in (('bash', '/bin/bash'), ('cat', '/bin/cat'),
                             ('podman', str(self.bin / 'podman'))):
            (restricted / name).symlink_to(target)
        for unsupported in (False, True):
            with self.subTest(unsupported=unsupported):
                if unsupported:
                    timeout = restricted / 'timeout'
                    timeout.write_text('#!/bin/sh\nprintf "unsupported timeout\\n"\n')
                    timeout.chmod(0o755)
                result = self.run_wrapper(PATH=str(restricted))
                self.assertNotEqual(result.returncode, 0)
                self.assertIn('GNU timeout is required', result.stderr)
                self.assertFalse(self.calls())
                self.assertFalse(self.state.exists())
                help_result = self.run_wrapper('--container-help', PATH=str(restricted))
                self.assertEqual(help_result.returncode, 0, help_result.stderr)

    def test_build_only_operation_builds_and_exits(self):
        # U3, U16, U17: no application argument means build and exit, also from a
        # managed worktree launcher; settings are still validated before the build.
        for options in (('--container-build',), ('--container-build', '--container-git-worktree'),
                        ('--container-build', '--container-shell')):
            with self.subTest(options=options):
                self.log.unlink(missing_ok=True)
                result = self.run_wrapper(*options)
                self.assertEqual(result.returncode, 0, result.stderr)
                commands = [c[0] for c in self.calls()]
                self.assertIn('build', commands)
                self.assertFalse({'create', 'start', 'ps'} & set(commands), commands)
                self.assertFalse(self.state.exists())
        self.log.unlink(missing_ok=True)
        self.assertEqual(self.run_wrapper('--container-build', FAKE_BUILD_STATUS='17').returncode, 17)
        self.assertNotIn('create', [c[0] for c in self.calls()])
        self.log.unlink(missing_ok=True)
        result = self.run_wrapper('--container-build', FIXTURE_SHELL_MEMORY_LIMIT='lots')
        self.assertEqual(result.returncode, 1)
        self.assertEqual(self.calls(), [])
        result = self.run_wrapper('--container-build', FIXTURE_SHELL_MAINTENANCE='')
        self.assertIn('MAINTENANCE=1', result.stderr)
        self.assertNotIn('build', [c[0] for c in self.calls()])

    def test_engine_records_reject_carriage_returns_and_extra_records(self):
        # One capture rule for every read-only query (phase 3-4).
        for env in ({'FAKE_INFO_RAW': 'true linux false\r\n'}, {'FAKE_INFO_RAW': 'true linux false extra\n'},
                    {'FAKE_CONTROLLERS': '[cpu memory pids]\r'}, {'FAKE_CONTROLLERS': '[cpu memory pids]\n[cpu]'}):
            with self.subTest(env=env):
                self.log.unlink(missing_ok=True)
                result = self.run_wrapper(**env)
                self.assertNotEqual(result.returncode, 0)
                self.assertFalse(any(c[0] in ('image', 'build', 'create') for c in self.calls()))

    def test_stalled_read_only_query_is_bounded(self):
        started = time.monotonic()
        result = self.run_wrapper(FAKE_STALL='info')
        self.assertLess(time.monotonic() - started, 20)
        self.assertEqual(result.returncode, 1)
        self.assertIn('cannot query Podman', result.stderr)
        self.assertFalse(any(c[0] in ('image', 'build', 'create') for c in self.calls()))

    def test_state_paths_are_checked_before_the_engine(self):
        for value in ('relative/state', '/with:colon', '/with\nnewline'):
            with self.subTest(value=value):
                self.log.unlink(missing_ok=True)
                result = self.run_wrapper(FIXTURE_SHELL_STATE_DIR=value)
                self.assertEqual(result.returncode, 1)
                self.assertIn('FIXTURE_SHELL_STATE_DIR must be an absolute path without colon, CR or LF', result.stderr)
                self.assertEqual(self.calls(), [])

    def test_isolated_children_are_contained_and_private(self):
        # M4: every child of the isolated home and the CA mount parent.
        shared = self.state / '.config/openspec'
        shared.mkdir(parents=True)
        self.state.chmod(0o700)
        (self.state / '.config').chmod(0o700)
        shared.chmod(0o755)
        result = self.run_wrapper()
        self.assertEqual(result.returncode, 1)
        self.assertIn('state directory must be private: ' + str(shared.resolve()), result.stderr)
        shared.chmod(0o700)
        outside = self.base / 'outside-ca'
        outside.mkdir(mode=0o700)
        (self.state / 'ca').symlink_to(outside)
        bundle = self.base / 'bundle.pem'
        bundle.write_text('synthetic certificate bundle')
        result = self.run_wrapper(FIXTURE_SHELL_TRUST_HOST_CA='1', FIXTURE_SHELL_CA_BUNDLE=str(bundle))
        self.assertEqual(result.returncode, 1)
        self.assertIn('isolated configuration escapes state home', result.stderr)
        self.assertFalse(any(c[0] == 'create' for c in self.calls()))

    def test_read_only_state_mounts_existing_directories_read_only(self):
        # U6, M9: shared or isolated state, existing directories only, nothing writable.
        home = Path(self.env['HOME'])
        result = self.run_wrapper(FIXTURE_SHELL_STATE_DIR='', FIXTURE_SHELL_READONLY_STATE='1')
        self.assertEqual(result.returncode, 1)
        self.assertIn('read-only state needs an existing directory', result.stderr)
        self.assertFalse((home / '.config/fixture-shell').exists())
        for relative in ('.config/fixture-shell', '.config/openspec'):
            (home / relative).mkdir(parents=True, exist_ok=True)
            (self.state / relative).mkdir(parents=True, exist_ok=True)
        for isolated, root in (('', home), (str(self.state), self.state)):
            with self.subTest(isolated=bool(isolated)):
                self.log.unlink(missing_ok=True)
                result = self.run_wrapper(FIXTURE_SHELL_STATE_DIR=isolated, FIXTURE_SHELL_READONLY_STATE='yes')
                self.assertEqual(result.returncode, 0, result.stderr)
                create = self.create()
                volumes = [create[i + 1] for i, a in enumerate(create) if a == '--volume']
                for relative in ('.config/fixture-shell', '.config/openspec'):
                    self.assertIn(f'{(root / relative).resolve()}:/fixture-shell-home/{relative}:ro', volumes)
                self.assertFalse(any(v.endswith(':/fixture-shell-home:rw') for v in volumes))
                self.assertFalse(any(v.endswith(':rw') and '/fixture-shell-home' in v for v in volumes))

    def test_each_attempt_names_itself_and_reads_no_stdin(self):
        result = self.run_wrapper(FAKE_NAMES='my-project-0', FAKE_COLLISION='1')
        self.assertEqual(result.returncode, 0, result.stderr)
        creates = [c for c in self.calls() if c[0] == 'create']
        self.assertEqual(len(creates), 2)
        for create in creates:
            self.assertIn('CONTAINER_NAME=' + create[create.index('--name') + 1], create)

    def test_owned_name_behind_a_failed_create_is_not_a_collision(self):
        result = self.run_wrapper(FAKE_COLLISION='1', FAKE_NAME_OWNER='self')
        self.assertEqual(result.returncode, 125)
        self.assertEqual(len([c for c in self.calls() if c[0] == 'create']), 1)
        self.assertIn('creation outcome unresolved', result.stderr)

    def test_creation_records_are_validated(self):
        result = self.run_wrapper(FAKE_CID_CONTENT='b' * 64 + '\\n')
        self.assertEqual(result.returncode, 1)
        self.assertIn('inconsistent creation IDs', result.stderr)
        self.assertFalse(any(c[0] == 'start' for c in self.calls()))
        for content in ('a' * 64 + '\\x00', 'a' * 64 + '\\n' + 'a' * 64, 'not-an-id'):
            with self.subTest(content=content):
                self.log.unlink(missing_ok=True)
                result = self.run_wrapper(FAKE_CID_CONTENT=content, FAKE_CREATED_STATUS='19')
                self.assertEqual(result.returncode, 19)
                self.assertIn('invalid container ID in the private creation record', result.stderr)
                self.assertFalse(any(c[0] == 'rm' for c in self.calls()))

    def test_healthy_build_and_session_outlive_shutdown_budget(self):
        started = time.monotonic()
        result = subprocess.run([str(WRAPPER), '--container-build', '-c', 'true'], cwd=self.project,
                                env=self.env | {'FAKE_BUILD_DELAY': '21', 'FAKE_START_DELAY': '21'},
                                input='healthy input', text=True, capture_output=True, timeout=55)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertGreater(time.monotonic() - started, 40)
        self.assertIn('stdin:healthy input', result.stdout)

    def test_existing_names_and_collision_retry(self):
        result = self.run_wrapper(FAKE_NAMES='my-project-2\nmy-project-09\nother-50', FAKE_COLLISION='1')
        self.assertEqual(result.returncode, 0, result.stderr)
        creates = [c for c in self.calls() if c[0] == 'create']
        self.assertEqual(creates[0][2], 'my-project-10')
        self.assertEqual(creates[1][2], 'my-project-11')

    def test_create_failure_preserved_without_cleanup_of_other_containers(self):
        result = self.run_wrapper(FAKE_CREATE_FAILURE='1')
        self.assertEqual(result.returncode, 125)
        self.assertIn('create failed', result.stderr)
        self.assertFalse(any(c[0] in ('rm', 'start') for c in self.calls()))

    def test_term_forwarding(self):
        proc = subprocess.Popen([str(WRAPPER)], cwd=self.project, env=self.env | {'FAKE_WAIT': '1'},
                                stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        import time
        for _ in range(100):
            if Path(str(self.log) + '.started').exists():
                break
            time.sleep(0.02)
        proc.terminate()
        proc.communicate(timeout=5)
        self.assertEqual(proc.returncode, 143)
        self.assertTrue(any(c[:3] == ['kill', '--signal', 'TERM'] for c in self.calls()))

    def test_launch_verification_fails_before_image_operations(self):
        for result in ('', 'false linux false', 'true darwin false', 'true linux',
                       'true linux maybe', 'true linux false extra', 'true linux false\nextra'):
            with self.subTest(result=result):
                self.log.unlink(missing_ok=True)
                run = self.run_wrapper('--container-build', FAKE_INFO=result)
                self.assertNotEqual(run.returncode, 0)
                self.assertFalse(any(c[0] in ('image', 'build', 'create') for c in self.calls()))
        self.assertNotEqual(self.run_wrapper(FAKE_INFO_STATUS='125').returncode, 0)

    def test_verification_preserves_exact_record_boundaries_and_status(self):
        for query, valid in (('INFO', 'true linux false'), ('SOCKET', 'true /host/socket with spaces')):
            for raw, accepted in ((valid, True), (valid + '\n', True), ('', False),
                                  (valid + '\n\n', False), (valid + '\n\n\n', False),
                                  ('\n' + valid, False), (valid + '\n\nextra\n', False),
                                  (valid + '\nextra\n', False)):
                with self.subTest(query=query, raw=repr(raw)):
                    self.log.unlink(missing_ok=True)
                    result = self.run_wrapper('--container-build', '-c', 'true', FIXTURE_SHELL_PODMAN='1',
                                              **{f'FAKE_{query}_RAW': raw})
                    self.assertEqual(result.returncode == 0, accepted, result.stderr)
                    operations = [c for c in self.calls() if c[0] in ('image', 'build', 'create')]
                    self.assertEqual(bool(operations), accepted)
                    if query == 'SOCKET' and not accepted:
                        self.assertIn(str(self.socket_path), result.stderr)
                    if query == 'SOCKET' and accepted:
                        self.assertIn('/host/socket with spaces:/run/podman/podman.sock:rw', self.create())
            for raw in (valid, valid + '\n', valid + '\n\n'):
                with self.subTest(query=query, failed_after_output=repr(raw)):
                    self.log.unlink(missing_ok=True)
                    result = self.run_wrapper('--container-build', '-c', 'true', FIXTURE_SHELL_PODMAN='1',
                                              **{f'FAKE_{query}_RAW': raw, f'FAKE_{query}_STATUS': '19'})
                    self.assertNotEqual(result.returncode, 0)
                    self.assertIn('cannot query Podman', result.stderr)
                    self.assertFalse(any(c[0] in ('image', 'build', 'create') for c in self.calls()))

    def test_delegated_response_rejects_carriage_returns_before_image_operations(self):
        responses = ('true /host/socket with spaces\r\n',
                     'true /host/podman.sock\r', '\rtrue /host/podman.sock\n',
                     'tr\rue /host/podman.sock\n', 'true\r /host/podman.sock\n',
                     'true \r/host/podman.sock\n', 'true /host/pod\rman.sock\n')
        for options in ((), ('--container-build',)):
            for raw in responses:
                with self.subTest(options=options, raw=repr(raw)):
                    self.log.unlink(missing_ok=True)
                    result = self.run_wrapper(*options, FIXTURE_SHELL_PODMAN='1',
                                              FAKE_SOCKET_RAW=raw)
                    self.assertNotEqual(result.returncode, 0)
                    self.assertIn(f'invalid Podman socket response: {self.socket_path}', result.stderr)
                    self.assertFalse(any(c[0] in ('image', 'build', 'create') for c in self.calls()))

    def test_response_validation_composes_with_launch_modes(self):
        for isolated in ('', str(self.state)):
            for shell in (False, True):
                for service in ('0', '1'):
                    for bad_query in ('', 'INFO', 'SOCKET'):
                        with self.subTest(isolated=isolated, shell=shell, service=service, query=bad_query):
                            self.log.unlink(missing_ok=True)
                            options = ['--container-build', '--container-git-worktree']
                            if shell:
                                options.append('--container-shell')
                            values = {'FAKE_INFO_RAW': 'true linux false\n',
                                      'FAKE_SOCKET_RAW': 'true /host/socket with spaces\n'}
                            if bad_query:
                                values[f'FAKE_{bad_query}_RAW'] += '\n'
                            accepted = not bad_query or (bad_query == 'SOCKET' and service == '0')
                            result = self.run_wrapper(*options, FIXTURE_SHELL_STATE_DIR=isolated,
                                                      FIXTURE_SHELL_PODMAN=service, **values)
                            self.assertEqual(result.returncode == 0, accepted, result.stderr)
                            self.assertEqual(any(c[0] in ('build', 'image', 'create') for c in self.calls()), accepted)
                            if service == '0':
                                self.assertFalse(any(c[0] == '--remote' for c in self.calls()))

    def test_delegated_cr_response_preserves_query_failure_and_disabled_access(self):
        for raw in ('true /host/podman.sock\r\n', 'true /host/pod\rman.sock'):
            with self.subTest(raw=repr(raw), query_failure=True):
                self.log.unlink(missing_ok=True)
                result = self.run_wrapper('--container-build', FIXTURE_SHELL_PODMAN='1',
                                          FAKE_SOCKET_RAW=raw, FAKE_SOCKET_STATUS='19')
                self.assertNotEqual(result.returncode, 0)
                self.assertIn(f'cannot query Podman socket: {self.socket_path}', result.stderr)
                self.assertNotIn('invalid Podman socket response', result.stderr)
                self.assertFalse(any(c[0] in ('image', 'build', 'create') for c in self.calls()))
            with self.subTest(raw=repr(raw), delegation_disabled=True):
                self.log.unlink(missing_ok=True)
                result = self.run_wrapper(FIXTURE_SHELL_PODMAN='0', FAKE_SOCKET_RAW=raw)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertFalse(any(c[0] == '--remote' for c in self.calls()))
                self.assertNotIn('CONTAINER_HOST=unix:///run/podman/podman.sock', self.create())

    def test_pathless_or_relative_unix_launch_endpoint_rejected_before_query(self):
        for endpoint in ('unix://', 'unix:///', 'unix://////', 'unix://relative/socket'):
            for delegation in ('0', '1'):
                for override in ('', str(self.socket_path)):
                    with self.subTest(endpoint=endpoint, delegation=delegation, override=override):
                        self.log.unlink(missing_ok=True)
                        result = self.run_wrapper('--container-build', CONTAINER_HOST=endpoint,
                                                  FIXTURE_SHELL_PODMAN=delegation,
                                                  FIXTURE_SHELL_PODMAN_SOCKET=override)
                        self.assertNotEqual(result.returncode, 0)
                        self.assertIn('absolute Unix socket path', result.stderr)
                        self.assertEqual(self.calls(), [])

    def test_help_with_pathless_launch_endpoint(self):
        result = self.run_wrapper('--container-help', CONTAINER_HOST='unix:///')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('absolute socket pathname', result.stdout)
        self.assertEqual(self.calls(), [])
        self.assertFalse(self.state.exists())

    def test_shared_state_default_and_override(self):
        for custom in ('', str(self.base / 'custom config')):
            with self.subTest(custom=custom):
                self.log.unlink(missing_ok=True)
                result = self.run_wrapper(FIXTURE_SHELL_STATE_DIR='', FIXTURE_SHELL_CONFIG_DIR=custom)
                self.assertEqual(result.returncode, 0, result.stderr)
                home = Path(self.env['HOME'])
                source = Path(custom) if custom else home / '.config/fixture-shell'
                self.assertIn(f'{source}:/fixture-shell-home/.config/fixture-shell:rw', self.create())
                self.assertIn(f'{home}/.config/openspec:/fixture-shell-home/.config/openspec:rw', self.create())
                self.assertNotIn(f'{self.state}:/fixture-shell-home:rw', self.create())
                self.assertFalse((home / '.cache').exists())
                # Only the toolchain library is created below ~/.local/share.
                self.assertEqual([p.name for p in (home / '.local/share').iterdir()], ['sandbox-toolchains'])

    def test_state_conflict_fails_without_engine(self):
        result = self.run_wrapper(FIXTURE_SHELL_CONFIG_DIR=str(self.base / 'custom'))
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('conflicts', result.stderr)
        self.assertFalse(self.calls())

    def test_state_overlapping_the_workspace_fails_without_engine(self):
        alias = self.base / 'alias'
        alias.symlink_to(self.project)
        for case, state in (('workspace', self.project), ('inside', self.project / '.sandbox-state'),
                            ('containing', self.project.parent), ('symlink', alias / 'state')):
            with self.subTest(case=case):
                self.log.unlink(missing_ok=True)
                result = self.run_wrapper(FIXTURE_SHELL_STATE_DIR=str(state))
                self.assertNotEqual(result.returncode, 0)
                self.assertIn('FIXTURE_SHELL_STATE_DIR must not overlap the workspace: ' + str(state), result.stderr)
                self.assertFalse(self.calls())
                self.assertFalse((self.project / '.sandbox-state').exists())
        result = self.run_wrapper('--container-git-worktree', FIXTURE_SHELL_STATE_DIR=str(self.project.parent / 'state'))
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('must not overlap the workspace', result.stderr)
        self.assertFalse(self.calls())

    def test_private_creation_does_not_change_host_command_umask(self):
        for mask in (0o022, 0o002):
            for isolated in (False, True):
                with self.subTest(mask=oct(mask), isolated=isolated):
                    home = self.base / f'home-{mask}-{isolated}'
                    state = self.base / f'state-{mask}-{isolated}'
                    umask_log = self.base / f'umask-{mask}-{isolated}.jsonl'
                    result = self.run_wrapper('--container-build', '-c', 'true', caller_umask=mask,
                                              HOME=str(home), FAKE_UMASK_LOG=str(umask_log),
                                              FIXTURE_SHELL_STATE_DIR=str(state) if isolated else '')
                    self.assertEqual(result.returncode, 0, result.stderr)
                    observations = [json.loads(line) for line in umask_log.read_text().splitlines()]
                    self.assertTrue({'build', 'create', 'start', 'rm'} <= {c for c, _ in observations})
                    self.assertTrue(all(actual == mask for _, actual in observations), observations)
                    root = state if isolated else home
                    for relative in ('.', '.config', '.config/fixture-shell', '.config/openspec'):
                        self.assertEqual((root / relative).stat().st_mode & 0o777, 0o700)

    def test_shell_state_and_history_location(self):
        for isolated in ('', str(self.state)):
            with self.subTest(isolated=isolated):
                self.log.unlink(missing_ok=True)
                result = self.run_wrapper(FIXTURE_SHELL_STATE_DIR=isolated)
                self.assertEqual(result.returncode, 0, result.stderr)
                environment = self.environment()
                self.assertIn('HOME=/fixture-shell-home', environment)
                self.assertIn('FIXTURE_SHELL_CONFIG_DIR=/fixture-shell-home/.config/fixture-shell', environment)
                self.assertIn('HISTFILE=/fixture-shell-home/.config/fixture-shell/bash_history', environment)
                volumes = self.volumes()
                if isolated:
                    self.assertIn(f'{self.state}:/fixture-shell-home:rw', volumes)
                else:
                    home = Path(self.env['HOME'])
                    self.assertIn(f'{home}/.config/fixture-shell:/fixture-shell-home/.config/fixture-shell:rw',
                                  volumes)
                    self.assertIn(f'{home}/.config/openspec:/fixture-shell-home/.config/openspec:rw', volumes)

    def test_state_alias_and_configuration_escape(self):
        self.state.mkdir(mode=0o700)
        alias = self.base / 'state-alias'
        alias.symlink_to(self.state)
        self.assertEqual(self.run_wrapper(FIXTURE_SHELL_STATE_DIR=str(alias)).returncode, 0)
        self.assertIn(f'{self.state}:/fixture-shell-home:rw', self.create())
        outside = self.base / 'outside'
        outside.mkdir()
        for relative in ('.config/fixture-shell', '.config/openspec'):
            with self.subTest(relative=relative):
                target = self.state / relative
                target.rmdir()
                target.symlink_to(outside)
                self.log.unlink(missing_ok=True)
                result = self.run_wrapper()
                self.assertNotEqual(result.returncode, 0)
                self.assertIn('escapes', result.stderr)
                self.assertFalse(any(c[0] == 'create' for c in self.calls()))
                target.unlink()
                target.mkdir(mode=0o700)

    def test_private_existing_configuration_and_wrong_owner(self):
        self.state.mkdir(mode=0o700)
        config = self.state / '.config/fixture-shell'
        config.mkdir(mode=0o755, parents=True)
        result = self.run_wrapper()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn(str(config), result.stderr)
        self.assertEqual(config.stat().st_mode & 0o777, 0o755)
        config.chmod(0o700)
        stat = self.bin / 'stat'
        stat.write_text('#!/bin/bash\nif [[ "$2" == %u ]]; then echo 999999; else exec /usr/bin/stat "$@"; fi\n')
        stat.chmod(0o755)
        result = self.run_wrapper()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('belong', result.stderr)

    def test_inaccessible_state_and_ignored_permissions(self):
        # Every state directory the caller cannot enter, or cannot create, stops
        # with the wrapper's own diagnostic and hint, never a raw shell error.
        home = self.base / 'host-home'
        config = home / '.config/fixture-shell'
        shared = home / '.config/openspec'
        cases = [
            ('isolated home', {}, [self.state], self.state, 'not accessible'),
            ('isolated child', {}, [self.state, self.state / '.config/fixture-shell'],
             self.state / '.config/fixture-shell', 'not accessible'),
            ('shared configuration', {'FIXTURE_SHELL_STATE_DIR': ''}, [config], config, 'not accessible'),
            ('shared directory', {'FIXTURE_SHELL_STATE_DIR': ''}, [config, shared], shared, 'not accessible'),
            ('read-only state', {'FIXTURE_SHELL_STATE_DIR': '', 'FIXTURE_SHELL_READONLY_STATE': '1'},
             [config, shared], config, 'not accessible'),
            ('uncreatable', {'FIXTURE_SHELL_STATE_DIR': ''}, [], config, 'cannot create'),
        ]
        for name, env, directories, locked, problem in cases:
            with self.subTest(name=name):
                shutil.rmtree(home, ignore_errors=True)
                shutil.rmtree(self.state, ignore_errors=True)
                home.mkdir(mode=0o700)
                for directory in directories:
                    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
                target = home if problem == 'cannot create' else locked
                target.chmod(0o500 if problem == 'cannot create' else 0o000)
                self.log.unlink(missing_ok=True)
                try:
                    result = self.run_wrapper(**env)
                finally:
                    target.chmod(0o700)
                self.assertEqual(result.returncode, 1, result.stderr)
                self.assertIn(f'fixture-shell: ', result.stderr)
                self.assertIn(f'{problem}', result.stderr)
                self.assertIn(str(locked), result.stderr)
                self.assertIn('choose another directory', result.stderr)
                self.assertNotIn('Permission denied', result.stderr)
                self.assertFalse(any(c[0] in ('image', 'build', 'create') for c in self.calls()), name)
        shutil.rmtree(self.state, ignore_errors=True)
        stat = self.bin / 'stat'
        stat.write_text('#!/bin/bash\nif [[ "$2" == %a ]]; then echo 777; else exec /usr/bin/stat "$@"; fi\n')
        stat.chmod(0o755)
        self.assertIn('native Linux storage', self.run_wrapper().stderr)

    def test_socket_disabled_values_skip_delegation_checks(self):
        for value in ('', '0', 'true', 'yes', '01', 'maybe'):
            with self.subTest(value=value):
                self.log.unlink(missing_ok=True)
                result = self.run_wrapper(FIXTURE_SHELL_PODMAN=value,
                                          FIXTURE_SHELL_PODMAN_SOCKET='relative-missing')
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertFalse(any(c[0] == '--remote' for c in self.calls()))
                self.assertNotIn('CONTAINER_HOST=unix:///run/podman/podman.sock', self.create())
                create = self.create()
                self.assertIn('CONTAINER_HOST', [a for i, a in enumerate(create[1:]) if create[i] == '--unsetenv'])

    def test_socket_precedence_and_remapping(self):
        alias = self.base / 'socket-alias'
        alias.symlink_to(self.socket_path)
        cases = (
            {'FIXTURE_SHELL_PODMAN_SOCKET': str(alias), 'CONTAINER_HOST': 'unix:///other/engine'},
            {'FIXTURE_SHELL_PODMAN_SOCKET': '', 'CONTAINER_HOST': f'unix://{self.socket_path}'},
        )
        for env in cases:
            with self.subTest(env=env):
                self.log.unlink(missing_ok=True)
                result = self.run_wrapper(FIXTURE_SHELL_PODMAN='1', **env)
                self.assertEqual(result.returncode, 0, result.stderr)
                query = next(c for c in self.calls() if c[0] == '--remote')
                self.assertEqual(query[2], f'unix://{self.socket_path}')
                self.assertIn('/host/podman.sock:/run/podman/podman.sock:rw', self.create())
        runtime = self.base / 'runtime'
        (runtime / 'podman').mkdir(parents=True)
        (runtime / 'podman/podman.sock').symlink_to(self.socket_path)
        self.log.unlink()
        result = self.run_wrapper(FIXTURE_SHELL_PODMAN='1', FIXTURE_SHELL_PODMAN_SOCKET='',
                                  XDG_RUNTIME_DIR=str(runtime))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(next(c for c in self.calls() if c[0] == '--remote')[2], f'unix://{self.socket_path}')

    def test_podman5_unix_url_host_socket_is_bound_as_path(self):
        # Podman 5 reports Host.RemoteSocket.Path as a unix:// URL.
        for reported, accepted in (('unix:///host/podman.sock', True), ('unix://relative.sock', False)):
            with self.subTest(reported=reported):
                self.log.unlink(missing_ok=True)
                result = self.run_wrapper(FIXTURE_SHELL_PODMAN='1', FAKE_HOST_SOCKET=reported)
                self.assertEqual(result.returncode == 0, accepted, result.stderr)
                if accepted:
                    self.assertIn('/host/podman.sock:/run/podman/podman.sock:rw', self.create())
                    self.assertNotIn('unix:///host/podman.sock:', self.create())
                else:
                    self.assertIn('absolute host socket path', result.stderr)

    def test_reported_host_socket_must_be_a_socket_when_visible(self):
        # The reported host path becomes a bind source: never the root, and never
        # a visible non-socket. An invisible path is the remapped-caller case.
        directory = self.base / 'reported-directory'
        directory.mkdir()
        regular = self.base / 'reported-file'
        regular.write_text('not a socket')
        dangling = self.base / 'reported-dangling'
        dangling.symlink_to(self.base / 'missing-target')
        alias = self.base / 'reported-alias'
        alias.symlink_to(self.socket_path)
        refused = ('/', '//', 'unix:///', str(directory), str(regular), str(dangling))
        for options, reported in [(o, r) for o in ((), ('--container-build',)) for r in refused]:
            with self.subTest(options=options, reported=reported):
                self.log.unlink(missing_ok=True)
                result = self.run_wrapper(*options, FIXTURE_SHELL_PODMAN='1', FAKE_HOST_SOCKET=reported)
                self.assertEqual(result.returncode, 1, result.stderr)
                self.assertIn(str(self.socket_path), result.stderr)
                self.assertFalse(any(c[0] in ('image', 'build', 'create') for c in self.calls()))
        for reported in (str(self.socket_path), str(alias), '/host/podman.sock'):
            with self.subTest(reported=reported):
                self.log.unlink(missing_ok=True)
                result = self.run_wrapper(FIXTURE_SHELL_PODMAN='1', FAKE_HOST_SOCKET=reported)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertIn(f'{reported}:/run/podman/podman.sock:rw', self.create())

    def test_socket_fallback_and_invalid_sources(self):
        default = f'/run/user/{os.getuid()}/podman/podman.sock'
        result = self.run_wrapper(FIXTURE_SHELL_PODMAN='1', FIXTURE_SHELL_PODMAN_SOCKET='')
        if Path(default).exists():
            # A real user service exists on this host; the fake engine answers for it,
            # so verify the selected fallback endpoint instead of a missing-socket error.
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(next(c for c in self.calls() if c[0] == '--remote')[2], 'unix://' + default)
        else:
            self.assertIn(default, result.stderr)
        for source in ('relative', str(self.base / 'missing'), str(WRAPPER)):
            with self.subTest(source=source):
                self.log.unlink(missing_ok=True)
                result = self.run_wrapper('--container-build', FIXTURE_SHELL_PODMAN='1',
                                          FIXTURE_SHELL_PODMAN_SOCKET=source)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn(source, result.stderr)
                self.assertFalse(any(c[0] in ('build', 'image', 'create') for c in self.calls()))
        self.socket_path.chmod(0o000)
        try:
            self.assertIn('not accessible', self.run_wrapper(FIXTURE_SHELL_PODMAN='1').stderr)
        finally:
            self.socket_path.chmod(0o700)

    def test_invalid_delegation_results_gate_explicit_build(self):
        for env in ({'FAKE_SOCKET_STATUS': '125'}, {'FAKE_SOCKET_ROOTLESS': ''},
                    {'FAKE_SOCKET_ROOTLESS': 'unexpected'}, {'FAKE_SOCKET_ROOTLESS': 'false'},
                    {'FAKE_HOST_SOCKET': ''}, {'FAKE_HOST_SOCKET': 'relative'},
                    {'FAKE_HOST_SOCKET': '/path\nextra'}):
            with self.subTest(env=env):
                self.log.unlink(missing_ok=True)
                result = self.run_wrapper('--container-build', FIXTURE_SHELL_PODMAN='1', **env)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn(str(self.socket_path), result.stderr)
                self.assertFalse(any(c[0] in ('image', 'build', 'create') for c in self.calls()))

    def test_composition_and_independence_in_both_state_modes(self):
        for isolated in ('', str(self.state)):
            for shell in (False, True):
                for yolo in ('0', '1'):
                    for service in ('0', '1'):
                        with self.subTest(isolated=isolated, shell=shell, yolo=yolo, service=service):
                            self.log.unlink(missing_ok=True)
                            options = ['--container-build', '--container-git-worktree', '-c', 'true']
                            if shell:
                                options.append('--container-shell')
                            result = self.run_wrapper(*options, FIXTURE_SHELL_STATE_DIR=isolated,
                                                      OTHER_AGENT_YOLO=yolo, FIXTURE_SHELL_PODMAN=service)
                            self.assertEqual(result.returncode, 0, result.stderr)
                            create = self.create()
                            self.assertNotIn('--dangerously-skip-permissions', create)
                            self.assertEqual('CONTAINER_HOST=unix:///run/podman/podman.sock' in create, service == '1')
                            unsets = [a for i, a in enumerate(create[1:]) if create[i] == '--unsetenv']
                            self.assertEqual('CONTAINER_HOST' in unsets, service != '1')
                            self.assertIn('CONTAINER_CONNECTION', unsets)
                            self.assertNotIn('--read-only-tmpfs=false', create)
                            mounts = [create[i+1] for i, arg in enumerate(create) if arg == '--tmpfs']
                            # U7: one layout; the shared-state home is an ephemeral tmpfs;
                            # delegation adds the nested Podman storage (U12).
                            expected = ['/tmp:rw,nosuid,nodev,noexec,size=512m,mode=1777',
                                        '/run:rw,nosuid,nodev,noexec,size=32m',
                                        '/var/tmp:rw,nosuid,nodev,noexec,size=512m,mode=1777']
                            if not isolated:
                                expected.append('/fixture-shell-home:rw,nosuid,nodev,noexec,size=512m,mode=1777')
                            if service == '1':
                                expected += ['/var/lib/containers:rw,noexec,nosuid,nodev,mode=0700,U,size=256m',
                                             '/run/containers:rw,noexec,nosuid,nodev,mode=0700,U,size=64m']
                            self.assertEqual(mounts, expected)
                            self.assertIn(f'{self.project.parent}:{self.project.parent}:rw', create)

    def test_disabled_delegation_preserves_host_launch_endpoint(self):
        probe = self.bin / 'podman'
        probe.write_text(FAKE.replace("args = sys.argv[1:]",
                         "assert os.environ['CONTAINER_HOST'] == 'unix:///launch/socket'\nargs = sys.argv[1:]"))
        result = self.run_wrapper('--container-build', '-c', 'true', CONTAINER_HOST='unix:///launch/socket')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('--unsetenv', self.create())

    def test_ca_mount_and_security_policy(self):
        ca = self.base / 'bundle.pem'
        ca.write_text('synthetic certificate bundle')
        for isolated in ('', str(self.state)):
            for trust in ('0', '1', 'TrUe'):
                self.log.unlink(missing_ok=True)
                result = self.run_wrapper(FIXTURE_SHELL_STATE_DIR=isolated,
                                          FIXTURE_SHELL_TRUST_HOST_CA=trust,
                                          FIXTURE_SHELL_CA_BUNDLE=str(ca))
                self.assertEqual(result.returncode, 0, result.stderr)
                create = self.create()
                for variable in ('SSL_CERT_FILE', 'REQUESTS_CA_BUNDLE', 'CURL_CA_BUNDLE', 'NODE_EXTRA_CA_CERTS'):
                    self.assertEqual(f'{variable}=/fixture-shell-home/ca/bundle.pem' in create, trust != '0')
                self.assertEqual(f'{ca}:/fixture-shell-home/ca/bundle.pem:ro' in create, trust != '0')
                self.assertIn('/tmp:rw,nosuid,nodev,noexec,size=512m,mode=1777', create)
                self.assertIn('/run:rw,nosuid,nodev,noexec,size=32m', create)
                self.assertFalse(any(x.startswith(('--privileged', '--cap-add')) for x in create))
                self.assertEqual([x for x in create if x.startswith('--security-opt')],
                                 ['--security-opt=no-new-privileges'])
                self.assertFalse(any(x.endswith((':z', ':Z')) for x in create))
        self.log.unlink()
        self.assertNotEqual(self.run_wrapper(FIXTURE_SHELL_TRUST_HOST_CA='1',
                                            FIXTURE_SHELL_CA_BUNDLE='/missing').returncode, 0)
        self.assertFalse(any(c[0] in ('image', 'build', 'create') for c in self.calls()))

    def test_symlink_invocation_and_native_permissions(self):
        alias = self.base / 'agent-alias'
        alias.symlink_to(WRAPPER)
        result = subprocess.run([str(alias), '--container-build', '--dangerously-skip-permissions'],
                                cwd=self.project, env=self.env, input='', text=True, capture_output=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        build = next(c for c in self.calls() if c[0] == 'build')
        self.assertEqual(build[-3:], ['--file', str(ROOT / 'Containerfile'), str(ROOT)])
        self.assertEqual(self.create()[-1], '--dangerously-skip-permissions')

    def test_collision_exhaustion_and_diagnostic_cleanup(self):
        diagnostics = self.base / 'diagnostics'
        diagnostics.mkdir()
        result = self.run_wrapper(FAKE_COLLISION='1', FAKE_ALWAYS_COLLIDE='1', TMPDIR=str(diagnostics))
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('20 attempts', result.stderr)
        self.assertEqual(len([c for c in self.calls() if c[0] == 'create']), 20)
        self.assertFalse(list(diagnostics.iterdir()))
        self.assertFalse(any(c[0] == 'rm' for c in self.calls()))

    def test_int_and_hup_forwarding(self):
        import signal
        import time
        for name, status in (('INT', 130), ('HUP', 129)):
            self.log.unlink(missing_ok=True)
            Path(str(self.log) + '.started').unlink(missing_ok=True)
            proc = subprocess.Popen([str(WRAPPER)], cwd=self.project, env=self.env | {'FAKE_WAIT': '1'},
                                    stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            try:
                for _ in range(100):
                    if Path(str(self.log) + '.started').exists():
                        break
                    time.sleep(0.02)
                proc.send_signal(getattr(signal, 'SIG' + name))
                proc.communicate(timeout=5)
                self.assertEqual(proc.returncode, status)
                self.assertTrue(any(c[:3] == ['kill', '--signal', name] for c in self.calls()))
                self.assertIn(['rm', '--force', '--time', '0', '--ignore', OWNED_ID], self.calls())
                # Only the wrapper forwards the signal; the attached client does not proxy it.
                self.assertIn('--sig-proxy=false', next(c for c in self.calls() if c[0] == 'start'))
            finally:
                if proc.poll() is None:
                    proc.kill()
                    proc.communicate()



from sandbox_profile import AGENT_FIXTURE  # noqa: E402

sys.path.insert(0, str(ROOT / 'network'))
import agent_profile  # noqa: E402
sys.path.pop(0)
AGENT_PROFILE = agent_profile.load(AGENT_FIXTURE / 'profile.json')

# A second fixture root whose agent part defines every hook and declares
# authentication methods: the agent-only paths of the core.
AGENT_ROOT = fixture_root(AGENT_FIXTURE)
atexit.register(shutil.rmtree, AGENT_ROOT, True)
AGENT_WRAPPER = AGENT_ROOT / AGENT_PROFILE.wrapper


class AgentProfileSettingsTests(unittest.TestCase):
    """Phases 1-2 with the fixture agent part (docs/launcher-contract.md)."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='sandbox-agent-', dir=os.environ.get('SANDBOX_TEST_TMPDIR'))
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        self.bin = self.base / 'bin'
        self.bin.mkdir()
        (self.bin / 'podman').write_text(FAKE)
        (self.bin / 'podman').chmod(0o755)
        self.project = self.base / 'project'
        self.project.mkdir()
        self.log = self.base / 'calls.jsonl'
        self.hooks = self.base / 'hooks.log'
        self.env = {'PATH': str(self.bin) + ':' + os.environ['PATH'], 'HOME': str(self.base / 'home'),
                    'FAKE_LOG': str(self.log), 'FIXTURE_HOOK_LOG': str(self.hooks), 'FAKE_LABEL_HASH': BUILD_HASH}

    def run_agent(self, *args, wrapper=AGENT_WRAPPER, **env):
        return subprocess.run([str(wrapper), *args], cwd=self.project, env=self.env | env, input='',
                              text=True, capture_output=True, timeout=30)

    def engine_calls(self):
        return self.log.read_text().splitlines() if self.log.exists() else []

    def hook_calls(self):
        return [line.split('\t') for line in self.hooks.read_text().splitlines()] if self.hooks.exists() else []

    def test_agent_profile_defaults_to_provider_and_needs_setup(self):
        # U1: an agent wrapper exists to use its provider; without saved settings it needs setup.
        for value in (None, ''):
            with self.subTest(value=value):
                env = {} if value is None else {'FIXTURE_AGENT_NETWORK': value}
                result = self.run_agent(**env)
                self.assertEqual(result.returncode, 1)
                self.assertIn('setup required: provider sessions', result.stderr)
                self.assertIn('--container-setup', result.stderr)
                self.assertEqual(self.engine_calls(), [])

    def test_provider_setup_guidance_from_the_windows_entry(self):
        # Both refusals name the Windows step: without an installation, and with
        # one but without the provider settings setup saves.
        install = self.base / 'install'
        shutil.copytree(AGENT_ROOT, install)
        (install / 'network/bin').mkdir(exist_ok=True)
        (install / 'network/bin/guard.sha256').write_text('0' * 64 + '  guard\n')
        step = 'run ' + AGENT_PROFILE.name + '.ps1 --container-setup from Windows'
        cases = (
            (AGENT_WRAPPER, 'provider sessions need a protected installation; ' + step +
                ', or set ' + AGENT_PROFILE.env_prefix + '_NETWORK=unrestricted'),
            (install / AGENT_PROFILE.wrapper, 'provider sessions, the default for ' + AGENT_PROFILE.display_name +
                ', need the settings setup saves; ' + step + '\n'),
        )
        for wrapper, message in cases:
            with self.subTest(wrapper=wrapper):
                result = self.run_agent(wrapper=wrapper, WRAPPER_WINDOWS_ENTRY='/mnt/c/Work')
                self.assertEqual(result.returncode, 1)
                self.assertIn('setup required: ' + message, result.stderr)
                self.assertNotIn(str(wrapper), result.stderr)
                self.assertNotIn('managed launcher', result.stderr)
                result = self.run_agent(wrapper=wrapper)
                self.assertIn('--container-setup and use the managed launcher', result.stderr)
                self.assertNotIn('.ps1', result.stderr)
        self.assertEqual(self.engine_calls(), [])

    def test_shell_profile_defaults_to_offline(self):
        result = self.run_agent(wrapper=WRAPPER)
        self.assertEqual(result.returncode, 1)
        self.assertIn('setup required: offline sessions', result.stderr)
        self.assertEqual(self.engine_calls(), [])

    def test_explicit_provider_mode_names_missing_settings(self):
        result = self.run_agent(FIXTURE_AGENT_NETWORK='provider')
        self.assertEqual(result.returncode, 1)
        self.assertIn('setup required: provider sessions', result.stderr)
        install = self.base / 'install'
        shutil.copytree(AGENT_ROOT, install)
        (install / 'network/bin').mkdir(exist_ok=True)
        (install / 'network/bin/guard.sha256').write_text('0' * 64 + '  guard\n')
        result = self.run_agent(wrapper=install / AGENT_PROFILE.wrapper, FIXTURE_AGENT_NETWORK='provider')
        self.assertEqual(result.returncode, 1)
        self.assertIn('provider mode requires FIXTURE_AGENT_NETWORK_PROFILE and FIXTURE_AGENT_NETWORK_POLICY',
                      result.stderr)
        self.assertEqual(self.engine_calls(), [])

    def test_mode_values_follow_the_profile(self):
        result = self.run_agent(FIXTURE_AGENT_NETWORK='direct')
        self.assertIn('must be offline, provider, or unrestricted', result.stderr)
        result = self.run_agent(wrapper=WRAPPER, FIXTURE_SHELL_NETWORK='provider')
        self.assertIn('the profile declares no authentication method', result.stderr)

    def test_help_composes_profile_provider_and_agent_parts(self):
        # Only bash itself: help needs no other host tool.
        (self.bin / 'bash').symlink_to(shutil.which('bash'))
        result = self.run_agent('--container-help', PATH=str(self.bin))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('Usage: ' + AGENT_PROFILE.wrapper, result.stdout)
        self.assertIn('provider (default when unset or empty)', result.stdout)
        self.assertIn('fixture-account: api.provider.test, login.provider.test', result.stdout)
        self.assertIn('fixture-api: api.provider.test', result.stdout)
        self.assertIn('Only offline mode removes this channel', result.stdout)
        self.assertIn('FIXTURE_AGENT_EXTRA', result.stdout)
        self.assertLess(result.stdout.index('FIXTURE_AGENT_READONLY_STATE'), result.stdout.index('FIXTURE_AGENT_EXTRA'))
        shell = self.run_agent('--container-help', wrapper=WRAPPER, PATH=str(self.bin))
        self.assertIn('provider is unavailable', shell.stdout)
        self.assertNotIn('Allowed hosts', shell.stdout)
        self.assertEqual(self.engine_calls(), [])

    def test_settings_are_validated_before_any_engine_call(self):
        cases = (
            ({'FIXTURE_AGENT_ENV_VARS': 'GOOD 1BAD'}, 'FIXTURE_AGENT_ENV_VARS contains an invalid variable name: 1BAD'),
            ({'FIXTURE_AGENT_READONLY_STATE': 'maybe'}, 'FIXTURE_AGENT_READONLY_STATE must be 0, 1, true'),
            ({'FIXTURE_AGENT_YOLO': 'perhaps'}, 'FIXTURE_AGENT_YOLO must be 0, 1, true'),
            ({'FIXTURE_AGENT_IMAGE': 'localhost/agent latest'}, 'must not contain whitespace or control characters'),
            ({'FIXTURE_CONFIG_DIR': 'relative/config'}, 'FIXTURE_CONFIG_DIR must be an absolute path'),
            ({'FIXTURE_CONFIG_DIR': '/with:colon'}, 'FIXTURE_CONFIG_DIR must be an absolute path'),
        )
        for env, message in cases:
            with self.subTest(env=env):
                self.log.unlink(missing_ok=True)
                result = self.run_agent(FIXTURE_AGENT_NETWORK='unrestricted', **env)
                self.assertEqual(result.returncode, 1, result.stderr)
                self.assertIn(message, result.stderr)
                self.assertEqual(self.engine_calls(), [])
        self.log.unlink(missing_ok=True)
        result = self.run_agent(FIXTURE_AGENT_NETWORK='unrestricted',
                                FIXTURE_AGENT_ENV_VARS='GH_TOKEN\tOTHER\n THIRD', FIXTURE_AGENT_READONLY_STATE='yes',
                                FIXTURE_HOOK_FAIL='agent_validate')
        self.assertIn('hook agent_validate failed', result.stderr)

    def test_agent_validate_runs_after_settings_with_the_mode(self):
        result = self.run_agent(FIXTURE_AGENT_NETWORK='unrestricted', FIXTURE_HOOK_FAIL='agent_validate')
        self.assertEqual(result.returncode, 1)
        self.assertIn('hook agent_validate failed', result.stderr)
        self.assertEqual(self.engine_calls(), [])
        calls = self.hook_calls()
        self.assertEqual([call[0] for call in calls], ['agent_validate'])
        self.assertEqual(calls[0][1], 'unrestricted')
        self.assertEqual(calls[0][2:], ['token=unset', 'container=unset'])


    def session_create(self, result):
        self.assertEqual(result.returncode, 0, result.stderr)
        calls = [json.loads(line) for line in self.engine_calls()]
        return next(c for c in calls if c[0] == 'create')

    def test_agent_mounts_are_validated_and_applied(self):
        source = self.base / 'agents'
        source.mkdir()
        create = self.session_create(self.run_agent(
            FIXTURE_AGENT_NETWORK='unrestricted',
            FIXTURE_HOOK_MOUNTS=f'ro:{source}:/fixture-home/.agents tmpfs:/fixture-home/.npm:64M'))
        self.assertIn(f'{source}:/fixture-home/.agents:ro', create)
        self.assertIn('/fixture-home/.npm:rw,noexec,nosuid,nodev,mode=0700,U,size=64M', create)
        refused = (f'rw:{source}:/fixture-home/.agents', f'ro:{source}:/tmp', f'ro:{source}:/fixture-home',
                   f'ro:{source}:/', f'ro:{self.base}/missing:/fixture-home/.missing', 'tmpfs:/fixture-home/.npm:64M,exec',
                   f'ro:{source}:relative', f'ro:{source}:/fixture-home/../etc',
                   f'ro:{source}:/fixture-home/.a ro:{source}:/fixture-home/.a')
        for spec in refused:
            with self.subTest(spec=spec):
                self.log.unlink(missing_ok=True)
                result = self.run_agent(FIXTURE_AGENT_NETWORK='unrestricted', FIXTURE_HOOK_MOUNTS=spec)
                self.assertEqual(result.returncode, 1, result.stderr)
                self.assertIn('hook agent_mounts returned', result.stderr)
                self.assertNotIn('create', [json.loads(line)[0] for line in self.engine_calls()])

    def test_profile_may_allow_executable_temporary_storage(self):
        create = self.session_create(self.run_agent(FIXTURE_AGENT_NETWORK='unrestricted'))
        mounts = [create[i + 1] for i, arg in enumerate(create) if arg == '--tmpfs']
        self.assertIn('/tmp:rw,nosuid,nodev,exec,size=512m,mode=1777', mounts)
        self.assertIn('/var/tmp:rw,nosuid,nodev,noexec,size=512m,mode=1777', mounts)
        self.assertIn('/run:rw,nosuid,nodev,noexec,size=32m', mounts)
        self.assertIn('/fixture-home:rw,nosuid,nodev,exec,size=512m,mode=1777', mounts)


    def environment_of(self, create):
        return [create[i + 1] for i, arg in enumerate(create) if arg == '--env']

    def test_unrestricted_environment_order_forwarding_and_hooks(self):
        # M6, U10, U11, U13: order, forwarding, reserved names and approval bypass.
        host = {'TERM': 'xterm', 'LANG': 'C.UTF-8', 'HTTPS_PROXY': 'http://proxy.test:3128', 'EDITOR': 'vim',
                'FIXTURE_API_KEY': 'host-key', 'FIXTURE_FORWARDED': 'agent-value', 'GH_TOKEN': 'token',
                'FIXTURE_AGENT_YOLO': '1', 'FIXTURE_AGENT_ENV_VARS': 'GH_TOKEN HOME FIXTURE_FIXED EMPTY_VALUE'}
        result = self.run_agent('--first', FIXTURE_AGENT_NETWORK='unrestricted', EMPTY_VALUE='', **host)
        create = self.session_create(result)
        env = self.environment_of(create)
        for name in ('TERM', 'LANG', 'HTTPS_PROXY', 'FIXTURE_FORWARDED', 'GH_TOKEN'):
            self.assertIn(name, env)
        self.assertNotIn('FIXTURE_API_KEY', env)
        self.assertNotIn('EMPTY_VALUE', env)
        self.assertIn('EDITOR=nano', env)
        self.assertIn('FIXTURE_FIXED=1', env)
        for skipped in ('HOME', 'FIXTURE_FIXED'):
            self.assertIn(f'FIXTURE_AGENT_ENV_VARS: skipping {skipped}', result.stderr)
        order = [env.index(name) for name in ('TERM', 'FIXTURE_FORWARDED', 'GH_TOKEN', 'FIXTURE_BYPASS=1',
                                              'HOME=/fixture-home', 'FIXTURE_ALWAYS=1')]
        self.assertEqual(order, sorted(order))
        self.assertNotIn('FIXTURE_TELEMETRY=0', env)
        self.assertNotIn('FIXTURE_PROVIDER_ONLY=1', env)
        unsets = [create[i + 1] for i, arg in enumerate(create) if arg == '--unsetenv']
        self.assertEqual(unsets, ['DBUS_SESSION_BUS_ADDRESS', 'CONTAINER_CONNECTION', 'CONTAINER_HOST'])
        self.assertIn('--init', create)
        self.assertNotIn('--entrypoint', create)
        self.assertEqual(create[-4:], ['--fixture-mode', 'unrestricted', '--fixture-bypass', '--first'])

    def test_shell_mode_skips_the_agent_arguments_and_bypass(self):
        create = self.session_create(self.run_agent('--container-shell', '-c', 'true',
                                                    FIXTURE_AGENT_NETWORK='unrestricted', FIXTURE_AGENT_YOLO='1'))
        self.assertEqual(create[create.index('--entrypoint') + 1], '/bin/bash')
        self.assertEqual(create[-2:], ['-c', 'true'])
        self.assertNotIn('FIXTURE_BYPASS=1', self.environment_of(create))
        calls = [call[0] for call in self.hook_calls()]
        self.assertNotIn('agent_approval_bypass', calls)
        self.assertNotIn('agent_command_args', calls)

    def test_agent_environment_cannot_set_core_names(self):
        for entries in ('HOME=/elsewhere', 'CONTAINER_NAME=x', 'bad-name=1'):
            with self.subTest(entries=entries):
                self.log.unlink(missing_ok=True)
                result = self.run_agent(FIXTURE_AGENT_NETWORK='unrestricted', FIXTURE_HOOK_ENV=entries)
                self.assertEqual(result.returncode, 1)
                self.assertIn('hook agent_environment returned', result.stderr)

    def test_restricted_environment_and_application(self):
        wrapper = synthetic_install(self.base, AGENT_ROOT, AGENT_PROFILE.wrapper)
        host = {'HTTPS_PROXY': 'http://proxy.test:3128', 'LANG': 'C.UTF-8',
                'FIXTURE_AGENT_ENV_VARS': 'HTTPS_PROXY FIXTURE_TELEMETRY'}
        result = self.run_agent('--first', wrapper=wrapper, FIXTURE_AGENT_NETWORK='offline', FAKE_NETWORK='1',
                                FAKE_INFO='true linux true', CONTAINER_HOST='unix:///run/service.sock', **host)
        create = self.session_create(result)
        env = self.environment_of(create)
        self.assertIn('LANG', env)
        self.assertNotIn('HTTPS_PROXY', env)
        self.assertIn('FIXTURE_TELEMETRY=0', env)
        self.assertNotIn('--init', create)
        for skipped in ('HTTPS_PROXY', 'FIXTURE_TELEMETRY'):
            self.assertIn(f'FIXTURE_AGENT_ENV_VARS: skipping {skipped}', result.stderr)
        self.assertIn('/usr/local/bin/fixture', create)
        self.assertEqual(create[-3:], ['--fixture-mode', 'offline', '--first'])


    def build_call(self):
        return next(json.loads(line) for line in self.engine_calls() if json.loads(line)[0] == 'build')

    def test_image_freshness_and_build_arguments(self):
        # U8, U12, H6, M12: a stale image is refused; builds pull bases first and are labeled.
        result = self.run_agent(FIXTURE_AGENT_NETWORK='unrestricted', FAKE_LABEL_HASH='0' * 64)
        self.assertEqual(result.returncode, 1)
        self.assertIn('is stale for the current build inputs', result.stderr)
        self.assertIn('--container-build', result.stderr)
        self.assertNotIn('create', [json.loads(line)[0] for line in self.engine_calls()])
        self.log.unlink(missing_ok=True)
        result = self.run_agent('--container-build', FIXTURE_AGENT_NETWORK='unrestricted',
                                FIXTURE_AGENT_MAINTENANCE='1', FAKE_IMAGE_STATUS='1')
        self.assertEqual(result.returncode, 0, result.stderr)
        calls = [json.loads(line) for line in self.engine_calls()]
        bases = [line.split()[1] for line in (AGENT_ROOT / 'Containerfile').read_text().splitlines()
                 if line.upper().startswith('FROM ')]
        self.assertEqual([c[1] for c in calls if c[0] == 'pull'], bases)
        build = self.build_call()
        for flag in ('--pull=never', '--format', 'docker', 'build-inputs-hash=' + BUILD_HASH,
                     '--build-arg', 'FIXTURE_VERSION=1'):
            self.assertIn(flag, build)
        self.assertLess(max(i for i, c in enumerate(calls) if c[0] == 'pull'), calls.index(build))

    def test_agent_build_inputs_join_the_hash(self):
        self.log.unlink(missing_ok=True)
        result = self.run_agent('--container-build', FIXTURE_AGENT_NETWORK='unrestricted',
                                FIXTURE_AGENT_MAINTENANCE='1', FIXTURE_HOOK_BUILD_INPUTS='agent/profile.json')
        self.assertEqual(result.returncode, 0, result.stderr)
        expected = build_inputs_hash(AGENT_ROOT, ('agent/profile.json',))
        self.assertIn('build-inputs-hash=' + expected, self.build_call())
        for value in ('../outside', '/etc/passwd', 'missing-file'):
            with self.subTest(value=value):
                result = self.run_agent('--container-build', FIXTURE_AGENT_NETWORK='unrestricted',
                                        FIXTURE_AGENT_MAINTENANCE='1', FIXTURE_HOOK_BUILD_INPUTS=value)
                self.assertEqual(result.returncode, 1)
                self.assertIn('build input is not a file inside the installation', result.stderr)


    def test_provider_session_starts_and_stops_the_proxy_with_the_selected_credential(self):
        # U10: the selected policy profile's credential only; the proxy helper's start and stop.
        wrapper = synthetic_install(self.base, AGENT_ROOT, AGENT_PROFILE.wrapper)
        policy = wrapper.parent / 'agent/policies/default.json'
        policy.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(AGENT_ROOT / 'agent/policies/default.json', policy)
        runtime = self.base / 'runtime'
        runtime.mkdir(mode=0o700)
        result = self.run_agent('--first', wrapper=wrapper, FIXTURE_AGENT_NETWORK='provider',
                                FIXTURE_AGENT_NETWORK_PROFILE='fixture-api', FIXTURE_AGENT_NETWORK_POLICY=str(policy),
                                FIXTURE_AGENT_NETWORK_RUNTIME_DIR=str(runtime), FIXTURE_AGENT_EGRESS_IMAGE='sha256:' + 'e' * 64,
                                FIXTURE_API_KEY='key', FIXTURE_AGENT_ENV_VARS='FIXTURE_API_KEY OTHER_KEY',
                                FAKE_NETWORK='1', FAKE_INFO='true linux true', CONTAINER_HOST='unix:///run/service.sock')
        self.assertEqual(result.returncode, 0, result.stderr)
        calls = [json.loads(line) for line in self.engine_calls()]
        agent = next(c for c in calls if c[0] == 'create' and not any('.egress=' in a for a in c))
        env = self.environment_of(agent)
        self.assertIn('FIXTURE_API_KEY', env)
        self.assertIn('FIXTURE_PROVIDER_ONLY=1', env)
        self.assertIn('FIXTURE_TELEMETRY=0', env)
        self.assertTrue(any(c[0] == 'create' and any('.egress=' in a for a in c) for c in calls))
        self.assertEqual(list(runtime.iterdir()), [])


if __name__ == '__main__':
    unittest.main()

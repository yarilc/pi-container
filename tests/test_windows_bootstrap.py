"""Shared tests of the Windows bootstrap, launcher/windows/bootstrap.sh.

The bootstrap runs inside the Podman machine's WSL distribution. Here it runs on
Linux from a synthetic release: a fake ``wslpath`` maps drive paths into a
temporary directory, and a fake managed command records what it receives. The
release's namespace helper reads a synthetic /proc whose PID 1 is systemd, so
it runs the command directly; tests/test_windows_enter.py covers the helper.
"""
import base64
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from sandbox_profile import PROFILE, ROOT, test_setting

FAKE_WSLPATH = r'''#!/usr/bin/env python3
import os, sys
args = sys.argv[1:]
if args[:2] != ['-a', '-u'] or len(args) != 3:
    sys.exit(2)
raw = args[2]
if len(raw) < 3 or raw[1] != ':' or raw[2] not in '\\/':
    print('wslpath: ' + raw + ': Invalid argument', file=sys.stderr)
    sys.exit(1)
rest = raw[3:].replace('\\', '/').strip('/')
print(os.path.join(os.environ['TEST_DRIVES'], raw[0].lower(), rest).rstrip('/'))
'''
FAKE_COMMAND = r'''#!/usr/bin/env python3
import json, os, sys
names = ('WRAPPER_WINDOWS_ARGS', 'WRAPPER_WINDOWS_CWD', 'WRAPPER_WINDOWS_ENTRY', 'WSLENV', 'KEPT',
         'XDG_RUNTIME_DIR')
with open(os.environ['TEST_RECORD'], 'w') as output:
    json.dump({'argv': sys.argv[1:], 'cwd': os.getcwd(), 'env': {n: os.environ.get(n) for n in names}}, output)
sys.exit(int(os.environ.get('TEST_EXIT', '0')))
'''


def payload(arguments):
    return base64.b64encode(b''.join(item.encode() + b'\0' for item in arguments)).decode()


class WindowsBootstrapTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='windows-bootstrap-', dir=test_setting('TEST_TMPDIR'))
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        installation = self.base / 'installation'
        self.release = installation / 'releases/first'
        (self.release / 'launcher/windows').mkdir(parents=True)
        (self.release / 'agent').mkdir()
        shutil.copyfile(ROOT / 'agent/profile.json', self.release / 'agent/profile.json')
        (installation / 'current').symlink_to('releases/first')
        self.bootstrap = installation / 'current/launcher/windows/bootstrap.sh'
        bin_dir = self.base / 'bin'
        bin_dir.mkdir()
        for name, text in (('wslpath', FAKE_WSLPATH), ('managed-command', FAKE_COMMAND)):
            (bin_dir / name).write_text(text)
            (bin_dir / name).chmod(0o700)
        self.saved = {'command': str(bin_dir / 'managed-command'), 'network': 'unrestricted', 'podman': False}
        (self.release / 'setup.json').write_text(json.dumps(self.saved))
        self.drives = self.base / 'drives'
        self.project = self.drives / 'c/Work/my project'
        self.entry = self.drives / 'c/Work/checkout'
        self.project.mkdir(parents=True)
        self.entry.mkdir()
        self.record = self.base / 'record.json'
        # Stands in for /run/user/<uid>, which a Podman-started machine has.
        self.runtime = self.base / 'runtime'
        self.runtime.mkdir(mode=0o700)
        self.install_bootstrap(self.runtime)
        self.env = {'PATH': str(bin_dir) + ':' + os.environ['PATH'], 'HOME': str(self.base),
                    'TEST_DRIVES': str(self.drives), 'TEST_RECORD': str(self.record),
                    'WRAPPER_WINDOWS_CWD': 'C:\\Work\\my project', 'WRAPPER_WINDOWS_ENTRY': 'C:\\Work\\checkout',
                    'WSLENV': 'WRAPPER_WINDOWS_ARGS/u:WRAPPER_WINDOWS_CWD/u:WRAPPER_WINDOWS_ENTRY/u:KEPT/u',
                    'WSL_DISTRO_NAME': 'machine-distro', 'XDG_RUNTIME_DIR': '/mnt/wslg/runtime-dir',
                    'KEPT': 'value'}

    def install_bootstrap(self, runtime):
        # The release copies check this directory instead of /run/user/<uid>,
        # and the helper reads a /proc whose PID 1 is systemd.
        text = (ROOT / 'launcher/windows/bootstrap.sh').read_text()
        self.assertEqual(text.count('/run/user/$(id -u)'), 1)
        target = self.release / 'launcher/windows/bootstrap.sh'
        target.write_text(text.replace('/run/user/$(id -u)', str(runtime)))
        proc = self.base / 'proc'
        (proc / '1').mkdir(parents=True, exist_ok=True)
        (proc / '1/comm').write_text('systemd\n')
        text = (ROOT / 'launcher/windows/enter.sh').read_text()
        for old, new in (('proc=/proc', 'proc=' + str(proc)), ('runtime=/run/user/$(id -u)', 'runtime=' + str(runtime))):
            self.assertEqual(text.count(old), 1)
            text = text.replace(old, new)
        (self.release / 'launcher/windows/enter.sh').write_text(text)

    def run_bootstrap(self, **env):
        values = self.env | env
        values = {key: value for key, value in values.items() if value is not None}
        return subprocess.run(['/bin/bash', str(self.bootstrap)], env=values, cwd=self.base,
                              capture_output=True, text=True, timeout=20)

    def recorded(self):
        return json.loads(self.record.read_text())

    def test_arguments_reach_the_managed_command_unchanged(self):
        arguments = ['-c', 'printf "<%s>" "$@"', 'x', '', 'a "b" c\\', '\\\\server\\x', '\u00e8\U0001F600',
                     'tab\tnl\nend', '--', '-x:y']
        result = self.run_bootstrap(WRAPPER_WINDOWS_ARGS=payload(arguments), TEST_EXIT='7')
        self.assertEqual(result.returncode, 7, result.stderr)
        record = self.recorded()
        self.assertEqual(record['argv'], arguments)
        self.assertEqual(record['cwd'], str(self.project))
        # Only the translated entry directory stays; the transport and WSLENV
        # are gone, and the machine's runtime directory applies.
        self.assertEqual(record['env'], {'WRAPPER_WINDOWS_ARGS': None, 'WRAPPER_WINDOWS_CWD': None,
                                         'WRAPPER_WINDOWS_ENTRY': str(self.entry), 'WSLENV': None,
                                         'KEPT': 'value', 'XDG_RUNTIME_DIR': str(self.runtime)})

    def test_no_arguments_and_one_empty_argument_differ(self):
        for value, expected in ((None, []), ('', []), (payload(['']), ['']), (payload(['', '']), ['', ''])):
            with self.subTest(value=value):
                self.record.unlink(missing_ok=True)
                result = self.run_bootstrap(WRAPPER_WINDOWS_ARGS=value)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(self.recorded()['argv'], expected)

    def test_malformed_argument_transport_is_refused(self):
        unterminated = base64.b64encode(b'abc').decode()
        for value, message in (('not base64!', 'not base64'), ('YWJ', 'not base64'), ('====', 'not base64'),
                               (unterminated, 'the last argument is not terminated')):
            with self.subTest(value=value):
                result = self.run_bootstrap(WRAPPER_WINDOWS_ARGS=value)
                self.assertEqual(result.returncode, 1)
                self.assertIn(PROFILE.name + ': malformed argument transport: ' + message, result.stderr)
                self.assertFalse(self.record.exists())

    def test_windows_paths_are_translated_or_refused_with_specific_messages(self):
        lower = self.drives / 'd/lower'
        lower.mkdir(parents=True)
        for raw in ('d:\\lower', 'D:/lower', 'D:\\lower\\'):
            with self.subTest(accepted=raw):
                self.record.unlink(missing_ok=True)
                result = self.run_bootstrap(WRAPPER_WINDOWS_CWD=raw)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(self.recorded()['cwd'], str(lower))
        self.record.unlink()
        refused = (
            ('\\\\wsl$\\Ubuntu\\home\\me', 'the current directory is inside a WSL distribution'),
            ('\\\\WSL.LOCALHOST\\Ubuntu\\home\\me', 'the current directory is inside a WSL distribution'),
            ('\\\\server\\share\\project', 'the current directory is a network or device path'),
            ('\\\\?\\C:\\Work\\my project', 'the current directory is a network or device path'),
            ('HKCU:\\Software', 'the current directory is not a Windows file system path'),
            ('project', 'the current directory is not a Windows file system path'),
            ('Z:\\project', 'the current directory is on drive Z:, which this distribution does not mount'),
            ('C:\\Work\\missing', 'the current directory is on drive C:, which this distribution does not mount'),
        )
        for raw, message in refused:
            with self.subTest(refused=raw):
                result = self.run_bootstrap(WRAPPER_WINDOWS_CWD=raw)
                self.assertEqual(result.returncode, 1)
                self.assertIn(PROFILE.name + ': ' + message, result.stderr)
                self.assertFalse(self.record.exists())
        result = self.run_bootstrap(WRAPPER_WINDOWS_ENTRY='\\\\server\\share\\checkout')
        self.assertEqual(result.returncode, 1)
        self.assertIn('the Windows entry directory is a network or device path', result.stderr)
        self.assertFalse(self.record.exists())

    def test_missing_transport_or_installation_parts_stop_before_the_command(self):
        for name in ('WRAPPER_WINDOWS_CWD', 'WRAPPER_WINDOWS_ENTRY'):
            with self.subTest(missing=name):
                result = self.run_bootstrap(**{name: None})
                self.assertEqual(result.returncode, 1)
                self.assertIn('start sessions with the Windows entry', result.stderr)
        (self.release / 'setup.json').unlink()
        result = self.run_bootstrap()
        self.assertEqual(result.returncode, 1)
        self.assertIn('bootstrap: the installation in ' + str(self.release) + ' is incomplete', result.stderr)
        self.assertIn('--container-setup', result.stderr)
        self.assertFalse(self.record.exists())

    def test_distribution_started_without_the_machine_stops_before_the_command(self):
        # windows-launcher: Machine started by Podman / Distribution started by WSL alone.
        missing = self.base / 'no-runtime'
        read_only = self.base / 'read-only-runtime'
        read_only.mkdir(mode=0o500)
        self.addCleanup(read_only.chmod, 0o700)
        for runtime in (missing, read_only):
            if runtime == read_only and os.access(read_only, os.W_OK):
                continue  # root ignores the mode
            with self.subTest(runtime=runtime.name):
                self.install_bootstrap(runtime)
                result = self.run_bootstrap()
                self.assertEqual(result.returncode, 1)
                self.assertIn(PROFILE.name + ': the WSL distribution machine-distro runs without the Podman machine: '
                              + str(runtime) + ' is missing', result.stderr)
                self.assertIn('wsl --terminate machine-distro', result.stderr)
                self.assertIn('podman machine start', result.stderr)
                self.assertFalse(self.record.exists())

    def test_saved_delegation_stops_before_the_command(self):
        # windows-launcher: Saved delegation refused / Saved delegation.
        saved = {key: value for key, value in self.saved.items() if key != 'podman'}
        for value in ({**saved, 'podman': True}, {**saved, 'podman': 'false'}, saved):
            with self.subTest(saved=value):
                (self.release / 'setup.json').write_text(json.dumps(value))
                result = self.run_bootstrap()
                self.assertEqual(result.returncode, 1)
                self.assertIn(PROFILE.name + ': the installation in ' + str(self.release) + ' saved Podman '
                              'delegation, which Podman machine on Windows does not support; rerun setup from '
                              'Windows with --container-setup', result.stderr)
                self.assertFalse(self.record.exists())

    def test_saved_network_modes_run_the_command(self):
        # windows-launcher: Saved delegation refused / Saved offline networking.
        for network in ('offline', 'provider', 'unrestricted'):
            with self.subTest(network=network):
                self.record.unlink(missing_ok=True)
                (self.release / 'setup.json').write_text(json.dumps(self.saved | {'network': network}))
                result = self.run_bootstrap()
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(self.recorded()['cwd'], str(self.project))

    def test_relative_invocation_from_the_home_directory(self):
        # The shim starts the bootstrap with a path relative to the user's home.
        relative = os.path.relpath(self.bootstrap, self.base)
        result = subprocess.run(['/bin/bash', relative], env=self.env, cwd=self.base,
                                capture_output=True, text=True, timeout=20)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.recorded()['cwd'], str(self.project))


if __name__ == '__main__':
    unittest.main()

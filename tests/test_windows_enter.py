"""Shared tests of the Windows namespace helper, launcher/windows/enter.sh.

The helper runs inside the Podman machine's WSL distribution and enters the
PID and mount namespaces of the machine's systemd with sudo and nsenter. Here
it runs on Linux from a copy that reads a synthetic /proc, accepts the test
user as the owner of systemd, and uses a temporary runtime directory. A fake
``sudo`` resets the environment, as the real one does, and a fake ``nsenter``
changes to the requested directory; both record their arguments.
"""
import pwd
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from sandbox_profile import ROOT, test_setting

PREFIX = 'test-entry'
FAKE_SUDO = r'''#!/usr/bin/env python3
import json, os, sys
here = os.path.dirname(os.path.abspath(__file__))
args = sys.argv[1:]
with open(os.path.join(here, 'log.jsonl'), 'a') as log:
    log.write(json.dumps(['sudo'] + args) + '\n')
if args == ['-n', 'true']:
    sys.exit(1 if os.path.exists(os.path.join(here, 'sudo-password')) else 0)
if args[:2] == ['-n', '--']:
    command = args[2:]
elif args[:2] == ['-n', '-u'] and args[3] == '--':
    command = args[4:]
else:
    sys.exit('fake sudo: unexpected arguments')
# The real sudo resets the environment (env_reset, secure_path).
os.execve(command[0] if '/' in command[0] else os.path.join(here, command[0]), command,
          {'PATH': here + ':/usr/bin:/bin', 'SUDO_USER': 'someone'})
'''
FAKE_NSENTER = r'''#!/usr/bin/env python3
import json, os, sys
here = os.path.dirname(os.path.abspath(__file__))
args = sys.argv[1:]
separator = args.index('--')
options, command = args[:separator], args[separator + 1:]
transport = [arg for arg in command if '/windows-entry/env.' in arg]
modes = {}
if transport:
    directory = os.path.dirname(transport[0])
    modes = {'directory': oct(os.stat(directory).st_mode & 0o777),
             'file': oct(os.stat(transport[0]).st_mode & 0o777)}
with open(os.path.join(here, 'log.jsonl'), 'a') as log:
    log.write(json.dumps(['nsenter'] + args + [modes]) + '\n')
if os.path.exists(os.path.join(here, 'nsenter-fail')):
    sys.exit(1)
for option in options:
    if option.startswith('--wd='):
        os.chdir(option[5:])
os.execvp(command[0], command)
'''
RECORDER = r'''#!/usr/bin/env python3
import json, os, sys
names = ('HOME', 'TERM', 'LANG', 'KEPT', 'LARGE', 'XDG_RUNTIME_DIR', 'SUDO_USER', 'TEST_RECORD')
data = sys.stdin.read() if os.environ.get('READ_STDIN') else None
sys.stderr.write('to-stderr\n')
with open(os.environ['TEST_RECORD'], 'w') as output:
    json.dump({'argv': sys.argv[1:], 'cwd': os.getcwd(), 'stdin': data,
               'env': {name: os.environ.get(name) for name in names}}, output)
sys.exit(int(os.environ.get('TEST_EXIT', '0')))
'''


class WindowsEnterTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='windows-enter-', dir=test_setting('TEST_TMPDIR'))
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        self.proc = self.base / 'proc'
        self.add_process(1, 'init(podman-machine-default)', '1')
        self.add_process(21, 'systemd', '21\t1')
        # The user's systemd manager, inside the namespace: not PID 1 there.
        self.add_process(224, 'systemd', '224\t180')
        self.runtime = self.base / 'runtime'
        self.runtime.mkdir(mode=0o700)
        self.transport = self.runtime / 'windows-entry'
        self.helper = self.install_helper(str(os.getuid()))
        self.bin = self.base / 'bin'
        self.bin.mkdir()
        for name, text in (('sudo', FAKE_SUDO), ('nsenter', FAKE_NSENTER), ('recorder', RECORDER)):
            (self.bin / name).write_text(text)
            (self.bin / name).chmod(0o700)
        self.log = self.bin / 'log.jsonl'
        self.project = self.base / 'drives/c/Work/my project'
        self.project.mkdir(parents=True)
        self.record = self.base / 'record.json'
        self.large = ('a "b" c\\ è € ' * 2500)[:30000]
        self.env = {'PATH': str(self.bin) + ':' + os.environ['PATH'], 'HOME': str(self.base),
                    'TERM': 'xterm-256color', 'LANG': 'C.UTF-8', 'KEPT': 'value', 'LARGE': self.large,
                    'XDG_RUNTIME_DIR': '/mnt/wslg/runtime-dir', 'TEST_RECORD': str(self.record),
                    'WSL_DISTRO_NAME': 'machine-distro'}

    def add_process(self, pid, name, nspid):
        directory = self.proc / str(pid)
        directory.mkdir(parents=True)
        (directory / 'comm').write_text(name + '\n')
        (directory / 'status').write_text('Name:\t' + name + '\nNSpid:\t' + nspid + '\n')

    def install_helper(self, root_uid):
        text = (ROOT / 'launcher/windows/enter.sh').read_text()
        for old, new in (('proc=/proc', 'proc=' + str(self.proc)), ('root_uid=0', 'root_uid=' + root_uid),
                         ('runtime=/run/user/$(id -u)', 'runtime=' + str(self.runtime))):
            self.assertEqual(text.count(old), 1, old)
            text = text.replace(old, new)
        target = self.base / 'release/launcher/windows/enter.sh'
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text)
        return target

    def run_helper(self, *command, stdin=None, **env):
        values = {key: value for key, value in (self.env | env).items() if value is not None}
        return subprocess.run(['/bin/bash', str(self.helper), PREFIX, *command], env=values, cwd=self.project,
                              input=stdin, capture_output=True, text=True, timeout=20)

    def recorded(self):
        return json.loads(self.record.read_text())

    def logged(self):
        if not self.log.exists():
            return []
        return [json.loads(line) for line in self.log.read_text().splitlines()]

    def transport_files(self):
        return sorted(path.name for path in self.transport.iterdir()) if self.transport.exists() else []

    def test_command_runs_in_systemd_namespaces_with_environment_and_status(self):
        arguments = ['-c', 'printf "<%s>" "$@"', '', 'a "b" c\\', 'è\U0001F600', 'tab\tnl\nend', '--']
        result = self.run_helper(str(self.bin / 'recorder'), *arguments, TEST_EXIT='7')
        self.assertEqual(result.returncode, 7, result.stderr)
        record = self.recorded()
        self.assertEqual(record['argv'], arguments)
        self.assertEqual(record['cwd'], str(self.project))
        self.assertEqual(record['env'], {'HOME': str(self.base), 'TERM': 'xterm-256color', 'LANG': 'C.UTF-8',
                                         'KEPT': 'value', 'LARGE': self.large,
                                         'XDG_RUNTIME_DIR': str(self.runtime), 'SUDO_USER': None,
                                         'TEST_RECORD': str(self.record)})
        log = self.logged()
        user = pwd.getpwuid(os.getuid()).pw_name
        self.assertEqual(log[0], ['sudo', '-n', 'true'])
        outer = log[1]
        self.assertEqual(outer[:12], ['sudo', '-n', '--', 'nsenter', '--target', '21', '--mount', '--pid',
                                      '--wd=' + str(self.project), '--', 'sudo', '-n'])
        self.assertEqual(outer[12:18], ['-u', user, '--', '/bin/bash', str(self.helper), '--inner'])
        self.assertEqual(outer[18], PREFIX)
        self.assertRegex(outer[19], '^' + str(self.transport) + r'/env\.[0-9]+\.[A-Za-z0-9]{10}$')
        self.assertEqual(outer[20:], [str(self.bin / 'recorder'), *arguments])
        self.assertEqual(log[2][:-1], ['nsenter', *outer[4:]])
        self.assertEqual(log[2][-1], {'directory': '0o700', 'file': '0o600'})
        self.assertEqual(log[3], ['sudo', *outer[11:]])
        self.assertEqual(len(log), 4)
        self.assertEqual(self.transport_files(), [])
        self.assertEqual(stat.S_IMODE(self.transport.stat().st_mode), 0o700)

    def test_standard_streams_pass_through(self):
        result = self.run_helper(str(self.bin / 'recorder'), stdin='piped data\n', READ_STDIN='1')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.recorded()['stdin'], 'piped data\n')
        self.assertEqual(result.stderr, 'to-stderr\n')
        self.assertEqual(result.stdout, '')

    def test_direct_run_when_pid_1_is_systemd(self):
        (self.proc / '1/comm').write_text('systemd\n')
        result = self.run_helper(str(self.bin / 'recorder'), 'x', TEST_EXIT='3')
        self.assertEqual(result.returncode, 3, result.stderr)
        record = self.recorded()
        self.assertEqual(record['argv'], ['x'])
        self.assertEqual(record['cwd'], str(self.project))
        self.assertEqual(record['env']['XDG_RUNTIME_DIR'], str(self.runtime))
        self.assertEqual(record['env']['LARGE'], self.large)
        self.assertEqual(self.logged(), [])
        self.assertFalse(self.transport.exists())

    def test_lowest_root_systemd_of_a_child_namespace_is_the_target(self):
        self.add_process(150, 'systemd', '150\t1')
        self.add_process(9, 'other', '9\t1')
        result = self.run_helper(str(self.bin / 'recorder'))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.logged()[1][4:6], ['--target', '21'])

    def test_missing_systemd_stops_before_sudo(self):
        for case in ('no process', 'not owned by root'):
            with self.subTest(case=case):
                self.log.unlink(missing_ok=True)
                if case == 'no process':
                    for path in (self.proc / '21').iterdir():
                        path.unlink()
                    (self.proc / '21').rmdir()
                else:
                    self.add_process(21, 'systemd', '21\t1')
                    self.helper = self.install_helper(str(os.getuid() + 1))
                result = self.run_helper(str(self.bin / 'recorder'))
                self.assertEqual(result.returncode, 1)
                self.assertIn(PREFIX + ": the Podman machine's systemd is not running in the WSL distribution "
                              'machine-distro. Run wsl --terminate machine-distro, then start the machine with '
                              'Podman Desktop or podman machine start, and retry.', result.stderr)
                self.assertEqual(self.logged(), [])
                self.assertFalse(self.record.exists())
                self.assertFalse(self.transport.exists())

    def test_password_required_stops_before_entering(self):
        (self.bin / 'sudo-password').write_text('')
        result = self.run_helper(str(self.bin / 'recorder'))
        self.assertEqual(result.returncode, 1)
        self.assertIn(PREFIX + ": entering the Podman machine's systemd namespaces needs sudo without a password "
                      'for ' + pwd.getpwuid(os.getuid()).pw_name + ' in machine-distro', result.stderr)
        self.assertEqual(self.logged(), [['sudo', '-n', 'true']])
        self.assertFalse(self.record.exists())
        self.assertFalse(self.transport.exists())

    def test_transport_of_a_failed_start_is_removed_by_the_next_start(self):
        (self.bin / 'nsenter-fail').write_text('')
        result = self.run_helper(str(self.bin / 'recorder'))
        self.assertEqual(result.returncode, 1)
        self.assertEqual(len(self.transport_files()), 1)
        # A file whose creator still runs stays.
        self.add_process(4242, 'sudo', '4242')
        (self.transport / 'env.4242.abcdefghij').write_text('')
        (self.bin / 'nsenter-fail').unlink()
        result = self.run_helper(str(self.bin / 'recorder'))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.transport_files(), ['env.4242.abcdefghij'])

    def test_inner_part_accepts_only_its_own_transport_file(self):
        foreign = self.base / 'env.1.abcdefghij'
        foreign.write_text('PATH=/bin\0')
        self.transport.mkdir(mode=0o700)
        link = self.transport / 'env.1.abcdefghij'
        link.symlink_to(foreign)
        for path in (foreign, link, self.transport / 'env.1.missing'):
            with self.subTest(path=path.name):
                result = subprocess.run(['/bin/bash', str(self.helper), '--inner', PREFIX, str(path),
                                         str(self.bin / 'recorder')], env=self.env, capture_output=True,
                                        text=True, timeout=20)
                self.assertEqual(result.returncode, 1)
                self.assertIn(PREFIX + ': the environment transport ' + str(path) + ' is missing', result.stderr)
                self.assertFalse(self.record.exists())
        self.assertTrue(foreign.exists())

    def test_usage(self):
        for arguments in ([], [PREFIX], ['Bad Prefix', 'true']):
            with self.subTest(arguments=arguments):
                result = subprocess.run(['/bin/bash', str(self.helper), *arguments], env=self.env,
                                        capture_output=True, text=True, timeout=20)
                self.assertEqual(result.returncode, 2)
                self.assertIn('usage: bash enter.sh <prefix> <command> [args...]', result.stderr)


if __name__ == '__main__':
    unittest.main()

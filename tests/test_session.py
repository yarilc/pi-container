"""Shared restricted-session helper contracts with a synthetic engine.

The helper runs as a separate process, exactly as wrappers call it. Engine,
control and guard are synthetic fixtures; real enforcement acceptance lives in
the runtime suites. Needs executable temporary storage (SANDBOX_TEST_TMPDIR).
"""
import json
import os
from pathlib import Path
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import time
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from sandbox_profile import NETWORK, PROFILE, ROOT, SHELL_FIXTURE, fixture_root, test_setting
import agent_profile
from agent_profile import NO_METHODS
from revisions import TLS_ENFORCEMENT

DIGEST = 'c' * 64
PROXY = 'b' * 64
POLICY_IDENTITY = 'fixture-policy 0123'
TOKEN = 'e' * 32
PLATFORM = json.dumps({'kernel': '6.6.87.2-microsoft-standard-WSL2', 'arch': 'amd64',
                       'security': {'seccompEnabled': True, 'selinuxEnabled': False, 'apparmorEnabled': False}})

FAKE_ENGINE = r'''#!/usr/bin/env python3
import json, os, pathlib, signal, sys, time
args = sys.argv[1:]
with open(os.environ['FAKE_LOG'], 'a') as log:
    log.write(json.dumps(args) + '\n')
command = args[0]
if command in os.environ.get('FAKE_STALL', '').split(','):
    if command == 'create' and '--cidfile' in args:
        pathlib.Path(args[args.index('--cidfile') + 1]).write_text(os.environ['FAKE_PROXY'] + '\n')
    signal.signal(signal.SIGTERM, signal.SIG_IGN)
    pathlib.Path(os.environ['FAKE_LOG'] + '.stalled').write_text(str(os.getpid()))
    while True:
        time.sleep(0.05)
if command in os.environ.get('FAKE_FAIL', '').split(','):
    sys.exit(17)
if command == 'create':
    pathlib.Path(args[args.index('--cidfile') + 1]).write_text(os.environ['FAKE_PROXY'] + '\n')
    print(os.environ.get('FAKE_CREATED', os.environ['FAKE_PROXY']))
elif command == 'inspect':
    if args[-2] == '{{json .HostConfig}}':
        print(os.environ.get('FAKE_CONFIG', '{"PidsLimit":128,"Memory":268435456}'))
    else:
        print(os.environ.get('FAKE_OWNER', ''))
elif command == 'exec':
    print(os.environ.get('FAKE_EFFECTIVE',
          '{"pids":128,"memory":268435456,"capabilities":[0,0,0,0,0],"no_new_privs":1,"seccomp":2,'
          '"nproc":[63948,63948]}'))
elif command == 'ps':
    print(os.environ.get('FAKE_RECOVERY', ''))
elif command == 'info' and args[-1] == '{{.Host.CgroupManager}}':
    print(os.environ.get('FAKE_CGROUP_MANAGER', 'systemd'))
elif command == 'info' and args[-1] == '{{.Host.Kernel}}':
    print(os.environ.get('FAKE_KERNEL', '6.6.87.2-microsoft-standard-WSL2'))
elif command == 'info':
    print(os.environ.get('FAKE_CONTROLLERS', '[cpu memory pids]'))
'''

FAKE_CONTROL = r'''import json, os, pathlib, socket, sys
args = sys.argv[1:]
with open(os.environ['FAKE_LOG'], 'a') as log:
    log.write(json.dumps(['control', *args]) + '\n')
if os.environ.get('FAKE_CONTROL_FAIL') == args[0]:
    print('control refused ' + args[0], file=sys.stderr)
    sys.exit(23)
if args[0] == 'snapshot':
    session = pathlib.Path(args[args.index('--session') + 1])
    for name in ('config', 'transport', 'logs'):
        (session / name).mkdir()
    ready = os.environ.get('FAKE_READY')
    if ready is not None:
        (session / 'transport/ready').write_text(ready + '\n')
        listener = socket.socket(socket.AF_UNIX)
        listener.bind(str(session / 'transport/proxy.sock'))
        listener.close()
    print(os.environ['FAKE_POLICY_IDENTITY'])
elif args[0] == 'qualification-input':
    print(os.environ.get('FAKE_QUALIFICATION', 'e' * 32 + ' 1'))
'''


def unix_sockets_available():
    try:
        socket.socket(socket.AF_UNIX).close()
    except OSError:
        return False
    return True


class SessionHelper(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='session-helper-', dir=test_setting('TEST_TMPDIR'))
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        self.install = self.base / 'installed'
        (self.install / 'network/bin').mkdir(parents=True)
        (self.install / 'agent').mkdir()
        for name in ('session.py', 'revisions.py', 'agent_profile.py', 'agent_budgets.py', 'policy.py', 'proxy_hardening.py', 'platform_check.py',
                     'relay.py', 'mux.py', 'resolv.conf', 'qualification_proxy.py',
                     'qualification_probe.py', 'qualification_runtime.py'):
            shutil.copyfile(NETWORK / name, self.install / 'network' / name)
        shutil.copyfile(ROOT / 'agent/profile.json', self.install / 'agent/profile.json')
        (self.install / 'network/control.py').write_text(FAKE_CONTROL)
        guard = self.install / 'network/bin/sandbox-egress-guard'
        guard.write_text('#!/bin/sh\necho "Landlock ABI 3; required >= 3; query-only, enforcement unverified"\n')
        guard.chmod(0o700)
        (guard.parent / 'sandbox-egress-guard.sha256').write_text(DIGEST + '  sandbox-egress-guard\n')
        self.bin = self.base / 'bin'
        self.bin.mkdir()
        (self.bin / 'podman').write_text(FAKE_ENGINE)
        (self.bin / 'podman').chmod(0o700)
        self.log = self.base / 'calls.jsonl'
        self.runtime = self.base / 'runtime'
        self.runtime.mkdir(mode=0o700)
        self.session = self.runtime / 'session.fixture12345'
        self.session.mkdir(mode=0o700)
        self.env = {'PATH': str(self.bin) + ':' + os.environ['PATH'], 'FAKE_LOG': str(self.log),
                    'FAKE_PROXY': PROXY, 'FAKE_POLICY_IDENTITY': POLICY_IDENTITY,
                    'FAKE_OWNER': self.session.name}
        self.provider = ['--policy', str(self.base / 'policy.json'), '--profile', 'fixture',
                         '--proxy-image', 'd' * 64, '--runtime', str(self.runtime)]

    def helper(self, *args, env=None, input=None, **kwargs):
        return subprocess.run([sys.executable, '-I', str(self.install / 'network/session.py'), *args],
                              env=self.env | (env or {}), input=input, capture_output=True, **kwargs)

    def calls(self):
        return [json.loads(line) for line in self.log.read_text().splitlines()] if self.log.exists() else []

    def engine_calls(self):
        return [call for call in self.calls() if call[0] != 'control']

    def network(self):
        return ['--installation', str(self.install), '--writable', str(self.base / 'workspace'),
                '--mount-target', str(self.base / 'workspace')]

    def prepare(self, mode='offline', *extra, env=None):
        return self.helper('prepare', *self.network(), *(self.provider if mode == 'provider' else []),
                           '--mode', mode, '--server-version', '4.9.3', '--backend', 'netavark',
                           '--endpoint', 'unix:///run/service.sock', '--engine', 'true linux true', *extra,
                           env=env, input=PLATFORM.encode())

    def start(self, *extra, env=None, **kwargs):
        return self.helper('start', *self.network(), *self.provider, '--session', str(self.session),
                           '--guard-digest', DIGEST, *extra, env=env, **kwargs)

    def stop(self, deadline=20, env=None):
        return self.helper('stop', '--session', str(self.session), '--deadline', str(deadline),
                           '--container', 'a' * 64, env=env, text=True)

    def agent_args(self, mode, *extra, command=('/usr/local/bin/agent',)):
        result = self.helper('agent-args', '--installation', str(self.install), '--mode', mode,
                             '--session', str(self.session), '--guard-digest', DIGEST, *extra, '--', *command)
        self.assertEqual(result.returncode, 0, result.stderr)
        records = result.stdout.split(b'\0')
        self.assertEqual(records[-1], b'')
        records = [record.decode() for record in records[:-1]]
        count = int(records[0])
        return records[1:1 + count], records[1 + count:], result.stderr.decode()

    # Interface -----------------------------------------------------------------

    def test_rejects_unknown_operations_and_arguments_without_side_effects(self):
        for args in (('bogus',), ('stop', '--session', str(self.session)),
                     ('stop', '--session', str(self.session), '--deadline', '5', 'extra'),
                     ('agent-args', '--installation', str(self.install), '--mode', 'offline',
                      '--session', str(self.session), '--guard-digest', DIGEST),
                     ('agent-args', '--installation', str(self.install), '--mode', 'offline',
                      '--session', str(self.session), '--guard-digest', 'short', '--', 'x'),
                     ('agent-args', '--installation', str(self.install), '--mode', 'unrestricted',
                      '--session', str(self.session), '--guard-digest', DIGEST, '--', 'x'),
                     ('agent-args', '--installation', str(self.install), '--mode', 'offline', '--tls',
                      '--session', str(self.session), '--guard-digest', DIGEST, '--', 'x'),
                     ('start', *self.network(), '--session', str(self.session), '--guard-digest', DIGEST)):
            with self.subTest(args=args):
                result = self.helper(*args)
                self.assertNotEqual(result.returncode, 0)
                self.assertFalse(self.calls())

    # prepare -------------------------------------------------------------------

    def test_prepare_outputs_guard_identity_and_probe_record(self):
        result = self.prepare()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.decode(), DIGEST + '\n')
        self.assertIn(b'Landlock ABI 3', result.stderr)
        self.assertEqual([call[:2] for call in self.calls()], [['control', 'preflight']])
        self.assertFalse(self.engine_calls())
        self.log.unlink()
        result = self.prepare('provider')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('--proxy-image', self.calls()[0])
        self.log.unlink()
        result = self.prepare('offline', '--probe', '--qualification-input', str(self.base / 'input.json'),
                              '--workspace', str(self.base / 'workspace'))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.decode(), f'{DIGEST} {TOKEN} 1\n')
        self.assertEqual([call[:2] for call in self.calls()],
                         [['control', 'preflight'], ['control', 'qualification-input']])
        for invalid in ('short 1', TOKEN + ' 2', TOKEN, ''):
            result = self.prepare('offline', '--probe', '--qualification-input', 'x', '--workspace', 'y',
                                  env={'FAKE_QUALIFICATION': invalid})
            self.assertNotEqual(result.returncode, 0, invalid)
            self.assertIn(b'invalid fixed qualification input', result.stderr)

    def test_prepare_probe_uses_pipes_and_reports_failures(self):
        guard = self.install / 'network/bin/sandbox-egress-guard'
        # Like the real guard: exit 78 silently unless stdout/stderr are ordinary descriptors.
        guard.write_text('#!/bin/sh\n[ -S /dev/stdout ] || [ -S /dev/stderr ] && exit 78\n'
                         'echo "Landlock ABI 3; required >= 3; query-only, enforcement unverified"\n')
        caller, peer = socket.socketpair()
        self.addCleanup(caller.close)
        self.addCleanup(peer.close)
        command = [sys.executable, '-I', str(self.install / 'network/session.py'), 'prepare', *self.network(),
                   '--mode', 'offline', '--server-version', '4.9.3', '--backend', 'netavark',
                   '--endpoint', 'unix:///run/service.sock', '--engine', 'true linux true']
        result = subprocess.run(command, input=PLATFORM.encode(), stdout=subprocess.PIPE, stderr=caller,
                                env=os.environ | self.env)
        caller.close()
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout.decode(), DIGEST + '\n')
        self.assertIn(b'Landlock ABI 3', peer.recv(65536))
        guard.write_text('#!/bin/sh\nexit 78\n')
        result = self.prepare()
        self.assertEqual(result.returncode, 78)
        self.assertIn(b'sandbox egress guard probe failed (status 78)', result.stderr)
        self.assertEqual(result.stdout, b'')

    def test_prepare_refusals_stop_before_the_guard_and_keep_status(self):
        result = self.prepare(env={'FAKE_CONTROL_FAIL': 'preflight'})
        self.assertEqual(result.returncode, 23)
        self.assertIn(b'control refused preflight', result.stderr)
        self.assertNotIn(b'query-only', result.stderr)
        result = self.helper('prepare', *self.network(), '--mode', 'offline', '--server-version', '4.8.0',
                             '--backend', 'netavark', '--endpoint', 'unix:///run/service.sock',
                             '--engine', 'true linux true', input=PLATFORM.encode())
        self.assertNotEqual(result.returncode, 0)
        self.assertIn(b'ineligible restricted platform', result.stderr)
        self.assertNotIn(b'query-only', result.stderr)

    # start ---------------------------------------------------------------------

    def ready_env(self, ready=None):
        if not unix_sockets_available():
            self.skipTest('AF_UNIX unavailable; run on the host')
        return {'FAKE_READY': ready or f'{POLICY_IDENTITY} guard={DIGEST} mux=1 tls=' + TLS_ENFORCEMENT}

    def test_start_creates_verifies_and_records_the_owned_proxy(self):
        result = self.start(env=self.ready_env(), text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, POLICY_IDENTITY + '\n')
        self.assertIn(f'network profile=fixture policy={POLICY_IDENTITY}', result.stderr)
        self.assertIn(f'egress session={self.session.name}', result.stderr)
        self.assertEqual((self.session / 'proxy.id').read_text(), PROXY + '\n')
        self.assertFalse((self.session / 'proxy.pending').exists())
        calls = self.engine_calls()
        self.assertEqual([call[0] for call in calls], ['info', 'info', 'info', 'create', 'start', 'inspect', 'exec'])
        self.assertEqual(calls[0], ['info', '--format', '{{.Host.CgroupControllers}}'])
        self.assertEqual(calls[1], ['info', '--format', '{{.Host.Kernel}}'])
        self.assertEqual(calls[2], ['info', '--format', '{{.Host.CgroupManager}}'])
        self.assertNotIn('budget not enforced', result.stderr)
        create = calls[3]
        self.assertNotIn('--ulimit', create)
        self.assertEqual(create[create.index('--name') + 1], PROFILE.state_name + '-' + self.session.name)
        self.assertEqual(create[create.index('type=tmpfs,destination=/run/secrets,ro=true') - 1], '--mount')
        for option in ('--cap-drop=all', '--security-opt=no-new-privileges', '--pids-limit=128',
                       '--memory=256m', '--read-only', PROFILE.label('egress') + '=' + self.session.name,
                       'EGRESS_PROFILE=fixture', 'EGRESS_SESSION=' + self.session.name):
            self.assertIn(option, create)
        self.assertEqual(create[-1], 'd' * 64)

    def test_proxy_budgets_follow_delegated_controllers(self):
        rlimit = ',"Ulimits":[{"Name":"RLIMIT_NPROC","Soft":128,"Hard":128}]}'
        config = {'memory': '{"PidsLimit":0,"Memory":268435456}', 'pids': '{"PidsLimit":128,"Memory":0}',
                  'none': '{"PidsLimit":-1,"Memory":0}',
                  'memory-rlimit': '{"PidsLimit":0,"Memory":268435456' + rlimit,
                  'rlimit': '{"PidsLimit":-1,"Memory":0' + rlimit}
        effective = ('{{"pids":{},"memory":{},"capabilities":[0,0,0,0,0],"no_new_privs":1,"seccomp":2,'
                     '"nproc":{}}}')
        default, fallback = '[63948,63948]', '[128,128]'
        old = '5.10.0-28-amd64'
        cases = (('[cpu memory]', None, config['memory-rlimit'], effective.format('null', 268435456, fallback),
                  ['memory'], 'rlimit'),
                 ('[cpu memory]', old, config['memory'], effective.format('null', 268435456, default),
                  ['memory'], 'none'),
                 ('[cpu pids]', None, config['pids'], effective.format(128, 'null', default), ['pids'], 'cgroup'),
                 ('[]', None, config['rlimit'], effective.format('null', 'null', fallback), [], 'rlimit'),
                 ('[]', 'bogus', config['none'], effective.format('null', 'null', default), [], 'none'))
        for controllers, kernel, configured, measured, enforced, process in cases:
            with self.subTest(controllers=controllers, kernel=kernel):
                shutil.rmtree(self.session); self.session.mkdir(mode=0o700)
                Path(str(self.log)).unlink(missing_ok=True)
                env = self.ready_env() | {'FAKE_CONTROLLERS': controllers, 'FAKE_CONFIG': configured,
                                          'FAKE_EFFECTIVE': measured} | ({'FAKE_KERNEL': kernel} if kernel else {})
                result = self.start(env=env, text=True)
                self.assertEqual(result.returncode, 0, result.stderr)
                create = next(call for call in self.engine_calls() if call[0] == 'create')
                self.assertEqual('--memory=256m' in create, 'memory' in enforced)
                self.assertEqual('--pids-limit=128' in create, process == 'cgroup')
                self.assertEqual('--pids-limit=-1' in create, process != 'cgroup')
                self.assertEqual('nproc=128:128' in create, process == 'rlimit')
                self.assertEqual('proxy memory budget not enforced: cgroup controller memory' in result.stderr,
                                 'memory' not in enforced)
                self.assertEqual('proxy process budget not enforced: cgroup controller pids' in result.stderr,
                                 process == 'none')
                self.assertEqual('proxy process budget enforced through the process rlimit (128 tasks'
                                 in result.stderr, process == 'rlimit')
                if process == 'none':
                    self.assertRegex(result.stderr, 'kernel 5.10.0-28-amd64 counts the process rlimit per user'
                                     '|unrecognized kernel version')
        # cgroupfs reports every controller but delegates none: no cgroup limits, the rlimit fallback.
        shutil.rmtree(self.session); self.session.mkdir(mode=0o700)
        Path(str(self.log)).unlink(missing_ok=True)
        env = self.ready_env() | {'FAKE_CONTROLLERS': '[cpuset cpu io memory hugetlb pids rdma]',
                                  'FAKE_CGROUP_MANAGER': 'cgroupfs', 'FAKE_CONFIG': config['rlimit'],
                                  'FAKE_EFFECTIVE': effective.format('null', 'null', fallback)}
        result = self.start(env=env, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        create = next(call for call in self.engine_calls() if call[0] == 'create')
        self.assertFalse(any(a.startswith('--memory') for a in create))
        self.assertNotIn('--pids-limit=128', create)
        self.assertEqual(create[create.index('--ulimit') + 1], 'nproc=128:128')
        manager = 'the rootless engine uses the cgroupfs cgroup manager, which applies no cgroup limits'
        self.assertIn('proxy memory budget not enforced: ' + manager, result.stderr)
        self.assertIn('proxy process budget enforced through the process rlimit (128 tasks of the proxy user, '
                      'threads included): ' + manager, result.stderr)
        for bad in ('', 'Systemd'):
            with self.subTest(manager=bad):
                shutil.rmtree(self.session); self.session.mkdir(mode=0o700)
                result = self.start(env=self.ready_env() | {'FAKE_CGROUP_MANAGER': bad}, text=True)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn('unverifiable cgroup controller list or cgroup manager', result.stderr)
        # A delegated budget that is missing, or an unenforced one that appears, stops startup;
        # so does a fallback that the engine drops or the proxy does not measure.
        for controllers, configured, measured in (
                ('[cpu memory]', config['memory'], effective.format(128, 268435456, fallback)),
                ('[cpu memory]', '{"PidsLimit":128,"Memory":268435456}', effective.format('null', 268435456, fallback)),
                ('[cpu memory pids]', config['memory'], effective.format('null', 268435456, default)),
                ('[cpu memory]', config['memory'], effective.format('null', 268435456, fallback)),
                ('[cpu memory]', config['memory-rlimit'], effective.format('null', 268435456, default)),
                ('[cpu memory]', config['memory-rlimit'], effective.format('null', 268435456, '[128,null]')),
                ('bogus', config['none'], effective.format('null', 'null', default))):
            with self.subTest(controllers=controllers, configured=configured, measured=measured):
                shutil.rmtree(self.session); self.session.mkdir(mode=0o700)
                env = self.ready_env() | {'FAKE_CONTROLLERS': controllers, 'FAKE_CONFIG': configured,
                                          'FAKE_EFFECTIVE': measured}
                result = self.start(env=env, text=True)
                self.assertNotEqual(result.returncode, 0)
                self.assertRegex(result.stderr, 'proxy hardening unavailable|unverifiable cgroup controller list')

    def test_proxy_hardening_verification_is_exact_per_enforced_budget(self):
        sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'network'))
        import proxy_hardening as hardening
        full = dict(capabilities=[0] * 5, no_new_privs=1, seccomp=2, nproc=[63948, 63948])
        hardening.verify({'PidsLimit': 128, 'Memory': 268435456}, full | dict(pids=128, memory=268435456))
        hardening.verify({'PidsLimit': 128, 'Memory': 0}, full | dict(pids=128, memory=None), ('pids',))
        hardening.verify({'PidsLimit': -1, 'Memory': 0}, full | dict(pids=None, memory=None), ())
        hardening.verify({'PidsLimit': -1, 'Memory': 0, 'Ulimits': None},
                         full | dict(pids=None, memory=None, nproc=[None, None]), (), 'none')
        # The process rlimit fallback: one RLIMIT_NPROC entry at 128, measured in the proxy.
        nproc = {'Name': 'RLIMIT_NPROC', 'Soft': 128, 'Hard': 128}
        fallback = full | dict(pids=None, memory=None, nproc=[128, 128])
        hardening.verify({'PidsLimit': -1, 'Memory': 0, 'Ulimits': [nproc]}, fallback, (), 'rlimit')
        hardening.verify({'PidsLimit': 0, 'Memory': 0, 'Ulimits': [{'Name': 'RLIMIT_NOFILE', 'Soft': 1, 'Hard': 1}, nproc]},
                         fallback, (), 'rlimit')
        for config, effective, process in (
                ({'PidsLimit': -1, 'Memory': 0}, fallback, 'rlimit'),
                ({'PidsLimit': -1, 'Memory': 0, 'Ulimits': [nproc | {'Soft': 64}]}, fallback, 'rlimit'),
                ({'PidsLimit': -1, 'Memory': 0, 'Ulimits': [nproc | {'Hard': '128'}]}, fallback, 'rlimit'),
                ({'PidsLimit': -1, 'Memory': 0, 'Ulimits': [nproc, nproc]}, fallback, 'rlimit'),
                ({'PidsLimit': -1, 'Memory': 0, 'Ulimits': nproc}, fallback, 'rlimit'),
                ({'PidsLimit': 128, 'Memory': 0, 'Ulimits': [nproc]}, fallback, 'rlimit'),
                ({'PidsLimit': -1, 'Memory': 0, 'Ulimits': [nproc]}, fallback | dict(nproc=[128, None]), 'rlimit'),
                ({'PidsLimit': -1, 'Memory': 0, 'Ulimits': [nproc]}, fallback | dict(nproc=[63948, 63948]), 'rlimit'),
                ({'PidsLimit': -1, 'Memory': 0, 'Ulimits': [nproc]}, fallback | dict(pids=128), 'rlimit'),
                ({'PidsLimit': -1, 'Memory': 0, 'Ulimits': [nproc]}, {k: v for k, v in fallback.items() if k != 'nproc'},
                 'rlimit'),
                ({'PidsLimit': -1, 'Memory': 0}, full | dict(pids=None, memory=None, nproc='128'), 'none'),
                ({'PidsLimit': -1, 'Memory': 0}, full | dict(pids=None, memory=None), 'other')):
            with self.subTest(config=config, effective=effective, process=process), self.assertRaises(ValueError):
                hardening.verify(config, effective, (), process)
        with self.assertRaises(ValueError):
            hardening.verify({'PidsLimit': 128, 'Memory': 0}, full | dict(pids=128, memory=None), ('pids',), 'rlimit')
        self.assertEqual(hardening.process_rlimit('Max open files 1 1 files\nMax processes 128 128 processes\n'),
                         [128, 128])
        self.assertEqual(hardening.process_rlimit('Max processes unlimited unlimited processes'), [None, None])
        with self.assertRaises(ValueError):
            hardening.process_rlimit('Max open files 1 1 files')
        for config, effective, enforced in (
                ({'PidsLimit': 128, 'Memory': 0}, full | dict(pids=128, memory=None), ('memory', 'pids')),
                ({'PidsLimit': 128, 'Memory': 268435456}, full | dict(pids=128, memory=268435456), ('pids',)),
                ({'PidsLimit': 2048, 'Memory': 0}, full | dict(pids=None, memory=None), ()),
                ({'PidsLimit': -1, 'Memory': 0}, full | dict(pids=None, memory=1), ()),
                ({'PidsLimit': 128, 'Memory': 0}, full | dict(pids='128', memory=None), ('pids',)),
                ({'PidsLimit': -1, 'Memory': 0}, full | dict(pids=None, memory=None), ('cpu',))):
            with self.subTest(config=config, effective=effective, enforced=enforced), self.assertRaises(ValueError):
                hardening.verify(config, effective, enforced)

    def test_start_fails_closed_on_identity_hardening_and_invalid_results(self):
        cases = [({'FAKE_READY': 'wrong-policy guard=' + DIGEST + ' mux=1 tls=' + TLS_ENFORCEMENT},
                  'identity mismatch'),
                 ({'FAKE_READY': f'{POLICY_IDENTITY} guard={DIGEST} mux=1 tls=tls-clienthello-sni-v1'},
                  'identity mismatch'),
                 ({'FAKE_CONFIG': '{"PidsLimit":0,"Memory":268435456}'}, 'proxy hardening unavailable'),
                 ({'FAKE_EFFECTIVE': '{"pids":129}'}, 'proxy hardening unavailable'),
                 ({'FAKE_FAIL': 'inspect'}, 'cannot inspect proxy resource budgets'),
                 ({'FAKE_FAIL': 'exec'}, 'cannot verify effective proxy hardening')]
        for case, message in cases:
            with self.subTest(case=case):
                env = self.ready_env(case.get('FAKE_READY')) | {k: v for k, v in case.items() if k != 'FAKE_READY'}
                shutil.rmtree(self.session)
                self.session.mkdir(mode=0o700)
                result = self.start(env=env, text=True)
                self.assertEqual(result.returncode, 1, result.stderr)
                self.assertIn(message, result.stderr)
                self.assertEqual(result.stdout, '')
                self.assertTrue((self.session / 'proxy.id').exists())

    def test_start_rejects_invalid_identity_and_keeps_engine_status(self):
        result = self.start(env={'FAKE_CREATED': 'not-an-id'}, text=True)
        self.assertEqual(result.returncode, 1)
        self.assertIn('invalid egress proxy container ID', result.stderr)
        self.assertTrue((self.session / 'proxy.pending').exists())
        shutil.rmtree(self.session)
        self.session.mkdir(mode=0o700)
        result = self.start(env={'FAKE_FAIL': 'create'}, text=True)
        self.assertEqual(result.returncode, 17)
        self.assertEqual(result.stdout, '')

    def test_start_readiness_deadline_is_bounded(self):
        started = time.monotonic()
        result = self.start(text=True)
        self.assertEqual(result.returncode, 1)
        self.assertIn('readiness deadline expired', result.stderr)
        self.assertLess(time.monotonic() - started, 15)

    def test_interrupted_start_group_is_terminated_and_stop_recovers_ownership(self):
        process = subprocess.Popen([sys.executable, '-I', str(self.install / 'network/session.py'), 'start',
                                    *self.network(), *self.provider, '--session', str(self.session),
                                    '--guard-digest', DIGEST], env=self.env | {'FAKE_STALL': 'create'},
                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        marker = Path(str(self.log) + '.stalled')
        deadline = time.monotonic() + 10
        while not marker.exists() and time.monotonic() < deadline:
            time.sleep(0.02)
        self.assertTrue(marker.exists(), 'start did not reach proxy creation')
        stalled = int(marker.read_text())
        self.assertEqual(os.getpgid(stalled), process.pid, 'engine client must share the helper process group')
        os.killpg(process.pid, signal.SIGTERM)
        time.sleep(0.1)
        os.killpg(process.pid, signal.SIGKILL)
        process.communicate(timeout=5)
        deadline = time.monotonic() + 2
        while Path(f'/proc/{stalled}').exists() and time.monotonic() < deadline:
            stat = Path(f'/proc/{stalled}/stat')
            if stat.exists() and stat.read_text().split()[2] == 'Z':
                break
            time.sleep(0.02)
        self.assertTrue((self.session / 'proxy.pending').exists())
        self.log.unlink()
        result = self.stop()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual([call[0] for call in self.calls()], ['inspect', 'rm'])
        self.assertEqual(self.calls()[-1][-1], PROXY)

    # stop ----------------------------------------------------------------------

    def test_stop_recovers_only_confirmed_owned_proxies(self):
        cases = (
            ('known', {}, ['rm']),
            ('pending-cid', {}, ['inspect', 'rm']),
            ('pending-label', {'FAKE_RECOVERY': PROXY}, ['ps', 'inspect', 'rm']),
            ('pending-none', {}, ['ps']),
            ('foreign', {'FAKE_OWNER': 'session.other'}, ['inspect']),
            ('never-started', {}, []),
        )
        for name, env, expected in cases:
            with self.subTest(case=name):
                shutil.rmtree(self.session)
                self.session.mkdir(mode=0o700)
                self.log.unlink(missing_ok=True)
                if name == 'known':
                    (self.session / 'proxy.id').write_text(PROXY + '\n')
                elif name != 'never-started':
                    (self.session / 'proxy.pending').touch()
                if name in ('pending-cid', 'foreign'):
                    (self.session / 'proxy.cid').write_text(PROXY + '\n')
                result = self.stop(env=env)
                self.assertEqual([call[0] for call in self.calls()], expected, result.stderr)
                if 'rm' in expected:
                    self.assertEqual(self.calls()[-1], ['rm', '--force', '--time', '0', '--ignore', PROXY])
                if name == 'foreign':
                    self.assertIn('could not confirm recovered proxy ownership', result.stderr)
                    self.assertIn('container=' + 'a' * 64, result.stderr)

    def test_stop_respects_the_remaining_deadline(self):
        (self.session / 'proxy.id').write_text(PROXY + '\n')
        result = self.stop(deadline=3)
        self.assertEqual(result.returncode, 1)
        self.assertIn('deadline exhausted before rm', result.stderr)
        self.assertFalse(self.calls())
        started = time.monotonic()
        result = self.stop(deadline=8, env={'FAKE_STALL': 'rm'})
        self.assertEqual(result.returncode, 1)
        self.assertLess(time.monotonic() - started, 6)
        self.assertIn('cleanup rm failed or timed out', result.stderr)
        self.assertIn('proxy=' + PROXY, result.stderr)
        stalled = int(Path(str(self.log) + '.stalled').read_text())
        stat = Path(f'/proc/{stalled}/stat')
        self.assertTrue(not stat.exists() or stat.read_text().split()[2] == 'Z')

    def test_stop_prints_the_sanitized_diagnostics_tail(self):
        (self.session / 'logs').mkdir()
        (self.session / 'logs/denials.jsonl').write_text(''.join(f'{{"n": {n}}}\n' for n in range(25)))
        result = self.stop()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(PROFILE.message_prefix + 'recent protected egress diagnostics (sanitized)', result.stderr)
        self.assertIn('{"n": 24}', result.stderr)
        self.assertIn('{"n": 5}', result.stderr)
        self.assertNotIn('{"n": 4}\n', result.stderr)

    # agent-args ----------------------------------------------------------------

    def test_agent_arguments_for_each_mode_are_exact(self):
        command = ('/usr/local/bin/agent', '-p', 'hello world', '', 'line\nbreak', '--help', '--')
        options, args, stderr = self.agent_args('offline', command=command)
        self.assertEqual(args, ['--offline', '--', *command])
        self.assertIn(f'guard={DIGEST} abi-min=3 filter=native-x86_64-v1 mux=1', stderr)
        for option in ('--network=none', '--pid=private', '--ipc=private', '--cap-drop=all',
                       '--security-opt=no-new-privileges',
                       f'{self.install}/network/bin/sandbox-egress-guard:/opt/sandbox-egress/guard:ro',
                       f'{self.install}/network/resolv.conf:/etc/resolv.conf:ro'):
            self.assertIn(option, options)
        self.assertEqual(options[-2:], ['--entrypoint', '/opt/sandbox-egress/guard'])
        self.assertEqual([options[i + 1] for i, value in enumerate(options) if value == '--unsetenv'],
                         ['HTTP_PROXY', 'HTTPS_PROXY', 'NO_PROXY', 'ALL_PROXY',
                          'http_proxy', 'https_proxy', 'no_proxy', 'all_proxy'])
        self.assertNotIn(f'{self.session}/transport:/run/sandbox-egress:ro', options)
        options, args, _ = self.agent_args('provider', command=('/bin/bash',))
        self.assertEqual(args, ['--provider', '--', '/usr/bin/python3', '-I', '/opt/sandbox-egress/relay.py',
                                '/bin/bash'])
        for option in (f'{self.session}/transport:/run/sandbox-egress:ro',
                       'HTTP_PROXY=http://127.0.0.1:18080', 'https_proxy=http://127.0.0.1:18080',
                       'NO_PROXY=localhost,127.0.0.1,::1', 'no_proxy=localhost,127.0.0.1,::1'):
            self.assertIn(option, options)
        self.assertGreater(options.index('HTTP_PROXY=http://127.0.0.1:18080'),
                           options.index('--unsetenv'))
        self.assertFalse(self.calls())

    def test_probe_arguments_ignore_application_commands(self):
        probe = ['--probe', '--token', TOKEN, '--workspace', str(self.base / 'workspace'),
                 '--qualification-input', str(self.base / 'input/input.json'), '--tls']
        options, args, _ = self.agent_args('provider', *probe, command=('touch', 'agent-started'))
        self.assertEqual(args, ['--provider', '--', '/usr/bin/python3', '-I', '/opt/sandbox-egress/relay.py',
                                '/usr/bin/python3', '-I', '/opt/sandbox-egress/qualification_probe.py', 'probe'])
        self.assertIn(PROFILE.label('qualification') + '=' + TOKEN, options)
        self.assertIn(f'{self.base}/input/cert.pem:/opt/sandbox-egress/qualification-cert.pem:ro', options)
        for target in ('/workspace', '/shared-state', '/isolated-home', '/worktree-parent'):
            self.assertIn(f'{self.base}/workspace:{target}:rw', options)
        options, args, _ = self.agent_args('offline', *probe[:-1], command=())
        self.assertEqual(args, ['--offline', '--', '/usr/bin/python3', '-I',
                                '/opt/sandbox-egress/qualification_probe.py', 'probe'])
        self.assertNotIn('--tls', options)

    def test_restricted_sessions_require_an_application(self):
        result = self.helper('agent-args', '--installation', str(self.install), '--mode', 'offline',
                             '--session', str(self.session), '--guard-digest', DIGEST, '--')
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(result.stdout, b'')


class ProfileWithoutMethodsTests(unittest.TestCase):
    """Provider mode is refused before any engine operation without authentication methods."""
    @classmethod
    def setUpClass(cls):
        cls.root = fixture_root(SHELL_FIXTURE)
        cls.addClassCleanup(shutil.rmtree, cls.root, True)
        cls.log = cls.root / 'podman.log'
        cls.bin = cls.root / 'bin-fake'
        cls.bin.mkdir()
        (cls.bin / 'podman').write_text('#!/bin/sh\necho "$@" >> ' + str(cls.log) + '\nexit 125\n')
        (cls.bin / 'podman').chmod(0o700)

    def run_module(self, *args, env=None):
        environment = {'PATH': str(self.bin) + ':' + os.environ['PATH'], 'HOME': str(self.root)} | (env or {})
        return subprocess.run([sys.executable, '-I', *map(str, args)], env=environment,
                              capture_output=True, text=True, timeout=30)

    def assert_refused(self, result):
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertIn(NO_METHODS, result.stderr)
        self.assertEqual(result.stdout, '')
        self.assertFalse(self.log.exists(), 'no engine command may run')

    def test_session_helper_refuses_provider_operations(self):
        helper = self.root / 'network/session.py'
        common = ('--installation', self.root, '--server-version', '4.9.3', '--backend', 'netavark',
                  '--endpoint', 'unix:///run/podman.sock', '--engine', 'podman')
        self.assert_refused(self.run_module(helper, 'prepare', '--mode', 'provider', *common))
        self.assert_refused(self.run_module(helper, 'prepare', '--mode', 'offline', '--policy', self.root, *common))
        self.assert_refused(self.run_module(helper, 'start', '--installation', self.root, '--session', 'a' * 32,
                                            '--guard-digest', 'b' * 64))
        self.assert_refused(self.run_module(helper, 'agent-args', '--installation', self.root, '--mode', 'provider',
                                            '--session', 'a' * 32, '--guard-digest', 'b' * 64, '--', 'bash'))

    def test_qualification_refuses_provider(self):
        result = self.run_module(self.root / 'network/qualify.py', 'qualify', env={
            'CONTAINER_HOST': 'unix:///run/podman.sock', 'FIXTURE_SHELL_NETWORK': 'provider'})
        self.assert_refused(result)
        self.assertIn('status=qualification-required', result.stderr)

    def test_toolchain_protection_without_approval_bypass(self):
        profile = agent_profile.load(self.root / agent_profile.PROFILE)
        sys.path.insert(0, str(ROOT / 'setup'))
        import toolchains
        names, prefixes = toolchains.profile_protection(profile)
        self.assertEqual(names, {profile.config_dir_env.lower()})
        self.assertEqual(prefixes, (profile.env_prefix.lower() + '_',))


if __name__ == '__main__':
    unittest.main()

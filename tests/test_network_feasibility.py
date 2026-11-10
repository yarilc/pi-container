"""Opt-in, disposable rootless Unix-socket egress topology gate."""
import concurrent.futures
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
import uuid


sys.path.insert(0, str(Path(__file__).resolve().parent))
from sandbox_profile import AGENT_IMAGE, PROFILE, env as profile_env
IMAGE = os.environ.get(profile_env("IMAGE"), AGENT_IMAGE)
FIXTURE = Path(__file__).with_name('network_fixture.py')


@unittest.skipUnless(os.environ.get('SANDBOX_RUNTIME_TESTS') == '1',
                     'set SANDBOX_RUNTIME_TESTS=1 with a rootless engine')
class NetworkFeasibility(unittest.TestCase):
    def command(self, *args, **kwargs):
        result = subprocess.run(['podman', *args], text=True, capture_output=True,
                                timeout=30, **kwargs)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        return result.stdout.strip()

    def test_isolated_agent_unix_proxy(self):
        info = json.loads(self.command('info', '--format', 'json'))
        self.assertTrue(info['host']['security']['rootless'])
        self.assertEqual(info['host']['networkBackend'], 'netavark')
        with tempfile.TemporaryDirectory(prefix='egress-gate-',
                                        dir=os.environ.get('SANDBOX_TEST_STATE_ROOT')) as native:
            root = Path(native)
            common = ['--userns=keep-id', '--user', f'{os.getuid()}:{os.getgid()}']
            sessions = []
            for index in range(2):
                session = root / str(index)
                session.mkdir(mode=0o700)
                transport = session / 'transport'
                transport.mkdir(mode=0o700)
                shutil.copyfile(FIXTURE, session / 'fixture.py')
                self.command('run', '--rm', '--network=none', *common,
                             '--volume', f'{session}:/fixture:rw', '--entrypoint', 'openssl',
                             IMAGE, 'req', '-x509', '-newkey', 'rsa:2048', '-nodes',
                             '-days', '1', '-subj', '/CN=upstream.test', '-addext',
                             'subjectAltName=DNS:upstream.test', '-keyout', '/fixture/key.pem',
                             '-out', '/fixture/cert.pem')
                token = 'gate-' + uuid.uuid4().hex
                name = PROFILE.name + '-egress-gate-' + uuid.uuid4().hex
                self.addCleanup(self.command, 'rm', '--force', '--time', '0', '--ignore', name)
                self.command('run', '--detach', '--name', name, '--read-only', *common,
                             '--volume', f'{session}:/fixture:ro',
                             '--volume', f'{transport}:/transport:rw',
                             '--entrypoint', 'python3', IMAGE, '/fixture/fixture.py', 'serve', token)
                deadline = time.monotonic() + 10
                while not (transport / 'proxy.sock').exists():
                    self.assertLess(time.monotonic(), deadline, self.command('logs', name))
                    time.sleep(0.05)
                sessions.append((session, transport, token, name))

            def probe(session):
                directory, transport, token, _ = session
                return self.command('run', '--rm', '--network=none', '--read-only', *common,
                                    '--volume', f'{directory / "fixture.py"}:/probe.py:ro',
                                    '--volume', f'{directory / "cert.pem"}:/cert.pem:ro',
                                    '--volume', f'{transport}:/transport:ro',
                                    '--entrypoint', 'python3', IMAGE, '/probe.py', 'probe', token)

            with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
                for output in executor.map(probe, sessions):
                    print(output, flush=True)
            directory, transport, token, _ = sessions[0]
            output = self.command('run', '--rm', '--network=none', '--read-only', *common,
                                  '--volume', f'{directory / "fixture.py"}:/probe.py:ro',
                                  '--volume', f'{directory / "cert.pem"}:/cert.pem:ro',
                                  '--volume', f'{transport}:/workspace:rw',
                                  '--entrypoint', 'python3', IMAGE, '/probe.py', 'ipc-probe', token)
            self.assertIn('DESIGN BLOCKER', output)
            print(output, flush=True)
            for _, _, _, name in sessions:
                self.command('rm', '--force', '--time', '0', name)
            # Caller-owned directories remain removable after container cleanup.
            print('PASS concurrent session identities and owned fixture cleanup', flush=True)

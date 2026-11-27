"""Opt-in production-wrapper network acceptance with synthetic state."""
import json
import os
from pathlib import Path
import shutil
import select
import signal
import subprocess
import sys
import tempfile
import unittest
import uuid
import time
import hashlib


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'network'))
from revisions import TLS_ENFORCEMENT  # noqa: E402
sys.path.insert(0, str(ROOT / 'tests'))
from guard_terminal_probe import terminal_skip_reason  # noqa: E402
sys.path.insert(0, str(ROOT / 'setup'))
import engine  # noqa: E402
IMAGE = os.environ.get('PI_CONTAINER_IMAGE', 'localhost/pi-container:latest')
ENGINE_IMAGE = os.environ.get('PI_CONTAINER_ENGINE_IMAGE', 'localhost/pi-container-engine:latest')
# A small pinned image that the engine tests copy into the library's store.
SAMPLE = os.environ.get('SANDBOX_TEST_ENGINE_SAMPLE', 'docker.io/library/alpine@sha256:'
                        'c64c687cbea9300178b30c95835354e34c4e4febc4badfe27102879de0483b5e')


@unittest.skipUnless(os.environ.get('SANDBOX_RUNTIME_TESTS') == '1', 'requires real rootless engine')
class NetworkRuntime(unittest.TestCase):
    _shared_fixtures = False
    _provider_cache = None

    @classmethod
    def setUpClass(cls):
        cls._shared_fixtures = True
        cls._provider_cache = None
        cls.guard_output = tempfile.TemporaryDirectory(prefix='network-guard-', dir=os.environ.get('SANDBOX_TEST_STATE_ROOT'))
        cls.addClassCleanup(cls.guard_output.cleanup)
        result = subprocess.run(['bash', str(ROOT / 'network/build-guard.sh'), cls.guard_output.name],
            env=os.environ | {'PI_CONTAINER_MAINTENANCE': '1'}, capture_output=True, text=True, timeout=60)
        if result.returncode:
            raise RuntimeError(result.stdout + result.stderr)

    def remove_toolchain_on_cleanup(self, name, values):
        """Store layers belong to the engine's subordinate IDs: only the toolchain command removes them."""
        self.addCleanup(subprocess.run, [sys.executable, '-I', str(self.install / 'setup/toolchains.py'), 'remove', name],
                        cwd=self.project, env=self.env | values, capture_output=True, timeout=300)

    def engine_profile(self):
        """The engine seccomp profile derived once from the engine host's default, or None without an engine image."""
        cached = Path(self.guard_output.name) / 'engine-seccomp.json'
        if cached.exists():
            return cached
        if subprocess.run(['podman', 'image', 'exists', ENGINE_IMAGE], capture_output=True).returncode:
            return None
        default = subprocess.run(['podman', 'info', '--format', '{{.Host.Security.SECCOMPProfilePath}}'],
                                 capture_output=True, text=True, check=True, timeout=60).stdout.strip()
        content = subprocess.run(['podman', 'run', '--rm', '--network=none', '--volume', default + ':/default.json:ro',
                                  '--entrypoint', 'cat', IMAGE, '/default.json'], capture_output=True, check=True, timeout=60).stdout
        source = Path(self.guard_output.name) / 'default-seccomp.json'
        source.write_bytes(content)
        engine.write_seccomp(source, cached)
        return cached

    def podman(self, *args):
        result = subprocess.run(['podman', *args], capture_output=True, text=True, timeout=60)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        return result.stdout.strip()

    def setUp(self):
        self.base = Path(tempfile.mkdtemp(prefix='network-runtime-', dir=os.environ.get('SANDBOX_TEST_STATE_ROOT')))
        self.addCleanup(shutil.rmtree, self.base)
        self.install = Path(self.guard_output.name) / 'installed' if self._shared_fixtures else self.base / 'installed'
        self.install.mkdir(mode=0o700, exist_ok=True)
        (self.install / 'network').mkdir(mode=0o700, exist_ok=True)
        self.wrapper = self.install / 'pi-container.sh'
        shutil.copyfile(ROOT / 'pi-container.sh', self.wrapper)
        self.wrapper.chmod(0o700)
        for source in list((ROOT / 'network').glob('*.py')) + [ROOT / 'network/resolv.conf']:
            shutil.copyfile(source, self.install / 'network' / source.name)
        (self.install / 'agent/policies').mkdir(mode=0o700, parents=True, exist_ok=True)
        (self.install / 'setup').mkdir(mode=0o700, exist_ok=True)
        (self.install / 'launcher/engine').mkdir(mode=0o700, parents=True, exist_ok=True)
        # The Pi wrapper also reads its recipe and version for the staleness hash.
        for name in ('agent/profile.json', 'agent/policies/default.json', 'agent/launcher.sh', 'launcher/core.sh',
                     'setup/common.py', 'setup/toolchains.py', 'setup/engine.py', *engine.INPUTS,
                     '.version', 'Containerfile', '.containerignore'):
            shutil.copyfile(ROOT / name, self.install / name)
        shutil.copytree(ROOT / 'setup/toolchain-catalog', self.install / 'setup/toolchain-catalog', dirs_exist_ok=True)
        binary_dir = self.install / 'network/bin'
        binary_dir.mkdir(mode=0o700, exist_ok=True)
        for name in ('sandbox-egress-guard', 'sandbox-egress-guard.sha256'):
            (binary_dir / name).unlink(missing_ok=True)
            shutil.copyfile(Path(self.guard_output.name) / name, binary_dir / name)
        (binary_dir / 'sandbox-egress-guard').chmod(0o500)
        engine_profile = self.engine_profile()
        if engine_profile:
            shutil.copyfile(engine_profile, self.install / engine.SECCOMP)
        self.project = self.base / 'project'
        self.project.mkdir()
        self.runtime = self.base / 'runtime'
        self.runtime.mkdir(mode=0o700)
        (self.base / 'home').mkdir(mode=0o700)
        self.env = {'PATH': os.environ['PATH'], 'HOME': str(self.base / 'home'),
                    'CONTAINER_HOST': os.environ['CONTAINER_HOST'],
                    # Ordinary launches require explicit mode since N20.
                    'PI_CONTAINER_NETWORK': 'offline',
                    'PI_CONTAINER_STATE_DIR': str(self.base / 'state'),
                    'PI_CONTAINER_IMAGE': IMAGE,
                    'PI_CONTAINER_NETWORK_RUNTIME_DIR': str(self.runtime)}
        self._qualified = set()

    def ensure_qualification(self, environment):
        values = self.env | environment
        # Prepare real reports on the same protected installation. Never copy or
        # fabricate receipts; both state modes are covered by each actual gate.
        inputs = {key:value for key,value in values.items() if key.startswith('PI_CONTAINER_')
                  and key not in ('PI_CONTAINER_STATE_DIR','PI_CONTAINER_NETWORK_RUNTIME_DIR')}
        for key in ('PI_CONTAINER_NETWORK_POLICY','PI_CONTAINER_CA_BUNDLE'):
            path = values.get(key)
            if path and Path(path).is_file():
                inputs[key + '_sha256'] = hashlib.sha256(Path(path).read_bytes()).hexdigest()
        token = json.dumps(inputs,sort_keys=True)
        if token in self._qualified:
            return
        clean = {key:value for key,value in values.items() if not key.startswith('NETWORK_')}
        clean['PATH'] = self.env['PATH']
        check = subprocess.run(['python3','-I',str(self.install/'network/qualify.py'),'check'],
            cwd=self.project,env=clean,capture_output=True,text=True,timeout=360)
        if check.returncode:
            result = subprocess.run([str(self.wrapper),'--container-qualify'],cwd=self.project,
                env=clean,capture_output=True,text=True,timeout=360)
            self.assert_success(result)
        self._qualified.add(token)

    def shell(self, script, qualify=True, **environment):
        if qualify:
            self.ensure_qualification(environment)
        return subprocess.run([str(self.wrapper), '--container-shell'], cwd=self.project,
                              env=self.env | environment, input='set -Eeuo pipefail\n' + script,
                              text=True, capture_output=True, timeout=45)

    def test_toolchain_added_during_offline_session_without_network(self):
        # The library is a read-only directory bind: a toolchain the operator adds
        # on the host appears in a running session, which keeps its restrictions.
        import io, tarfile
        buffer = io.BytesIO()
        with tarfile.open(fileobj=buffer, mode='w:gz') as archive:
            for directory in ('live-1', 'live-1/bin'):
                info = tarfile.TarInfo(directory)
                info.type, info.mode = tarfile.DIRTYPE, 0o755
                archive.addfile(info)
            data = b'#!/bin/sh\necho live-tool\n'
            info = tarfile.TarInfo('live-1/bin/live')
            info.size, info.mode = len(data), 0o755
            archive.addfile(info, io.BytesIO(data))
        source = self.base / 'live.tar.gz'
        source.write_bytes(buffer.getvalue())
        recipe = self.base / 'live.json'
        recipe.write_text(json.dumps({'schema': 1, 'name': 'live', 'version': '1', 'default': True, 'check': ['live'],
                                      'source': {'archive': str(source), 'strip_components': 1,
                                                 'sha256': hashlib.sha256(source.read_bytes()).hexdigest()}}))
        self.ensure_qualification({})
        proc = subprocess.Popen([str(self.wrapper), '--container-shell'], cwd=self.project, env=self.env,
                                stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        self.addCleanup(lambda: proc.poll() is None and proc.kill())
        proc.stdin.write("""echo network-ready
for attempt in $(seq 1 300); do test -f /toolchains/live/env.sh && break; sleep 0.2; done
. /toolchains/live/env.sh && live
if python3 -c 'import socket; socket.create_connection(("1.1.1.1", 443), timeout=3)' 2>/dev/null; then echo direct-network; fi
exit 0
""")
        proc.stdin.flush()
        ready, _, _ = select.select([proc.stdout], [], [], 60)
        self.assertTrue(ready, 'session readiness timed out')
        self.assertEqual(proc.stdout.readline().strip(), 'network-ready')
        added = subprocess.run([str(self.wrapper), '--container-toolchain', 'add', str(recipe)], cwd=self.project,
                               env=self.env, capture_output=True, text=True, timeout=300)
        self.assert_success(added)
        output, errors = proc.communicate(timeout=60)
        self.assertEqual(proc.returncode, 0, output + errors)
        self.assertIn('live-tool', output)
        self.assertNotIn('direct-network', output)

    def assert_success(self, result):
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def owned_proxies(self):
        # Other operators/tests can legitimately have the same role label.
        # Attribute resources to this disposable runtime, never to the role alone.
        owned = []
        for ident in self.podman('ps', '--all', '--no-trunc', '--filter',
                                 'label=io.pi-container.egress', '--format', '{{.ID}}').splitlines():
            result = subprocess.run(['podman', 'inspect', '--format', '{{json .Mounts}}', ident],
                                    capture_output=True, text=True, timeout=10)
            if result.returncode and ('no such' in result.stderr or 'not known' in result.stderr):
                continue  # A concurrent foreign session may have exited.
            self.assertEqual(result.returncode, 0, result.stderr)
            if any(Path(mount['Source']).is_relative_to(self.runtime)
                   for mount in json.loads(result.stdout) if mount.get('Source')):
                owned.append(ident)
        return owned

    def test_leftover_delegation_opt_in_and_other_values(self):
        # Host Podman delegation was removed: exact PI_CONTAINER_PODMAN=1 stops
        # every launch in all modes, and other values or the old socket override are ignored.
        _, provider = self.provider_fixture()
        for mode in ('offline', 'provider', 'unrestricted'):
            # Provider mode checks its own settings first, so the grid supplies them.
            settings = provider if mode == 'provider' else {}
            for state in ('', self.env['PI_CONTAINER_STATE_DIR']):
                for shell in (False, True):
                    for yolo in ('0', '1'):
                        result = subprocess.run([str(self.wrapper), *(['--container-shell'] if shell else ['--version'])],
                            cwd=self.project, env=self.env | settings | {'PI_CONTAINER_NETWORK': mode,
                                'PI_CONTAINER_STATE_DIR': state, 'PI_CONTAINER_YOLO': yolo,
                                'PI_CONTAINER_PODMAN': '1'}, input='', capture_output=True, text=True, timeout=10)
                        self.assertEqual(result.returncode, 1)
                        self.assertIn('PI_CONTAINER_PODMAN=1: host Podman delegation was removed', result.stderr)
        for mode in ('offline', 'provider'):
            for state in ('', self.env['PI_CONTAINER_STATE_DIR']):
                environment = provider | {'PI_CONTAINER_NETWORK': mode}
                result = self.shell('test ! -S /run/podman/podman.sock; test -z "${CONTAINER_HOST+x}${DOCKER_HOST+x}"\n',
                    **environment, PI_CONTAINER_STATE_DIR=state,
                    PI_CONTAINER_PODMAN='true', PI_CONTAINER_PODMAN_SOCKET='/absent/disabled.sock')
                self.assert_success(result)

    def test_offline_defaults_and_leftover_delegation_refusal(self):
        result = self.shell("python3 - <<'PY'\nimport os,socket\nassert sorted(l.split(':',1)[0].strip() for l in open('/proc/net/dev').read().splitlines()[2:]) == ['lo']\nassert 'HTTP_PROXY' not in os.environ\ntry: socket.create_connection(('1.1.1.1',443),1)\nexcept OSError: pass\nelse: raise AssertionError('direct route')\nPY\n")
        self.assert_success(result)
        self.assertIn('mode=offline', result.stderr)
        self.assertFalse(list(self.runtime.iterdir()))
        result = self.shell('true\n', qualify=False, PI_CONTAINER_PODMAN='1')
        self.assertEqual(result.returncode, 1)
        self.assertIn('PI_CONTAINER_PODMAN=1: host Podman delegation was removed', result.stderr)

    def test_offline_session_engine_has_no_external_path(self):
        # session-container-engine: Engine shares the session network boundary / Offline nested container.
        for image in (ENGINE_IMAGE, SAMPLE):
            if subprocess.run(['podman', 'image', 'exists', image], capture_output=True).returncode:
                self.skipTest('prepare ' + image + ' in the engine first')
        sample_id = self.podman('image', 'inspect', '--format', '{{.Id}}', SAMPLE).removeprefix('sha256:')
        # Bind sources must exist at the same path for the engine service.
        values = {'TMPDIR': str(self.base), 'PI_CONTAINER_ENGINE_IMAGE': ENGINE_IMAGE}
        recipe = self.base / 'sample.json'
        recipe.write_text(json.dumps({'schema': 2, 'name': 'sample', 'version': '1', 'default': False,
                                      'images': [{'local': 'sha256:' + sample_id, 'name': 'localhost/sandbox-test-sample:1'}],
                                      'check': ['podman', 'run', '--rm', '--network=none', 'localhost/sandbox-test-sample:1',
                                                'true']}))
        added = subprocess.run([sys.executable, '-I', str(self.install / 'setup/toolchains.py'), 'add', str(recipe)],
                               cwd=self.project, env=self.env | values, capture_output=True, text=True, timeout=300)
        self.assertEqual(added.returncode, 0, added.stdout + added.stderr)
        self.remove_toolchain_on_cleanup('sample', values)
        result = self.shell(r"""
test "$(podman info --format '{{.Host.Security.Rootless}}')" = true
# The namespace has only loopback; /sys/class/net may be the host's.
test "$(tail -n +3 /proc/net/dev | cut -d: -f1 | tr -d ' ' | sort | tr '\n' ' ')" = 'lo '
podman network create engine-test-net >/dev/null
for network in host none default engine-test-net; do
  flags=(--network="$network"); [ "$network" != default ] || flags=()
  out=$(podman run --rm "${flags[@]}" localhost/sandbox-test-sample:1 sh -c \
    'wget -q -T 3 -O /dev/null http://1.1.1.1/ && echo REACHED; nslookup -timeout=2 example.com >/dev/null 2>&1 && echo RESOLVED; echo RAN' 2>&1)
  case $out in *REACHED*|*RESOLVED*) echo "EXTERNAL_PATH $network: $out"; exit 1 ;; esac
  case $out in *RAN*) ;; *) echo "NOT_RUN $network: $out"; exit 1 ;; esac
done
! podman pull --quiet docker.io/library/busybox:latest >/dev/null 2>&1
echo OFFLINE_ENGINE_OK
""", **values)
        self.assert_success(result)
        self.assertIn('OFFLINE_ENGINE_OK', result.stdout)
        self.assertIn('mode=offline', result.stderr)

    def test_image_recipe_check_runs_without_network(self):
        # toolchain-library: Verified against the runtime image / Image check without network.
        for image in (ENGINE_IMAGE, SAMPLE):
            if subprocess.run(['podman', 'image', 'exists', image], capture_output=True).returncode:
                self.skipTest('prepare ' + image + ' in the engine first')
        sample_id = self.podman('image', 'inspect', '--format', '{{.Id}}', SAMPLE).removeprefix('sha256:')
        values = {'PI_CONTAINER_ENGINE_IMAGE': ENGINE_IMAGE}
        for name, check, accepted in (
                ('offline-ok', ['true'], True),
                ('needs-network', ['wget', '-q', '-T', '3', '-O', '/dev/null', 'http://1.1.1.1/'], False)):
            with self.subTest(name=name):
                reference = 'localhost/sandbox-test-' + name + ':1'
                recipe = self.base / (name + '.json')
                recipe.write_text(json.dumps({'schema': 2, 'name': name, 'version': '1', 'default': False,
                                              'images': [{'local': 'sha256:' + sample_id, 'name': reference}],
                                              'check': ['podman', 'run', '--rm', reference, *check]}))
                added = subprocess.run([sys.executable, '-I', str(self.install / 'setup/toolchains.py'), 'add',
                                        str(recipe)], cwd=self.project, env=self.env | values, capture_output=True,
                                       text=True, timeout=300)
                self.assertEqual(added.returncode == 0, accepted, added.stdout + added.stderr)
                if accepted:
                    self.remove_toolchain_on_cleanup(name, values)
                library = Path(self.env['HOME']) / '.local/share/sandbox-toolchains'
                self.assertEqual((library / name / 'toolchain.json').exists(), accepted)
                if not accepted:
                    self.assertIn('toolchain check failed', added.stderr)

    def test_restricted_hardening_identity_and_proxy_readiness(self):
        _, provider = self.provider_fixture()
        check = """from pathlib import Path
import os,socket
status=dict(line.split(':',1) for line in Path('/proc/self/status').read_text().splitlines())
for key in ('CapInh','CapPrm','CapEff','CapBnd','CapAmb'): assert int(status[key],16)==0, key
assert int(status['NoNewPrivs'])==1
assert int(status['Seccomp'])==2
assert os.getuid()==int(os.environ['EXPECTED_UID'])
Path('owned-hardening-file').write_text('ok')
assert Path('owned-hardening-file').stat().st_uid==os.getuid()
left,right=socket.socketpair(); left.sendall(b'ok'); assert right.recv(2)==b'ok'
left.close(); right.close()
"""
        for mode in ('offline', 'provider'):
            for state in ('', self.env['PI_CONTAINER_STATE_DIR']):
                with self.subTest(mode=mode, isolated=bool(state)):
                    environment = provider | {'PI_CONTAINER_NETWORK': mode,
                        'PI_CONTAINER_STATE_DIR': state}
                    script = ('EXPECTED_UID=' + str(os.getuid()) + " python3 - <<'PY'\n" + check
                              + "PY\nprintf 'network-ready\\n'; read -r marker; exit 0")
                    proc = self.start_session(script, environment)
                    self.assertEqual((self.project / 'owned-hardening-file').stat().st_uid, os.getuid())
                    if mode == 'provider':
                        session = next(self.runtime.iterdir())
                        self.assertTrue((session / 'transport/proxy.sock').is_socket())
                        self.assertIn('tls=' + TLS_ENFORCEMENT, (session / 'transport/ready').read_text())
                        proxy_id = self.podman('ps', '--no-trunc', '--filter',
                            f'label=io.pi-container.egress={session.name}', '--format', '{{.ID}}')
                        self.assertEqual(len(proxy_id), 64)
                        status = self.podman('exec', proxy_id, 'cat', '/proc/1/status')
                        fields = dict(line.split(':', 1) for line in status.splitlines())
                        for key in ('CapInh', 'CapPrm', 'CapEff', 'CapBnd', 'CapAmb'):
                            self.assertEqual(int(fields[key], 16), 0, key)
                        self.assertEqual(int(fields['NoNewPrivs']), 1)
                        self.assertEqual(int(fields['Seccomp']), 2)
                    stdout, stderr = proc.communicate('done\n', timeout=25)
                    self.assertEqual(proc.returncode, 0, stdout + stderr)
                    self.assertFalse(list(self.runtime.iterdir()))

    def provider_fixture(self):
        if self._shared_fixtures and type(self)._provider_cache:
            context, fixture_id, value = type(self)._provider_cache
            policy_file = self.install/'test-policy.json'
            policy_file.write_text(json.dumps(value)); policy_file.chmod(0o600)
            self.policy_file = policy_file
            shutil.copyfile(context/'cert.pem',self.project/'cert.pem')
            return context, dict(PI_CONTAINER_NETWORK='provider',
                PI_CONTAINER_NETWORK_POLICY=str(policy_file),PI_CONTAINER_NETWORK_PROFILE='controlled-test',
                PI_CONTAINER_EGRESS_IMAGE=fixture_id)
        context = (Path(self.guard_output.name) if self._shared_fixtures else self.base) / 'fixture'
        context.mkdir(mode=0o700)
        # Build production proxy from the checked-out source and pin the result
        # by immutable image ID for this disposable operator policy invocation.
        proxy_tag = 'localhost/pi-egress-test-' + uuid.uuid4().hex
        cleanup = type(self).addClassCleanup if self._shared_fixtures else self.addCleanup
        cleanup(self.podman, 'rmi', '--force', proxy_tag)
        self.podman('build', '--pull=never', '--tag', proxy_tag, '--file',
                    str(ROOT / 'network/Containerfile'), str(ROOT / 'network'))
        proxy_id = self.podman('image', 'inspect', '--format', '{{.Id}}', proxy_tag)
        self.podman('run', '--rm', '--network=none', '--userns=keep-id',
                    '--user', f'{os.getuid()}:{os.getgid()}', '--volume', f'{context}:/fixture:rw',
                    '--entrypoint', 'openssl', IMAGE, 'req', '-x509', '-newkey', 'rsa:2048',
                    '-nodes', '-days', '1', '-subj', '/CN=localhost.localdomain', '-addext',
                    'subjectAltName=DNS:localhost.localdomain,DNS:alternate.test,DNS:api.anthropic.com,DNS:api.openai.com,'
                    'DNS:generativelanguage.googleapis.com,DNS:openrouter.ai,DNS:pi.dev,DNS:registry.npmjs.org',
                    # Strict TLS clients reject a CA certificate used as the server certificate.
                    '-addext', 'basicConstraints=critical,CA:FALSE', '-addext', 'extendedKeyUsage=serverAuth',
                    '-keyout', '/fixture/key.pem',
                    '-out', '/fixture/cert.pem')
        shutil.copyfile(ROOT / 'tests/network_tls_fixture.py', context / 'upstream.py')
        (context / 'Containerfile').write_text(f'FROM {proxy_id}\nCOPY cert.pem key.pem upstream.py /test/\nENTRYPOINT ["python3", "/test/upstream.py"]\n')
        # Synthetic key is world-readable inside only this disposable test image.
        (context / 'key.pem').chmod(0o644)
        fixture_tag = 'localhost/pi-tls-test-' + uuid.uuid4().hex
        cleanup(self.podman, 'rmi', '--force', fixture_tag)
        self.podman('build', '--pull=never', '--tag', fixture_tag, str(context))
        fixture_id = self.podman('image', 'inspect', '--format', '{{.Id}}', fixture_tag)
        value = json.loads((ROOT / 'agent/policies/default.json').read_text())
        value['profiles']['controlled-test'] = {'authentication': 'custom', 'disable_optional_traffic': True,
            'destinations': [{'host': 'localhost.localdomain', 'port': 8443, 'addresses': ['127.0.0.1', '::1']}]}
        for name in ('anthropic-api', 'openai-api', 'gemini-api', 'openrouter-api'):
            profile = json.loads(json.dumps(value['profiles'][name]))
            for destination in profile['destinations']:
                destination['addresses'] = ['127.0.0.1']
            value['profiles']['controlled-' + name] = profile
        policy_file = self.install / 'test-policy.json'
        policy_file.write_text(json.dumps(value))
        shutil.copyfile(context / 'cert.pem', self.project / 'cert.pem')
        environment = {'PI_CONTAINER_NETWORK': 'provider',
                       'PI_CONTAINER_NETWORK_POLICY': str(policy_file),
                       'PI_CONTAINER_NETWORK_PROFILE': 'controlled-test',
                       'PI_CONTAINER_EGRESS_IMAGE': fixture_id}
        import sys
        sys.path.insert(0, str(ROOT / 'network'))
        from policy import revision
        print('controlled TLS evidence: proxy=' + proxy_id + ' fixture=' + fixture_id
              + ' enforcement=' + TLS_ENFORCEMENT + ' policy=' + revision(value), flush=True)
        self.policy_file = policy_file
        if self._shared_fixtures:
            type(self)._provider_cache = (context, fixture_id, value)
        return context, environment

    def test_tls_destination_binding_controlled_profiles(self):
        _, environment = self.provider_fixture()
        shutil.copyfile(ROOT / 'tests/tls_binding_fixture.py', self.project / 'binding.py')
        for profile, hosts in (('controlled-test', 'localhost.localdomain'),
                               ('controlled-anthropic-api', 'api.anthropic.com'),
                               ('controlled-openai-api', 'api.openai.com'),
                               ('controlled-gemini-api', 'generativelanguage.googleapis.com'),
                               ('controlled-openrouter-api', 'openrouter.ai')):
            result = self.shell('python3 binding.py ' + hosts + '\n', **(environment | {
                'PI_CONTAINER_NETWORK_PROFILE': profile}))
            self.assert_success(result)
            self.assertIn('tls-destination-binding-ok', result.stdout)
        # Optional Pi hosts and other providers are policy denials, even
        # though the fixture resolver and certificate would still serve them.
        result = self.shell("""python3 - <<'PY'
import socket
for host in ('pi.dev', 'registry.npmjs.org', 'api.openai.com'):
    connection = socket.create_connection(('127.0.0.1', 18080), 5)
    connection.sendall(('CONNECT ' + host + ':443 HTTP/1.1\\r\\n\\r\\n').encode())
    response = connection.recv(64)
    assert not response.startswith(b'HTTP/1.1 200'), response
    connection.close()
print('optional-hosts-denied')
PY
""", **(environment | {'PI_CONTAINER_NETWORK_PROFILE': 'controlled-openrouter-api'}))
        self.assert_success(result)
        self.assertIn('optional-hosts-denied', result.stdout)
        self.assertIn('policy-denied', result.stderr)
        self.assertIn('pi.dev', result.stderr)

    def test_provider_uses_real_proxy_and_cleans_resources(self):
        context, environment = self.provider_fixture()
        # An unrelated container with the same role label must survive cleanup.
        foreign = self.podman('create', '--network=none', '--label',
            'io.pi-container.egress=unrelated-fixture', '--volume',
            f'{self.base}:/unrelated:ro', '--entrypoint', '/bin/true', IMAGE)
        self.addCleanup(self.podman, 'rm', '--force', '--ignore', foreign)
        result = self.shell("""test "$HTTP_PROXY" = http://127.0.0.1:18080
test "$http_proxy" = "$HTTP_PROXY"
test "$NO_PROXY" = localhost,127.0.0.1,::1
test -z "${ALL_PROXY+x}"
test -z "${SSL_CERT_FILE+x}${REQUESTS_CA_BUNDLE+x}${CURL_CA_BUNDLE+x}${NODE_EXTRA_CA_CERTS+x}"
test ! -e /config/policy.json
test ! -e /logs/denials.jsonl
test "$(curl --fail --silent --show-error --max-time 10 --cacert cert.pem https://localhost.localdomain:8443/)" = controlled-production-proxy-ok
test "$(curl --fail --silent --show-error --max-time 10 --cacert cert.pem https://localhost.localdomain:8443/stream)" = abc
if curl --silent --show-error --max-time 3 https://localhost.localdomain:8443/; then exit 43; fi
if curl --silent --show-error --max-time 3 https://unapproved.test/; then exit 41; fi
if curl --location --fail --silent --show-error --max-time 3 --cacert cert.pem https://localhost.localdomain:8443/redirect; then exit 44; fi
if curl --fail --silent --show-error --max-time 3 https://localhost.localdomain.evil.test:8443/; then exit 45; fi
if curl --fail --silent --show-error --max-time 3 https://localhost.localdomain:8444/; then exit 46; fi
if curl --noproxy '' --fail --silent --show-error --max-time 3 https://127.0.0.1:8443/; then exit 47; fi
if curl --fail --silent --show-error --max-time 3 http://127.0.0.1:18080/admin; then exit 48; fi
if env -u HTTP_PROXY -u HTTPS_PROXY -u http_proxy -u https_proxy curl --max-time 3 https://1.1.1.1/; then exit 42; fi
python3 - <<'PY'
import socket,ssl
connection=socket.create_connection(('127.0.0.1',18080),3)
connection.sendall(b'CONNECT localhost.localdomain:8443 HTTP/1.1\\r\\n\\r\\n')
response=b''
while not response.endswith(b'\\r\\n\\r\\n'): response+=connection.recv(1)
assert b'200' in response
context=ssl.create_default_context(cafile='cert.pem')
with context.wrap_socket(connection,server_hostname='localhost.localdomain') as secure:
    secure.sendall(b'GET /websocket HTTP/1.1\\r\\nHost: localhost.localdomain\\r\\nUpgrade: websocket\\r\\nConnection: Upgrade\\r\\nSec-WebSocket-Key: dGhlIHNhbXBsZSBub25jZQ==\\r\\nSec-WebSocket-Version: 13\\r\\n\\r\\n')
    response=b''
    while not response.endswith(b'\\r\\n\\r\\n'): response+=secure.recv(1)
    assert b'101' in response
    assert secure.recv(4)==b'\\x81\\x02ok'
PY
""", **environment)
        self.assert_success(result)
        self.assertIn('profile=controlled-test', result.stderr)
        self.assertFalse(list(self.runtime.iterdir()), 'session transport/configuration leaked')
        self.assertIn('policy-denied', result.stderr)
        self.assertNotIn('fixture-secret-token', result.stderr)
        ca_result = self.shell("""test "$SSL_CERT_FILE" = /pi-home/ca/bundle.pem
test "$REQUESTS_CA_BUNDLE" = "$SSL_CERT_FILE"
test "$CURL_CA_BUNDLE" = "$SSL_CERT_FILE"
test "$NODE_EXTRA_CA_CERTS" = "$SSL_CERT_FILE"
test ! -w "$SSL_CERT_FILE"
test "$(curl --fail --silent --show-error --max-time 10 https://localhost.localdomain:8443/)" = controlled-production-proxy-ok
""", **environment, PI_CONTAINER_TRUST_HOST_CA='1',
            PI_CONTAINER_CA_BUNDLE=str(context / 'cert.pem'))
        self.assert_success(ca_result)
        self.assertEqual((self.base / 'state/ca').stat().st_mode & 0o777, 0o700)
        self.assertEqual((self.base / 'state/ca').stat().st_uid, os.getuid())
        self.assertFalse(list(self.runtime.iterdir()))
        self.assertEqual(self.owned_proxies(), [])
        self.podman('container', 'exists', foreign)

    def start_session(self, command, environment):
        self.ensure_qualification(environment)
        proc = subprocess.Popen([str(self.wrapper), '--container-shell'], cwd=self.project,
                                env=self.env | environment, stdin=subprocess.PIPE,
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        def finish():
            if proc.poll() is None:
                proc.terminate()
                try:
                    proc.communicate(timeout=25)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    proc.communicate()
        self.addCleanup(finish)
        proc.stdin.write(command + '\n')
        proc.stdin.flush()
        ready, _, _ = select.select([proc.stdout], [], [], 20)
        self.assertTrue(ready, 'session readiness timed out')
        self.assertEqual(proc.stdout.readline().strip(), 'network-ready')
        return proc

    def engine_budgets(self):
        """Delegated controllers and process mechanism of the engine, by the launcher's rule."""
        import agent_budgets
        delegated = agent_budgets.delegated(self.podman('info', '--format', '{{.Host.CgroupControllers}}'),
                                            self.podman('info', '--format', '{{.Host.CgroupManager}}'))
        return delegated, agent_budgets.process_mechanism(delegated, self.podman('info', '--format', '{{.Host.Kernel}}'))

    def test_agent_budgets_are_effective_and_lifetime_cleans_owned_proxy(self):
        # Each budget is checked as the engine enforces it: a cgroup limit only for a
        # delegated controller, the process rlimit as fallback (agent_budgets).
        delegated, mechanism = self.engine_budgets()
        _, provider = self.provider_fixture()
        check = """from pathlib import Path
import sys
memory, nano, pids = map(int, sys.argv[1:4])
delegated, mechanism = sys.argv[4].split(','), sys.argv[5]
root = Path('/sys/fs/cgroup')
assert Path('/proc/self/cgroup').read_text() == '0::/\\n'
def limit(name):
    path = root / name
    return path.read_text().split() if path.exists() else ['max']
if 'memory' in delegated:
    assert int(limit('memory.max')[0]) == memory
else:
    assert limit('memory.max') == ['max'], limit('memory.max')
quota, *period = limit('cpu.max')
if 'cpu' in delegated:
    assert int(quota) * 10**9 == nano * int(period[0])
else:
    assert quota == 'max', quota
if mechanism == 'cgroup':
    assert int(limit('pids.max')[0]) == pids
else:
    assert limit('pids.max') == ['max'], limit('pids.max')
if mechanism == 'rlimit':
    line = next(l for l in Path('/proc/self/limits').read_text().splitlines() if l.startswith('Max processes'))
    assert line.split()[2:4] == [str(pids), str(pids)], line
print('AGENT_BUDGETS_OK')
"""
        cases = (({}, (4 << 30, 2 * 10**9, 512)),
                 ({'PI_CONTAINER_MEMORY_LIMIT': '2g', 'PI_CONTAINER_CPU_LIMIT': '0.5',
                   'PI_CONTAINER_PIDS_LIMIT': '384'}, (2 << 30, 500000000, 384)))
        for mode in ('offline', 'provider'):
            for budgets, expected in cases:
                with self.subTest(mode=mode, budgets=budgets):
                    environment = provider | budgets | {'PI_CONTAINER_NETWORK': mode}
                    script = ("python3 - " + ' '.join(map(str, [*expected, ','.join(delegated) or 'none', mechanism]))
                              + " <<'PY'\n" + check + 'PY\n')
                    result = self.shell(script, **environment)
                    self.assert_success(result)
                    self.assertIn('AGENT_BUDGETS_OK', result.stdout)
        environment = provider | {'PI_CONTAINER_NETWORK': 'provider', 'PI_CONTAINER_RUN_TIMEOUT': '4'}
        result = self.shell('sleep 60\n', **environment)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn(f'session lifetime limit reached (4 s); exit status {result.returncode}', result.stderr)
        self.assertEqual(self.owned_proxies(), [])
        self.assertFalse(list(self.runtime.iterdir()))

    def test_proxy_starts_beside_containers_holding_more_than_its_budget(self):
        # set-process-limits-inside-containers: on the rlimit fallback the proxy's process
        # budget is its own. A limit applied at creation would count every container of the
        # user, and the proxy could not start or pass its effective check.
        if self.engine_budgets()[1] != 'rlimit':
            self.skipTest('the engine does not use the process rlimit fallback')
        _, environment = self.provider_fixture()
        crowd = 'pi-test-crowd-' + uuid.uuid4().hex[:12]
        self.addCleanup(subprocess.run, ['podman', 'rm', '--force', '--time', '0', '--ignore', crowd],
                        capture_output=True, timeout=60)
        self.podman('run', '--detach', '--rm', '--name', crowd, '--userns=keep-id', '--user',
                    f'{os.getuid()}:{os.getgid()}', '--network=none', '--entrypoint', '/bin/sh', IMAGE, '-c',
                    'i=0; while [ $i -lt 150 ]; do sleep 600 & i=$((i + 1)); done; wait')
        deadline = time.monotonic() + 60
        # The header line, the shell and its 150 sleeping children.
        while len(self.podman('top', crowd, 'pid').splitlines()) < 152:
            self.assertLess(time.monotonic(), deadline, 'the crowd container did not start its processes')
            time.sleep(0.5)
        result = self.shell('test "$HTTP_PROXY" = http://127.0.0.1:18080\necho PROXY_BESIDE_CROWD_OK\n',
                            **environment)
        self.assert_success(result)
        self.assertIn('PROXY_BESIDE_CROWD_OK', result.stdout)
        self.assertIn('proxy process budget enforced through the process rlimit (128 tasks', result.stderr)
        self.assertFalse(list(self.runtime.iterdir()))

    def test_proxy_death_fails_closed_and_preserves_status(self):
        _, environment = self.provider_fixture()
        command = 'printf "network-ready\\n"; read -r marker; if curl --fail --silent --max-time 3 --cacert cert.pem https://localhost.localdomain:8443/; then exit 42; fi; exit 37'
        proc = self.start_session(command, environment)
        session = next(self.runtime.iterdir()).name
        proxy_id = self.podman('ps', '--no-trunc', '--filter', f'label=io.pi-container.egress={session}', '--format', '{{.ID}}')
        self.assertEqual(len(proxy_id), 64)
        self.podman('rm', '--force', '--time', '0', proxy_id)
        stdout, stderr = proc.communicate('proceed\n', timeout=25)
        self.assertEqual(proc.returncode, 37, stdout + stderr)
        self.assertFalse(list(self.runtime.iterdir()))

    def test_proxy_budgets_at_maximum_streams_and_slow_inspection(self):
        delegated, mechanism = self.engine_budgets()
        _, environment = self.provider_fixture()
        shutil.copyfile(ROOT / 'tests/proxy_budget_fixture.py', self.project / 'budget.py')
        proc = self.start_session('python3 budget.py', environment)
        session = next(self.runtime.iterdir()).name
        proxy_id = self.podman('ps', '--no-trunc', '--filter',
            f'label=io.pi-container.egress={session}', '--format', '{{.ID}}')

        def sample(phase):
            data = json.loads(self.podman('exec', proxy_id, 'python3', '-c',
                "from pathlib import Path; import json; p=Path('/sys/fs/cgroup'); "
                "print(json.dumps({n:(p/n).read_text().strip() for n in "
                "('memory.current','memory.peak','pids.current','pids.max','memory.max') if (p/n).exists()}))"))
            if 'memory' in delegated:
                self.assertEqual(data['memory.max'], str(256 * 1024 * 1024))
                self.assertLessEqual(int(data.get('memory.peak', data['memory.current'])), 256 * 1024 * 1024)
            else:
                self.assertEqual(data.get('memory.max', 'max'), 'max')
            if mechanism == 'cgroup':
                self.assertEqual(data['pids.max'], '128')
                self.assertLessEqual(int(data['pids.current']), 128)
            else:
                self.assertEqual(data.get('pids.max', 'max'), 'max')
            if mechanism == 'rlimit':
                limits = self.podman('exec', proxy_id, 'cat', '/proc/1/limits')
                processes = next(line for line in limits.splitlines() if line.startswith('Max processes'))
                self.assertEqual(processes.split()[2:4], ['128', '128'])
            print('proxy budget evidence: ' + phase + ' ' + json.dumps(data, sort_keys=True), flush=True)

        sample('64-slow-inspections')
        proc.stdin.write('continue\n'); proc.stdin.flush()
        ready, _, _ = select.select([proc.stdout], [], [], 15)
        self.assertTrue(ready, 'matching TLS phase timed out')
        self.assertEqual(proc.stdout.readline().strip(), 'matching-ready')
        sample('64-verified-TLS-connections')
        stdout, stderr = proc.communicate('continue\n', timeout=25)
        self.assertEqual(proc.returncode, 0, stdout + stderr)
        self.assertIn('proxy-budget-64-streams-ok', stdout)
        self.assertFalse(list(self.runtime.iterdir()))

    def test_proxy_resource_exhaustion_is_bounded_and_fails_closed(self):
        delegated, _ = self.engine_budgets()
        _, environment = self.provider_fixture()
        processes = """import errno,subprocess
children=[]
try:
 for _ in range(160):
  try: children.append(subprocess.Popen(['sleep','5']))
  except OSError as error:
   assert error.errno==errno.EAGAIN, error
   print('pids-budget-enforced',flush=True)
   break
 else: raise AssertionError('process budget not enforced')
finally:
 for child in children: child.kill()
 for child in children: child.wait()
"""
        memory = "blocks=[]\nwhile True: blocks.append(bytearray(8*1024*1024))\n"
        for kind, script in (('pids', processes), ('memory', memory)):
            with self.subTest(resource=kind):
                if kind not in delegated:
                    self.skipTest('proxy ' + kind + ' exhaustion needs a delegated cgroup controller')
                proc = self.start_session('printf "network-ready\\n"; read -r marker; '
                    'if curl --fail --silent --max-time 3 --cacert cert.pem https://localhost.localdomain:8443/; '
                    'then exit 42; fi; exit 37', environment)
                session = next(self.runtime.iterdir()).name
                proxy_id = self.podman('ps', '--no-trunc', '--filter',
                    f'label=io.pi-container.egress={session}', '--format', '{{.ID}}')
                result = subprocess.run(['podman', 'exec', proxy_id, 'python3', '-c', script],
                    capture_output=True, text=True, timeout=15)
                if kind == 'pids':
                    self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                    self.assertIn('pids-budget-enforced', result.stdout)
                    events = self.podman('exec', proxy_id, 'cat', '/sys/fs/cgroup/pids.events')
                    self.assertGreater(int(events.split()[1]), 0)
                else:
                    self.assertEqual(result.returncode, 137, result.stdout + result.stderr)
                    running = self.podman('inspect', '--format', '{{.State.Running}}', proxy_id)
                    if running == 'true':
                        events = dict(line.split() for line in self.podman('exec', proxy_id,
                            'cat', '/sys/fs/cgroup/memory.events').splitlines())
                        self.assertGreater(int(events['oom_kill']), 0)
                    else:
                        self.assertEqual(self.podman('inspect', '--format', '{{.State.OOMKilled}}', proxy_id), 'true')
                print('proxy exhaustion evidence: ' + kind + ' enforced within actual session cgroup', flush=True)
                self.podman('rm', '--force', '--time', '0', '--ignore', proxy_id)
                stdout, stderr = proc.communicate('continue\n', timeout=25)
                self.assertEqual(proc.returncode, 37, stdout + stderr)
                self.assertFalse(list(self.runtime.iterdir()))

    def test_concurrent_policies_and_signal_cleanup_are_owned(self):
        _, environment = self.provider_fixture()
        value = json.loads(self.policy_file.read_text())
        value['profiles']['controlled-denied'] = {'authentication': 'custom', 'disable_optional_traffic': True,
            'destinations': [{'host': 'other.test', 'port': 443}]}
        self.policy_file.write_text(json.dumps(value))
        first = self.start_session('printf "network-ready\\n"; trap "" TERM; read -r marker; sleep 300', environment)
        second = self.start_session('printf "network-ready\\n"; read -r marker; if curl --fail --silent --max-time 3 https://localhost.localdomain:8443/; then exit 42; fi; exit 0',
                                    environment | {'PI_CONTAINER_NETWORK_PROFILE': 'controlled-denied',
                                                   'PI_CONTAINER_STATE_DIR': ''})
        self.assertEqual(len(list(self.runtime.iterdir())), 2)
        started = time.monotonic()
        first.send_signal(signal.SIGTERM)
        stdout, stderr = first.communicate(timeout=23)
        self.assertEqual(first.returncode, 143, stdout + stderr)
        self.assertLess(time.monotonic() - started, 22)
        self.assertIsNone(second.poll(), 'another session was removed')
        self.assertEqual(len(list(self.runtime.iterdir())), 1)
        stdout, stderr = second.communicate('proceed\n', timeout=25)
        self.assertEqual(second.returncode, 0, stdout + stderr)
        self.assertIn('policy-denied', stderr)
        self.assertFalse(list(self.runtime.iterdir()))

    def test_interrupted_and_failed_creation_recovers_both_roles(self):
        _, environment = self.provider_fixture()
        self.ensure_qualification(environment)
        shim_dir = self.base / 'bin'
        shim_dir.mkdir()
        shim = shim_dir / 'podman'
        shim.write_text('''#!/usr/bin/env python3
import os,pathlib,subprocess,sys,time
args=sys.argv[1:]
real=os.environ['NETWORK_REAL_PODMAN']
selected=args and args[0]=='create' and any(a.startswith(os.environ['NETWORK_ROLE']+'=') for a in args)
if not selected: os.execv(real,[real,*args])
if os.environ['NETWORK_PHASE']=='before': sys.exit(17)
result=subprocess.run([real,*args],capture_output=True,text=True)
sys.stdout.write(result.stdout); sys.stdout.flush()
sys.stderr.write(result.stderr); sys.stderr.flush()
if result.returncode: sys.exit(result.returncode)
pathlib.Path(os.environ['NETWORK_MARKER']).write_text('created')
if os.environ['NETWORK_PHASE']=='after': sys.exit(17)
time.sleep(300)
''')
        shim.chmod(0o700)
        marker = self.base / 'creation-marker'
        for role in ('io.pi-container.egress', 'io.pi-container.session'):
            for phase in ('before', 'after', 'interrupt'):
                with self.subTest(role=role, phase=phase):
                    marker.unlink(missing_ok=True)
                    values = self.env | environment | {
                        'PATH': str(shim_dir) + ':' + os.environ['PATH'],
                        'NETWORK_REAL_PODMAN': shutil.which('podman'), 'NETWORK_ROLE': role,
                        'NETWORK_PHASE': phase, 'NETWORK_MARKER': str(marker)}
                    proc = subprocess.Popen([str(self.wrapper), '--container-shell'], cwd=self.project,
                                            env=values, stdin=subprocess.DEVNULL,
                                            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
                    try:
                        if phase == 'interrupt':
                            # Before the intercepted create, a provider launch checks its
                            # qualification, which can take most of a minute on a loaded host.
                            deadline = time.monotonic() + 60
                            while not marker.exists() and proc.poll() is None and time.monotonic() < deadline:
                                time.sleep(0.02)
                            self.assertTrue(marker.exists(), 'create interception not reached')
                            proc.terminate()
                        # After the signal, 25 s keep the 20-second shutdown deadline under test.
                        stdout, stderr = proc.communicate(timeout=25 if phase == 'interrupt' else 90)
                    finally:
                        if proc.poll() is None:
                            proc.terminate()
                            try:
                                proc.communicate(timeout=30)
                            except subprocess.TimeoutExpired:
                                proc.kill()
                                proc.communicate(timeout=30)
                    self.assertEqual(proc.returncode, 143 if phase == 'interrupt' else 17, stdout + stderr)
                    self.assertFalse(list(self.runtime.iterdir()))
        self.assertEqual(self.owned_proxies(), [])

    def test_readiness_binds_policy_guard_and_protocol(self):
        _, environment = self.provider_fixture()
        shim_dir = self.base / 'bin'
        shim_dir.mkdir()
        shim = shim_dir / 'podman'
        shim.write_text('''#!/usr/bin/env python3
import os,pathlib,re,subprocess,sys,time
args=sys.argv[1:]; real=os.environ['NETWORK_REAL_PODMAN']
if args and args[0]=='start':
 result=subprocess.run([real,*args],capture_output=True,text=True)
 if result.returncode==0:
  deadline=time.monotonic()+10
  while time.monotonic()<deadline:
   paths=list(pathlib.Path(os.environ['NETWORK_RUNTIME']).glob('session.*/transport/ready'))
   if paths:
    ready=paths[0].read_text(); case=os.environ['NETWORK_READY_CASE']
    if case=='tls': ready=re.sub(r' tls=\\S+', '', ready)
    elif case=='guard': ready=ready.replace(' guard=', ' guard=wrong')
    elif case=='protocol': ready=ready.replace(' mux=1', ' mux=2')
    else: ready='wrong-policy '+ready
    paths[0].write_text(ready); break
   time.sleep(.02)
 sys.stdout.write(result.stdout); sys.stderr.write(result.stderr); sys.exit(result.returncode)
os.execv(real,[real,*args])
''')
        shim.chmod(0o700)
        for case in ('tls', 'guard', 'protocol', 'policy'):
            with self.subTest(identity=case):
                result = self.shell('touch agent-started\n', **environment,
                    PATH=str(shim_dir)+':'+os.environ['PATH'], NETWORK_REAL_PODMAN=shutil.which('podman'),
                    NETWORK_RUNTIME=str(self.runtime), NETWORK_READY_CASE=case)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn('identity mismatch', result.stderr)
                self.assertFalse((self.project / 'agent-started').exists())
                self.assertFalse(list(self.runtime.iterdir()))

    def test_guarded_arguments_stdin_status_and_tty_both_state_modes(self):
        import pty
        context = self.base / 'invocation-fixture'
        context.mkdir()
        source = '''#!/usr/bin/python3
import errno,json,socket,sys
try: socket.socket(socket.AF_UNIX)
except OSError as error: assert error.errno==errno.EPERM
else: raise AssertionError('guard missing')
if sys.argv[1:]==['--version']:
 print('Synthetic invocation fixture'); sys.exit(0)
is_terminal=sys.stdin.isatty()
print(json.dumps({'argv':sys.argv[1:],'stdin':'' if is_terminal else sys.stdin.read(),'tty':is_terminal}),flush=True)
sys.exit(37)
'''
        (context / 'pi-fixture').write_text(source)
        (context / 'Containerfile').write_text(f'FROM {IMAGE}\nUSER root\nRUN rm -f /usr/local/bin/pi\nCOPY pi-fixture /usr/local/bin/pi\nRUN chmod 555 /usr/local/bin/pi\n')
        tag = 'localhost/pi-invocation-test-' + uuid.uuid4().hex
        self.addCleanup(self.podman, 'rmi', '--force', tag)
        self.podman('build', '--pull=never', '--tag', tag, str(context))
        for state in ('', self.env['PI_CONTAINER_STATE_DIR']):
            environment = self.env | {'PI_CONTAINER_STATE_DIR': state, 'PI_CONTAINER_IMAGE': tag}
            self.ensure_qualification(environment)
            arguments = ['-p', 'space value', '', '--help']
            try:
                result = subprocess.run([str(self.wrapper), *arguments], cwd=self.project, env=environment,
                    input='synthetic stdin\n', capture_output=True, text=True, timeout=30)
            except subprocess.TimeoutExpired as error:
                self.fail(f'guarded pipe timed out; isolated={bool(state)} stdout={error.stdout!r} stderr={error.stderr!r}')
            self.assertEqual(result.returncode, 37, result.stdout + result.stderr)
            self.assertEqual(json.loads(result.stdout), {'argv':arguments, 'stdin':'synthetic stdin\n', 'tty':False})
            with self.subTest(terminal=True, isolated=bool(state)):
                reason = terminal_skip_reason(IMAGE)
                if reason:
                    self.skipTest(reason)
                master, slave = pty.openpty()
                proc = None
                try:
                    proc = subprocess.Popen([str(self.wrapper), '--tty-probe'], cwd=self.project, env=environment,
                        stdin=slave, stdout=slave, stderr=subprocess.PIPE)
                    os.close(slave); slave = -1
                    _, error = proc.communicate(timeout=30)
                    self.assertEqual(proc.returncode, 37, error.decode())
                    output = b''
                    while True:
                        try:
                            data = os.read(master, 65536)
                        except OSError:
                            break
                        if not data: break
                        output += data
                    records = [json.loads(line) for line in output.decode().splitlines() if line.startswith('{"argv"')]
                    self.assertEqual(records, [{'argv':['--tty-probe'], 'stdin':'', 'tty':True}])
                finally:
                    if proc is not None and proc.poll() is None:
                        proc.terminate()
                        try:
                            proc.communicate(timeout=25)
                        except subprocess.TimeoutExpired:
                            proc.kill()
                            proc.communicate(timeout=5)
                    if slave >= 0: os.close(slave)
                    os.close(master)

    def test_bootstrap_failure_after_proxy_setup_cleans_owned_resources(self):
        _, environment = self.provider_fixture()
        shim_dir = self.base / 'bin'
        shim_dir.mkdir()
        shim = shim_dir / 'podman'
        shim.write_text("#!/usr/bin/env python3\nimport os,sys\nargs=sys.argv[1:]\nif args and args[0]=='create' and any(a.startswith('io.pi-container.session=') for a in args):\n args[1:1]=['--volume',os.environ['NETWORK_INJECTED_BIND']+':/tmp/untrusted-nested:rw']\nos.execv(os.environ['NETWORK_REAL_PODMAN'],[os.environ['NETWORK_REAL_PODMAN'],*args])\n")
        shim.chmod(0o700)
        result = self.shell('touch agent-started\n', **environment,
            PATH=str(shim_dir) + ':' + os.environ['PATH'],
            NETWORK_REAL_PODMAN=shutil.which('podman'), NETWORK_INJECTED_BIND=str(self.project))
        self.assertEqual(result.returncode, 78, result.stdout + result.stderr)
        self.assertIn('nested private IPC mount validation', result.stderr)
        self.assertFalse((self.project / 'agent-started').exists())
        self.assertFalse(list(self.runtime.iterdir()))

    def test_windows_workspace_ordinary_files_and_restricted_modes(self):
        parent = ROOT / '.test-state'
        parent.mkdir(exist_ok=True)
        project = Path(tempfile.mkdtemp(prefix='guarded-workspace-', dir=parent))
        self.addCleanup(shutil.rmtree, project)
        self.project = project
        for state in ('', self.env['PI_CONTAINER_STATE_DIR']):
            script = "mkdir -p first second; printf persisted >first/file; mv first/file second/file; test \"$(cat second/file)\" = persisted\n"
            script += "python3 - <<'CHECK'\nimport socket,errno\ntry: socket.socket(socket.AF_UNIX)\nexcept OSError as error: assert error.errno == errno.EPERM\nelse: raise AssertionError('Unix socket allowed')\nCHECK\n"
            result = self.shell(script, PI_CONTAINER_STATE_DIR=state)
            self.assert_success(result)
            self.assertEqual((project / 'second/file').read_text(), 'persisted')

    def test_stalled_proxy_cleanup_keeps_exit_status_and_deadline(self):
        _, environment = self.provider_fixture()
        shim_dir = self.base / 'bin'
        shim_dir.mkdir()
        shim = shim_dir / 'podman'
        shim.write_text('''#!/usr/bin/env python3
import os,signal,subprocess,sys,time
args=sys.argv[1:]
real=os.environ['NETWORK_REAL_PODMAN']
if args and args[0]=='rm':
    owner=subprocess.run([real,'inspect','--format','{{index .Config.Labels "io.pi-container.egress"}}',args[-1]],capture_output=True,text=True)
    if owner.returncode==0 and owner.stdout.strip():
        signal.signal(signal.SIGTERM,signal.SIG_IGN)
        time.sleep(300)
os.execv(real,[real,*args])
''')
        shim.chmod(0o700)
        values = environment | {'PATH': str(shim_dir) + ':' + os.environ['PATH'],
                                'NETWORK_REAL_PODMAN': shutil.which('podman')}
        proc = self.start_session('printf "network-ready\\n"; read -r marker; exit 37', values)
        session = next(self.runtime.iterdir()).name
        proxy_id = self.podman('ps', '--no-trunc', '--filter', f'label=io.pi-container.egress={session}', '--format', '{{.ID}}')
        self.addCleanup(self.podman, 'rm', '--force', '--time', '0', '--ignore', proxy_id)
        started = time.monotonic()
        stdout, stderr = proc.communicate('proceed\n', timeout=23)
        self.assertEqual(proc.returncode, 37, stdout + stderr)
        self.assertLess(time.monotonic() - started, 22)
        self.assertIn('failed or timed out', stderr)
        self.assertIn(proxy_id, stderr)

    def test_cli_credentials_and_optional_controls_both_state_modes(self):
        _, environment = self.provider_fixture()
        keys = {'ANTHROPIC_API_KEY': 'synthetic-a', 'OPENAI_API_KEY': 'synthetic-o', 'GEMINI_API_KEY': 'synthetic-g',
                'OPENROUTER_API_KEY': 'synthetic-r', 'GOOGLE_API_KEY': 'synthetic-old',
                'HTTPS_PROXY': 'http://host-proxy.invalid:3128', 'PI_OFFLINE': '0'}
        protected = 'test "$PI_OFFLINE" = 1; test "$PI_SKIP_VERSION_CHECK" = 1; test "$PI_TELEMETRY" = 0; test "$PI_CONTAINER_CONFIG_DIR" = /pi-home/.pi'
        for state in ('', self.env['PI_CONTAINER_STATE_DIR']):
            for profile, credential in (('controlled-test', None), ('anthropic-api', 'ANTHROPIC_API_KEY'),
                                        ('openai-api', 'OPENAI_API_KEY'), ('gemini-api', 'GEMINI_API_KEY'),
                                        ('openrouter-api', 'OPENROUTER_API_KEY')):
                with self.subTest(state=state, profile=profile):
                    checks = [f'test "${{{name}}}" = {value}' if name == credential else f'test -z "${{{name}+x}}"'
                              for name, value in keys.items() if name not in ('HTTPS_PROXY', 'PI_OFFLINE')]
                    checks.append('test "$HTTPS_PROXY" = http://127.0.0.1:18080')
                    result = self.shell('\n'.join(checks) + '\n' + protected + '\n', **(environment | keys | {
                        'PI_CONTAINER_STATE_DIR': state, 'PI_CONTAINER_NETWORK_PROFILE': profile}))
                    self.assert_success(result)
            values = self.env | environment | {'PI_CONTAINER_STATE_DIR': state}
            result = subprocess.run([str(self.wrapper), '--version'], cwd=self.project, env=values, input='',
                                    text=True, capture_output=True, timeout=60)
            self.assert_success(result)
            self.assertEqual(result.stdout.strip(), '1.5.2')
            self.assertFalse(list(self.runtime.iterdir()))

    def test_actual_pi_bash_tool_with_synthetic_chat_api(self):
        context, environment = self.provider_fixture()
        # The controlled custom profile and fixture CA authorize only this local
        # synthetic API. No account state, real key or external model is involved.
        models = json.dumps({'providers': {'fixture': {
            'baseUrl': 'https://localhost.localdomain:8443/v1', 'api': 'openai-completions',
            'apiKey': 'synthetic-not-a-real-key',
            'compat': {'supportsDeveloperRole': False, 'supportsReasoningEffort': False},
            'models': [{'id': 'fixture-model'}]}}})
        for state in ('', self.env['PI_CONTAINER_STATE_DIR']):
            with self.subTest(state=state):
                sentinel = self.project / 'pi-tool-sentinel'
                sentinel.unlink(missing_ok=True)
                script = ("mkdir -p \"$HOME/.pi/agent\"\nprintf '%s' '" + models + "' > \"$HOME/.pi/agent/models.json\"\n"
                          "pi -p --provider fixture --model fixture-model fixture-tool-operation </dev/null\n"
                          "rm -f \"$HOME/.pi/agent/models.json\"\n"
                          "test \"$(cat pi-tool-sentinel)\" = actual-pi-tool-ok\n")
                result = self.shell(script, **environment, PI_CONTAINER_STATE_DIR=state,
                    PI_CONTAINER_TRUST_HOST_CA='1', PI_CONTAINER_CA_BUNDLE=str(context / 'cert.pem'))
                self.assert_success(result)
                self.assertIn('fixture-tool-complete', result.stdout + result.stderr)
                self.assertEqual(sentinel.read_text(), 'actual-pi-tool-ok')

    def test_pi_tui_starts_and_quits_under_the_guard(self):
        import pty
        reason = terminal_skip_reason(IMAGE)
        if reason:
            self.skipTest(reason)
        for state in ('', self.env['PI_CONTAINER_STATE_DIR']):
            with self.subTest(state=state):
                environment = self.env | {'PI_CONTAINER_STATE_DIR': state}
                self.ensure_qualification(environment)
                master, slave = pty.openpty()
                proc = subprocess.Popen([str(self.wrapper)], cwd=self.project, env=environment | {'TERM': 'xterm-256color'},
                                        stdin=slave, stdout=slave, stderr=subprocess.PIPE)
                os.close(slave)
                output = b''
                def pump(seconds):
                    nonlocal output
                    deadline = time.monotonic() + seconds
                    while time.monotonic() < deadline:
                        ready, _, _ = select.select([master], [], [], 0.2)
                        if not ready:
                            continue
                        try:
                            data = os.read(master, 65536)
                        except OSError:
                            return
                        if not data:
                            return
                        output += data
                        if b'\x1b[6n' in data:
                            os.write(master, b'\x1b[24;1R')
                try:
                    pump(15)
                    for ch in b'/quit':
                        os.write(master, bytes([ch]))
                        time.sleep(0.1)
                    os.write(master, b'\r')
                    _, error = proc.communicate(timeout=30)
                    pump(1)
                finally:
                    if proc.poll() is None:
                        proc.terminate()
                        try:
                            proc.communicate(timeout=25)
                        except subprocess.TimeoutExpired:
                            proc.kill()
                            proc.communicate(timeout=5)
                    os.close(master)
                self.assertEqual(proc.returncode, 0, error.decode() + output.decode(errors='replace')[-2000:])
                self.assertIn('network mode=offline', error.decode())
                self.assertGreater(len(output), 1000)

    def test_unsafe_policy_and_missing_proxy_image_fail_before_agent(self):
        _, environment = self.provider_fixture()
        self.policy_file.chmod(0o666)
        result = self.shell('touch agent-started\n', qualify=False, **environment)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('policy preflight failed', result.stderr)
        self.assertFalse((self.project / 'agent-started').exists())
        self.policy_file.chmod(0o600)
        result = self.shell('touch agent-started\n', qualify=False, **(environment | {
            'PI_CONTAINER_EGRESS_IMAGE': 'sha256:' + '0' * 64}))
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('proxy image is absent', result.stderr)
        self.assertFalse((self.project / 'agent-started').exists())
        self.assertFalse(list(self.runtime.iterdir()))

    def test_tampered_bootstrap_fails_before_application(self):
        guard = self.install / 'network/bin/sandbox-egress-guard'
        guard.chmod(0o700)
        with guard.open('ab') as output:
            output.write(b'tampered')
        result = self.shell('touch agent-started\n', qualify=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('bootstrap digest mismatch', result.stderr)
        self.assertFalse((self.project / 'agent-started').exists())
        self.assertFalse(list(self.runtime.iterdir()))

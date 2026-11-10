"""Opt-in real WSL setup acceptance; no credentials or user-service mutations."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
import uuid

from test_setup import pty_run

ROOT = Path(__file__).resolve().parents[1]
VERSION = (ROOT / '.version').read_text().strip()


@unittest.skipUnless(os.environ.get('SANDBOX_RUNTIME_TESTS') == '1', 'requires real rootless WSL engine')
class SetupRuntime(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='setup-acceptance-', dir=os.environ['SANDBOX_TEST_STATE_ROOT'])
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        self.home = self.base / 'home'
        self.home.mkdir(mode=0o700)
        self.workspace = self.base / 'workspace with spaces'
        self.workspace.mkdir()
        self.root = self.base / 'installation'
        self.command = self.base / 'bin/pi-container'
        self.env = {'PATH': os.environ['PATH'], 'HOME': str(self.home),
                    'CONTAINER_HOST': os.environ['CONTAINER_HOST']}
        self.tags = set()
        self.addCleanup(self.clean_tags)
        self.real_podman = shutil.which('podman')
        self.proxy_selection = self.base / 'test-proxy-image'
        self.proxy_selection.write_text(self.build_proxy(ROOT / 'network'))
        prepared_proxy = self.proxy_selection.read_text()
        prepared_runtime = subprocess.check_output([self.real_podman, 'image', 'inspect',
            '--format', '{{.Id}}', os.environ.get('PI_CONTAINER_IMAGE', 'localhost/pi-container:latest')],
            env=self.env, text=True).strip()
        # Route prepared lookups to the requested runtime and disposable proxy.
        # Do not retag or replace any operator-owned image.
        shim_dir = self.base / 'test-engine'
        shim_dir.mkdir()
        shim = shim_dir / 'podman'
        shim.write_text('#!/usr/bin/env python3\nimport os,sys\nfrom pathlib import Path\n'
            + 'args=sys.argv[1:]\n'
            + "if args[:2] == ['image','exists'] and args[-1] in " + repr(('localhost/pi-container:latest', prepared_runtime)) + ":\n"
            + ' sys.exit(1 if Path(' + repr(str(self.base / 'withhold-runtime')) + ').exists() else 0)\n'
            + "if args[:2] == ['image','inspect'] and args[-1] in " + repr(('localhost/pi-container:latest', prepared_runtime)) + ":\n"
            + ' print(' + repr(prepared_runtime) + '); sys.exit(0)\n'
            + "if args[:2] == ['image','exists'] and args[-1] in " + repr(('localhost/pi-egress:local', prepared_proxy)) + ": sys.exit(0)\n"
            + "if args[:2] == ['image','inspect'] and args[-1] in " + repr(('localhost/pi-egress:local', prepared_proxy)) + ":\n"
            + ' print(Path(' + repr(str(self.proxy_selection)) + ').read_text().strip()); sys.exit(0)\n'
            + 'os.execv(' + repr(self.real_podman) + ',[' + repr(self.real_podman) + ',*args])\n')
        shim.chmod(0o700)
        self.env['PATH'] = str(shim_dir) + ':' + self.env['PATH']

    def build_proxy(self, context):
        tag = 'localhost/pi-setup-tls-test:' + uuid.uuid4().hex
        self.tags.add(tag)
        result = subprocess.run([self.real_podman, 'build', '--pull=never', '--tag', tag,
                                 '--file', str(context / 'Containerfile'), str(context)],
                                env=self.env, capture_output=True, text=True, timeout=60)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        return subprocess.check_output([self.real_podman, 'image', 'inspect', '--format', '{{.Id}}', tag],
                                       env=self.env, text=True).strip()

    def clean_tags(self):
        for path in self.root.glob('releases/*/setup.json'):
            self.tags.add(json.loads(path.read_text())['image'])
        for tag in self.tags:
            subprocess.run(['podman', 'image', 'rm', tag], capture_output=True, timeout=30)

    def answers(self, mode, ca=False, method='openrouter'):
        answers = [('Protected native installation directory', str(self.root)), ('Network mode', mode)]
        if mode == 'provider':
            answers += [('Acknowledge that allowed provider hosts', 'yes')]
        if mode != 'offline':
            answers += [('Authentication method', method)]
        answers += [('State mode', 'isolated'), ('Private isolated state directory', str(self.base / 'state')),
                    ('Delegate the host Podman API', 'no'), ('Enable Pi permission bypass', 'no'),
                    ('Use parent-directory worktree scope', 'no'), ('Agent memory limit', ''),
                    ('Agent CPU limit', ''), ('Agent process limit', ''), ('Session lifetime in seconds', ''),
                    ('Trust a host CA bundle', 'yes' if ca else 'no')]
        if ca:
            answers += [('CA bundle file', '/etc/ssl/certs/ca-certificates.crt')]
        answers += [('Managed launch command path', str(self.command)),
                    ('Podman launch endpoint', self.env['CONTAINER_HOST'])]
        if mode == 'provider':
            answers += [('Private native egress runtime directory', str(self.base / 'egress'))]
        answers += [('Refresh prepared images', 'no'), ('Apply this installation', 'yes')]
        return answers

    def setup_run(self, mode, source=ROOT, login_prompt=True, ca=False, method='openrouter'):
        answers = self.answers(mode, ca=ca, method=method)
        # API-key methods only: setup reports authentication pending without a login prompt.
        return pty_run(['bash', str(source / 'pi-container.sh'), '--container-setup'],
                       self.env, self.workspace, answers, timeout=180)

    def test_fresh_provider_new_terminal_rerun_offline_and_failed_update(self):
        # Regression: a caller-owned 0755 root from manual installation is
        # protected but not private. Preserve it without chmod or replacement.
        self.root.mkdir(mode=0o755)
        manual = self.root / 'manual-install-marker'
        manual.write_text('preserve existing installation')
        code, output = self.setup_run('provider', ca=True)
        self.assertEqual(code, 0, output)
        self.assertEqual(self.root.stat().st_mode & 0o777, 0o755)
        self.assertEqual(manual.read_text(), 'preserve existing installation')
        self.assertIn('Sandbox: ready', output)
        self.assertIn('Authentication: pending', output)
        self.assertIn('Sandbox qualification: locally-qualified', output)
        release = (self.root / 'current').resolve()
        reports = list((release / 'qualification').glob('*.json'))
        self.assertEqual(len(reports), 1)
        report = reports[0]
        original_report = report.read_bytes()
        self.assertEqual(json.loads(original_report)['identity']['mode'], 'provider')
        self.assertEqual(report.stat().st_mode & 0o777, 0o600)
        first = json.loads((release / 'setup.json').read_text())
        self.tags.add(first['image'])
        self.assertEqual(first['network'], 'provider')
        guard = (release / 'network/bin/sandbox-egress-guard').read_bytes()
        # No exported wrapper/network settings in this fresh launch environment.
        result = subprocess.run([str(self.command), '--version'], cwd=self.workspace,
                                env={'PATH': self.env['PATH'], 'HOME': self.env['HOME']},
                                stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=60)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn(VERSION, result.stdout)
        self.assertIn('enforced revision=abi3-seccomp-mux-v1', result.stderr)
        self.assertRegex(result.stderr, r'(INFO\[\d+\] Should restart: false|level=info msg="Should restart: false")')
        self.assertNotRegex(result.stderr, r'ERRO\[\d+\] Should restart: false')
        self.assertNotIn('level=error msg="Should restart: false"', result.stderr)
        # An otherwise complete candidate with historical proxy readiness must
        # fail smoke before changing the managed current release.
        old_source = self.base / 'old-proxy-source'
        shutil.copytree(release, old_source)
        proxy_source = old_source / 'network/proxy.py'
        proxy_source.write_text(proxy_source.read_text().replace("' mux=1 tls=' + ENFORCEMENT", "' mux=1'"))
        current_proxy = self.proxy_selection.read_text()
        self.proxy_selection.write_text(self.build_proxy(old_source / 'network'))
        old_candidates = set(self.root.joinpath('releases').iterdir())
        code, output = self.setup_run('provider', source=old_source, login_prompt=False)
        self.assertNotEqual(code, 0, output)
        self.assertIn('setup incomplete', output)
        self.assertEqual((self.root / 'current').resolve(), release)
        self.assertEqual(report.read_bytes(), original_report)
        self.assertEqual(set(self.root.joinpath('releases').iterdir()), old_candidates)
        self.proxy_selection.write_text(current_proxy)
        for line in output.splitlines():
            if 'Prepared runtime image tag: ' in line:
                self.tags.add(line.split('Prepared runtime image tag: ', 1)[1].strip())
        code, output = self.setup_run('provider')
        self.assertEqual(code, 0, output)
        second = (self.root / 'current').resolve()
        self.assertNotEqual(release, second)
        self.assertEqual((second / 'network/bin/sandbox-egress-guard').read_bytes(), guard)
        self.assertNotIn('Packaged guard', output)
        self.assertTrue(release.exists())
        self.assertEqual(report.read_bytes(), original_report)
        self.assertTrue(list((second / 'qualification').glob('*.json')))
        code, output = self.setup_run('offline')
        self.assertEqual(code, 0, output)
        self.assertIn('Authentication: not applicable', output)
        active = (self.root / 'current').resolve()
        offline_reports = list((active / 'qualification').glob('*.json'))
        self.assertEqual(len(offline_reports), 1)
        offline_report = offline_reports[0].read_bytes()
        self.assertEqual(json.loads(offline_report)['identity']['mode'], 'offline')
        self.assertEqual((active / 'network/bin/sandbox-egress-guard').read_bytes(), guard)
        # A reviewed update with an intentionally failing smoke must not activate.
        source = self.base / 'failed-source'
        shutil.copytree(active, source)
        (source / 'setup/smoke.py').write_text('import sys\nsys.exit(42)\n')
        before = set(self.root.joinpath('releases').iterdir())
        code, output = self.setup_run('offline', source=source)
        self.assertNotEqual(code, 0, output)
        self.assertEqual((self.root / 'current').resolve(), active)
        self.assertEqual(offline_reports[0].read_bytes(), offline_report)
        self.assertEqual(set(self.root.joinpath('releases').iterdir()), before)
        self.assertFalse((self.root / '.setup.lock').exists())
        # Capture only setup-owned tags from failure reporting for cleanup.
        for line in output.splitlines():
            if 'Prepared runtime image tag: ' in line:
                self.tags.add(line.split('Prepared runtime image tag: ', 1)[1].strip())

    def test_unrestricted_fresh_setup_and_shell(self):
        code, output = self.setup_run('unrestricted')
        self.assertEqual(code, 0, output)
        release = (self.root / 'current').resolve()
        self.assertFalse((release / 'network/bin').exists())
        result = subprocess.run([str(self.command), '--container-shell'], cwd=self.workspace,
                                env={'PATH': self.env['PATH'], 'HOME': self.env['HOME']},
                                input='printf SETUP_SHELL_OK\n', capture_output=True, text=True, timeout=60)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn('SETUP_SHELL_OK', result.stdout)
        # Move the managed command through the actual wizard, then verify that
        # no obsolete host entry point is left behind in the former workspace.
        previous_command = self.command
        self.command = self.base / 'relocated-bin/pi-container'
        code, output = self.setup_run('unrestricted')
        self.assertEqual(code, 0, output)
        self.assertFalse(previous_command.exists())
        result = subprocess.run([str(self.command), '--version'], cwd=previous_command.parent,
                                env={'PATH': self.env['PATH'], 'HOME': self.env['HOME']},
                                stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=60)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn(VERSION, result.stdout)

    def test_wrapper_built_runtime_passes_the_staleness_check(self):
        # With no reusable runtime image, setup builds through the installed
        # wrapper (install.runtime_build = wrapper) under its own maintenance.
        (self.base / 'withhold-runtime').touch()
        code, output = self.setup_run('unrestricted')
        for line in output.splitlines():
            if 'Prepared runtime image tag: ' in line:
                self.tags.add(line.split('Prepared runtime image tag: ', 1)[1].strip())
        self.assertEqual(code, 0, output)
        self.assertIn('Runtime build requested', output)
        self.assertIn('Building Pi v' + VERSION + ' image', output)
        release = (self.root / 'current').resolve()
        saved = json.loads((release / 'setup.json').read_text())
        self.tags.add(saved['image'])
        label = subprocess.check_output([self.real_podman, 'image', 'inspect', '--format',
                                         '{{index .Labels "build-inputs-hash"}}', saved['image']],
                                        env=self.env, text=True).strip()
        self.assertRegex(label, '^[0-9a-f]{64}$')
        result = subprocess.run([str(self.command), '--version'], cwd=self.workspace,
                                env={'PATH': self.env['PATH'], 'HOME': self.env['HOME']},
                                stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=60)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn(VERSION, result.stdout)
        self.assertNotIn('is stale', result.stderr)
        self.assertNotIn('PI_CONTAINER_YOLO', result.stderr)

    def test_provider_gemini_transcript(self):
        # Operator-style provider run with the gemini method and no key set.
        code, output = self.setup_run('provider', method='gemini')
        self.assertEqual(code, 0, output)
        for host in ('api.anthropic.com', 'api.openai.com', 'generativelanguage.googleapis.com', 'openrouter.ai'):
            self.assertIn(host, output)
        self.assertIn('Acknowledge that allowed provider hosts', output)
        self.assertIn('maintenance', output)
        self.assertIn('Sandbox: ready', output)
        self.assertIn('Authentication: pending', output)
        self.assertIn('GEMINI_API_KEY', output)
        self.assertNotIn('PI_CONTAINER_YOLO', output)
        release = (self.root / 'current').resolve()
        saved = json.loads((release / 'setup.json').read_text())
        self.tags.add(saved['image'])
        self.assertEqual(saved['network'], 'provider')
        self.assertEqual(saved['auth'], 'gemini')
        result = subprocess.run([str(self.command), '--version'], cwd=self.workspace,
                                env={'PATH': self.env['PATH'], 'HOME': self.env['HOME']},
                                stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=60)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn(VERSION, result.stdout)
        self.assertNotIn('PI_CONTAINER_YOLO', result.stderr)
        # Keep the transcript for the validation record (the checkout is mounted rw).
        (ROOT / '.test-state').mkdir(exist_ok=True)
        (ROOT / '.test-state/setup-gemini-transcript.txt').write_text(output)

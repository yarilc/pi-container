"""Synthetic toolchain library tests: native disposable storage and a fake engine."""
import contextlib
import hashlib
import io
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import sys
import tarfile
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
from sandbox_profile import PROFILE, ROOT, env as name, test_setting
sys.path.insert(0, str(ROOT / 'setup'))
import common  # noqa: E402
import toolchains  # noqa: E402

BASE = toolchains.base_reference(ROOT)
DIGEST = 'docker.io/library/example@sha256:' + 'a' * 64


def tar_bytes(entries, mode='w'):
    """entries: (name, kind, data_or_target, file_mode)."""
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode=mode) as archive:
        for entry_name, kind, data, file_mode in entries:
            info = tarfile.TarInfo(entry_name)
            info.mode = file_mode
            if kind == 'dir':
                info.type = tarfile.DIRTYPE
                archive.addfile(info)
            elif kind == 'file':
                info.size = len(data)
                archive.addfile(info, io.BytesIO(data))
            elif kind == 'symlink':
                info.type = tarfile.SYMTYPE
                info.linkname = data
                archive.addfile(info)
            elif kind == 'hardlink':
                info.type = tarfile.LNKTYPE
                info.linkname = data
                archive.addfile(info)
            elif kind == 'device':
                info.type = tarfile.CHRTYPE
                archive.addfile(info)
            elif kind == 'fifo':
                info.type = tarfile.FIFOTYPE
                archive.addfile(info)
    return buffer.getvalue()


def tool_archive(prefix='tool-1.0', command='tool', extra=()):
    script = b'#!/bin/sh\necho tool-ok\n'
    return tar_bytes([(prefix, 'dir', None, 0o755), (prefix + '/bin', 'dir', None, 0o755),
                      (prefix + '/bin/' + command, 'file', script, 0o755),
                      (prefix + '/README', 'file', b'readme\n', 0o644), *extra])


class Engine:
    """Fake engine: image presence, pulls, owned containers, tar streams and checks."""

    def __init__(self, image_tar=b'', check_status=0, exists=True):
        self.calls = []
        self.image_tar = image_tar
        self.check_status = check_status
        self.exists = exists

    def run(self, args, timeout=None):
        self.calls.append(list(args))
        output = ''
        status = 0
        if args[:2] == ['image', 'exists']:
            status = 0 if self.exists else 1
        elif args[:2] == ['image', 'inspect']:
            output = 'sha256:' + 'b' * 64 + '\n'
        elif args[:1] == ['pull']:
            self.exists = True
        elif args[:1] == ['create']:
            output = 'c' * 64 + '\n'
        elif args[:1] == ['run']:
            status = self.check_status
            output = 'check output\n'
        return subprocess.CompletedProcess(['podman', *args], status, output, '')

    @contextlib.contextmanager
    def stream(self, args):
        self.calls.append(list(args))
        yield io.BytesIO(self.image_tar)


class ToolchainTests(unittest.TestCase):
    def setUp(self):
        self.base = Path(tempfile.mkdtemp(dir=test_setting('TEST_TMPDIR'))).resolve()
        os.chmod(self.base, 0o700)
        self.addCleanup(shutil.rmtree, self.base, True)
        self.library = self.base / 'library'
        self.env = {'HOME': str(self.base / 'home'), name('IMAGE'): 'localhost/runtime:test'}
        self.engine = Engine()
        for target, value in (('run', self.engine.run), ('stream', self.engine.stream)):
            patcher = patch.object(toolchains, target, side_effect=value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def recipe(self, **values):
        archive = self.base / ('tool-' + values.get('name', 'tool') + '.tar')
        archive.write_bytes(values.pop('archive_bytes', tool_archive()))
        recipe = {'schema': 1, 'name': 'tool', 'version': '1.0',
                  'source': {'archive': str(archive), 'sha256': hashlib.sha256(archive.read_bytes()).hexdigest(),
                             'strip_components': 1},
                  'path': ['bin'], 'env': {'TOOL_HOME': {'toolchain': ''}}, 'requires': [], 'notes': [],
                  'check': ['tool'], 'default': True}
        recipe.update(values)
        path = self.base / (recipe['name'] + '.json')
        path.write_text(json.dumps(recipe))
        return path

    def add(self, **values):
        return toolchains.add(self.library, self.recipe(**values), self.env)

    def index(self):
        return json.loads((self.library / 'index.json').read_text())

    def assert_rejected(self, message, **values):
        before = sorted(p.name for p in self.library.iterdir()) if self.library.exists() else None
        with self.assertRaises(common.SetupError) as raised:
            self.add(**values)
        self.assertIn(message, str(raised.exception))
        after = sorted(p.name for p in self.library.iterdir()) if self.library.exists() else None
        if before is not None:
            self.assertEqual(before, after)
        return raised.exception

    # Library location and safety

    def test_default_and_override_location(self):
        home = self.base / 'home'
        self.assertEqual(toolchains.library_path({'HOME': str(home)}), home / '.local/share/sandbox-toolchains')
        self.assertEqual(toolchains.library_path({'HOME': str(home), 'XDG_DATA_HOME': str(self.base / 'data')}),
                         self.base / 'data/sandbox-toolchains')
        override = {'HOME': str(home), name('TOOLCHAINS_DIR'): str(self.base / 'custom')}
        self.assertEqual(toolchains.library_path(override), self.base / 'custom')
        for invalid in ('relative', str(self.base / 'a:b'), str(self.base) + '/x\ty'):
            with self.subTest(invalid=invalid), self.assertRaises(common.SetupError):
                toolchains.library_path({'HOME': str(home), name('TOOLCHAINS_DIR'): invalid})

    def test_library_is_created_private_and_checked(self):
        path = toolchains.prepare_library(self.library, avoid=())
        self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o700)
        os.chmod(self.library, 0o750)
        with self.assertRaises(common.SetupError):
            toolchains.prepare_library(self.library, avoid=())
        os.chmod(self.library, 0o700)
        workspace = self.base / 'workspace'
        workspace.mkdir()
        for avoid in (self.library, self.library / 'inside', self.base):
            with self.subTest(avoid=avoid), self.assertRaises(common.SetupError) as raised:
                toolchains.prepare_library(self.library, avoid=(avoid,))
            self.assertIn(str(self.library), str(raised.exception))
        toolchains.prepare_library(self.library, avoid=(workspace,))

    # Recipes and sources

    def test_recipe_validation(self):
        cases = {
            'unknown key': ({'extra': 1}, 'unknown'),
            'bad name': ({'name': 'Bad Name'}, 'name'),
            'absolute path entry': ({'path': ['/bin']}, 'relative'),
            'parent path entry': ({'path': ['../bin']}, 'relative'),
            'tag-only image': ({'source': {'image': 'docker.io/library/example:21', 'path': '/opt'}}, 'digest'),
            'relative image path': ({'source': {'image': DIGEST, 'path': 'opt'}}, 'absolute'),
            'newline literal': ({'env': {'GOCACHE': {'value': '/tmp/a\nb'}}}, 'control'),
            'nul literal': ({'env': {'GOCACHE': {'value': '/tmp/a\0b'}}}, 'control'),
            'protected variable': ({'env': {'HOME': {'value': '/tmp'}}}, 'protected'),
            'prefix variable': ({'env': {PROFILE.env('IMAGE'): {'value': 'x'}}}, 'protected'),
            'loader variable': ({'env': {'LD_PRELOAD': {'value': '/tmp/x.so'}}}, 'protected'),
            'proxy variable': ({'env': {'https_proxy': {'value': 'http://x'}}}, 'protected'),
            'xdg variable': ({'env': {'XDG_DATA_HOME': {'value': '/tmp/data'}}}, 'protected'),
            'bad env form': ({'env': {'TOOL_HOME': ''}}, 'env'),
            'empty check': ({'check': []}, 'check'),
            'default not boolean': ({'default': 'yes'}, 'default'),
        }
        for label, (values, message) in cases.items():
            with self.subTest(label=label):
                self.assert_rejected(message, **values)

    def test_archive_checksum_mismatch(self):
        recipe = json.loads(self.recipe().read_text())
        recipe['source']['sha256'] = '0' * 64
        path = self.base / 'mismatch.json'
        path.write_text(json.dumps(recipe))
        with self.assertRaises(common.SetupError) as raised:
            toolchains.add(self.library, path, self.env)
        self.assertIn('SHA-256', str(raised.exception))
        self.assertFalse((self.library / 'tool').exists())

    def test_unsafe_members_are_rejected(self):
        cases = {
            'absolute': ('/etc/passwd', 'file', b'x', 0o644),
            'parent': ('tool-1.0/../escape', 'file', b'x', 0o644),
            'device': ('tool-1.0/dev', 'device', None, 0o644),
            'fifo': ('tool-1.0/fifo', 'fifo', None, 0o644),
            'absolute link': ('tool-1.0/bin/link', 'symlink', '/usr/bin/env', 0o777),
            'escaping link': ('tool-1.0/bin/link', 'symlink', '../../../outside', 0o777),
            'escaping hardlink': ('tool-1.0/hard', 'hardlink', 'other/file', 0o644),
        }
        for label, entry in cases.items():
            with self.subTest(label=label):
                self.assert_rejected('unsafe', archive_bytes=tool_archive(extra=(entry,)))
                self.assertFalse(any(p.name.startswith('.staging') for p in self.library.iterdir()))

    def test_extracted_permissions_and_relative_links(self):
        extra = (('tool-1.0/bin/setuid', 'file', b'#!/bin/sh\n', 0o6755),
                 ('tool-1.0/bin/alias', 'symlink', 'tool', 0o777),
                 ('tool-1.0/same', 'hardlink', 'tool-1.0/README', 0o644))
        self.add(archive_bytes=tool_archive(extra=extra))
        root = self.library / 'tool'
        mode = (root / 'bin/setuid').stat().st_mode
        self.assertFalse(mode & (stat.S_ISUID | stat.S_ISGID))
        self.assertTrue(mode & stat.S_IXUSR)
        self.assertTrue((root / 'bin/tool').stat().st_mode & stat.S_IXUSR)
        self.assertEqual(os.readlink(root / 'bin/alias'), 'tool')
        self.assertEqual((root / 'same').read_text(), 'readme\n')
        for path in root.rglob('*'):
            self.assertEqual(path.lstat().st_uid, os.getuid(), str(path))

    def test_image_source_requires_maintenance_to_pull(self):
        self.engine.exists = False
        self.engine.image_tar = tool_archive(prefix='tool')
        recipe = {'source': {'image': DIGEST, 'path': '/opt/tool'}}
        self.assert_rejected(name('MAINTENANCE'), **recipe)
        self.assertFalse(any(call[:1] == ['pull'] for call in self.engine.calls))
        self.env[name('MAINTENANCE')] = '1'
        self.add(**recipe)
        self.assertIn(['pull', DIGEST], self.engine.calls)
        create = next(call for call in self.engine.calls if call[:1] == ['create'])
        self.assertIn('--network=none', create)
        self.assertIn(['cp', 'c' * 64 + ':/opt/tool', '-'], self.engine.calls)
        self.assertIn(['rm', '--force', 'c' * 64], self.engine.calls)
        manifest = json.loads((self.library / 'tool/toolchain.json').read_text())
        self.assertEqual(manifest['source'], {'image': DIGEST, 'path': '/opt/tool'})

    def test_owned_container_removed_after_failed_copy(self):
        self.engine.image_tar = tar_bytes([('tool/../x', 'file', b'x', 0o644)])
        self.assert_rejected('unsafe', source={'image': DIGEST, 'path': '/opt/tool'})
        self.assertIn(['rm', '--force', 'c' * 64], self.engine.calls)

    # Verification

    def test_check_runs_hardened_without_network(self):
        self.add()
        run = next(call for call in self.engine.calls if call[:1] == ['run'])
        for flag in ('--rm', '--network=none', '--read-only', '--userns=keep-id', '--cap-drop=all',
                     '--security-opt=no-new-privileges', '--pull=never'):
            self.assertIn(flag, run)
        self.assertIn(f'{os.getuid()}:{os.getgid()}', run)
        self.assertIn('localhost/runtime:test', run)
        mounts = [run[i + 1] for i, arg in enumerate(run) if arg == '--volume']
        self.assertTrue(any(m.endswith(':/toolchains/tool:ro,nosuid,nodev') for m in mounts), mounts)
        self.assertEqual(run[-1], 'tool')
        manifest = json.loads((self.library / 'tool/toolchain.json').read_text())
        self.assertEqual(manifest['verified']['base'], BASE)
        self.assertRegex(manifest['verified']['date'], r'^\d{4}-\d{2}-\d{2}$')

    def test_failed_check_leaves_library_unchanged(self):
        self.engine.check_status = 1
        error = self.assert_rejected('check')
        self.assertIn('check output', str(error))
        self.assertFalse((self.library / 'tool').exists())

    def test_missing_runtime_image_fails_without_build(self):
        self.engine.exists = False
        self.assert_rejected('runtime image')
        self.assertFalse(any(call[:1] in (['build'], ['pull']) for call in self.engine.calls))

    def test_verify_updates_record(self):
        self.add()
        manifest = self.library / 'tool/toolchain.json'
        value = json.loads(manifest.read_text())
        value['verified']['base'] = 'docker.io/library/other@sha256:' + 'd' * 64
        manifest.write_text(json.dumps(value))
        toolchains.verify(self.library, None, self.env)
        self.assertEqual(json.loads(manifest.read_text())['verified']['base'], BASE)
        self.assertEqual(self.index()['toolchains'][0]['verified']['base'], BASE)

    # Library changes, dependencies and conflicts

    def test_replace_and_remove_are_atomic(self):
        self.add()
        old = (self.library / 'tool/bin/tool').stat().st_ino
        self.add(version='2.0')
        self.assertNotEqual((self.library / 'tool/bin/tool').stat().st_ino, old)
        self.assertEqual(self.index()['toolchains'][0]['version'], '2.0')
        self.assertFalse(any(p.name.startswith(('.staging', '.old')) for p in self.library.iterdir()))
        toolchains.remove(self.library, 'tool')
        self.assertFalse((self.library / 'tool').exists())
        self.assertEqual(self.index()['toolchains'], [])
        with self.assertRaises(common.SetupError):
            toolchains.remove(self.library, 'tool')

    def test_changes_take_the_library_lock(self):
        self.add()
        with patch.object(toolchains.fcntl, 'flock', wraps=toolchains.fcntl.flock) as flock:
            self.add(name='other', path=['bin'], env={}, default=False)
            toolchains.remove(self.library, 'other')
        self.assertTrue(all(call.args[1] == toolchains.fcntl.LOCK_EX for call in flock.call_args_list))
        self.assertGreaterEqual(flock.call_count, 2)

    def test_requires(self):
        self.assert_rejected('missing', name='maven', requires=['java'])
        self.add(name='java', env={'JAVA_HOME': {'toolchain': ''}}, default=False,
                 archive_bytes=tool_archive(command='java'), check=['java'])
        self.assert_rejected('default', name='maven', requires=['java'], env={},
                             archive_bytes=tool_archive(command='mvn'), check=['mvn'])
        self.add(name='maven', requires=['java'], env={}, default=False,
                 archive_bytes=tool_archive(command='mvn'), check=['mvn'])
        script = (self.library / 'maven/env.sh').read_text()
        self.assertIn('. /toolchains/java/env.sh', script)
        self.assertLess(script.index('/toolchains/java/env.sh'), script.index("PATH='/toolchains/maven/bin'"))
        with self.assertRaises(common.SetupError) as raised:
            toolchains.remove(self.library, 'java')
        self.assertIn('maven', str(raised.exception))
        self.assert_rejected('cycle', name='java', requires=['maven'], default=False,
                             env={'JAVA_HOME': {'toolchain': ''}}, archive_bytes=tool_archive(command='java'),
                             check=['java'])

    def test_default_conflicts(self):
        self.add(name='java21', env={'JAVA_HOME': {'toolchain': ''}}, archive_bytes=tool_archive(command='java'),
                 check=['java'])
        error = self.assert_rejected('java21', name='java17', env={'OTHER': {'toolchain': ''}},
                                     archive_bytes=tool_archive(command='java'), check=['java'])
        self.assertIn('java', str(error))
        self.assert_rejected('JAVA_HOME', name='jdk', env={'JAVA_HOME': {'toolchain': ''}},
                             archive_bytes=tool_archive(command='jdk'), check=['jdk'])
        self.add(name='java17', env={'JAVA_HOME': {'toolchain': ''}}, default=False,
                 archive_bytes=tool_archive(command='java'), check=['java'])
        self.add(name='java21', version='21.1', env={'JAVA_HOME': {'toolchain': ''}},
                 archive_bytes=tool_archive(command='java'), check=['java'])

    # Generated files

    def test_generated_files(self):
        self.add(env={'TOOL_HOME': {'toolchain': ''}, 'TOOL_CACHE': {'value': "/tmp/tool cache'x"}},
                 notes=['Use GOTMPDIR under the workspace for go test.'])
        script = (self.library / 'tool/env.sh').read_text()
        self.assertIn("export TOOL_HOME='/toolchains/tool'", script)
        self.assertIn("export TOOL_CACHE='/tmp/tool cache'\"'\"'x'", script)
        self.assertIn("export PATH='/toolchains/tool/bin':\"$PATH\"", script)
        result = subprocess.run(['sh', '-c', '. "$1"; printf "%s" "$TOOL_CACHE"', 'sh', str(self.library / 'tool/env.sh')],
                                capture_output=True, text=True)
        self.assertEqual(result.stdout, "/tmp/tool cache'x")
        index = self.index()
        entry = index['toolchains'][0]
        self.assertEqual(index['schema'], 1)
        self.assertEqual(entry['commands'], ['tool'])
        self.assertEqual(entry['env']['TOOL_HOME'], '/toolchains/tool')
        self.assertEqual(entry['path'], ['/toolchains/tool/bin'])
        self.assertEqual(entry['source'], {'archive': 'tool-tool.tar',
                                           'sha256': json.loads(self.recipe().read_text())['source']['sha256']})
        guide = (self.library / 'toolchains.md').read_text()
        for needle in ('read-only', 'Do not install', 'ask the operator', '. /toolchains/tool/env.sh && tool',
                       'Use GOTMPDIR under the workspace for go test.', BASE, 'TOOL_HOME'):
            self.assertIn(needle, guide)
        for generated in ('toolchains.md', 'index.json', 'tool/env.sh', 'tool/toolchain.json'):
            text = (self.library / generated).read_text()
            self.assertNotIn(str(self.base), text, generated)
        self.assertNotIn(str(self.base), json.dumps(self.engine.calls[-1:]).replace(str(self.library), ''))

    def test_empty_library_guide(self):
        toolchains.prepare_library(self.library, avoid=())
        toolchains.render(self.library)
        self.assertIn('No toolchains are installed', (self.library / 'toolchains.md').read_text())
        self.assertEqual(self.index(), {'schema': 1, 'toolchains': []})

    # Launch environment

    def test_launch_env(self):
        self.add(name='java', env={'JAVA_HOME': {'toolchain': ''}}, archive_bytes=tool_archive(command='java'),
                 check=['java'])
        self.add(name='maven', requires=['java'], env={'M2': {'value': '/tmp/m2'}},
                 archive_bytes=tool_archive(command='mvn'), check=['mvn'])
        self.add(name='node24', env={}, default=False, archive_bytes=tool_archive(command='node'), check=['node'])
        lines, warnings = toolchains.launch_env(self.library, BASE)
        self.assertEqual(lines, [('path', '/toolchains/java/bin'), ('path', '/toolchains/maven/bin'),
                                 ('env', 'JAVA_HOME', '/toolchains/java'), ('env', 'M2', '/tmp/m2')])
        self.assertEqual(warnings, [])
        lines, warnings = toolchains.launch_env(self.library, 'docker.io/library/other@sha256:' + 'e' * 64)
        self.assertEqual(lines, [])
        self.assertEqual(len(warnings), 2)
        self.assertTrue(all('verify' in warning for warning in warnings))

    def test_launch_env_rejects_xdg_variables_in_the_index(self):
        # A wrapper may place its state with XDG variables; Podman keeps the last
        # --env, so a toolchain value would silently move that state.
        self.add(name='java', env={'JAVA_HOME': {'toolchain': ''}}, archive_bytes=tool_archive(command='java'),
                 check=['java'])
        index = json.loads((self.library / 'index.json').read_text())
        index['toolchains'][0]['env']['XDG_CONFIG_HOME'] = '/tmp/elsewhere'
        (self.library / 'index.json').write_text(json.dumps(index))
        with self.assertRaises(common.SetupError) as raised:
            toolchains.launch_env(self.library, BASE)
        self.assertIn('XDG_CONFIG_HOME', str(raised.exception))

    def test_launch_env_command_output(self):
        self.add()
        result = subprocess.run([sys.executable, '-I', str(ROOT / 'setup/toolchains.py'), 'launch-env',
                                 '--library', str(self.library), '--avoid', str(self.base / 'workspace')],
                                capture_output=True, text=True, env={'HOME': self.env['HOME'], 'PATH': os.environ['PATH']})
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.splitlines(),
                         ['library\t' + str(self.library), 'path\t/toolchains/tool/bin', 'env\tTOOL_HOME\t/toolchains/tool'])
        result = subprocess.run([sys.executable, '-I', str(ROOT / 'setup/toolchains.py'), 'launch-env',
                                 '--library', str(self.library), '--avoid', str(self.library / 'x')],
                                capture_output=True, text=True, env={'HOME': self.env['HOME'], 'PATH': os.environ['PATH']})
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(result.stdout, '')

    def test_base_reference(self):
        self.assertRegex(BASE, r'^\S+@sha256:[a-f0-9]{64}$')
        fake = self.base / 'release'
        fake.mkdir()
        for text in ('FROM example:latest\n', 'FROM a@sha256:' + 'a' * 64 + '\nFROM b@sha256:' + 'b' * 64 + '\n'):
            (fake / 'Containerfile').write_text(text)
            with self.subTest(text=text), self.assertRaises(common.SetupError):
                toolchains.base_reference(fake)


if __name__ == '__main__':
    unittest.main()

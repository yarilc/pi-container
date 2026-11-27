"""Synthetic toolchain library tests: native disposable storage and a fake engine."""
import contextlib
import hashlib
import http.server
import io
import json
import os
from pathlib import Path
import re
import shutil
import ssl
import stat
import subprocess
import sys
import tarfile
import tempfile
import threading
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
        self.pull_status = 0
        # The library's image store, as helper containers of the engine image see it.
        self.store = {}
        self.local_images = {}
        self.pipelines = []
        # Running session engines as (name, store path), of any wrapper.
        self.engines = []
        # The check engine: readiness answer, and the default seccomp profile path.
        self.engine_ready = 'true'
        self.seccomp = ''

    def helper(self, inner):
        """podman inside a store helper container."""
        if inner[:2] == ['image', 'inspect']:
            return (0, self.store[inner[-1]] + '\n', '') if inner[-1] in self.store else (125, '', 'no such image')
        if inner[:1] == ['pull']:
            if self.pull_status:
                return self.pull_status, '', 'Error: initializing source: manifest unknown\n'
            self.store[inner[-1]] = 'd' * 64
        elif inner[:1] == ['tag']:
            self.store[inner[2]] = inner[1]
        elif inner[:1] == ['rmi']:
            self.store.pop(inner[1], None)
        return 0, '', ''

    def pipeline(self, producer, consumer):
        self.pipelines.append((list(producer), list(consumer)))
        return 0, 0, ''

    def run(self, args, timeout=None):
        self.calls.append(list(args))
        output = error = ''
        status = 0
        if args[:2] == ['unshare', 'chown']:
            pass
        elif args[:1] == ['ps']:
            # As Podman 6.2: `index .Labels` fails in ps templates; JSON works in every version.
            if args[args.index('--format') + 1] == 'json':
                output = json.dumps([{'Names': [name], 'Labels': {toolchains.engine.STORE_LABEL: store, 'other': 'x'}}
                                     for name, store in self.engines])
            else:
                status, error = 125, 'Error: template: ps:1:24: cannot index slice/array with type string'
        elif args[:1] == ['info']:
            output = self.seccomp + '\n'
        elif args[:1] == ['volume'] or args[:1] == ['rm']:
            pass
        elif args[:2] == ['run', '--detach']:
            output = 'e' * 64 + '\n'
        elif args[:1] == ['exec']:
            # Commands in an engine run as its user, never as its startup root
            # (support-nested-systemd-containers, design D4).
            if args[1:3] == ['--user', 'podman']:
                output = self.engine_ready + '\n'
            else:
                status, error = 97, 'fake podman: a command in the engine must run as --user podman\n'
        elif args[:1] == ['run'] and '--entrypoint' in args and args[args.index('--entrypoint') + 1] == 'podman':
            status, output, error = self.helper(args[args.index('--entrypoint') + 3:])
        elif args[:2] == ['image', 'exists']:
            status = 0 if self.exists else 1
        elif args[:2] == ['image', 'inspect']:
            output = self.local_images.get(args[-1], 'sha256:' + 'b' * 64) + '\n'
        elif args[:1] == ['pull']:
            status = self.pull_status
            if status:
                error = 'Error: initializing source: manifest unknown\n'
            else:
                self.exists = True
        elif args[:1] == ['create']:
            output = 'c' * 64 + '\n'
        elif args[:1] == ['run']:
            status = self.check_status
            output = 'check output\n'
        return subprocess.CompletedProcess(['podman', *args], status, output, error)

    @contextlib.contextmanager
    def stream(self, args):
        self.calls.append(list(args))
        yield io.BytesIO(self.image_tar)


def certificate(directory):
    """Self-signed certificate for localhost, or None without the openssl CLI."""
    if not shutil.which('openssl'):
        return None
    result = subprocess.run(['openssl', 'req', '-x509', '-newkey', 'ec', '-pkeyopt', 'ec_paramgen_curve:P-256',
                             '-nodes', '-keyout', str(directory / 'key.pem'), '-out', str(directory / 'cert.pem'),
                             '-days', '1', '-subj', '/CN=localhost',
                             '-addext', 'subjectAltName=DNS:localhost'], capture_output=True)
    return directory / 'cert.pem' if result.returncode == 0 else None


class ArchiveServer:
    """Local HTTPS server: routes map a path to (status, headers, body); requests are recorded."""

    def __init__(self, directory, routes):
        self.routes = routes
        self.requests = []
        self.cert = certificate(directory)
        if self.cert is None:
            raise unittest.SkipTest('openssl CLI unavailable for a controlled certificate')
        server = self

        class Handler(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                server.requests.append(self.path)
                status, headers, body = server.routes.get(self.path, (404, {}, b'missing'))
                self.send_response(status)
                for key, value in {'Content-Length': str(len(body)), **headers}.items():
                    self.send_header(key, value)
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *args):
                pass
        self.httpd = http.server.ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.load_cert_chain(str(self.cert), str(directory / 'key.pem'))
        self.httpd.socket = context.wrap_socket(self.httpd.socket, server_side=True)
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()

    def url(self, path, scheme='https'):
        return f'{scheme}://localhost:{self.httpd.server_address[1]}{path}'

    def close(self):
        self.httpd.shutdown()
        self.httpd.server_close()


class ToolchainTests(unittest.TestCase):
    def setUp(self):
        self.base = Path(tempfile.mkdtemp(dir=test_setting('TEST_TMPDIR'))).resolve()
        os.chmod(self.base, 0o700)
        self.addCleanup(shutil.rmtree, self.base, True)
        self.library = self.base / 'library'
        self.env = {'HOME': str(self.base / 'home'), name('IMAGE'): 'localhost/runtime:test'}
        # add refuses recipes in the directory it runs from: run from a directory of our own.
        self.cwd = self.base / 'elsewhere'
        self.cwd.mkdir()
        self.addCleanup(os.chdir, os.getcwd())
        os.chdir(self.cwd)
        self.engine = Engine()
        # The engine host's default seccomp profile, for the temporary check engines.
        default = self.base / 'default-seccomp.json'
        default.write_text(json.dumps({'syscalls': [{'names': ['read'], 'action': 'SCMP_ACT_ALLOW'}]}))
        self.engine.seccomp = str(default)
        for target, value in (('run', self.engine.run), ('stream', self.engine.stream),
                              ('pipeline', self.engine.pipeline)):
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
        if recipe['schema'] == 2 and 'source' not in values:
            del recipe['source']
        path = self.base / (recipe['name'] + '.json')
        path.write_text(json.dumps(recipe))
        return path

    def archive_source(self, data, label='part', **extra):
        """A schema-2 local archive source for the given tar bytes."""
        archive = self.base / (label + '.tar')
        archive.write_bytes(data)
        return {'archive': str(archive), 'sha256': hashlib.sha256(data).hexdigest(), **extra}

    def leftovers(self):
        return [p.name for p in self.library.iterdir() if p.name.startswith(('.staging', '.download', '.old'))]

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
            'bus variable': ({'env': {'DBUS_SESSION_BUS_ADDRESS': {'value': 'unix:path=/tmp/bus'}}}, 'protected'),
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
        self.assertEqual(self.leftovers(), [])

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
                self.assertEqual(self.leftovers(), [])

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

    def test_image_source_is_pulled_without_maintenance(self):
        self.engine.exists = False
        self.engine.image_tar = tool_archive(prefix='tool')
        self.assertNotIn(name('MAINTENANCE'), self.env)
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            self.add(source={'image': DIGEST, 'path': '/opt/tool'})
        self.assertIn('Pulling ' + DIGEST, output.getvalue())
        self.assertIn(['pull', DIGEST], self.engine.calls)
        self.assertFalse(any(call[:1] == ['build'] for call in self.engine.calls))
        create = next(call for call in self.engine.calls if call[:1] == ['create'])
        self.assertIn('--network=none', create)
        self.assertIn(['cp', 'c' * 64 + ':/opt/tool', '-'], self.engine.calls)
        self.assertIn(['rm', '--force', 'c' * 64], self.engine.calls)
        manifest = json.loads((self.library / 'tool/toolchain.json').read_text())
        self.assertEqual(manifest['source'], [{'image': DIGEST, 'path': '/opt/tool', 'image_id': 'sha256:' + 'b' * 64}])

    def test_failed_pull_names_the_image(self):
        self.add(name='other', archive_bytes=tool_archive(command='other'), check=['other'], env={})
        self.engine.exists = False
        self.engine.pull_status = 125
        error = self.assert_rejected('Cannot pull ' + DIGEST, source={'image': DIGEST, 'path': '/opt/tool'})
        self.assertIn('manifest unknown', str(error))
        self.assertFalse((self.library / 'tool').exists())
        self.assertFalse(any(call[:1] == ['create'] for call in self.engine.calls))

    def test_owned_container_removed_after_failed_copy(self):
        self.engine.image_tar = tar_bytes([('tool/../x', 'file', b'x', 0o644)])
        self.assert_rejected('unsafe', source={'image': DIGEST, 'path': '/opt/tool'})
        self.assertIn(['rm', '--force', 'c' * 64], self.engine.calls)

    # Schema 2: several sources in one toolchain

    def test_schema_two_recipe_validation(self):
        good = self.archive_source(tool_archive(), strip_components=1)
        member = {'archive': good['archive'], 'sha256': good['sha256']}
        url = {'url': 'https://example.org/tool.tar', 'sha256': good['sha256']}
        cases = {
            'unsupported schema': ({'schema': 3}, 'schema must be 1 or 2'),
            'schema-1 key in schema 2': ({'schema': 2, 'sources': [good], 'source': good}, 'unknown key source'),
            'no sources': ({'schema': 2}, 'missing key sources'),
            'empty sources': ({'schema': 2, 'sources': []}, 'sources must be a list'),
            'too many sources': ({'schema': 2, 'sources': [good] * 17}, 'sources must be a list'),
            'source not an object': ({'schema': 2, 'sources': ['tool.tar']}, 'must be an object'),
            'URL in schema 1': ({'source': url}, 'needs image and path, or archive'),
            'plain HTTP URL': ({'schema': 2, 'sources': [{**url, 'url': 'http://example.org/t.tar'}]}, 'https://'),
            'URL with credentials': ({'schema': 2, 'sources': [{**url, 'url': 'https://u:p@example.org/t.tar'}]},
                                     'without credentials'),
            'URL with spaces': ({'schema': 2, 'sources': [{**url, 'url': 'https://example.org/a b.tar'}]}, 'https://'),
            'path and strip': ({'schema': 2, 'sources': [{**good, 'path': 'tool-1.0'}]}, 'either path or strip'),
            'absolute member path': ({'schema': 2, 'sources': [{**member, 'path': '/tool-1.0'}]}, 'relative'),
            'parent member path': ({'schema': 2, 'sources': [{**member, 'path': 'tool-1.0/..'}]}, 'relative'),
            'empty member path': ({'schema': 2, 'sources': [{**member, 'path': ''}]}, 'directory inside the archive'),
            'absolute target': ({'schema': 2, 'sources': [{**good, 'target': '/opt'}]}, 'relative'),
            'parent target': ({'schema': 2, 'sources': [{**good, 'target': '../x'}]}, 'relative'),
            'strip on an image': ({'schema': 2, 'sources': [{'image': DIGEST, 'path': '/opt', 'strip_components': 1}]},
                                  'unknown keys'),
            'target in schema 1': ({'source': {**good, 'target': 'lib'}}, 'unknown keys'),
        }
        for label, (values, message) in cases.items():
            with self.subTest(label=label):
                self.assert_rejected(message, **values)

    def test_image_recipe_validation(self):
        # Images for the session container engine: digest-pinned references or
        # local images by full ID; an image-only toolchain has no files.
        local = {'local': 'sha256:' + 'b' * 64, 'name': 'localhost/runtime:dev'}
        image_only = {'schema': 2, 'name': 'db', 'version': '16', 'images': [DIGEST],
                      'check': ['podman', 'run', '--rm', DIGEST, 'true'], 'default': False}
        recipe = toolchains.validate_recipe(image_only)
        self.assertEqual(recipe['images'], [{'image': DIGEST}])
        self.assertEqual((recipe['sources'], recipe['path'], recipe['env']), ([], [], {}))
        mixed = toolchains.validate_recipe({**image_only, 'images': [DIGEST, local], 'path': ['bin'],
                                            'sources': [{'image': DIGEST, 'path': '/opt/tool'}]})
        self.assertEqual(mixed['images'], [{'image': DIGEST}, local])
        self.assertEqual(mixed['path'], ['bin'])
        files_only = {key: item for key, item in image_only.items() if key != 'images'}
        files_only['sources'] = [{'image': DIGEST, 'path': '/opt/tool'}]
        self.assertNotIn('images', toolchains.validate_recipe(files_only))
        cases = {
            'tag only': ({'images': ['docker.io/library/postgres:16']}, '@sha256: digest'),
            'images in schema 1': ({'schema': 1, 'source': {'image': DIGEST, 'path': '/opt'}}, 'unknown key images'),
            'empty images': ({'images': []}, 'images must be a list'),
            'too many images': ({'images': [f'docker.io/x/i{n}@sha256:' + 'a' * 64 for n in range(17)]},
                                'images must be a list'),
            'duplicate image': ({'images': [DIGEST, DIGEST]}, 'each image once'),
            'short local ID': ({'images': [{**local, 'local': 'b' * 64}]}, 'full ID'),
            'local name outside localhost': ({'images': [{**local, 'name': 'docker.io/library/runtime:dev'}]},
                                             'localhost/ name'),
            'local with extra key': ({'images': [{**local, 'pull': True}]}, 'digest-pinned reference'),
            'path without files': ({'path': ['bin']}, 'path needs file sources'),
            'env without files': ({'env': {'DB_HOME': {'value': '/x'}}}, 'env needs file sources'),
            'default without files': ({'default': True}, 'default needs file sources'),
            'neither files nor images': ({'images': None}, 'missing key sources'),
        }
        for label, (values, message) in cases.items():
            with self.subTest(label=label):
                value = {key: item for key, item in (image_only | values).items() if item is not None}
                with self.assertRaises(common.SetupError) as raised:
                    toolchains.validate_recipe(value)
                self.assertIn(message, str(raised.exception))

    def image_recipe(self, **values):
        recipe = {'schema': 2, 'name': 'db', 'version': '16', 'images': [DIGEST],
                  'check': ['podman', 'run', '--rm', DIGEST, 'true'], 'default': False} | values
        path = self.base / 'db.json'
        path.write_text(json.dumps(recipe))
        return path

    def store_helpers(self):
        return [call for call in self.engine.calls if call[:1] == ['run'] and '--entrypoint' in call
                and call[call.index('--entrypoint') + 1] == 'podman']

    def test_image_recipe_pulls_into_the_store_through_an_engine_helper(self):
        # toolchain-library: Read-only image store in the library / Helper container scope.
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            toolchains.add(self.library, self.image_recipe(), self.env)
        store = self.library / '.images'
        self.assertTrue(store.is_dir())
        self.assertEqual(stat.S_IMODE(store.stat().st_mode), 0o700)
        self.assertFalse([call for call in self.engine.calls if call[:1] == ['unshare']])
        self.assertIn('Pulling ' + DIGEST + ' into the image store', output.getvalue())
        helpers = self.store_helpers()
        self.assertTrue(helpers)
        for call in helpers:
            volumes = [call[i + 1] for i, arg in enumerate(call) if arg == '--volume']
            self.assertEqual(volumes, [str(store) + ':' + toolchains.ENGINE_STORAGE])
            self.assertEqual(call[call.index('--user') + 1:call.index('--user') + 3],
                             ['podman', '--userns=keep-id:uid=1000,gid=1000'])
            self.assertEqual(call[call.index('--entrypoint') + 2], PROFILE.image('engine', 'latest'))
        self.assertIn(['pull', '--quiet', DIGEST], [call[call.index('--entrypoint') + 3:] for call in helpers])
        manifest = json.loads((self.library / 'db/toolchain.json').read_text())
        self.assertEqual(manifest['images'], [{'image': DIGEST, 'image_id': 'd' * 64}])
        self.assertEqual((manifest['source'], manifest['commands'], manifest['path']), ([], [], []))
        self.assertEqual(self.index()['schema'], toolchains.SCHEMA)
        # A second toolchain with the same image finds it in the store and pulls nothing.
        before = len(self.store_helpers())
        toolchains.add(self.library, self.image_recipe(name='db2'), self.env)
        pulls = [call for call in self.store_helpers()[before:] if 'pull' in call]
        self.assertEqual(pulls, [])

    def test_store_helper_trusts_the_saved_host_ca(self):
        bundle = self.base / 'bundle.pem'
        bundle.write_text('synthetic bundle')
        env = self.env | {name('TRUST_HOST_CA'): '1', name('CA_BUNDLE'): str(bundle)}
        toolchains.add(self.library, self.image_recipe(), env)
        for call in self.store_helpers():
            volumes = [call[i + 1] for i, arg in enumerate(call) if arg == '--volume']
            self.assertEqual(volumes, [str(self.library / '.images') + ':' + toolchains.ENGINE_STORAGE,
                                       str(bundle) + ':' + toolchains.ENGINE_CA + ':ro'])

    def test_local_image_is_copied_by_id_and_checked(self):
        identity = 'sha256:' + 'e' * 64
        recipe = self.image_recipe(images=[{'local': identity, 'name': 'localhost/runtime:dev'}])
        # The host engine has another image under that ID: nothing is copied.
        with self.assertRaisesRegex(common.SetupError, 'has no local image ' + identity):
            toolchains.add(self.library, recipe, self.env)
        self.assertEqual(self.engine.pipelines, [])
        self.assertFalse((self.library / 'db').exists())
        self.engine.local_images[identity] = 'e' * 64
        toolchains.add(self.library, recipe, self.env)
        (producer, consumer), = self.engine.pipelines
        self.assertEqual(producer, ['save', identity])
        self.assertEqual(consumer[consumer.index('--entrypoint') + 3:], ['load', '--quiet'])
        self.assertIn('--interactive', consumer)
        self.assertEqual(self.engine.store['localhost/runtime:dev'], 'e' * 64)
        manifest = json.loads((self.library / 'db/toolchain.json').read_text())
        self.assertEqual(manifest['images'], [{'local': identity, 'name': 'localhost/runtime:dev',
                                               'image_id': 'e' * 64}])

    def test_failed_pull_or_check_leaves_the_library_unchanged(self):
        self.engine.pull_status = 125
        with self.assertRaisesRegex(common.SetupError, 'Cannot pull ' + re.escape(DIGEST)):
            toolchains.add(self.library, self.image_recipe(), self.env)
        self.assertEqual(self.engine.store, {})
        self.assertFalse((self.library / 'db').exists())
        self.engine.pull_status = 0
        self.engine.check_status = 1
        with self.assertRaisesRegex(common.SetupError, 'toolchain check failed'):
            toolchains.add(self.library, self.image_recipe(), self.env)
        # The image pulled for the failed add is taken out of the store again.
        self.assertEqual(self.engine.store, {})
        self.assertIn(['rmi', DIGEST], [call[call.index('--entrypoint') + 3:] for call in self.store_helpers()])
        self.assertFalse((self.library / 'db').exists())

    def test_shared_image_stays_until_its_last_toolchain_is_removed(self):
        # toolchain-library: Read-only image store in the library / Shared image.
        toolchains.add(self.library, self.image_recipe(), self.env)
        toolchains.add(self.library, self.image_recipe(name='db2'), self.env)
        toolchains.remove(self.library, 'db', self.env)
        self.assertIn(DIGEST, self.engine.store)
        self.assertNotIn(['rmi', DIGEST], [c[c.index('--entrypoint') + 3:] for c in self.store_helpers()])
        toolchains.remove(self.library, 'db2', self.env)
        self.assertEqual(self.engine.store, {})
        self.assertEqual(self.index()['toolchains'], [])

    def test_image_removal_waits_for_idle_engines(self):
        # toolchain-library: Image removal waits for idle engines.
        toolchains.add(self.library, self.image_recipe(), self.env)
        store = str(self.library / '.images')
        self.engine.engines = [('other-library-engine', str(self.base / 'elsewhere/.images')),
                               ('project-0-engine', store)]
        with self.assertRaisesRegex(common.SetupError, 'while session engines run: project-0-engine'):
            toolchains.remove(self.library, 'db', self.env)
        self.assertTrue((self.library / 'db').is_dir())
        self.assertIn(DIGEST, self.engine.store)
        # A replacement that drops the image is refused the same way, before any change.
        other = 'docker.io/library/other@sha256:' + 'c' * 64
        with self.assertRaisesRegex(common.SetupError, 'project-0-engine'):
            toolchains.add(self.library, self.image_recipe(images=[other]), self.env)
        self.assertNotIn(other, self.engine.store)
        # Adding images, or replacing a toolchain that keeps its images, proceeds while engines run.
        toolchains.add(self.library, self.image_recipe(name='cache', images=[other]), self.env)
        toolchains.add(self.library, self.image_recipe(version='16.1'), self.env)
        self.assertEqual(sorted(self.engine.store), sorted([DIGEST, other]))
        self.engine.engines = []
        toolchains.remove(self.library, 'db', self.env)
        self.assertEqual(sorted(self.engine.store), [other])

    def test_engine_listing_reads_the_json_listing(self):
        # toolchain-library: Image removal waits for idle engines, with any Podman version's listing.
        store = str(self.library / '.images')
        self.engine.engines = [('project-1-engine', store), ('elsewhere-engine', store + '-other')]
        self.assertEqual(toolchains.running_engines(self.library), ['project-1-engine'])
        listing = json.dumps([{'Names': ['b-engine', 'a-engine'], 'Labels': {toolchains.engine.STORE_LABEL: store}},
                              {'Names': ['unlabeled'], 'Labels': None}, {'Names': None, 'Labels': {}}])
        for stdout, expected in (('', []), ('[]\n', []), (listing, ['a-engine', 'b-engine'])):
            with self.subTest(stdout=stdout), patch.object(toolchains, 'run', return_value=subprocess.CompletedProcess(
                    [], 0, stdout, '')):
                self.assertEqual(toolchains.running_engines(self.library), expected)
        for stdout in ('{{.Names}}', '{"Names": []}', '[1]'):
            with self.subTest(stdout=stdout), patch.object(toolchains, 'run', return_value=subprocess.CompletedProcess(
                    [], 0, stdout, '')), self.assertRaisesRegex(common.SetupError, 'unreadable listing'):
                toolchains.running_engines(self.library)

    def test_image_check_runs_against_a_temporary_engine_without_network(self):
        # toolchain-library: Verified against the runtime image / Image check without network.
        default = self.base / 'default-seccomp.json'
        default.write_text(json.dumps({'syscalls': [{'names': ['read'], 'action': 'SCMP_ACT_ALLOW'}]}))
        self.engine.seccomp = str(default)
        toolchains.add(self.library, self.image_recipe(), self.env)
        started = next(call for call in self.engine.calls if call[:2] == ['run', '--detach'])
        name = started[started.index('--name') + 1]
        self.assertIn('--network=none', started)
        self.assertEqual(started[-2:], [PROFILE.image('engine', 'latest'), '2375'])
        volumes = [started[i + 1] for i, arg in enumerate(started) if arg == '--volume']
        self.assertEqual(volumes, [toolchains.ENGINE_STORAGE, str(self.library / '.images/storage') + ':/var/lib/shared:ro'])
        self.assertIn('--rm', started)
        check = next(call for call in self.engine.calls if call[:2] == ['run', '--rm'] and '/bin/sh' in call)
        self.assertIn('--network=container:' + name, check)
        self.assertNotIn('--network=none', check)
        for variable in ('CONTAINER_HOST', 'DOCKER_HOST'):
            self.assertIn(variable + '=tcp://127.0.0.1:2375', check)
        self.assertIn(['rm', '--force', '--volumes', '--time', '0', name], self.engine.calls)
        # The check engine starts like a session's, and is queried as its user.
        self.assertEqual(started[started.index('--user') + 1], '0:0')
        self.assertNotIn('--init', started)
        self.assertTrue([call for call in self.engine.calls if call[:4] == ['exec', '--user', 'podman', name]])
        # A toolchain without images is checked without network and without an engine.
        self.engine.calls.clear()
        toolchains.add(self.library, self.recipe(), self.env)
        self.assertFalse([call for call in self.engine.calls if call[:2] == ['run', '--detach']])
        check = next(call for call in self.engine.calls if call[:2] == ['run', '--rm'] and '/bin/sh' in call)
        self.assertIn('--network=none', check)

    def test_unready_check_engine_fails_and_is_removed(self):
        default = self.base / 'default-seccomp.json'
        default.write_text(json.dumps({'syscalls': []}))
        self.engine.seccomp = str(default)
        self.engine.engine_ready = 'false'
        with patch.object(toolchains.engine, 'READY_SECONDS', 2), patch.object(toolchains.time, 'sleep'):
            with self.assertRaisesRegex(common.SetupError, 'did not answer'):
                toolchains.add(self.library, self.image_recipe(), self.env)
        self.assertTrue([call for call in self.engine.calls if call[:3] == ['rm', '--force', '--volumes']])
        self.assertFalse((self.library / 'db').exists())
        self.assertEqual(self.engine.store, {})

    def test_images_are_listed_for_the_agent_and_reported_to_the_launcher(self):
        # toolchain-library: Self-describing library for the agent / Images listed for the agent.
        toolchains.add(self.library, self.recipe(), self.env)
        lines, _ = toolchains.launch_env(self.library, toolchains.base_reference(toolchains.INSTALLATION))
        self.assertNotIn('store', [line[0] for line in lines])
        toolchains.add(self.library, self.image_recipe(), self.env)
        mixed = self.image_recipe(name='mixed', sources=[{'image': DIGEST, 'path': '/opt/tool'}], path=['bin'])
        self.engine.image_tar = tool_archive(prefix='tool')
        toolchains.add(self.library, mixed, self.env)
        guide = (self.library / 'toolchains.md').read_text()
        self.assertIn('podman (CONTAINER_HOST) or a Docker-API client (DOCKER_HOST)', guide)
        self.assertEqual(guide.count('- Image: `' + DIGEST + '`, for example `podman run --rm ' + DIGEST + '`'), 2)
        items = {item['name']: item for item in self.index()['toolchains']}
        self.assertEqual(items['db']['images'], [{'reference': DIGEST, 'image_id': 'd' * 64}])
        self.assertNotIn('images', items['tool'])
        self.assertEqual(self.index()['schema'], toolchains.SCHEMA)
        # session-container-engine: Engine for sessions with library images.
        lines, _ = toolchains.launch_env(self.library, toolchains.base_reference(toolchains.INSTALLATION))
        self.assertIn(('store', str(self.library / '.images')), lines)

    def test_catalog_refuses_local_images(self):
        catalog = self.base / 'catalog'
        catalog.mkdir()
        (catalog / 'db.json').write_text(json.dumps({
            'schema': 2, 'name': 'db', 'version': '1', 'check': ['true'], 'default': False,
            'images': [{'local': 'sha256:' + 'c' * 64, 'name': 'localhost/db:1'}]}))
        with self.assertRaises(common.SetupError) as raised:
            toolchains.catalog(catalog)
        self.assertIn('names a local image', str(raised.exception))
        (catalog / 'db.json').write_text(json.dumps({
            'schema': 2, 'name': 'db', 'version': '1', 'check': ['true'], 'default': False, 'images': [DIGEST]}))
        self.assertEqual(toolchains.catalog(catalog)['db']['images'], [{'image': DIGEST}])

    def test_schema_two_recipe_with_target(self):
        source = self.archive_source(tool_archive(), strip_components=1, target='opt/tool')
        self.add(schema=2, sources=[source], path=['opt/tool/bin'])
        self.assertTrue((self.library / 'tool/opt/tool/bin/tool').is_file())
        manifest = json.loads((self.library / 'tool/toolchain.json').read_text())
        self.assertEqual(manifest['source'], [{'archive': 'part.tar', 'sha256': source['sha256'], 'target': 'opt/tool'}])
        self.assertNotIn('sources', manifest)
        self.assertEqual(self.index()['toolchains'][0]['commands'], ['tool'])

    def test_sources_merge_into_one_root(self):
        compiler = tar_bytes([('dist/rustc/bin/tool', 'file', b'#!/bin/sh\necho ok\n', 0o755),
                              ('dist/rustc/lib/core.rlib', 'file', b'core', 0o644),
                              ('dist/rustc/manifest.in', 'file', b'rustc', 0o644)])
        library = tar_bytes([('std/rust-std/lib/std.rlib', 'file', b'std', 0o644),
                             ('std/rust-std/manifest.in', 'file', b'std', 0o644)])
        sources = [self.archive_source(compiler, 'rustc', path='dist/rustc/bin', target='bin'),
                   self.archive_source(compiler, 'rustc', path='dist/rustc/lib', target='lib'),
                   self.archive_source(library, 'std', path='std/rust-std/lib', target='lib')]
        checked = []
        original_check = toolchains.check

        def record_tree(library_path, toolchain, root, *args):
            checked.extend(sorted(str(p.relative_to(root)) for p in Path(root).rglob('*') if p.is_file()))
            return original_check(library_path, toolchain, root, *args)
        with patch.object(toolchains, 'verified_copy', wraps=toolchains.verified_copy) as copy, \
                patch.object(toolchains, 'check', side_effect=record_tree):
            self.add(schema=2, sources=sources)
        # Each archive is read once per command, however many sources use it.
        self.assertEqual(copy.call_count, 2)
        # The check ran on the merged tree, before the manifest was written.
        self.assertEqual(checked, ['bin/tool', 'env.sh', 'lib/core.rlib', 'lib/std.rlib'])
        root = self.library / 'tool'
        self.assertFalse((root / 'manifest.in').exists())
        manifest = json.loads((root / 'toolchain.json').read_text())
        self.assertEqual([(r['archive'], r['path'], r['target']) for r in manifest['source']],
                         [('rustc.tar', 'dist/rustc/bin', 'bin'), ('rustc.tar', 'dist/rustc/lib', 'lib'),
                          ('std.tar', 'std/rust-std/lib', 'lib')])
        self.assertEqual(self.leftovers(), [])

    def test_sources_that_provide_the_same_file_fail(self):
        first = self.archive_source(tool_archive(), 'first', strip_components=1)
        cases = {
            'same file': (self.archive_source(tar_bytes([('x/bin/tool', 'file', b'x', 0o755)]), 'second',
                                              strip_components=1), 'bin/tool'),
            'file where a directory goes': (self.archive_source(tar_bytes([('x/bin', 'file', b'x', 0o644)]), 'third',
                                                                strip_components=1), 'bin'),
            'target below a file': (self.archive_source(tar_bytes([('x/y', 'file', b'x', 0o644)]), 'fourth',
                                                        strip_components=1, target='README/sub'), 'README'),
        }
        for label, (second, path) in cases.items():
            with self.subTest(label=label):
                error = self.assert_rejected('overlap', schema=2, sources=[first, second])
                self.assertIn('overlap at ' + path, str(error))
                self.assertFalse((self.library / 'tool').exists())
                self.assertEqual(self.leftovers(), [])

    def test_missing_archive_path_fails(self):
        source = self.archive_source(tool_archive(), path='tool-2.0/bin')
        self.assert_rejected('not found', schema=2, sources=[source])
        self.assertEqual(self.leftovers(), [])

    def test_archive_is_extracted_from_the_verified_copy(self):
        # A local archive changed after its check (for example in a workspace)
        # cannot reach the toolchain: extraction reads the private copy.
        source = self.archive_source(tool_archive(), strip_components=1)
        original = toolchains.verified_copy

        def replace_after_copy(item, library, env):
            copy = original(item, library, env)
            Path(item['archive']).write_bytes(tool_archive(extra=(('tool-1.0/evil', 'file', b'x', 0o755),)))
            return copy
        with patch.object(toolchains, 'verified_copy', side_effect=replace_after_copy):
            self.add(schema=2, sources=[source])
        self.assertTrue((self.library / 'tool/bin/tool').is_file())
        self.assertFalse((self.library / 'tool/evil').exists())

    def test_library_format_stays_readable_by_older_wrappers(self):
        # Wrappers on older reference tags read the shared library (design D3).
        self.add()
        entries = self.index()['toolchains']
        environment = toolchains.launch_env(self.library, BASE)
        recipe = json.loads(self.recipe().read_text())
        recipe.update(schema=2, sources=[recipe.pop('source')])
        path = self.base / 'tool-schema-2.json'
        path.write_text(json.dumps(recipe))
        toolchains.add(self.library, path, self.env)
        index = self.index()
        self.assertEqual(index['schema'], 1)
        self.assertEqual(index['toolchains'], entries)
        self.assertEqual(toolchains.launch_env(self.library, BASE), environment)
        manifest = json.loads((self.library / 'tool/toolchain.json').read_text())
        for key in ('name', 'version', 'default', 'commands', 'path', 'env', 'requires', 'notes', 'check', 'source',
                    'verified'):
            self.assertIn(key, manifest)
        self.assertEqual(manifest['source'], [{'archive': 'tool-tool.tar', 'sha256': recipe['sources'][0]['sha256']}])

    # Archive downloads

    def archive_server(self, routes):
        directory = self.base / 'server'
        directory.mkdir(exist_ok=True)
        server = ArchiveServer(directory, routes)
        self.addCleanup(server.close)
        # urllib takes proxies from the process environment, as on the host.
        patcher = patch.dict(os.environ)
        patcher.start()
        self.addCleanup(patcher.stop)
        for key in [key for key in os.environ if key.lower() in ('http_proxy', 'https_proxy', 'all_proxy')]:
            del os.environ[key]
        return server

    def trust(self, server):
        self.env.update({name('TRUST_HOST_CA'): '1', name('CA_BUNDLE'): str(server.cert)})

    def test_download_with_the_saved_host_ca(self):
        data = tool_archive()
        server = self.archive_server({'/tool.tar': (200, {}, data)})
        self.trust(server)
        self.assertNotIn(name('MAINTENANCE'), self.env)
        common_source = {'url': server.url('/tool.tar'), 'sha256': hashlib.sha256(data).hexdigest()}
        sources = [{**common_source, 'path': 'tool-1.0/bin', 'target': 'bin'},
                   {**common_source, 'path': 'tool-1.0', 'target': 'share/tool'}]
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            self.add(schema=2, sources=sources)
        # Two sources share the archive: one download.
        self.assertEqual(server.requests, ['/tool.tar'])
        self.assertEqual(output.getvalue().count('Downloading ' + server.url('/tool.tar')), 1)
        self.assertTrue((self.library / 'tool/bin/tool').is_file())
        self.assertTrue((self.library / 'tool/share/tool/README').is_file())
        manifest = json.loads((self.library / 'tool/toolchain.json').read_text())
        self.assertEqual(manifest['source'][0], {'url': server.url('/tool.tar'), 'sha256': common_source['sha256'],
                                                 'path': 'tool-1.0/bin', 'target': 'bin'})
        self.assertEqual(self.leftovers(), [])

    def test_download_follows_https_redirects_only(self):
        data = tool_archive()
        server = self.archive_server({'/tool.tar': (200, {}, data)})
        server.routes['/moved'] = (302, {'Location': server.url('/tool.tar')}, b'')
        server.routes['/insecure'] = (302, {'Location': server.url('/tool.tar', scheme='http')}, b'')
        self.trust(server)
        source = {'sha256': hashlib.sha256(data).hexdigest(), 'strip_components': 1}
        error = self.assert_rejected('not https', schema=2, sources=[{**source, 'url': server.url('/insecure')}])
        self.assertIn(server.url('/insecure'), str(error))
        self.assertEqual(server.requests, ['/insecure'])
        self.assertFalse((self.library / 'tool').exists())
        self.assertEqual(self.leftovers(), [])
        self.add(schema=2, sources=[{**source, 'url': server.url('/moved')}])
        self.assertEqual(server.requests, ['/insecure', '/moved', '/tool.tar'])
        self.assertTrue((self.library / 'tool/bin/tool').is_file())

    def test_untrusted_certificate_fails_with_guidance(self):
        data = tool_archive()
        server = self.archive_server({'/tool.tar': (200, {}, data)})
        source = {'url': server.url('/tool.tar'), 'sha256': hashlib.sha256(data).hexdigest(), 'strip_components': 1}
        error = self.assert_rejected('Cannot download ' + server.url('/tool.tar'), schema=2, sources=[source])
        self.assertIn('host CA trust', str(error))
        self.assertFalse((self.library / 'tool').exists())
        self.assertEqual(self.leftovers(), [])

    def test_plain_http_url_is_refused_before_any_download(self):
        with patch.object(toolchains, 'download') as download:
            self.assert_rejected('https://', schema=2,
                                 sources=[{'url': 'http://localhost/tool.tar', 'sha256': '0' * 64}])
        download.assert_not_called()

    def test_failed_downloads_leave_nothing(self):
        data = tool_archive()
        server = self.archive_server({'/tool.tar': (200, {}, data)})
        self.trust(server)
        good = {'url': server.url('/tool.tar'), 'sha256': hashlib.sha256(data).hexdigest(), 'strip_components': 1}
        cases = {
            'checksum mismatch': ({**good, 'sha256': '0' * 64}, 'SHA-256 mismatch for ' + good['url']),
            'missing file': ({**good, 'url': server.url('/gone.tar')}, 'Cannot download ' + server.url('/gone.tar')),
        }
        for label, (source, message) in cases.items():
            with self.subTest(label=label):
                self.assert_rejected(message, schema=2, sources=[source])
                self.assertEqual(self.leftovers(), [])
        with patch.object(toolchains, 'DOWNLOAD_LIMIT', 16):
            self.assert_rejected('larger than 16 bytes', schema=2, sources=[good])
        self.assertEqual(self.leftovers(), [])
        self.assertFalse((self.library / 'tool').exists())

    # Release catalog

    def catalog_recipe(self, toolchain='tool', **values):
        recipe = {'schema': 2, 'name': toolchain, 'version': '1.0',
                  'sources': [{'image': DIGEST, 'path': '/opt/' + toolchain}],
                  'path': ['bin'], 'env': {}, 'check': [toolchain], 'default': False}
        recipe.update(values)
        return recipe

    def use_catalog(self, *recipes):
        directory = self.base / 'catalog'
        directory.mkdir()
        for recipe in recipes:
            (directory / (recipe['name'] + '.json')).write_text(json.dumps(recipe))
        patcher = patch.object(toolchains, 'CATALOG', directory)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_add_by_catalog_name(self):
        self.engine.image_tar = tool_archive(prefix='tool')
        self.use_catalog(self.catalog_recipe(), self.catalog_recipe('other'))
        toolchains.add(self.library, 'tool', self.env)
        self.assertTrue((self.library / 'tool/bin/tool').is_file())
        self.assertIn(['cp', 'c' * 64 + ':/opt/tool', '-'], self.engine.calls)
        self.assertEqual([item['name'] for item in self.index()['toolchains']], ['tool'])

    def test_unknown_catalog_name_fetches_nothing(self):
        self.use_catalog(self.catalog_recipe(), self.catalog_recipe('other'))
        with self.assertRaises(common.SetupError) as raised:
            toolchains.add(self.library, 'tol', self.env)
        self.assertIn('No catalog recipe named tol; available: other, tool', str(raised.exception))
        self.assertEqual(self.engine.calls, [])
        self.assertFalse(self.library.exists())

    def test_list_shows_available_catalog_recipes(self):
        self.engine.image_tar = tool_archive(prefix='tool')
        self.use_catalog(self.catalog_recipe(), self.catalog_recipe('other', version='2.0', requires=['tool']))
        toolchains.add(self.library, 'tool', self.env)
        lines = toolchains.listing(self.library, self.env)
        self.assertEqual(lines[0], 'Toolchain library: ' + str(self.library))
        self.assertTrue(lines[1].startswith('tool\t1.0\tdefault=no\t'), lines)
        self.assertEqual(lines[2:], ['Available in the catalog (add <name>):',
                                     'other\t2.0\tdefault=no\trequires=tool\tavailable'])

    def test_catalog_accepts_only_pinned_remote_sources(self):
        cases = {
            'tag-only image': {'sources': [{'image': 'docker.io/library/example:1', 'path': '/opt/tool'}]},
            'plain HTTP URL': {'sources': [{'url': 'http://example.org/t.tar', 'sha256': 'a' * 64}]},
            'URL without SHA-256': {'sources': [{'url': 'https://example.org/t.tar'}]},
            'local archive': {'sources': [{'archive': '/srv/t.tar', 'sha256': 'a' * 64}]},
            'name differs from the file': {'name': 'renamed'},
        }
        for index, (label, values) in enumerate(cases.items()):
            with self.subTest(label=label):
                directory = self.base / ('catalog-' + str(index))
                directory.mkdir()
                (directory / 'tool.json').write_text(json.dumps(self.catalog_recipe(**values)))
                with self.assertRaises(common.SetupError):
                    toolchains.catalog(directory)

    # Recipe location

    def project_recipe(self, relative, archive_inside=False):
        """A project directory, a recipe at project/relative, and its local archive."""
        project = self.base / 'projects/app'
        project.mkdir(parents=True, exist_ok=True)
        recipe_path = self.base / relative
        recipe_path.parent.mkdir(parents=True, exist_ok=True)
        data = tool_archive()
        archive = (project if archive_inside else self.base) / 'tool-archive.tar'
        archive.write_bytes(data)
        recipe = json.loads(self.recipe().read_text())
        recipe['source'] = {'archive': str(archive), 'sha256': hashlib.sha256(data).hexdigest(), 'strip_components': 1}
        recipe_path.write_text(json.dumps(recipe))
        os.chdir(project)
        return recipe_path

    def assert_location_refused(self, argument, inside):
        with self.assertRaises(common.SetupError) as raised:
            toolchains.add(self.library, argument, self.env)
        self.assertIn('is inside ' + str(inside), str(raised.exception))
        self.assertEqual(self.engine.calls, [])
        self.assertFalse(self.library.exists())

    def test_recipe_in_the_workspace_is_refused(self):
        self.project_recipe('projects/app/tools/java.json')
        self.assert_location_refused('tools/java.json', self.base / 'projects/app')

    def test_recipe_kept_outside_is_accepted(self):
        recipe = self.project_recipe('recipes/java.json')
        toolchains.add(self.library, str(recipe), self.env)
        self.assertTrue((self.library / 'tool/bin/tool').is_file())

    def test_saved_worktree_scope_widens_the_refusal(self):
        recipe = self.project_recipe('projects/sibling/java.json')
        with patch.object(toolchains, 'saved_worktree_scope', return_value=True):
            self.assert_location_refused(str(recipe), self.base / 'projects')
        # Without the scope, sessions started from the project do not mount its siblings.
        toolchains.add(self.library, str(recipe), self.env)
        self.assertTrue((self.library / 'tool').is_dir())

    def test_recipe_in_a_state_directory_is_refused(self):
        recipe = self.project_recipe('state/java.json')
        self.env[name('STATE_DIR')] = str(self.base / 'state')
        self.assert_location_refused(str(recipe), self.base / 'state')

    def test_local_archive_in_the_workspace_is_accepted(self):
        recipe = self.project_recipe('recipes/java.json', archive_inside=True)
        toolchains.add(self.library, str(recipe), self.env)
        self.assertTrue((self.library / 'tool/bin/tool').is_file())

    def test_catalog_recipes_are_not_location_checked(self):
        # The release catalog may lie below the current directory, as in a checkout.
        self.engine.image_tar = tool_archive(prefix='tool')
        self.use_catalog(self.catalog_recipe())
        os.chdir(self.base)
        toolchains.add(self.library, 'tool', self.env)
        self.assertTrue((self.library / 'tool/bin/tool').is_file())

    def test_saved_worktree_scope_is_read_from_the_release(self):
        release = self.base / 'release'
        release.mkdir()
        with patch.object(toolchains, 'INSTALLATION', release):
            self.assertFalse(toolchains.saved_worktree_scope())
            for saved, expected in (({'worktree': True}, True), ({'worktree': False}, False), ({}, False)):
                (release / 'setup.json').write_text(json.dumps(saved))
                self.assertEqual(toolchains.saved_worktree_scope(), expected, saved)
            (release / 'setup.json').write_text('{not json')
            with self.assertRaises(common.SetupError):
                toolchains.saved_worktree_scope()

    # Windows paths from the Windows entry

    def windows_entry(self):
        """A fake mountinfo with C: mounted on a directory of the test, as in a Podman machine."""
        self.drive = self.base / 'mnt/c'
        self.drive.mkdir(parents=True)
        mountinfo = self.base / 'mountinfo'
        mountinfo.write_text(
            '785 645 0:138 / ' + str(self.drive) + ' rw,noatime shared:266 - 9p C:\\134 '
            'rw,aname=drvfs;path=C:\\;uid=1000;gid=1000;symlinkroot=/mnt/,cache=0x5\n'
            '864 645 0:138 /Users/me/AppData/Roaming/containers /etc/containers rw,noatime shared:266 - 9p C:\\134 '
            'rw,aname=drvfs;path=C:\\;uid=1000;gid=1000\n')
        patcher = patch.object(toolchains, 'MOUNTINFO', mountinfo)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.env[common.WINDOWS_ENTRY] = '/mnt/c/Programs/sandbox'

    def windows_recipe(self, archive, schema=1):
        """C:\\Work\\recipes\\java.json naming the given archive path, with C:\\Work\\recipes\\tool.tar present."""
        recipes = self.drive / 'Work/recipes'
        recipes.mkdir(parents=True, exist_ok=True)
        data = tool_archive()
        (recipes / 'tool.tar').write_bytes(data)
        recipe = json.loads(self.recipe().read_text())
        source = {'archive': archive, 'sha256': hashlib.sha256(data).hexdigest(), 'strip_components': 1}
        if schema == 1:
            recipe['source'] = source
        else:
            del recipe['source']
            recipe.update(schema=2, sources=[source])
        (recipes / 'java.json').write_text(json.dumps(recipe))

    def test_drive_mounts_come_from_mountinfo(self):
        mountinfo = self.base / 'mountinfo'
        mountinfo.write_text(
            '785 645 0:138 / /mnt/c rw - 9p C:\\134 rw,aname=drvfs;path=C:\\;uid=1000\n'
            '864 645 0:138 /Users/me /etc/containers rw - 9p C:\\134 rw,aname=drvfs;path=C:\\;uid=1000\n'
            '900 645 0:140 / /mnt/d\\040disk rw - 9p D:\\134 rw,aname=drvfs;path=D:\\;uid=1000\n'
            '901 645 0:141 / /mnt/e rw - 9p E:\\134Data rw,aname=drvfs;path=E:\\Data;uid=1000\n'
            '902 645 0:142 / /data rw - ext4 /dev/sdb rw\n')
        with patch.object(toolchains, 'MOUNTINFO', mountinfo):
            # Whole drives only: a bind of a subdirectory and a drive subdirectory are not drive roots.
            self.assertEqual(toolchains.drive_mounts(), {'c': '/mnt/c', 'd': '/mnt/d disk'})
        with patch.object(toolchains, 'MOUNTINFO', self.base / 'missing'):
            self.assertEqual(toolchains.drive_mounts(), {})

    def test_windows_recipe_and_archive_paths_are_translated(self):
        self.windows_entry()
        self.windows_recipe('C:\\Work\\recipes\\tool.tar')
        with patch.object(toolchains, 'drive_mounts', wraps=toolchains.drive_mounts) as mounts:
            toolchains.add(self.library, 'C:\\Work\\recipes\\java.json', self.env)
        self.assertTrue((self.library / 'tool/bin/tool').is_file())
        # The recipe path and its archive path.
        self.assertEqual(mounts.call_count, 2)
        # Schema 2, forward slashes and another letter case.
        self.windows_recipe('c:/Work/recipes/tool.tar', schema=2)
        toolchains.add(self.library, 'C:/Work/recipes/java.json', self.env)
        manifest = json.loads((self.library / 'tool/toolchain.json').read_text())
        self.assertEqual(manifest['source'][0]['archive'], 'tool.tar')

    def test_windows_network_wsl_unmounted_and_missing_paths_are_refused(self):
        self.windows_entry()
        cases = {
            '\\\\server\\share\\java.json': 'network or device path',
            '\\\\wsl.localhost\\Ubuntu\\home\\java.json': 'inside a WSL distribution',
            '\\\\wsl$\\Ubuntu\\home\\java.json': 'inside a WSL distribution',
            'Z:\\recipes\\java.json': 'is on drive Z:, which this distribution does not mount',
            'C:\\Work\\missing.json': 'C:\\Work\\missing.json does not exist (' + str(self.drive) + '/Work/missing.json',
        }
        for argument, message in cases.items():
            with self.subTest(argument=argument), self.assertRaises(common.SetupError) as raised:
                toolchains.add(self.library, argument, self.env)
            self.assertIn(message, str(raised.exception))
        # The archive of a recipe on a Windows drive follows the same rules.
        self.windows_recipe('\\\\server\\share\\tool.tar')
        with self.assertRaises(common.SetupError) as raised:
            toolchains.add(self.library, 'C:\\Work\\recipes\\java.json', self.env)
        self.assertIn('network or device path', str(raised.exception))
        self.assertEqual(self.engine.calls, [])
        self.assertFalse(self.library.exists())

    def test_windows_paths_unchanged_outside_the_windows_entry(self):
        self.windows_entry()
        del self.env[common.WINDOWS_ENTRY]
        with patch.object(toolchains, 'drive_mounts') as mounts, self.assertRaises(common.SetupError) as raised:
            toolchains.add(self.library, 'C:\\Work\\recipes\\java.json', self.env)
        # A relative file name for Linux, like any other: no translation.
        self.assertIn(str(self.cwd / 'C:\\Work\\recipes\\java.json'), str(raised.exception))
        mounts.assert_not_called()

    def test_release_catalog_is_pinned_and_installed(self):
        directory = ROOT / 'setup/toolchain-catalog'
        files = sorted('setup/toolchain-catalog/' + path.name for path in directory.glob('*.json'))
        self.assertTrue(files)
        # Every recipe in the directory reaches releases and the Windows installed copy.
        self.assertEqual(sorted(common.TOOLCHAIN_CATALOG), files)
        self.assertLessEqual(set(common.TOOLCHAIN_CATALOG), set(common.MANIFEST))
        recipes = toolchains.catalog(directory)
        self.assertEqual(sorted(recipes), sorted(Path(name).stem for name in files))
        for toolchain, recipe in recipes.items():
            for source in recipe['sources']:
                with self.subTest(toolchain=toolchain, source=source):
                    if 'image' in source:
                        self.assertRegex(source['image'], r'@sha256:[a-f0-9]{64}$')
                    else:
                        self.assertTrue(source['url'].startswith('https://'))
                        self.assertRegex(source['sha256'], r'^[a-f0-9]{64}$')

    # Verification

    def test_check_runs_hardened_without_network(self):
        self.add()
        run = next(call for call in self.engine.calls if call[:1] == ['run'])
        for flag in ('--rm', '--network=none', '--read-only', '--userns=keep-id', '--cap-drop=all',
                     '--security-opt=no-new-privileges', '--pull=never'):
            self.assertIn(flag, run)
        self.assertIn(f'{os.getuid()}:{os.getgid()}', run)
        self.assertEqual(run[run.index('--workdir') + 1], '/')
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
        self.assertEqual(entry['source'], [{'archive': 'tool-tool.tar',
                                            'sha256': json.loads(self.recipe().read_text())['source']['sha256']}])
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

    def test_launch_env_rejects_the_bus_variable_in_the_index(self):
        # No wrapper provides a session bus, and --unsetenv does not remove a
        # value given with --env, so the variable is neutral and fails launches.
        self.add(name='java', env={'JAVA_HOME': {'toolchain': ''}}, archive_bytes=tool_archive(command='java'),
                 check=['java'])
        index = json.loads((self.library / 'index.json').read_text())
        index['toolchains'][0]['env']['DBUS_SESSION_BUS_ADDRESS'] = 'unix:path=/tmp/bus'
        (self.library / 'index.json').write_text(json.dumps(index))
        with self.assertRaises(common.SetupError) as raised:
            toolchains.launch_env(self.library, BASE)
        self.assertIn('DBUS_SESSION_BUS_ADDRESS', str(raised.exception))

    def test_launch_env_leaves_out_profile_variables_from_the_shared_index(self):
        # Another wrapper may have installed a toolchain that sets a variable
        # this profile protects: the session starts without that variable only.
        self.add(name='java', env={'JAVA_HOME': {'toolchain': ''}}, archive_bytes=tool_archive(command='java'),
                 check=['java'])
        variable = (PROFILE.credential_envs or (PROFILE.config_dir_env,))[0]
        index = json.loads((self.library / 'index.json').read_text())
        index['toolchains'][0]['env'][variable] = 'from-another-wrapper'
        index['toolchains'][0]['env'][PROFILE.env('IMAGE')] = 'from-another-wrapper'
        (self.library / 'index.json').write_text(json.dumps(index))
        lines, warnings = toolchains.launch_env(self.library, BASE)
        self.assertEqual(lines, [('path', '/toolchains/java/bin'), ('env', 'JAVA_HOME', '/toolchains/java')])
        self.assertEqual(len(warnings), 2)
        for name in (variable, PROFILE.env('IMAGE')):
            self.assertTrue(any(name in warning and 'toolchain java' in warning for warning in warnings), warnings)

    @contextlib.contextmanager
    def agent_variables(self, *entries):
        # The shared tests declare their own agent variables, whatever this profile lists.
        value = json.loads(json.dumps(PROFILE.value))
        value['native']['protected_env'] = list(entries)
        names, prefixes = toolchains.profile_protection(toolchains.agent_profile.validate(value))
        with patch.multiple(toolchains, PROFILE_PROTECTED=names, PROFILE_PREFIXES=prefixes):
            yield

    def test_add_rejects_agent_variables(self):
        with self.agent_variables('AGENT_FLAG', 'AGENT_CODE_'):
            for variable in ('AGENT_FLAG', 'AGENT_CODE_MODE', 'agent_code_mode'):
                with self.subTest(variable=variable), self.assertRaises(common.SetupError) as raised:
                    self.add(name='java', env={variable: {'value': 'x'}}, archive_bytes=tool_archive(command='java'),
                             check=['java'])
                self.assertIn('protected', str(raised.exception))
                self.assertFalse((self.library / 'java').exists())
            # A name that only shares the start of an agent variable is not protected.
            self.add(name='java', env={'AGENT_FLAGS': {'value': 'x'}}, archive_bytes=tool_archive(command='java'),
                     check=['java'])

    def test_launch_env_leaves_out_agent_variables_from_the_shared_index(self):
        self.add(name='java', env={'JAVA_HOME': {'toolchain': ''}}, archive_bytes=tool_archive(command='java'),
                 check=['java'])
        index = json.loads((self.library / 'index.json').read_text())
        index['toolchains'][0]['env'].update(AGENT_FLAG='1', AGENT_CODE_MODE='allow')
        (self.library / 'index.json').write_text(json.dumps(index))
        with self.agent_variables('AGENT_FLAG', 'AGENT_CODE_'):
            lines, warnings = toolchains.launch_env(self.library, BASE)
        self.assertEqual(lines, [('path', '/toolchains/java/bin'), ('env', 'JAVA_HOME', '/toolchains/java')])
        self.assertEqual(len(warnings), 2)
        for variable in ('AGENT_FLAG', 'AGENT_CODE_MODE'):
            self.assertTrue(any(variable in warning and 'toolchain java' in warning for warning in warnings), warnings)

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

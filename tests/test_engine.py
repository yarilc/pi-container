"""Session container engine: shared build inputs (session-container-engine, design D3)."""
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import time
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from sandbox_profile import ROOT  # noqa: E402

sys.path.insert(0, str(ROOT / 'setup'))
import common  # noqa: E402
import engine  # noqa: E402

ENGINE = ROOT / 'launcher/engine'
# An -immutable tag: quay.io deletes the manifests of the other podman/stable tags when it rebuilds them.
PINNED_BASE = re.compile(r'quay\.io/podman/stable:v[0-9]+(\.[0-9]+)*-immutable@sha256:[a-f0-9]{64}')
# Defaults of the base image that the engine must not keep (design D3).
REMOVED = ('/usr/share/containers/containers.conf.d/00-vendor.conf',
           '/etc/containers/containers.rootless.conf.d/20-image_build.conf')
EMPTIED = ('/etc/containers/mounts.conf', '/usr/share/containers/mounts.conf')


def recipe_violations(recipe):
    """What makes an engine recipe unacceptable: unpinned, networked or keeping base defaults."""
    found = []
    bases = re.findall(r'(?im)^\s*FROM\s+(\S+)', recipe)
    if len(bases) != 1 or not PINNED_BASE.fullmatch(bases[0]):
        found.append('the base must be one quay.io/podman/stable -immutable tag pinned by digest')
    if re.search(r'(?i)\b(dnf|yum|microdnf|curl|wget|pip)\b', recipe):
        found.append('the recipe must build without fetching anything')
    for path in REMOVED:
        if path not in recipe:
            found.append('keeps ' + path)
    for path in EMPTIED:
        if ': > ' + path not in recipe:
            found.append('does not empty ' + path)
    if not re.search(r'(?m)^USER podman$', recipe):
        found.append('the engine must run as the unprivileged podman user')
    if 'COPY containers.conf /etc/containers/containers.conf' not in recipe:
        found.append('does not replace containers.conf')
    # session-container-engine: Engine image declares its capabilities.
    options = engine.container_options(name='recipe-check', seccomp='/seccomp.json', store='/store')
    granted = next(value.removeprefix('--cap-add=') for value in options if value.startswith('--cap-add='))
    labels = re.findall(r'(?m)^LABEL io\.containers\.capabilities="([^"]*)"$', recipe)
    if labels != [granted]:
        found.append(f'the capability label must be exactly {granted!r}, the engine options; found {labels}')
    return found


def configuration_violations(text):
    found = []
    settings = dict(re.findall(r'(?m)^\s*([a-z_]+)\s*=\s*(.+?)\s*$', text))
    for key in ('netns', 'pidns', 'ipcns', 'utsns', 'userns', 'cgroupns', 'cgroups', 'volumes', 'mounts'):
        if key in settings:
            found.append(key + ' must keep the rootless default')
    if settings.get('log_driver') != '"k8s-file"':
        found.append('log_driver must be k8s-file')
    if settings.get('runtime') != '"crun"':
        found.append('runtime must be crun')
    return found


class EngineRecipeTests(unittest.TestCase):
    def setUp(self):
        self.recipe = (ENGINE / 'Containerfile').read_text()
        self.configuration = (ENGINE / 'containers.conf').read_text()

    def test_recipe_is_pinned_offline_and_replaces_base_defaults(self):
        self.assertEqual(recipe_violations(self.recipe), [])
        cases = {
            'tag only': self.recipe.replace(re.search(r'@sha256:[a-f0-9]{64}', self.recipe).group(0), ''),
            'rebuilt tag': self.recipe.replace('-immutable@sha256:', '@sha256:'),
            'second base': self.recipe + '\nFROM docker.io/library/alpine@sha256:' + 'a' * 64 + '\n',
            'package install': self.recipe.replace('RUN rm -f', 'RUN dnf -y install strace && rm -f'),
            'journald kept': self.recipe.replace(REMOVED[0], '/nonexistent'),
            'host /proc kept': self.recipe.replace(REMOVED[1], '/nonexistent'),
            'secrets passthrough kept': self.recipe.replace(': > ' + EMPTIED[0], 'true'),
            'root engine': self.recipe.replace('USER podman', 'USER root'),
            # The base image's label, kept, asks for capabilities the options drop.
            'base capability label': re.sub(r'(?m)^LABEL io\.containers\.capabilities=.*\n', '', self.recipe),
            'wider capability label': self.recipe.replace('SYS_CHROOT,CHOWN"', 'SYS_CHROOT,CHOWN,KILL"'),
            'narrower capability label': self.recipe.replace('SYS_CHROOT,CHOWN"', 'SYS_CHROOT"'),
        }
        for name, mutated in cases.items():
            with self.subTest(name=name):
                self.assertNotEqual(mutated, self.recipe)
                self.assertTrue(recipe_violations(mutated))

    def test_configuration_keeps_private_namespaces(self):
        self.assertEqual(configuration_violations(self.configuration), [])
        for setting in ('utsns = "host"', 'cgroups = "disabled"', 'volumes = ["/proc:/proc"]', 'netns = "host"'):
            with self.subTest(setting=setting):
                mutated = self.configuration.replace('[containers]\n', '[containers]\n' + setting + '\n')
                self.assertTrue(configuration_violations(mutated))
        self.assertTrue(configuration_violations(self.configuration.replace('k8s-file', 'journald')))

    def test_build_context_admits_only_engine_inputs(self):
        ignore = (ENGINE / '.containerignore').read_text().splitlines()
        admitted = sorted(line[1:] for line in ignore if line.startswith('!'))
        self.assertEqual(ignore[ignore.index('**')], '**')
        self.assertEqual(admitted, ['.containerignore', 'Containerfile', 'cgroup.sh', 'containers.conf', 'entrypoint.sh',
                                    'podman-build-secret*', 'resolv.conf', 'start.sh', 'storage.conf'])
        # The engine's resolver is the restricted sessions' one.
        self.assertEqual((ENGINE / 'resolv.conf').read_text(), (ROOT / 'network/resolv.conf').read_text())

    def test_storage_lives_on_a_neutral_path(self):
        # A workspace mounted at the same path never shadows the engine's storage.
        storage = (ENGINE / 'storage.conf').read_text()
        self.assertIn('rootless_storage_path = "' + engine.STORAGE + '/storage"', storage)
        self.assertIn('COPY storage.conf /etc/containers/storage.rootless.conf.d/', self.recipe)
        self.assertIn(engine.STORAGE, self.recipe)
        self.assertFalse(engine.STORAGE.startswith('/home/'))

    def test_entrypoint_serves_loopback_and_unix_socket(self):
        entrypoint = (ENGINE / 'entrypoint.sh').read_text()
        self.assertIn('tcp://127.0.0.1:$port', entrypoint)
        self.assertIn('unix://$socket', entrypoint)
        self.assertNotIn('0.0.0.0', entrypoint)
        self.assertIn('ENV XDG_RUNTIME_DIR=/run/user/1000', self.recipe)

    def test_startup_program_is_the_entrypoint(self):
        # support-nested-systemd-containers, design D1: the image starts the startup
        # program, which runs the services; any other use starts as podman.
        self.assertIn('ENTRYPOINT ["/usr/local/bin/sandbox-engine-start"]', self.recipe)
        for line in ('COPY --chmod=0755 start.sh /usr/local/bin/sandbox-engine-start',
                     'COPY --chmod=0755 cgroup.sh /usr/local/bin/sandbox-engine-cgroup',
                     'COPY --chmod=0755 entrypoint.sh /usr/local/bin/sandbox-engine'):
            self.assertIn(line, self.recipe)
        # The build fails when the base image loses the programs of the hand-over.
        self.assertIn('test -x /usr/libexec/podman/catatonit && command -v capsh', self.recipe)
        self.assertLess(self.recipe.index('ENTRYPOINT'), len(self.recipe))
        self.assertLess(self.recipe.index('USER podman'), self.recipe.index('ENTRYPOINT'))

    def stubs(self, base):
        """A copy of the startup program whose hand-over targets are recording stubs."""
        (base / 'bin').mkdir()
        recorder = ('#!/usr/bin/env python3\nimport os, sys\n'
                    'row = next(line for line in open("/proc/self/limits") if line.startswith("Max processes"))\n'
                    'with open(os.environ["LOG"], "a") as log:\n'
                    '    log.write(" ".join([*row.split()[2:4], os.path.basename(sys.argv[0]), *sys.argv[1:]]) + "\\n")\n')
        for name in ('catatonit', 'sandbox-engine', 'sandbox-engine-cgroup'):
            (base / 'bin' / name).write_text(recorder)
            (base / 'bin' / name).chmod(0o700)
        start = (ENGINE / 'start.sh').read_text()
        for constant in ('engine_cgroup=/usr/local/bin/sandbox-engine-cgroup', 'catatonit=/usr/libexec/podman/catatonit',
                         'services=/usr/local/bin/sandbox-engine'):
            self.assertEqual(start.count(constant + '\n'), 1, constant)
            name, value = constant.split('=')
            start = start.replace(constant + '\n', f'{name}={base / "bin" / Path(value).name}\n')
        (base / 'start.sh').write_text(start)

    def test_startup_program_sets_the_process_limit_after_the_port(self):
        # set-process-limits-inside-containers, design D2, moved to the engine's first
        # process (support-nested-systemd-containers, design D1): the limit after the
        # port is set before anything else; invalid arguments start nothing.
        import resource
        hard = resource.getrlimit(resource.RLIMIT_NPROC)[1]
        if hard != resource.RLIM_INFINITY and hard < 64:
            self.skipTest('the process rlimit of this test is below 64')
        root = os.getuid() == 0
        chosen = '999' if hard == resource.RLIM_INFINITY else str(hard - 1)
        # The stubs must be executable: SANDBOX_TEST_TMPDIR when /tmp is noexec.
        with tempfile.TemporaryDirectory(dir=os.environ.get('SANDBOX_TEST_TMPDIR')) as temporary:
            base = Path(temporary)
            self.stubs(base)
            for shell in ('sh', 'bash'):
                for arguments, status, limit, port in (
                        ([], 0, None, '2375'), (['2400'], 0, None, '2400'), (['2375', chosen], 0, chosen, '2375'),
                        (['2375', '0'], 2, None, None), (['2375', '012'], 2, None, None),
                        (['2375', '-1'], 2, None, None), (['2375', 'x'], 2, None, None), (['2375', ''], 2, None, None),
                        (['x'], 2, None, None), (['2375', chosen, 'x'], 2, None, None),
                        *([] if hard == resource.RLIM_INFINITY else [(['2375', str(hard + 1)], 'failed', None, None)])):
                    if root and port is not None:
                        continue  # As root the program delegates and hands over: the runtime tests cover it.
                    with self.subTest(shell=shell, arguments=arguments):
                        log = base / 'calls.log'
                        log.unlink(missing_ok=True)
                        result = subprocess.run([shell, str(base / 'start.sh'), *arguments],
                                                env={'PATH': '/usr/bin:/bin', 'LOG': str(log)},
                                                capture_output=True, text=True, timeout=30)
                        if status == 'failed':
                            self.assertNotEqual(result.returncode, 0)
                        else:
                            self.assertEqual(result.returncode, status, result.stderr)
                        if port is None:
                            self.assertFalse(log.exists())
                            continue
                        # Not root: nothing is delegated, and catatonit runs the services.
                        self.assertIn('not started as root; nothing delegated', result.stderr)
                        soft, hard_value, program, *rest = log.read_text().split()
                        self.assertEqual((program, rest), ('catatonit', ['--', str(base / 'bin/sandbox-engine'), port]))
                        if limit:
                            self.assertEqual((soft, hard_value), (limit, limit))
                        else:
                            self.assertNotEqual((soft, hard_value), (chosen, chosen))

    def test_startup_program_delegates_only_its_subtree_then_hands_over(self):
        # support-nested-systemd-containers, design D1 and D3: the order of the steps,
        # the files the delegation writes, and the capabilities of the hand-over.
        start = (ENGINE / 'start.sh').read_text()
        order = ['ulimit -u "$2"', 'if [ "$(id -u)" != 0 ]', 'state=$("$engine_cgroup")', 'mkdir -- "$cg/engine"',
                 '>"$cg/engine/cgroup.procs"', '>"$cg/cgroup.subtree_control"', 'chown 1000:1000 --',
                 '[ "$state" = delegated ] || fail', "'ineligible: '*)", 'exec capsh --user=podman']
        positions = [start.index(step) for step in order]
        self.assertEqual(positions, sorted(positions))
        # The delegation hands over the kernel's delegation files of the root and the leaf, nothing else.
        chown = re.search(r'chown 1000:1000 -- (.+?) \|\|', start, re.S).group(1)
        self.assertEqual(chown.replace('\\\n', ' ').split(),
                         [f'"$cg{leaf}{name}"' for leaf in ('', '/engine')
                          for name in ('', '/cgroup.procs', '/cgroup.subtree_control', '/cgroup.threads')])
        self.assertEqual(len(re.findall(r'\bchown\b', start)), 1)
        self.assertNotRegex(start, r'\bchmod\b|cgroup\.kill|cgroup\.freeze|memory\.|pids\.|cpu\.')
        # The engine's three capabilities, as ambient ones; no others.
        self.assertIn("--caps='cap_setuid,cap_setgid,cap_sys_chroot+eip'", start)
        self.assertIn('--addamb=cap_setuid,cap_setgid,cap_sys_chroot', start)
        self.assertIn('exec "$1" -- "$2" "$3"\' sandbox-engine-start "$catatonit" "$services" "$port"', start)
        # A failed delegation stops the engine; it never falls back.
        self.assertIn("fail 'cannot enable the cgroup controllers for nested containers'", start)
        self.assertIn('*)\n        fail "unexpected cgroup state: $state"', start)

    def test_entrypoint_serves_only_the_port(self):
        # The startup program sets the process limit; the services take the port only.
        with tempfile.TemporaryDirectory(dir=os.environ.get('SANDBOX_TEST_TMPDIR')) as temporary:
            base = Path(temporary)
            (base / 'bin').mkdir()
            podman = base / 'bin/podman'
            # One file per call: appends of concurrent processes may interleave on some file systems.
            podman.write_text('#!/usr/bin/env python3\nimport os, sys\n'
                              'with open(os.environ["LOG"] + "." + str(os.getpid()), "w") as log:\n'
                              '    log.write(" ".join(sys.argv[1:]))\n')
            podman.chmod(0o700)
            for shell in ('sh', 'bash'):
                for arguments, status, port in (([], 0, '2375'), ([''], 0, '2375'), (['2400'], 0, '2400'),
                                                (['x'], 2, None), (['2375', '512'], 2, None)):
                    with self.subTest(shell=shell, arguments=arguments):
                        logs = base / 'calls'
                        shutil.rmtree(logs, ignore_errors=True)
                        logs.mkdir()
                        result = subprocess.run([shell, str(ENGINE / 'entrypoint.sh'), *arguments],
                                                env={'PATH': f'{base / "bin"}:/usr/bin:/bin', 'LOG': str(logs / 'call'),
                                                     'XDG_RUNTIME_DIR': str(base / 'run')},
                                                capture_output=True, text=True, timeout=30)
                        self.assertEqual(result.returncode, status, result.stderr)
                        if port is None:
                            self.assertEqual(list(logs.iterdir()), [])
                            continue
                        for _ in range(100):
                            calls = [call.read_text() for call in logs.iterdir()]
                            if len(calls) == 2 and all(calls):
                                break
                            time.sleep(0.05)
                        self.assertEqual(sorted(calls), [f'system service --time=0 tcp://127.0.0.1:{port}',
                                                         f'system service --time=0 unix://{base}/run/podman/podman.sock'])

    def test_engine_inputs_are_installed(self):
        for path in sorted(ENGINE.iterdir()):
            with self.subTest(path=path.name):
                self.assertIn('launcher/engine/' + path.name, common.MANIFEST)


class EngineCgroupTests(unittest.TestCase):
    """The engine's eligibility rule (support-nested-systemd-containers, design D2)."""

    MOUNT = '1297 1296 0:25 {root} {point} {options} - {fstype} cgroup2 {super}\n'

    def setUp(self):
        # The stub must be executable: SANDBOX_TEST_TMPDIR when /tmp is noexec.
        self.base = Path(tempfile.mkdtemp(dir=os.environ.get('SANDBOX_TEST_TMPDIR')))
        self.addCleanup(shutil.rmtree, self.base, True)
        self.root = self.base / 'cgroup'
        (self.root / 'engine').mkdir(parents=True)
        # Ownership comes from a stat stub: tests cannot create files owned by 0:0.
        (self.base / 'bin').mkdir()
        stub = self.base / 'bin/stat'
        stub.write_text('#!/usr/bin/env python3\nimport json, os, sys\n'
                        'owners = json.loads(os.environ["OWNERS"])\n'
                        'path = sys.argv[-1]\n'
                        'sys.exit(1) if path not in owners else print(owners[path])\n')
        stub.chmod(0o700)

    def state(self, membership='0::/', root='/', point=None, options='rw,nosuid,nodev,noexec,relatime',
              fstype='cgroup2', super_options='rw,nsdelegate', owner='0:0', leaf='0:0', mounts=None, shell='sh'):
        (self.base / 'init-cgroup').write_text(membership)
        if mounts is None:
            mounts = [dict(root=root, point=point or str(self.root), options=options, fstype=fstype, super=super_options)]
        (self.base / 'mountinfo').write_text(
            '22 1 0:21 / /proc rw,nosuid - proc proc rw\n' + ''.join(self.MOUNT.format(**mount) for mount in mounts))
        owners = {str(self.root): owner, str(self.root / 'engine'): leaf}
        result = subprocess.run([shell, str(ENGINE / 'cgroup.sh'), str(self.base / 'init-cgroup'),
                                 str(self.base / 'mountinfo'), str(self.root)],
                                env={'PATH': f'{self.base / "bin"}:/usr/bin:/bin', 'OWNERS': json.dumps(owners)},
                                capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)
        return result.stdout.strip()

    def test_eligible_and_delegated(self):
        for shell in ('sh', 'bash'):
            with self.subTest(shell=shell):
                self.assertEqual(self.state(shell=shell), 'eligible')
                self.assertEqual(self.state(membership='0::/engine\n', owner='1000:1000', leaf='1000:1000',
                                            shell=shell), 'delegated')
                # The Windows Podman machine and native Linux differ only in controllers: not part of the rule.
                self.assertEqual(self.state(super_options='rw,nsdelegate,memory_recursiveprot', shell=shell),
                                 'eligible')

    def test_each_ineligible_reason(self):
        root = str(self.root)
        cases = {
            'cgroup v1 hierarchies are present': [
                dict(membership='12:memory:/user.slice\n0::/\n'), dict(membership='4:pids:/\n'), dict(membership='')],
            'the engine has no private cgroup namespace': [dict(root='/user.slice/libpod-0123.scope')],
            root + ' is mounted read-only': [dict(options='ro,nosuid,nodev,noexec,relatime')],
            root + ' is mounted without nsdelegate': [dict(super_options='rw')],
            root + ' is not a cgroup v2 hierarchy': [dict(fstype='tmpfs')],
            'no cgroup file system at ' + root: [dict(point='/sys/fs/other')],
            'the cgroup root belongs to': [
                dict(owner='1000:1000'), dict(owner='0:0', membership='0::/engine'),
                dict(owner='1000:1000', membership='0::/engine', leaf='0:0'), dict(owner='1001:1001')],
        }
        for reason, variants in cases.items():
            for variant in variants:
                with self.subTest(reason=reason, variant=variant):
                    self.assertTrue(self.state(**variant).startswith('ineligible: ' + reason), self.state(**variant))

    def test_the_last_mount_at_the_root_wins(self):
        mounts = [dict(root='/', point=str(self.root), options='rw', fstype='cgroup2', super='rw,nsdelegate'),
                  dict(root='/', point=str(self.root), options='ro,nosuid', fstype='cgroup2', super='rw,nsdelegate')]
        self.assertEqual(self.state(mounts=mounts), 'ineligible: ' + str(self.root) + ' is mounted read-only')
        self.assertEqual(self.state(mounts=mounts[::-1]), 'eligible')

    def test_unreadable_inputs_and_usage(self):
        result = subprocess.run(['sh', str(ENGINE / 'cgroup.sh'), str(self.base / 'missing'), '/dev/null', '/x'],
                                capture_output=True, text=True, timeout=30)
        self.assertEqual((result.returncode, result.stdout), (0, 'ineligible: the engine init cgroup is unreadable\n'))
        for arguments in (['a'], ['a', 'b'], ['a', 'b', 'c', 'd']):
            with self.subTest(arguments=arguments):
                result = subprocess.run(['sh', str(ENGINE / 'cgroup.sh'), *arguments],
                                        capture_output=True, text=True, timeout=30)
                self.assertEqual((result.returncode, result.stdout), (2, ''))


# The default profile's shape for the hostname calls: allowed with CAP_SYS_ADMIN, EPERM otherwise.
DEFAULT_PROFILE = {
    'defaultAction': 'SCMP_ACT_ERRNO', 'defaultErrnoRet': 38,
    'syscalls': [
        {'names': ['read', 'write'], 'action': 'SCMP_ACT_ALLOW'},
        {'names': ['setdomainname', 'sethostname'], 'action': 'SCMP_ACT_ALLOW',
         'includes': {'caps': ['CAP_SYS_ADMIN']}},
        {'names': ['mount', 'setdomainname', 'sethostname'], 'action': 'SCMP_ACT_ERRNO', 'errnoRet': 1,
         'excludes': {'caps': ['CAP_SYS_ADMIN']}},
    ],
}


class EngineSeccompTests(unittest.TestCase):
    def setUp(self):
        self.base = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.base, True)

    def test_profile_allows_only_the_hostname_calls_unconditionally(self):
        profile = engine.seccomp_profile(DEFAULT_PROFILE)
        self.assertEqual(profile['defaultAction'], 'SCMP_ACT_ERRNO')
        self.assertEqual(profile['defaultErrnoRet'], 38)
        rules = profile['syscalls']
        self.assertEqual(rules[0], DEFAULT_PROFILE['syscalls'][0])
        # The conditional allow lost both names and is gone; the denial keeps mount only.
        self.assertEqual(rules[1], {'names': ['mount'], 'action': 'SCMP_ACT_ERRNO', 'errnoRet': 1,
                                    'excludes': {'caps': ['CAP_SYS_ADMIN']}})
        self.assertEqual(rules[2], {'names': ['sethostname', 'setdomainname'], 'action': 'SCMP_ACT_ALLOW'})
        self.assertEqual(len(rules), 3)
        mentioned = [rule for rule in rules if set(engine.HOSTNAME_CALLS) & set(rule['names'])]
        self.assertEqual(len(mentioned), 1)
        self.assertNotIn('includes', mentioned[0])

    def test_written_profile_is_private_and_identified(self):
        source = self.base / 'default.json'
        source.write_text(json.dumps(DEFAULT_PROFILE))
        destination = self.base / 'seccomp.json'
        digest = engine.write_seccomp(source, destination)
        self.assertEqual(digest, hashlib.sha256(destination.read_bytes()).hexdigest())
        self.assertEqual(stat.S_IMODE(destination.stat().st_mode), 0o600)
        self.assertEqual(json.loads(destination.read_text()), engine.seccomp_profile(DEFAULT_PROFILE))
        self.assertEqual(engine.write_seccomp(source, destination), digest)
        for invalid in ('not json', json.dumps({'syscalls': 'none'}), json.dumps({'syscalls': [{'action': 'x'}]})):
            with self.subTest(invalid=invalid):
                source.write_text(invalid)
                with self.assertRaises(engine.EngineError):
                    engine.write_seccomp(source, destination)
        with self.assertRaises(engine.EngineError):
            engine.write_seccomp(self.base / 'missing.json', destination)

    def test_inputs_identity_covers_every_build_input(self):
        copy = self.base / 'release'
        for name in engine.INPUTS:
            (copy / name).parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(ROOT / name, copy / name)
        self.assertEqual(engine.inputs_identity(copy), engine.inputs_identity(ROOT))
        self.assertEqual(sorted(engine.INPUTS), sorted('launcher/engine/' + path.name for path in ENGINE.iterdir()))
        for name in engine.INPUTS:
            with self.subTest(name=name):
                original = (copy / name).read_bytes()
                (copy / name).write_bytes(original + b'\n')
                self.assertNotEqual(engine.inputs_identity(copy), engine.inputs_identity(ROOT))
                (copy / name).write_bytes(original)


class EngineOptionsTests(unittest.TestCase):
    def options(self, **extra):
        values = dict(name='project-0-engine', seccomp='/release/launcher/engine/seccomp.json',
                      store='/home/user/.local/share/sandbox-toolchains/.images')
        return engine.container_options(**(values | extra))

    def test_options_hold_exactly_the_documented_exceptions(self):
        # session-container-engine: Fixed engine hardening exceptions / Engine carries no secrets.
        # support-nested-systemd-containers: the startup step as the user namespace's root
        # with CHOWN, no --init (design D1).
        options = self.options()
        self.assertEqual(options, [
            '--name', 'project-0-engine', '--rm', '--user', '0:0', engine.USERNS, '--cap-drop=all',
            '--cap-add=SETUID,SETGID,SYS_CHROOT,CHOWN', '--security-opt=no-new-privileges',
            '--security-opt=unmask=ALL', '--security-opt=label=disable',
            '--security-opt=seccomp=/release/launcher/engine/seccomp.json', '--device=/dev/fuse',
            '--device=/dev/net/tun', '--http-proxy=false', '--mount', 'type=tmpfs,destination=/run/secrets,ro=true',
            '--volume', engine.STORAGE,
            '--volume', '/home/user/.local/share/sandbox-toolchains/.images/storage:/var/lib/shared:ro',
            '--label', engine.STORE_LABEL + '=/home/user/.local/share/sandbox-toolchains/.images'])
        self.assertNotIn('--init', options)
        for forbidden in ('--privileged', '--env', '--env-host', '--pid=host', '--network=host', '--userns=host'):
            self.assertFalse([value for value in options if value.startswith(forbidden)], forbidden)
        self.assertFalse([value for value in options if 'podman.sock' in value])
        # The image's own default user stays unprivileged for any other use of it.
        self.assertRegex((ENGINE / 'Containerfile').read_text(), r'(?m)^USER ' + engine.ENGINE_USER + '$')

    def test_mounts_are_storage_store_workspace_and_ca_only(self):
        # session-container-engine: Engine mounts only the workspace and the image store.
        options = self.options(mounts=['/home/user/project', '/home/user'], ca_bundle='/etc/ssl/ca.pem',
                               labels=['io.example.session=token'])
        volumes = [options[i + 1] for i, value in enumerate(options) if value == '--volume']
        self.assertEqual(volumes, [
            engine.STORAGE,
            '/home/user/.local/share/sandbox-toolchains/.images/storage:/var/lib/shared:ro',
            '/home/user/project:/home/user/project:rw', '/home/user:/home/user:rw',
            '/etc/ssl/ca.pem:' + engine.CA + ':ro'])
        labels = [options[i + 1] for i, value in enumerate(options) if value == '--label']
        self.assertEqual(labels, [engine.STORE_LABEL + '=/home/user/.local/share/sandbox-toolchains/.images',
                                  'io.example.session=token'])
        with self.assertRaises(engine.EngineError):
            self.options(mounts=['/work\nspace'])

    def test_command_line_prints_nul_separated_options(self):
        result = subprocess.run([sys.executable, '-I', str(ROOT / 'setup/engine.py'), 'options',
                                 '--name', 'n', '--seccomp', '/s.json', '--store', '/lib/.images',
                                 '--mount', '/w', '--label', 'a=b'], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.split('\0')[:-1],
                         engine.container_options(name='n', seccomp='/s.json', store='/lib/.images',
                                                  mounts=['/w'], labels=['a=b']))
        for argv in (['options', '--name', 'n'], ['options', '--bogus', 'x'], ['other']):
            with self.subTest(argv=argv):
                result = subprocess.run([sys.executable, '-I', str(ROOT / 'setup/engine.py'), *argv],
                                        capture_output=True, text=True)
                self.assertNotEqual(result.returncode, 0)


if __name__ == '__main__':
    unittest.main()

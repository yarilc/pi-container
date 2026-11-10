"""Opt-in real rootless Podman checks using disposable state and no credentials."""
import base64
import errno
import json
import os
from pathlib import Path
import pty
import select
import shlex
import shutil
import signal
import subprocess
import tempfile
import termios
import time
import unittest

ROOT = Path(__file__).resolve().parents[1]
WRAPPER = ROOT / 'pi-container.sh'
IMAGE = os.environ.get('PI_CONTAINER_IMAGE', 'localhost/pi-container')
ENABLED = os.environ.get('PI_RUNTIME_TESTS') == '1'


def terminal_shell(command, script, env, cwd, timeout=90):
    """Wait for interactive Bash, then feed one command through a PTY."""
    master, slave = pty.openpty()
    settings = termios.tcgetattr(slave)
    settings[3] &= ~termios.ECHO
    termios.tcsetattr(slave, termios.TCSANOW, settings)
    process = subprocess.Popen(command, stdin=slave, stdout=slave, stderr=slave,
                               cwd=cwd, env=env, start_new_session=True)
    os.close(slave)
    output = bytearray()
    sent = False
    encoded = base64.b64encode(script.encode()).decode()
    payload = f'exec /bin/bash -euc "$(printf %s {encoded} | base64 -d)"\n'.encode()
    deadline = time.monotonic() + timeout
    try:
        while time.monotonic() < deadline:
            if select.select([master], [], [], 0.1)[0]:
                try:
                    chunk = os.read(master, 65536)
                except OSError as exc:
                    if exc.errno == errno.EIO:
                        break
                    raise
                if not chunk:
                    break
                output.extend(chunk)
            if not sent and (b'$ ' in output or b'# ' in output):
                os.write(master, payload)
                sent = True
            if process.poll() is not None and not select.select([master], [], [], 0)[0]:
                break
        else:
            raise AssertionError('Runtime terminal timed out:\n' + output.decode(errors='replace'))
        status = process.wait(timeout=5)
        return subprocess.CompletedProcess(command, status, output.decode(errors='replace'), '')
    finally:
        if process.poll() is None:
            # Terminate this test's process group, including the attached client.
            import signal
            os.killpg(process.pid, signal.SIGTERM)
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                os.killpg(process.pid, signal.SIGKILL)
                process.wait()
        os.close(master)


@unittest.skipUnless(ENABLED, 'set PI_RUNTIME_TESTS=1 for real rootless Podman checks')
class RuntimeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Explicit opt-in failures remain failures, not skipped verification.
        info = subprocess.run(['podman', 'info', '--format',
                               '{{.Host.Security.Rootless}} {{.Host.OS}}'],
                              capture_output=True, text=True, timeout=20)
        if info.returncode or info.stdout.strip() != 'true linux':
            raise AssertionError('Real Linux rootless Podman is required:\n' + info.stdout + info.stderr)
        image = subprocess.run(['podman', 'image', 'exists', IMAGE], timeout=20)
        if image.returncode:
            raise AssertionError('Build the runtime image before opting into tests: ' + IMAGE)

    def setUp(self):
        parent = Path(os.environ.get('PI_TEST_ROOT', str(ROOT / '.test-state')))
        parent.mkdir(parents=True, exist_ok=True)
        self.base = Path(tempfile.mkdtemp(prefix='pi-runtime-', dir=parent)).resolve()
        self.addCleanup(shutil.rmtree, self.base)
        self.project = self.base / 'project with spaces'
        self.project.mkdir()
        self.home = self.base / 'home'
        self.home.mkdir(mode=0o700)
        self.state = self.home / '.pi'
        self.state.mkdir(mode=0o700)
        (self.home / '.agents').mkdir(mode=0o700)
        self.assertEqual(self.state.stat().st_mode & 0o777, 0o700,
                         'Select a native Linux PI_TEST_ROOT or use tests/run-runtime.sh')
        self.env = {k: v for k, v in os.environ.items()
                    if not k.startswith('PI_') and k not in ('CONTAINER_CONNECTION', 'ANTHROPIC_API_KEY', 'OPENAI_API_KEY', 'GOOGLE_API_KEY', 'GITHUB_TOKEN')}
        self.env.update(HOME=str(self.home), PI_CONTAINER_IMAGE=IMAGE, PI_CONTAINER_PODMAN='0',
                        PI_CONTAINER_NETWORK='unrestricted', PI_CONTAINER_MAINTENANCE='1')
        self.socket = os.environ.get('PI_CONTAINER_PODMAN_SOCKET', '')
        if not self.socket:
            connection = self.env.get('CONTAINER_HOST', '')
            if connection.startswith('unix:///'):
                self.socket = connection.removeprefix('unix://')
            else:
                self.socket = str(Path(os.environ.get('XDG_RUNTIME_DIR', f'/run/user/{os.getuid()}'))
                                  / 'podman/podman.sock')

    def shell(self, script, *options, **env):
        return terminal_shell(['bash', str(WRAPPER), '--container-shell', *options],
                              script, self.env | env, self.project, timeout=360 if env.get('PI_CONTAINER_PODMAN') == '1' or env.get('PI_ENABLE_BUN') else 90)

    def assert_success(self, result):
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def engine(self, *args, **kwargs):
        return subprocess.run(['podman', *args], capture_output=True, text=True,
                              timeout=kwargs.pop('timeout', 30), **kwargs)

    def pipe_shell(self, script, timeout=60):
        return subprocess.run(['bash', str(WRAPPER), '--container-shell'],
                              input=script, capture_output=True, text=True,
                              env=self.env, cwd=self.project, timeout=timeout)

    def start_shell(self, script):
        process = subprocess.Popen(['bash', str(WRAPPER), '--container-shell'],
                                   stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                   stderr=subprocess.PIPE, text=True, env=self.env,
                                   cwd=self.project, start_new_session=True)
        def stop():
            if process.poll() is None:
                process.send_signal(signal.SIGTERM)
                try:
                    process.wait(timeout=25)
                except subprocess.TimeoutExpired:
                    os.killpg(process.pid, signal.SIGKILL)
            process.communicate(timeout=5)
        self.addCleanup(stop)
        process.stdin.write(script)
        process.stdin.close()
        process.stdin = None
        return process

    def wait_file(self, path, process):
        deadline = time.monotonic() + 30
        while not path.exists():
            if process.poll() is not None:
                out, err = process.communicate()
                self.fail('Runtime wrapper exited before readiness:\n' + out + err)
            self.assertLess(time.monotonic(), deadline, 'runtime readiness timed out')
            time.sleep(0.05)

    def session_names(self):
        listing = self.engine('ps', '--all', '--format', '{{.Names}}')
        self.assertEqual(listing.returncode, 0, listing.stderr)
        return [name for name in listing.stdout.splitlines()
                if name.startswith(self.project.name.replace(' ', '-') + '-')]

    def unique_project(self):
        self.project = self.base / ('project-' + self.base.name)
        self.project.mkdir()

    def test_nonterminal_input_exit_status_and_pty(self):
        self.unique_project()
        result = self.pipe_shell('test ! -t 0\nprintf "pipe payload\\n"\nexit 125\n')
        self.assertEqual(result.returncode, 125, result.stdout + result.stderr)
        self.assertIn('pipe payload\n', result.stdout)
        self.assertEqual(self.session_names(), [])
        source = self.base / 'commands.sh'
        source.write_text('test ! -t 0\nprintf "file payload\\n"\n')
        with source.open() as stream:
            result = subprocess.run(['bash', str(WRAPPER), '--container-shell'],
                                    stdin=stream, capture_output=True, text=True,
                                    env=self.env, cwd=self.project, timeout=60)
        self.assert_success(result)
        self.assertIn('file payload\n', result.stdout)
        self.assert_success(self.shell('test -t 0\ntest -t 1'))

    def test_concurrent_reservation_with_stopped_container(self):
        self.unique_project()
        stopped = self.engine('create', '--name', self.project.name + '-08',
                              '--entrypoint', '/bin/true', IMAGE)
        self.assertEqual(stopped.returncode, 0, stopped.stderr)
        stopped_id = stopped.stdout.strip()
        self.addCleanup(self.engine, 'rm', '--force', '--ignore', stopped_id)
        processes = []
        for index in range(2):
            process = self.start_shell(f'touch ready-{index}\nwhile test ! -e release; do sleep 0.05; done\n')
            processes.append(process)
        for index, process in enumerate(processes):
            self.wait_file(self.project / f'ready-{index}', process)
        self.assertEqual(set(self.session_names()),
                         {self.project.name + suffix for suffix in ('-08', '-9', '-10')})
        (self.project / 'release').touch()
        for process in processes:
            out, err = process.communicate(timeout=30)
            self.assertEqual(process.returncode, 0, out + err)
        self.assertEqual(self.session_names(), [self.project.name + '-08'])

    def test_signal_delivery_owned_cleanup_and_stubborn_process(self):
        self.unique_project()
        unrelated = self.engine('create', '--name', self.project.name + '-08',
                                '--entrypoint', '/bin/true', IMAGE)
        self.assertEqual(unrelated.returncode, 0, unrelated.stderr)
        self.addCleanup(self.engine, 'rm', '--force', '--ignore', unrelated.stdout.strip())
        for sig, status in ((signal.SIGTERM, 143), (signal.SIGINT, 130), (signal.SIGHUP, 129)):
            with self.subTest(signal=sig):
                (self.project / 'ready').unlink(missing_ok=True)
                signame = signal.Signals(sig).name[3:]
                process = self.start_shell(f"trap 'printf {signame} > received; exit 0' {signame}\n"
                                           'touch ready\nwhile :; do sleep 0.1; done\n')
                self.wait_file(self.project / 'ready', process)
                process.send_signal(sig)
                out, err = process.communicate(timeout=25)
                self.assertEqual(process.returncode, status, out + err)
                self.assertEqual((self.project / 'received').read_text(), signame)
                self.assertEqual(self.session_names(), [self.project.name + '-08'])
        (self.project / 'ready').unlink()
        process = self.start_shell("trap '' TERM\ntouch ready\nwhile :; do sleep 0.1; done\n")
        self.wait_file(self.project / 'ready', process)
        start = time.monotonic()
        process.send_signal(signal.SIGTERM)
        out, err = process.communicate(timeout=25)
        self.assertEqual(process.returncode, 143, out + err)
        self.assertLess(time.monotonic() - start, 24)
        self.assertEqual(self.session_names(), [self.project.name + '-08'])

    def test_identity_storage_hardening_and_ephemeral_lifetime(self):
        script = f'''set -e
        test "$(id -u)" = {os.getuid()}
        test "$(id -g)" = {os.getgid()}
        grep -Eq '^CapEff:[[:space:]]+0+$' /proc/self/status
        grep -Eq '^NoNewPrivs:[[:space:]]+1$' /proc/self/status
        test -z "${{CONTAINER_HOST:-}}"
        test ! -S /run/podman/podman.sock
        if touch /usr/pi-test-write 2>/dev/null; then exit 10; fi
        for directory in /tmp /var/tmp /run "$HOME/.npm"; do
            printf temporary > "$directory/sentinel"
            printf '#!/bin/sh\\nexit 0\\n' > "$directory/executable"
            chmod +x "$directory/executable"
            if "$directory/executable" 2>/dev/null; then exit 11; fi
        done
        printf persistent > "$HOME/.pi/sentinel"
        printf workspace > owned-file
        node <<'NODE'
const fs = require('fs');
const paths = [['/tmp',256],['/var/tmp',256],['/run',32],[process.env.HOME+'/.npm',256]];
const mounts=fs.readFileSync('/proc/mounts','utf8').split('\\n');
for (const [path,mib] of paths) {{
 const stat=fs.statfsSync(path); if(stat.bsize*stat.blocks!==mib*1024*1024) throw Error('capacity '+path);
 const opts=mounts.find(x=>x.split(' ')[1]===path).split(' ')[3].split(',');
 for(const flag of ['rw','nosuid','nodev','noexec']) if(!opts.includes(flag)) throw Error(flag+' '+path);
}}
let fd=fs.openSync('/run/exhaust','w');
try {{ for(let n=0;n<34;n++) fs.writeSync(fd,Buffer.alloc(1024*1024)); throw Error('unbounded /run'); }}
catch(e) {{ if(e.code!=='ENOSPC') throw e; }} finally {{ fs.closeSync(fd); fs.unlinkSync('/run/exhaust'); }}
NODE
'''
        self.assert_success(self.pipe_shell(script))
        self.assertEqual((self.project / 'owned-file').stat().st_uid, os.getuid())
        self.assertEqual((self.project / 'owned-file').stat().st_gid, os.getgid())
        self.assertEqual((self.state / 'sentinel').read_text(), 'persistent')
        self.assert_success(self.pipe_shell('set -e\nfor d in /tmp /var/tmp /run "$HOME/.npm"; do test ! -e "$d/sentinel"; done\ntest "$(cat "$HOME/.pi/sentinel")" = persistent\n'))

    def test_native_pi_help_version_npm_git_and_optional_bun(self):
        for arg in ('--version', '--help'):
            result = subprocess.run(['bash', str(WRAPPER), arg], env=self.env,
                                    cwd=self.project, capture_output=True, text=True, timeout=60)
            self.assert_success(result)
            self.assertTrue(result.stdout.strip())
        # npm installs a local tarball: actual Pi npm: flow without registry credentials.
        fixture = self.project / 'extension'
        fixture.mkdir()
        (fixture / 'package.json').write_text(json.dumps({'name':'pi-acceptance-fixture','version':'1.0.0','pi':{'extensions':['index.js']}}))
        (fixture / 'index.js').write_text('export default function () {}\n')
        self.assert_success(self.pipe_shell('set -e\nif command -v bun >/dev/null; then exit 9; fi\ncd extension\nnpm pack --ignore-scripts\ncd ..\npi install "npm:$PWD/extension/pi-acceptance-fixture-1.0.0.tgz"\npi install -l "npm:$PWD/extension/pi-acceptance-fixture-1.0.0.tgz"\ngit init -q\ngit -c user.name=Test -c user.email=test@example.invalid commit --allow-empty -qm initial\n'))
        self.assertTrue((self.state / 'agent/npm/node_modules/pi-acceptance-fixture').is_dir())
        self.assertTrue((self.project / '.pi/npm/node_modules/pi-acceptance-fixture').is_dir())
        for path in self.state.rglob('*'):
            self.assertEqual(path.stat().st_uid, os.getuid(), str(path))
        self.assert_success(self.shell('set -e\ngit worktree add -qb test-worktree ../sibling\ntest -d ../sibling/.git || test -f ../sibling/.git', '--container-git-worktree'))
        self.assert_success(self.pipe_shell('test ! -e ../sibling/.git\n'))
        if os.environ.get('PI_TEST_BUN') == '1':
            # A disposable Bun image is built explicitly; a stale image never rebuilds itself.
            bun_image = f'{IMAGE}-bun-{os.getpid()}'
            self.assertNotEqual(self.engine('image', 'exists', bun_image).returncode, 0)
            try:
                result = self.piped('set -e\ntest "$(bun --version)" = 1.3.14\n'
                                    'printf \'console.log("bun-ok")\\n\' > bun-test.js\nbun bun-test.js\n',
                                    timeout=900, args=('--container-build',), PI_ENABLE_BUN='1',
                                    PI_CONTAINER_IMAGE=bun_image)
                self.assert_success(result)
                self.assertIn('bun-ok', result.stdout)
                result = self.piped('exit 0', PI_CONTAINER_IMAGE=bun_image)
                self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
                self.assertIn('is stale for the current inputs', result.stderr)
                self.assertIn('--container-build', result.stderr)
            finally:
                self.engine('rmi', '--force', bun_image, timeout=60)

    def test_home_layout_tools_and_isolated_state(self):
        result = self.piped('''set -e
test "$HOME" = /pi-home
test -d /pi-home/.pi && test -d /pi-home/.agents && test -d /pi-home/.npm
grep -q ' /pi-home tmpfs ' /proc/mounts
for tool in pi openspec podman bash bwrap bzip2 curl diff file find gawk git grep jq less nano patch ps python3 rg sed tar unzip xz zip; do
    command -v "$tool" >/dev/null || { echo "MISSING $tool"; exit 3; }
done
test "$(openspec --version)" = 1.16.0
printf scratch > "$HOME/scratch"
printf kept > "$HOME/.pi/home-sentinel"
echo LAYOUT_OK
''')
        self.assert_success(result)
        self.assertIn('LAYOUT_OK', result.stdout)
        self.assertEqual((self.state / 'home-sentinel').read_text(), 'kept')
        self.assert_success(self.piped('test ! -e "$HOME/scratch"'))
        isolated = self.home / 'isolated'
        result = self.piped('set -e\ntest "$HOME" = /pi-home\nprintf kept > "$HOME/notes"\nprintf pi > "$HOME/.pi/isolated"\n',
                            PI_CONTAINER_STATE_DIR=str(isolated))
        self.assert_success(result)
        self.assertEqual((isolated / 'notes').read_text(), 'kept')
        self.assertEqual((isolated / '.pi/isolated').read_text(), 'pi')
        self.assertEqual(isolated.stat().st_mode & 0o777, 0o700)
        self.assertFalse((self.state / 'isolated').exists())
        self.assert_success(self.piped('test "$(cat "$HOME/notes")" = kept', PI_CONTAINER_STATE_DIR=str(isolated)))

    def test_gitconfig_only_on_opt_in(self):
        (self.home/'.gitconfig').write_text('[user]\n\tname = Runtime Test\n')
        result=self.shell('test ! -e "$HOME/.gitconfig" && echo GITCONFIG_ABSENT')
        self.assert_success(result)
        self.assertIn('GITCONFIG_ABSENT',result.stdout)
        result=self.shell('test "$(git config --global user.name)" = "Runtime Test" && '
                          '{ if printf x >> "$HOME/.gitconfig" 2>/dev/null; then echo WRITABLE; else echo GITCONFIG_READONLY; fi; }',
                          PI_CONTAINER_GITCONFIG='1')
        self.assert_success(result)
        self.assertIn('GITCONFIG_READONLY',result.stdout)
        self.assertEqual((self.home/'.gitconfig').read_text(),'[user]\n\tname = Runtime Test\n')

    def test_private_state_and_readonly_mode(self):
        for state in (self.state, self.home / '.agents'):
            state.chmod(0o755)
            result = self.pipe_shell('exit 0\n')
            self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn('private', result.stderr)
            self.assertEqual(state.stat().st_mode & 0o777, 0o755)
            state.chmod(0o700)
        self.assert_success(self.shell('set -e\nif touch "$HOME/.pi/forbidden" 2>/dev/null; then exit 10; fi\nif touch "$HOME/.agents/forbidden" 2>/dev/null; then exit 11; fi', PI_READONLY_CONFIG='1'))

    def test_native_lifetime_timeout(self):
        start = time.monotonic()
        result = self.shell('sleep 30', PI_CONTAINER_RUN_TIMEOUT='3')
        self.assertLess(time.monotonic()-start, 25, result.stdout + result.stderr)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('session lifetime limit reached (3 s); exit status', result.stdout + result.stderr)
        print('Native Podman lifetime timeout status:', result.returncode)
        result = self.piped('exit 4', PI_CONTAINER_RUN_TIMEOUT='30')
        self.assertEqual(result.returncode, 4, result.stdout + result.stderr)
        self.assertNotIn('lifetime', result.stderr)

    def piped(self, script, timeout=120, cwd=None, args=(), **env):
        return subprocess.run(['bash', str(WRAPPER), *args, '--container-shell'], input=script, capture_output=True,
                              text=True, env=self.env | env, cwd=cwd or self.project, timeout=timeout)

    def test_effective_hardening_and_budgets(self):
        script = '''set -e
grep -E '^(CapInh|CapPrm|CapEff|CapBnd|CapAmb|NoNewPrivs):' /proc/self/status
for file in memory.max pids.max cpu.max; do printf '%s=%s\\n' "$file" "$(cat /sys/fs/cgroup/$file)"; done
'''
        cases = (({}, ('4294967296', '512', '200000 100000')),
                 ({'PI_CONTAINER_MEMORY_LIMIT': '1536m', 'PI_CONTAINER_CPU_LIMIT': '1.5',
                   'PI_CONTAINER_PIDS_LIMIT': '256'}, ('1610612736', '256', '150000 100000')))
        for env, (memory, pids, cpu) in cases:
            for delegated in ('0', '1'):
                with self.subTest(env=env, delegated=delegated):
                    extra = {'PI_CONTAINER_PODMAN': delegated}
                    if delegated == '1':
                        extra['PI_CONTAINER_PODMAN_SOCKET'] = self.socket
                    result = self.piped(script, timeout=360, **env, **extra)
                    self.assert_success(result)
                    for field in ('CapInh', 'CapPrm', 'CapEff', 'CapBnd', 'CapAmb'):
                        self.assertRegex(result.stdout, field + r':\s*0+\n')
                    self.assertRegex(result.stdout, r'NoNewPrivs:\s*1')
                    self.assertIn('memory.max=' + memory, result.stdout)
                    self.assertIn('pids.max=' + pids, result.stdout)
                    self.assertIn('cpu.max=' + cpu, result.stdout)

    def test_process_limit_enforced(self):
        script = '''node -e '
const {spawn}=require("child_process"); const kids=[]; let refused=false;
for (let i=0;i<80;i++) { try { const c=spawn("sleep",["30"]); c.on("error",()=>{refused=true}); kids.push(c); } catch (e) { refused=true; break; } }
setTimeout(()=>{ kids.forEach(k=>{ try{k.kill()}catch(e){} }); console.log(refused?"PIDS_BUDGET_ENFORCED":"PIDS_NOT_ENFORCED"); },1500);
'
'''
        result = self.piped(script, PI_CONTAINER_PIDS_LIMIT='32')
        self.assert_success(result)
        self.assertIn('PIDS_BUDGET_ENFORCED', result.stdout)

    def test_sensitive_home_refused(self):
        result = self.piped('exit 0', cwd=self.home)
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertIn('refusing sensitive workspace', result.stderr)

    def test_delegated_child_and_remapped_containerized_caller(self):
        script = 'set -e\ntest -S /run/podman/podman.sock\nfor directory in /var/lib/containers /run/containers; do test ! -e "$directory/sentinel"; printf temporary > "$directory/sentinel"; test "$(stat -c %u "$directory")" = "$(id -u)"; test "$(stat -c %a "$directory")" = 700; done\npodman run --rm --read-only --userns=keep-id --user "$(id -u):$(id -g)" --volume "$PWD:$PWD:rw" --workdir "$PWD" --entrypoint /bin/sh ' + shlex.quote(IMAGE) + " -ec 'printf child > child-file'\n"
        self.assert_success(self.shell(script, PI_CONTAINER_PODMAN='1', PI_CONTAINER_PODMAN_SOCKET=self.socket))
        self.assertEqual((self.project / 'child-file').stat().st_uid, os.getuid())
        host = self.engine('--remote', '--url', 'unix://' + self.socket, 'info', '--format', '{{.Host.RemoteSocket.Path}}')
        self.assert_success(host)
        visible = '/run/pi-test-service/socket.sock'
        # Use the disposable runner image for its Podman client and Python, never production dependencies.
        runner_image = os.environ['PI_TEST_RUNNER_IMAGE']
        command = ['podman','run','--rm','--interactive','--tty','--userns=keep-id','--user',f'{os.getuid()}:{os.getgid()}',
                   '--volume',f'{ROOT}:{ROOT}:ro','--volume',f'{self.base}:{self.base}:rw',
                   '--volume',f'{host.stdout.strip()}:{visible}:rw','--workdir',str(self.project),
                   '--env','CONTAINER_HOST=unix://'+visible,'--env','HOME='+str(self.home),
                   '--env','PI_CONTAINER_IMAGE='+IMAGE,'--env','PI_CONTAINER_PODMAN=1','--env','PI_CONTAINER_NETWORK=unrestricted',
                   '--entrypoint','/bin/bash',runner_image,str(WRAPPER),'--container-shell']
        self.assert_success(terminal_shell(command, 'set -e\nfor d in /var/lib/containers /run/containers; do test ! -e "$d/sentinel"; done\npodman info >/dev/null\nprintf nested > nested-file', self.env, self.project, timeout=360))
        self.assertEqual((self.project / 'nested-file').stat().st_uid, os.getuid())

    def test_build_context_excludes_sensitive_and_unknown_inputs(self):
        context = self.base / 'context'
        context.mkdir()
        shutil.copyfile(ROOT / '.containerignore', context / '.containerignore')
        (context / '.version').write_text('dummy')
        (context / '.gitignore').write_text('dummy')
        for name in ('.pi/agent/auth.json','.env','unknown','tests/sentinel','nested/Containerfile',
                     'network/relay.py','network/mux.py','network/proxy.py','network/bin/sandbox-egress-guard',
                     'nested/network/relay.py'):
            path=context/name
            path.parent.mkdir(parents=True,exist_ok=True)
            path.write_text('DUMMY-NOT-A-CREDENTIAL')
        (context/'Containerfile').write_text('FROM '+IMAGE+'\nCOPY . /context\nRUN test ! -e /context/.env && test ! -e /context/.pi && test ! -e /context/unknown && test ! -e /context/tests && test ! -e /context/nested && test ! -e /context/.gitignore && test "$(find /context -type f | wc -l)" = 5 && test -f /context/Containerfile && test -f /context/.containerignore && test -f /context/.version && test -f /context/network/relay.py && test -f /context/network/mux.py && test ! -e /context/network/proxy.py && test ! -e /context/network/bin\n')
        iid=self.base/'image-id'
        def remove():
            if iid.exists(): self.engine('rmi','--force',iid.read_text().strip())
        self.addCleanup(remove)
        result=self.engine('build','--iidfile',str(iid),'--file',str(context/'Containerfile'),str(context),timeout=180)
        self.assert_success(result)

    def test_declared_runtime_limits_and_owned_id(self):
        self.unique_project()
        process=self.start_shell('touch limits-ready\nwhile test ! -e limits-release; do sleep 0.05; done\n')
        self.wait_file(self.project/'limits-ready',process)
        ids=self.engine('ps','--filter','name=^'+self.project.name+'-','--no-trunc','--format','{{.ID}}')
        self.assert_success(ids)
        cid=ids.stdout.strip()
        self.assertRegex(cid,r'^[a-f0-9]{64}$')
        details=self.engine('inspect',cid)
        self.assert_success(details)
        container=json.loads(details.stdout)[0]
        config=container['HostConfig']
        self.assertTrue(config['ReadonlyRootfs'])
        self.assertEqual(config['Memory'],4*1024**3)
        self.assertEqual(config['NanoCpus'],2*10**9)
        self.assertEqual(config['PidsLimit'],512)
        self.assertFalse(config.get('CapAdd'))
        self.assertIn('no-new-privileges',config['SecurityOpt'])
        self.assertEqual(container['Config']['User'],f'{os.getuid()}:{os.getgid()}')
        (self.project/'limits-release').touch()
        out,err=process.communicate(timeout=30)
        self.assertEqual(process.returncode,0,out+err)
        self.assertEqual(self.engine('container','exists',cid).returncode,1)

if __name__ == '__main__':
    unittest.main()

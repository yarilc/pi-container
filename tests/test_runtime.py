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
import sys
import tempfile
import termios
import time
import unittest
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'network'))
import agent_budgets  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
WRAPPER = ROOT / 'pi-container.sh'
IMAGE = os.environ.get('PI_CONTAINER_IMAGE', 'localhost/pi-container:latest')
ENGINE_IMAGE = os.environ.get('PI_CONTAINER_ENGINE_IMAGE', 'localhost/pi-container-engine:latest')
# A small local image the library copies into its store (pinned, already in the engine).
SAMPLE = os.environ.get('SANDBOX_TEST_ENGINE_SAMPLE', 'docker.io/library/alpine@sha256:'
                        'c64c687cbea9300178b30c95835354e34c4e4febc4badfe27102879de0483b5e')
SYSTEMD_SAMPLE = os.environ.get('SANDBOX_TEST_SYSTEMD_SAMPLE', '')
INELIGIBLE = 'systemd containers and explicit limits for nested containers are unavailable'
LIMIT_PROBE = ('for f in memory.max memory.high pids.max cpu.max cgroup.max.descendants cgroup.max.depth; do '
               '[ -e /sys/fs/cgroup/$f ] || continue; v=$(cat /sys/fs/cgroup/$f); '
               'if { printf "%s\\n" "$v" > /sys/fs/cgroup/$f; } 2>/dev/null; then echo "limit=$f:writable"; '
               'else echo "limit=$f:denied"; fi; done')
ENABLED = os.environ.get('PI_RUNTIME_TESTS') == '1'


def engine_budgets(env):
    """Delegated controllers and process mechanism of the engine, by the launcher's rule."""
    def info(template):
        return subprocess.run(['podman', 'info', '--format', template], env=env, check=True,
                              capture_output=True, text=True, timeout=60).stdout.strip()
    delegated = agent_budgets.delegated(info('{{.Host.CgroupControllers}}'), info('{{.Host.CgroupManager}}'))
    return delegated, agent_budgets.process_mechanism(delegated, info('{{.Host.Kernel}}'))


def start_crowd(test, env, count):
    """A container of the caller holding count sleeping processes, removed at cleanup."""
    name = 'pi-test-crowd-' + uuid.uuid4().hex[:12]
    test.addCleanup(subprocess.run, ['podman', 'rm', '--force', '--time', '0', '--ignore', name],
                    env=env, capture_output=True, timeout=60)
    subprocess.run(['podman', 'run', '--detach', '--rm', '--name', name, '--userns=keep-id',
                    '--user', f'{os.getuid()}:{os.getgid()}', '--network=none', '--entrypoint', '/bin/sh', IMAGE,
                    '-c', f'i=0; while [ $i -lt {count} ]; do sleep 600 & i=$((i + 1)); done; wait'],
                   env=env, check=True, capture_output=True, text=True, timeout=60)
    deadline = time.monotonic() + 60
    while True:
        top = subprocess.run(['podman', 'top', name, 'pid'], env=env, capture_output=True, text=True, timeout=30)
        # The header line, the shell and its sleeping children.
        if len(top.stdout.splitlines()) >= count + 2 or time.monotonic() > deadline:
            break
        time.sleep(0.5)
    test.assertGreaterEqual(len(top.stdout.splitlines()), count + 2, top.stdout + top.stderr)
    return name


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
        # The synthetic home, with the default toolchain library, stays outside
        # the base so a worktree launch never exposes it through the workspace.
        self.home = Path(tempfile.mkdtemp(prefix='pi-home-', dir=parent)).resolve()
        self.addCleanup(shutil.rmtree, self.home)
        self.state = self.home / '.pi'
        self.state.mkdir(mode=0o700)
        (self.home / '.agents').mkdir(mode=0o700)
        self.assertEqual(self.state.stat().st_mode & 0o777, 0o700,
                         'Select a native Linux PI_TEST_ROOT or use tests/run-runtime.sh')
        self.env = {k: v for k, v in os.environ.items()
                    if not k.startswith('PI_') and k not in ('CONTAINER_CONNECTION', 'ANTHROPIC_API_KEY', 'OPENAI_API_KEY', 'GOOGLE_API_KEY', 'GITHUB_TOKEN')}
        self.env.update(HOME=str(self.home), PI_CONTAINER_IMAGE=IMAGE,
                        PI_CONTAINER_NETWORK='unrestricted', PI_CONTAINER_MAINTENANCE='1')

    def shell(self, script, *options, **env):
        return terminal_shell(['bash', str(WRAPPER), '--container-shell', *options],
                              script, self.env | env, self.project, timeout=90)

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

    def test_pseudo_terminals_and_device_masks(self):
        # Interactive tools open their own PTY: the session must allocate one,
        # while /dev/shm and /run/secrets stay empty read-only masks.
        probe = r'''import os
import pathlib
import pty
master, slave = pty.openpty()
assert os.ttyname(slave).startswith('/dev/pts/'), os.ttyname(slave)
os.close(master); os.close(slave)
for path in ('/dev/shm', '/run/secrets'):
    assert list(pathlib.Path(path).iterdir()) == [], path
    try:
        (pathlib.Path(path) / 'probe').write_text('x')
    except OSError:
        pass
    else:
        raise AssertionError(path + ' is writable')
print('pty-and-masks-ok')
'''
        result = self.shell('python3 -c ' + shlex.quote(probe) + '\n')
        self.assert_success(result)
        self.assertIn('pty-and-masks-ok', result.stdout)

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
        test -z "${{CONTAINER_HOST+x}}${{DOCKER_HOST+x}}"
        test ! -S /run/podman/podman.sock
        if touch /usr/pi-test-write 2>/dev/null; then exit 10; fi
        # /run is not writable by the session user (contract L7).
        if touch /run/pi-test-write 2>/dev/null; then exit 12; fi
        for directory in /tmp /var/tmp "$HOME" "$HOME/.npm"; do
            printf temporary > "$directory/sentinel"
            printf '#!/bin/sh\\nexit 0\\n' > "$directory/executable"
            chmod +x "$directory/executable"
            if "$directory/executable" 2>/dev/null; then exit 11; fi
        done
        printf persistent > "$HOME/.pi/sentinel"
        printf workspace > owned-file
        node <<'NODE'
const fs = require('fs');
const paths = [['/tmp',512],['/var/tmp',512],['/run',32],[process.env.HOME,512],[process.env.HOME+'/.npm',256]];
const mounts=fs.readFileSync('/proc/mounts','utf8').split('\\n');
for (const [path,mib] of paths) {{
 const stat=fs.statfsSync(path); if(stat.bsize*stat.blocks!==mib*1024*1024) throw Error('capacity '+path);
 const opts=mounts.find(x=>x.split(' ')[1]===path).split(' ')[3].split(',');
 for(const flag of ['rw','nosuid','nodev','noexec']) if(!opts.includes(flag)) throw Error(flag+' '+path);
}}
let fd=fs.openSync(process.env.HOME+'/.npm/exhaust','w');
try {{ for(let n=0;n<258;n++) fs.writeSync(fd,Buffer.alloc(1024*1024)); throw Error('unbounded npm cache'); }}
catch(e) {{ if(e.code!=='ENOSPC') throw e; }} finally {{ fs.closeSync(fd); fs.unlinkSync(process.env.HOME+'/.npm/exhaust'); }}
NODE
'''
        self.assert_success(self.pipe_shell(script))
        self.assertEqual((self.project / 'owned-file').stat().st_uid, os.getuid())
        self.assertEqual((self.project / 'owned-file').stat().st_gid, os.getgid())
        self.assertEqual((self.state / 'sentinel').read_text(), 'persistent')
        self.assert_success(self.pipe_shell('set -e\nfor d in /tmp /var/tmp "$HOME" "$HOME/.npm"; do test ! -e "$d/sentinel"; done\ntest "$(cat "$HOME/.pi/sentinel")" = persistent\n'))

    def test_native_pi_help_version_npm_git_and_no_bun(self):
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

    def test_home_layout_tools_and_isolated_state(self):
        result = self.piped('''set -e
test "$HOME" = /pi-home
test -d /pi-home/.pi && test -d /pi-home/.agents && test -d /pi-home/.npm
grep -q ' /pi-home tmpfs ' /proc/mounts
for tool in pi openspec podman bash bwrap bzip2 curl diff file find gawk git grep jq less nano patch ps python3 rg sed tar unzip xz zip; do
    command -v "$tool" >/dev/null || { echo "MISSING $tool"; exit 3; }
done
test "$(openspec --version)" = 2.0.0
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
        self.assert_success(self.shell('set -e\nif touch "$HOME/.pi/forbidden" 2>/dev/null; then exit 10; fi\nif touch "$HOME/.agents/forbidden" 2>/dev/null; then exit 11; fi', PI_CONTAINER_READONLY_STATE='1'))

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

    def engine_budgets(self):
        """Delegated controllers and process mechanism of the engine, by the launcher's rule."""
        return engine_budgets(self.env)

    def test_effective_hardening_and_budgets(self):
        # Budgets apply as the engine allows: cgroup limits only for delegated
        # controllers, the process rlimit as fallback, and a notice otherwise.
        # A controller file the engine did not create counts as unlimited.
        controllers, mechanism = self.engine_budgets()
        script = '''set -e
grep -E '^(CapInh|CapPrm|CapEff|CapBnd|CapAmb|NoNewPrivs):' /proc/self/status
for file in memory.max pids.max cpu.max; do printf '%s=%s\\n' "$file" "$(cat /sys/fs/cgroup/$file 2>/dev/null || echo max)"; done
grep '^Max processes' /proc/self/limits
'''
        cases = (({}, ('4294967296', '512', '200000 100000')),
                 ({'PI_CONTAINER_MEMORY_LIMIT': '1536m', 'PI_CONTAINER_CPU_LIMIT': '1.5',
                   'PI_CONTAINER_PIDS_LIMIT': '256'}, ('1610612736', '256', '150000 100000')))
        for env, (memory, pids, cpu) in cases:
            with self.subTest(env=env):
                result = self.piped(script, timeout=180, **env)
                self.assert_success(result)
                for field in ('CapInh', 'CapPrm', 'CapEff', 'CapBnd', 'CapAmb'):
                    self.assertRegex(result.stdout, field + r':\s*0+\n')
                self.assertRegex(result.stdout, r'NoNewPrivs:\s*1')
                self.assertIn('memory.max=' + (memory if 'memory' in controllers else 'max') + '\n', result.stdout)
                self.assertIn('pids.max=' + (pids if mechanism == 'cgroup' else 'max') + '\n', result.stdout)
                if 'cpu' in controllers:
                    self.assertIn('cpu.max=' + cpu, result.stdout)
                else:
                    self.assertRegex(result.stdout, r'cpu\.max=max\b')
                if mechanism == 'rlimit':
                    self.assertRegex(result.stdout, r'Max processes\s+' + pids + r'\s+' + pids + r'\s')
                for budget, controller in (('memory', 'memory'), ('CPU', 'cpu')):
                    notice = f'agent {budget} budget not enforced'
                    if controller in controllers:
                        self.assertNotIn(notice, result.stderr)
                    else:
                        self.assertIn(notice, result.stderr)
                rlimit = f'agent process budget enforced through the process rlimit ({pids} tasks'
                self.assertEqual(rlimit in result.stderr, mechanism == 'rlimit', result.stderr)
                self.assertEqual('agent process budget not enforced' in result.stderr, mechanism == 'none',
                                 result.stderr)

    def test_process_limit_enforced(self):
        # A process budget is enforced, not just reported. Under the rlimit
        # fallback, container startup also counts, so the budget leaves room.
        if self.engine_budgets()[1] == 'none':
            self.skipTest('the engine enforces no process budget')
        script = '''node -e '
const {spawn}=require("child_process"); const kids=[]; let refused=false;
for (let i=0;i<200;i++) { try { const c=spawn("sleep",["30"]); c.on("error",()=>{refused=true}); kids.push(c); } catch (e) { refused=true; break; } }
setTimeout(()=>{ kids.forEach(k=>{ try{k.kill()}catch(e){} }); console.log(refused?"PIDS_BUDGET_ENFORCED":"PIDS_NOT_ENFORCED"); },1500);
'
'''
        result = self.piped(script, PI_CONTAINER_PIDS_LIMIT='128')
        self.assert_success(result)
        self.assertIn('PIDS_BUDGET_ENFORCED', result.stdout)

    def test_process_rlimit_counts_per_container(self):
        # set-process-limits-inside-containers: on the rlimit fallback, other
        # containers of the user do not consume the session's budget.
        _, mechanism = self.engine_budgets()
        if mechanism != 'rlimit':
            self.skipTest('the engine does not use the process rlimit fallback')
        start_crowd(self, self.env, 150)
        result = self.piped(
            'python3 - <<\'CHECK\'\nimport subprocess\nchildren = []\n'
            'def spawn(total):\n    try:\n        while len(children) < total:\n'
            '            children.append(subprocess.Popen(["sleep", "60"]))\n'
            '    except (BlockingIOError, OSError):\n        pass\n    return len(children)\n'
            'first, second = spawn(100), spawn(200)\n[child.kill() for child in children]\n'
            'print("PROCESSES", first, second)\nCHECK\n', PI_CONTAINER_PIDS_LIMIT='128')
        self.assert_success(result)
        counts = next(line.split()[1:] for line in result.stdout.splitlines() if line.startswith('PROCESSES'))
        first, second = map(int, counts)
        self.assertEqual(first, 100, result.stdout)
        # The session's own processes count as well: the shell, Python and the init process.
        self.assertTrue(115 <= second < 128, result.stdout)

    def test_sensitive_home_refused(self):
        result = self.piped('exit 0', cwd=self.home)
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertIn('refusing sensitive workspace', result.stderr)

    def test_containerized_caller_and_leftover_delegation_refusal(self):
        host = self.engine('info', '--format', '{{.Host.RemoteSocket.Path}}')
        self.assert_success(host)
        host_socket = host.stdout.strip().removeprefix('unix://')
        visible = '/run/pi-test-service/socket.sock'
        # Use the disposable runner image for its Podman client and Python, never production dependencies.
        runner_image = os.environ.get('PI_TEST_RUNNER_IMAGE', IMAGE)
        base_cmd = ['podman', 'run', '--rm', '--interactive', '--read-only', '--userns=keep-id',
                    '--user', f'{os.getuid()}:{os.getgid()}',
                    '--volume', f'{ROOT}:{ROOT}:ro', '--volume', f'{self.base}:{self.base}:rw',
                    '--volume', f'{self.home}:{self.home}:rw',
                    '--volume', f'{host_socket}:{visible}:rw', '--workdir', str(self.project),
                    '--env', 'CONTAINER_HOST=unix://' + visible, '--env', 'HOME=' + str(self.home),
                    '--env', 'PI_CONTAINER_IMAGE=' + IMAGE, '--env', 'PI_CONTAINER_NETWORK=unrestricted',
                    '--env', 'PI_CONTAINER_MAINTENANCE=1', '--entrypoint', '/bin/bash']
        result = subprocess.run([*base_cmd, runner_image, str(WRAPPER), '--container-shell'],
                                input='set -e\ntest ! -S /run/podman/podman.sock\n'
                                      'test -z "${CONTAINER_HOST+x}"\ntest -z "${DOCKER_HOST+x}"\n'
                                      'printf nested > nested-file\n',
                                capture_output=True, text=True, timeout=90)
        self.assert_success(result)
        self.assertEqual((self.project / 'nested-file').read_text(), 'nested')
        self.assertEqual((self.project / 'nested-file').stat().st_uid, os.getuid())
        refused = subprocess.run([*base_cmd, '--env', 'PI_CONTAINER_PODMAN=1',
                                  runner_image, str(WRAPPER), '--container-shell'],
                                 input='exit 0\n', capture_output=True, text=True, timeout=90)
        self.assertEqual(refused.returncode, 1)
        self.assertIn('PI_CONTAINER_PODMAN=1: host Podman delegation was removed', refused.stderr)

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
        controllers, mechanism = self.engine_budgets()
        process = self.start_shell('touch limits-ready\nwhile test ! -e limits-release; do sleep 0.05; done\n')
        self.wait_file(self.project / 'limits-ready', process)
        ids = self.engine('ps', '--filter', 'name=^' + self.project.name + '-', '--no-trunc', '--format', '{{.ID}}')
        self.assert_success(ids)
        cid = ids.stdout.strip()
        self.assertRegex(cid, r'^[a-f0-9]{64}$')
        details = self.engine('inspect', cid)
        self.assert_success(details)
        container = json.loads(details.stdout)[0]
        config = container['HostConfig']
        self.assertTrue(config['ReadonlyRootfs'])
        self.assertEqual(config['Memory'], 4 * 1024**3 if 'memory' in controllers else 0)
        self.assertEqual(config['NanoCpus'], 2 * 10**9 if 'cpu' in controllers else 0)
        if mechanism == 'cgroup':
            self.assertEqual(config['PidsLimit'], 512)
        else:
            self.assertIn(config['PidsLimit'], (0, -1))
            if mechanism == 'rlimit':
                for entry in config.get('Ulimits') or ():
                    if entry.get('Name') == 'RLIMIT_NPROC':
                        self.assertGreater(entry['Soft'], 512)
                        self.assertGreater(entry['Hard'], 512)
        self.assertFalse(config.get('CapAdd'))
        self.assertIn('no-new-privileges', config['SecurityOpt'])
        self.assertEqual(container['Config']['User'], f'{os.getuid()}:{os.getgid()}')
        (self.project / 'limits-release').touch()
        out, err = process.communicate(timeout=30)
        self.assertEqual(process.returncode, 0, out + err)
        self.assertEqual(self.engine('container', 'exists', cid).returncode, 1)

    # Toolchain library

    def toolchain(self, *args, **env):
        return subprocess.run(['bash', str(WRAPPER), '--container-toolchain', *args], cwd=self.project,
                              env=self.env | env, text=True, capture_output=True, timeout=300)

    def archive_recipe(self, name, commands, **values):
        import hashlib, io, tarfile
        buffer = io.BytesIO()
        with tarfile.open(fileobj=buffer, mode='w:gz') as archive:
            for directory in (name + '-1', name + '-1/bin'):
                info = tarfile.TarInfo(directory)
                info.type, info.mode = tarfile.DIRTYPE, 0o755
                archive.addfile(info)
            for command, output in commands.items():
                data = ('#!/bin/sh\necho ' + output + '-"$*"\n').encode()
                info = tarfile.TarInfo(name + '-1/bin/' + command)
                info.size, info.mode = len(data), 0o755
                archive.addfile(info, io.BytesIO(data))
        path = self.base / (name + '.tar.gz')
        path.write_bytes(buffer.getvalue())
        recipe = {'schema': 1, 'name': name, 'version': '1', 'default': True, 'path': ['bin'],
                  'env': {name.upper() + '_HOME': {'toolchain': ''}}, 'check': [next(iter(commands)), 'check'],
                  'source': {'archive': str(path), 'sha256': hashlib.sha256(path.read_bytes()).hexdigest(),
                             'strip_components': 1}}
        recipe.update(values)
        recipe_path = self.base / (name + '.json')
        recipe_path.write_text(json.dumps(recipe))
        return recipe_path

    def test_toolchain_library_sources_environment_and_read_only_mount(self):
        import uuid
        library = self.home / '.local/share/sandbox-toolchains'
        self.assert_success(self.toolchain('add', str(self.archive_recipe('hello', {'hello': 'hello'}))))
        # A default toolchain providing node and python3 never replaces the runtime's own.
        self.assert_success(self.toolchain('add', str(self.archive_recipe(
            'shadow', {'node': 'fake-node', 'python3': 'fake-python'}, env={}))))
        failing = self.archive_recipe('broken', {'broken': 'broken'}, check=['false'], env={})
        result = self.toolchain('add', str(failing))
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('toolchain check failed for broken', result.stderr)
        self.assertFalse((library / 'broken').exists())
        context = self.base / 'image-context'
        (context / 'opt/imgtool/bin').mkdir(parents=True)
        (context / 'opt/imgtool/bin/imgtool').write_text('#!/bin/sh\necho image-tool\n')
        (context / 'opt/imgtool/bin/imgtool').chmod(0o755)
        (context / 'Containerfile').write_text('FROM scratch\nCOPY opt /opt\n')
        image = 'localhost/pi-toolchain-test-' + uuid.uuid4().hex
        self.addCleanup(self.engine, 'image', 'rm', '--force', '--ignore', image + ':latest', timeout=60)
        self.assert_success(self.engine('build', '--tag', image + ':latest', str(context), timeout=120))
        digest = self.engine('image', 'inspect', '--format', '{{.Digest}}', image + ':latest').stdout.strip()
        recipe = self.base / 'imgtool.json'
        recipe.write_text(json.dumps({'schema': 1, 'name': 'imgtool', 'version': '1', 'default': False,
                                      'source': {'image': image + '@' + digest, 'path': '/opt/imgtool'},
                                      'check': ['imgtool']}))
        self.assert_success(self.toolchain('add', str(recipe)))
        listing = self.toolchain('list')
        self.assert_success(listing)
        for name in ('hello', 'shadow', 'imgtool'):
            self.assertIn(name + '\t', listing.stdout)
        result = self.piped('''set -e
test "$(hello a)" = hello-a
test "$HELLO_HOME" = /toolchains/hello
test "$(command -v node)" = /usr/local/bin/node
test "$(command -v python3)" = /usr/bin/python3
test "$(. /toolchains/shadow/env.sh && node b)" = fake-node-b
test "$(. /toolchains/imgtool/env.sh && imgtool)" = image-tool
if command -v imgtool; then exit 9; fi
grep -q 'hello 1' /toolchains/toolchains.md
python3 -c 'import json; assert [t["name"] for t in json.load(open("/toolchains/index.json"))["toolchains"]] == ["hello", "imgtool", "shadow"]'
if touch /toolchains/new 2>/dev/null; then exit 10; fi
if rm /toolchains/hello/bin/hello 2>/dev/null; then exit 11; fi
test -x /toolchains/hello/bin/hello
echo toolchains-ok
''')
        self.assert_success(result)
        self.assertIn('toolchains-ok', result.stdout)
        self.assert_success(self.toolchain('remove', 'imgtool'))
        self.assertFalse((library / 'imgtool').exists())

    def test_toolchain_library_can_be_omitted(self):
        result = self.piped('test ! -e /toolchains\necho omitted\n', PI_CONTAINER_TOOLCHAINS='0')
        self.assert_success(result)
        self.assertIn('omitted', result.stdout)


@unittest.skipUnless(ENABLED, 'set PI_RUNTIME_TESTS=1 for real rootless Podman checks')
class SessionEngineTests(unittest.TestCase):
    """The session container engine on a real rootless engine (session-container-engine)."""

    @classmethod
    def setUpClass(cls):
        for image in (ENGINE_IMAGE, SAMPLE):
            if subprocess.run(['podman', 'image', 'exists', image], capture_output=True).returncode:
                raise unittest.SkipTest('prepare ' + image + ' in the engine first')
        cls.sample_id = subprocess.run(['podman', 'image', 'inspect', '--format', '{{.Id}}', SAMPLE],
                                       capture_output=True, text=True, check=True).stdout.strip()

    def setUp(self):
        workspace_root = Path(os.environ.get('PI_TEST_ROOT', str(ROOT / '.test-state')))
        workspace_root.mkdir(parents=True, exist_ok=True)
        self.base = Path(tempfile.mkdtemp(prefix='engine-', dir=workspace_root)).resolve()
        self.addCleanup(shutil.rmtree, self.base, True)
        self.project = self.base / self.base.name
        self.project.mkdir()
        native_root = os.environ.get('SANDBOX_TEST_STATE_ROOT') or os.environ.get('PI_TEST_ROOT')
        self.native = Path(tempfile.mkdtemp(prefix='sandbox-engine-', dir=native_root)).resolve()
        self.addCleanup(shutil.rmtree, self.native, True)
        self.host_home = self.native / 'home'
        self.host_home.mkdir(mode=0o700)
        self.env = {'PATH': os.environ['PATH'], 'HOME': str(self.host_home), 'TMPDIR': str(self.native),
                    'PI_CONTAINER_NETWORK': 'unrestricted', 'PI_CONTAINER_MAINTENANCE': '1',
                    'PI_CONTAINER_IMAGE': IMAGE, 'PI_CONTAINER_ENGINE_IMAGE': ENGINE_IMAGE,
                    'PI_CONTAINER_STATE_DIR': str(self.native / 'state')}
        for key in ('CONTAINER_HOST', 'XDG_RUNTIME_DIR'):
            if os.environ.get(key):
                self.env[key] = os.environ[key]
        self.add_image('sample', 'localhost/sandbox-test-sample:1')

    def toolchain(self, *args):
        # Operator recipes stay outside the directory the command runs from.
        result = subprocess.run([sys.executable, '-I', str(ROOT / 'setup/toolchains.py'), *args], env=self.env,
                                cwd=self.project, capture_output=True, text=True, timeout=300)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        return result

    def add_image(self, name, reference, image_id=None):
        recipe = self.native / (name + '.json')
        image_id = image_id or self.sample_id
        recipe.write_text(json.dumps({
            'schema': 2, 'name': name, 'version': '1', 'default': False,
            'images': [{'local': 'sha256:' + image_id.removeprefix('sha256:'), 'name': reference}],
            'check': ['podman', 'run', '--rm', '--network=none', reference, 'true']}))
        self.toolchain('add', str(recipe))
        self.addCleanup(subprocess.run, [sys.executable, '-I', str(ROOT / 'setup/toolchains.py'), 'remove', name],
                        env=self.env, cwd=self.project, capture_output=True, timeout=300)

    def shell(self, script, timeout=180):
        return subprocess.run(['bash', str(WRAPPER), '--container-shell'], cwd=self.project, env=self.env,
                              input='set -Eeuo pipefail\n' + script, text=True, capture_output=True, timeout=timeout)

    def assert_success(self, result):
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def engines(self):
        listing = subprocess.run(['podman', 'ps', '--all', '--filter', 'label=sandbox-engine.owner',
                                  '--format', '{{.Names}}'], env=self.env,
                                 capture_output=True, text=True, check=True).stdout
        return [name for name in listing.split() if name.startswith(self.project.name + '-engine-')]

    def test_session_engine_runs_library_images_inside_the_session_boundaries(self):
        # session-container-engine: Loopback endpoint / Library images run offline from a read-only store /
        # Nested containers have private process and host-name views / Engine mounts only the workspace /
        # Engine carries no secrets / Session-owned engine storage.
        result = self.shell(r"""
test "$CONTAINER_HOST" = tcp://127.0.0.1:2375
test "$DOCKER_HOST" = tcp://127.0.0.1:2375
test ! -S /run/podman/podman.sock
test "$(podman info --format '{{.Host.Security.Rootless}}')" = true
view=$(podman run --rm --network=none localhost/sandbox-test-sample:1 sh -c \
  'echo "$(cat /proc/1/comm) $(ls /proc | grep -c "^[0-9]") $(cat /proc/sys/kernel/hostname) $(ls -A /run/secrets 2>/dev/null | wc -l)"')
set -- $view
test "$1" = sh && test "$2" -le 4 && test "$3" != "$(cat /proc/sys/kernel/hostname)" && test "$4" = 0
echo "NESTED_VIEW $view"
podman run --rm --network=none -v "$PWD:$PWD" -w "$PWD" localhost/sandbox-test-sample:1 sh -c 'echo nested > nested-file'
test "$(stat -c %u nested-file)" = "$(id -u)"
podman run --rm --network=none -v /etc:/outside:ro localhost/sandbox-test-sample:1 grep -q k8s-file /outside/containers/containers.conf
! podman rmi localhost/sandbox-test-sample:1
podman image exists localhost/sandbox-test-sample:1
# Builds and the extraction of new layers (pull, load) chroot.
mkdir .build-context && printf 'FROM localhost/sandbox-test-sample:1\nRUN echo built > /built\n' > .build-context/Containerfile
podman build --quiet --pull=never --tag localhost/sandbox-test-built:1 .build-context >/dev/null
test "$(podman run --rm --network=none localhost/sandbox-test-built:1 cat /built)" = built
podman save --quiet --output .built.tar localhost/sandbox-test-built:1
podman rmi localhost/sandbox-test-built:1 >/dev/null
podman load --quiet --input .built.tar >/dev/null
podman image exists localhost/sandbox-test-built:1
rm -rf .build-context .built.tar
echo ENGINE_SESSION_OK
""")
        self.assert_success(result)
        self.assertIn('ENGINE_SESSION_OK', result.stdout)
        self.assertEqual((self.project / 'nested-file').stat().st_uid, os.getuid())
        self.assertEqual(self.engines(), [])

    def test_engine_process_rlimit_counts_per_container(self):
        # set-process-limits-inside-containers: on the rlimit fallback, an engine
        # session starts and runs a nested container beside a container holding more
        # processes than its budget.
        if engine_budgets(self.env)[1] != 'rlimit':
            self.skipTest('the engine does not use the process rlimit fallback')
        start_crowd(self, self.env, 520)
        result = self.shell('test "$(grep "^Max processes" /proc/self/limits | tr -s " " | cut -d" " -f3,4)" = "512 512"\n'
                            'podman run --rm --network=none localhost/sandbox-test-sample:1 true\n'
                            'echo NESTED_BESIDE_CROWD_OK\n')
        self.assert_success(result)
        self.assertIn('NESTED_BESIDE_CROWD_OK', result.stdout)
        self.assertEqual(self.engines(), [])

    def test_no_engine_without_library_images(self):
        # session-container-engine: Library without images.
        self.toolchain('remove', 'sample')
        result = self.shell('test -z "${CONTAINER_HOST+x}${DOCKER_HOST+x}"\necho NO_ENGINE_OK\n')
        self.assert_success(result)
        self.assertNotIn('container engine', result.stderr)

    def eligibility(self):
        """The engine's delegation as a session launch reports it: None when delegated, else the reason."""
        result = self.shell('echo ELIGIBILITY_PROBE\n')
        self.assert_success(result)
        notice = next((line for line in result.stderr.splitlines() if INELIGIBLE in line), None)
        return None if notice is None else notice.split(INELIGIBLE + ': ', 1)[-1]

    def test_systemd_runs_in_nested_containers(self):
        # support-nested-systemd-containers: Systemd in nested containers / Unit and journal.
        if not SYSTEMD_SAMPLE:
            self.skipTest('set SANDBOX_TEST_SYSTEMD_SAMPLE to a systemd image in the engine')
        if subprocess.run(['podman', 'image', 'exists', SYSTEMD_SAMPLE], capture_output=True).returncode:
            self.skipTest('prepare ' + SYSTEMD_SAMPLE + ' in the engine first')
        reason = self.eligibility()
        if reason is not None:
            self.skipTest('the engine is ineligible: ' + reason)
        image_id = subprocess.run(['podman', 'image', 'inspect', '--format', '{{.Id}}', SYSTEMD_SAMPLE],
                                  capture_output=True, text=True, check=True).stdout.strip()
        self.add_image('systemd', 'localhost/sandbox-test-systemd:1', image_id)
        result = self.shell(r"""
podman run --detach --name target --systemd=always localhost/sandbox-test-systemd:1 >/dev/null
if ! podman exec target timeout 120 sh -c 'until systemctl is-system-running | grep -qE "^(running|degraded)$"; do sleep 1; done'; then
  echo "SYSTEM_STATE $(podman exec target systemctl is-system-running || true)"
  podman exec target systemctl --failed --no-pager || true
  exit 1
fi
echo "SYSTEM_STATE $(podman exec target systemctl is-system-running || true)"
podman exec target systemd-run --unit=probe --property=Type=oneshot /bin/true
podman exec target systemd-run --unit=journaled --property=Type=oneshot --property=RemainAfterExit=yes \
  /bin/sh -c 'echo journaled-output'
test "$(podman exec target systemctl is-active journaled)" = active
podman exec target journalctl -u journaled --no-pager -o cat | grep -q journaled-output
podman rm --force --time 0 target >/dev/null
echo SYSTEMD_OK
""", timeout=300)
        self.assert_success(result)
        self.assertIn('SYSTEMD_OK', result.stdout)
        self.assertNotIn(INELIGIBLE, result.stderr)
        self.assertEqual(self.engines(), [])

    def test_engine_cgroup_delegation_in_sessions(self):
        # support-nested-systemd-containers: Delegated engine cgroup subtree / Explicit limits for
        # nested containers / Engine startup step / Ineligible engines are announced.
        reason = self.eligibility()
        if reason is not None:
            result = self.shell('! podman run --rm --network=none --memory=64m localhost/sandbox-test-sample:1 true\n'
                                'echo INELIGIBLE_SESSION_OK\n')
            self.assert_success(result)
            self.assertIn('INELIGIBLE_SESSION_OK', result.stdout)
            self.skipTest('the engine is ineligible: ' + reason)
        controllers = engine_budgets(self.env)[0]
        limited = 'memory' in controllers and 'pids' in controllers
        marker = self.project / '.inspected'
        session = subprocess.Popen(['bash', str(WRAPPER), '--container-shell'], cwd=self.project, env=self.env,
                                   stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        def stop_session():
            if session.poll() is None:
                session.terminate()
                try:
                    session.wait(timeout=25)
                except subprocess.TimeoutExpired:
                    session.kill()
            session.communicate()
        self.addCleanup(stop_session)
        session.stdin.write(r"""set -Eeuo pipefail
own=$(podman run --rm --network=none --cgroupns=host localhost/sandbox-test-sample:1 cat /proc/self/cgroup)
case $own in 0::/engine|0::/) echo "NESTED_AT $own"; exit 1 ;; 0::/?*) echo "NESTED_OWN_CGROUP $own" ;; *) exit 1 ;; esac
podman run --rm --network=none --cgroupns=host --security-opt=unmask=ALL localhost/sandbox-test-sample:1 \
  sh -c '""" + LIMIT_PROBE.replace("'", "'\\''") + r"""' | sed 's/^/NESTED_/'
if limits=$(podman run --rm --network=none --memory=64m --pids-limit=32 localhost/sandbox-test-sample:1 \
    sh -c 'echo "$(cat /sys/fs/cgroup/memory.max) $(cat /sys/fs/cgroup/pids.max)"' 2>&1); then
  echo "NESTED_LIMITS $limits"
else
  echo "NESTED_LIMITS refused"
fi
echo SESSION_READY
while [ ! -e .inspected ]; do sleep 0.2; done
echo DELEGATION_SESSION_OK
""")
        session.stdin.close()
        session.stdin = None
        ready = []
        for line in session.stdout:
            ready.append(line.strip())
            if line.strip() == 'SESSION_READY':
                break
        self.assertIn('SESSION_READY', ready, '\n'.join(ready) + (session.stderr.read() if session.poll() else ''))
        engine = self.engines()
        self.assertEqual(len(engine), 1, engine)
        listing = subprocess.run(['podman', 'exec', '--user', 'podman', engine[0], 'sh', '-c',
                                  'init=$(readlink /proc/1/ns/user); for p in /proc/[0-9]*; do '
                                  '[ "$(readlink "$p/ns/user" 2>/dev/null)" = "$init" ] || continue; '
                                  'grep -E "^(Uid|CapPrm|CapEff|CapAmb):" "$p/status" 2>/dev/null '
                                  '| tr -s "\t" " " | tr "\n" " "; echo; done'],
                                 env=self.env, capture_output=True, text=True, timeout=60)
        self.assertEqual(listing.returncode, 0, listing.stderr)
        processes = [line.split() for line in listing.stdout.splitlines() if line.strip()]
        self.assertTrue(processes)
        for fields in processes:
            with self.subTest(process=' '.join(fields)):
                self.assertNotEqual(fields[fields.index('Uid:') + 1], '0')
                for name in ('CapPrm:', 'CapEff:', 'CapAmb:'):
                    self.assertFalse(int(fields[fields.index(name) + 1], 16) & 1, 'CAP_CHOWN in ' + name)
        marker.touch()
        stdout, stderr = session.communicate(timeout=180)
        self.assertEqual(session.returncode, 0, stdout + stderr)
        output = '\n'.join(ready) + '\n' + stdout
        self.assertIn('DELEGATION_SESSION_OK', output)
        self.assertNotIn(INELIGIBLE, stderr)
        self.assertIn('NESTED_OWN_CGROUP 0::/', output)
        nested = [line[len('NESTED_limit='):] for line in output.splitlines() if line.startswith('NESTED_limit=')]
        self.assertGreaterEqual(len(nested), 2, output)
        self.assertTrue(all(result.endswith(':denied') for result in nested), nested)
        self.assertIn('NESTED_LIMITS 67108864 32' if limited else 'NESTED_LIMITS refused', output)
        self.assertEqual(self.engines(), [])

    def test_live_image_and_isolated_concurrent_sessions(self):
        # session-container-engine: Image added during a session / Two sessions.
        marker = self.project / '.image-added'
        first = subprocess.Popen(['bash', str(WRAPPER), '--container-shell'], cwd=self.project, env=self.env,
                                 stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        def stop_first():
            if first.poll() is None:
                first.terminate()
                try:
                    first.wait(timeout=25)
                except subprocess.TimeoutExpired:
                    first.kill()
            first.communicate()
        self.addCleanup(stop_first)
        first.stdin.write(r"""set -Eeuo pipefail
podman run -d --name first-session-marker --network=none localhost/sandbox-test-sample:1 sleep 120 >/dev/null
echo FIRST_READY
while [ ! -e .image-added ]; do sleep 0.2; done
podman run --rm --network=none localhost/sandbox-test-live:1 true
echo LIVE_IMAGE_OK
podman rm -f -t 0 first-session-marker >/dev/null
""")
        first.stdin.close()
        first.stdin = None
        ready, _, _ = select.select([first.stdout], [], [], 60)
        self.assertTrue(ready, 'first session did not report readiness')
        self.assertEqual(first.stdout.readline().strip(), 'FIRST_READY',
                         first.stderr.read() if first.poll() is not None else '')
        second = self.shell('! podman container exists first-session-marker\n'
                            'test -z "$(podman ps --all --quiet)"\necho SECOND_ISOLATED\n')
        self.assert_success(second)
        self.add_image('live', 'localhost/sandbox-test-live:1')
        marker.touch()
        stdout, stderr = first.communicate(timeout=180)
        self.assertEqual(first.returncode, 0, stdout + stderr)
        self.assertIn('LIVE_IMAGE_OK', stdout)
        self.assertEqual(self.engines(), [])


if __name__ == '__main__':
    unittest.main()

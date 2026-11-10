"""Qualification contracts and credential-free installed-path acceptance."""
import copy
import importlib.util
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import unittest
import uuid
import io
from contextlib import redirect_stdout
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
from sandbox_profile import AGENT_IMAGE, POLICY_FILE, PROFILE, ROOT, WIDE_PROFILE, env as name, test_setting
import agent_profile
import qualification_records as records
import qualify

QUALIFICATION_LABEL = PROFILE.label('qualification')
WORK_GLOB = '.' + PROFILE.name + '-qualification-*'


class QualificationContracts(unittest.TestCase):
    def identity(self):
        return dict(mode='provider', revision=records.REVISION, runtime='a'*64, proxy='b'*64,
                    policy='c'*64, platform=dict(abi=3), code={'guard':'d'*64},
                    hardening=dict(capabilities=[], no_new_privs=True, pids=128, memory=268435456,
                                   agent=dict(capabilities=[], no_new_privs=True, memory=4294967296,
                                              nano_cpus=2000000000, pids=512, timeout=0)))

    def report(self):
        identity = self.identity()
        return dict(schema=1, identity=identity, fingerprint=records.digest(records.canonical(identity)),
                    checks={name:'passed' for name in records.expected_checks(True)},
                    measured_at='2026-11-07T17:00:00+00:00', reusable=True)

    def test_report_requires_complete_exact_evidence_and_hardening(self):
        report = self.report()
        records.validate_report(report, self.identity())
        for mutate in (lambda r: r['checks'].pop('ip6'), lambda r:r['checks'].update(ip4='unavailable'),
                       lambda r:r['checks'].update(ip4='skipped'), lambda r:r.update(schema=True),
                       lambda r:r.update(extra='ignored'), lambda r:r.update(fingerprint='0'*64),
                       lambda r:r['identity']['hardening'].update(memory=0),
                       lambda r:r['identity']['hardening'].update(no_new_privs=1),
                       lambda r:r['identity']['hardening']['agent'].update(pids=1024),
                       lambda r:r['identity']['hardening']['agent'].update(timeout=60),
                       lambda r:r.update(reusable='true')):
            value = copy.deepcopy(report); mutate(value)
            with self.subTest(value=value), self.assertRaises(ValueError):
                records.validate_report(value, self.identity())

    def test_each_enforcement_identity_change_invalidates_evidence(self):
        report = self.report()
        for key in ('mode', 'runtime', 'proxy', 'policy', 'revision', 'platform', 'code', 'hardening'):
            changed = self.identity(); changed[key] = 'changed'
            with self.subTest(key=key), self.assertRaises(ValueError):
                records.validate_report(report, changed)
        for data in (b'{"schema":1,"schema":1}', b'{}\n{}', b'x'*65537):
            with self.assertRaises(ValueError):
                records.decode(data)

    def test_agent_hardening_follows_the_effective_environment(self):
        import agent_budgets
        default = agent_budgets.agent_hardening({}, PROFILE)
        self.assertEqual(default, self.identity()['hardening']['agent'])
        saved = {name('MEMORY_LIMIT'): '8g', name('CPU_LIMIT'): '1.5', name('PIDS_LIMIT'): '1024',
                 name('RUN_TIMEOUT'): '3600'}
        self.assertEqual(agent_budgets.agent_hardening(saved, PROFILE),
                         dict(capabilities=[], no_new_privs=True, memory=8 << 30, nano_cpus=1500000000,
                              pids=1024, timeout=3600))
        for suffix, value in (('PIDS_LIMIT', '2048'), ('RUN_TIMEOUT', '1'), ('CPU_LIMIT', '2.5'), ('MEMORY_LIMIT', '4097m')):
            with self.subTest(suffix=suffix):
                self.assertNotEqual(agent_budgets.agent_hardening(saved | {name(suffix): value}, PROFILE),
                                    agent_budgets.agent_hardening(saved, PROFILE))
        with self.assertRaises(agent_budgets.BudgetError):
            agent_budgets.agent_hardening({name('PIDS_LIMIT'): '0'}, PROFILE)

    def test_probe_requires_effective_agent_budgets(self):
        import ast
        source = (ROOT / 'network/qualification_probe.py').read_text()
        node = next(n for n in ast.parse(source).body if isinstance(n, ast.FunctionDef) and n.name == 'effective_budgets')
        namespace = {'Path': Path}
        exec(compile(ast.Module([node], []), 'qualification_probe.py', 'exec'), namespace)
        budgets = self.identity()['hardening']['agent']
        with tempfile.TemporaryDirectory(dir=test_setting('TEST_TMPDIR')) as temporary:
            base = Path(temporary)
            membership = base / 'membership'
            def write(memory='4294967296', pids='512', cpu='200000 100000', cgroup='0::/'):
                membership.write_text(cgroup + '\n')
                for key, value in (('memory.max', memory), ('pids.max', pids), ('cpu.max', cpu)):
                    (base / key).write_text(value + '\n')
            write()
            namespace['effective_budgets'](budgets, base, membership)
            for change in (dict(memory='max'), dict(pids='513'), dict(cpu='max 100000'), dict(cpu='100000 100000'),
                           dict(cgroup='0::/user.slice')):
                with self.subTest(change=change):
                    write(**change)
                    with self.assertRaises((AssertionError, ValueError)):
                        namespace['effective_budgets'](budgets, base, membership)

    def test_missing_report_names_budgets_as_a_cause(self):
        with tempfile.TemporaryDirectory(dir=test_setting('TEST_TMPDIR')) as temporary:
            root = Path(temporary)
            (root / 'qualification').mkdir(mode=0o700)
            with patch.object(records, 'trusted_path', side_effect=lambda path, writable, directory=False: Path(path)), \
                    self.assertRaisesRegex(ValueError, 'agent budgets/lifetime; rerun --container-qualify'):
                records.read(root, self.identity(), [])

    def test_release_measured_requires_exact_protected_acceptance_entry(self):
        identity = self.identity()
        self.assertEqual(records.evidence_status(dict(schema=1, fingerprints=[]), identity), 'locally-qualified')
        value = dict(schema=1, fingerprints=[records.digest(records.canonical(identity))])
        self.assertEqual(records.evidence_status(value, identity), 'release-measured')
        changed = identity | {'runtime':'e'*64}
        self.assertEqual(records.evidence_status(value, changed), 'locally-qualified')
        for invalid in ({}, dict(schema=True, fingerprints=[]), dict(schema=1, fingerprints=['*'])):
            with self.assertRaises(ValueError):
                records.evidence_status(invalid, identity)

    def test_bounded_subprocess_group_cleanup(self):
        with tempfile.TemporaryDirectory() as temporary:
            pidfile = Path(temporary) / 'pid'
            script = """import os,signal,sys,time
child=os.fork()
if child:
 time.sleep(.1); sys.exit(0)
signal.signal(signal.SIGTERM,signal.SIG_IGN)
open(sys.argv[1],'w').write(str(os.getpid()))
os.close(0); os.close(1); os.close(2)
time.sleep(60)
"""
            gate = qualify.Gate(os.environ)
            gate.run([sys.executable, '-c', script, str(pidfile)], timeout=3)
            pid = int(pidfile.read_text())
            deadline = time.monotonic()+2
            while time.monotonic()<deadline:
                stat = Path(f'/proc/{pid}/stat')
                if not stat.exists() or stat.read_text().split()[2]=='Z':
                    break
                time.sleep(.02)
            else:
                os.kill(pid, signal.SIGKILL)
                self.fail('owned descendant survived group cleanup')
            started = time.monotonic()
            with self.assertRaises(subprocess.TimeoutExpired):
                gate.run([sys.executable, '-c',
                    'import signal,time; signal.signal(signal.SIGTERM,signal.SIG_IGN); time.sleep(60)'],
                    timeout=.2)
            self.assertLess(time.monotonic() - started, 5)
            self.assertIsNone(gate.process)

    def test_code_identity_binds_wrapper_profile_and_policy(self):
        files = records.code_files(PROFILE)
        for path in (PROFILE.wrapper, agent_profile.PROFILE, agent_profile.POLICY,
                     'network/agent_profile.py', 'network/bin/sandbox-egress-guard'):
            self.assertIn(path, files)
        identity = self.identity()
        report = dict(schema=1, identity=identity, fingerprint=records.digest(records.canonical(identity)),
                      checks={check: 'passed' for check in records.expected_checks(True)},
                      reusable=True, measured_at='2026-11-08T00:00:00+00:00')
        changed = copy.deepcopy(identity)
        changed['code'][agent_profile.PROFILE] = 'f' * 64
        with self.assertRaises(ValueError):
            records.validate_report(report, changed)

    def test_changed_protected_profile_stops_the_gate(self):
        other = agent_profile.validate(json.loads((ROOT / agent_profile.PROFILE).read_text()) | {'display_name': 'Changed'})
        with tempfile.TemporaryDirectory() as temporary, patch.object(qualify,'ROOT',Path(temporary)), \
                patch.object(qualify,'trusted_path',side_effect=lambda path,*a,**k:Path(path)), \
                patch.object(qualify.agent_profile,'load',return_value=other), \
                patch.object(qualify,'Gate') as gate, \
                patch.object(sys,'argv',['qualify.py','qualify']), \
                patch.dict(os.environ,{'CONTAINER_HOST':'unix:///some/socket',name('NETWORK'):'offline'},clear=True):
            with self.assertRaisesRegex(qualify.GateError,'profile changed'):
                qualify.main()
            gate.assert_not_called()

    def test_unknown_policy_requalifies_and_changed_inputs_cannot_publish(self):
        identity=self.identity()
        for changed in (False, True):
            gate=unittest.mock.Mock()
            snapshots=[(identity,False),(identity | {'runtime':'changed'} if changed else identity,False)]
            with tempfile.TemporaryDirectory() as temporary, patch.object(qualify,'ROOT',Path(temporary)), \
                    patch.object(qualify,'trusted_path',side_effect=lambda path,*a,**k:Path(path)), \
                    patch.object(qualify,'Gate',return_value=gate), patch.object(qualify.records,'code_files',return_value=()), \
                    patch.object(qualify.agent_profile,'load',return_value=qualify.PROFILE), \
                    patch.object(qualify.records,'fingerprint',side_effect=snapshots), \
                    patch.object(qualify.records,'read',return_value={'reusable':False}), \
                    patch.object(qualify.records,'publish') as publish, \
                    patch.object(qualify.records,'status',return_value='locally-qualified'), \
                    patch.object(sys,'argv',['qualify.py','check']), \
                    patch.dict(os.environ,{'CONTAINER_HOST':'unix:///some/socket',name('NETWORK'):'offline'},clear=True):
                if changed:
                    with self.assertRaisesRegex(qualify.GateError,'changed'):
                        qualify.main()
                    publish.assert_not_called()
                else:
                    with redirect_stdout(io.StringIO()) as output:
                        qualify.main()
                    self.assertEqual(output.getvalue(),'')
                    publish.assert_called_once()
                gate.qualify.assert_called_once_with(identity)
                self.assertTrue(gate.cleanup.called)

    def test_failed_control_cannot_publish_a_success_report(self):
        gate=unittest.mock.Mock()
        gate.qualify.side_effect=qualify.GateError('positive control unavailable')
        with tempfile.TemporaryDirectory() as temporary, patch.object(qualify,'ROOT',Path(temporary)), \
                patch.object(qualify,'trusted_path',side_effect=lambda path,*a,**k:Path(path)), \
                patch.object(qualify,'Gate',return_value=gate), patch.object(qualify.records,'code_files',return_value=()), \
                    patch.object(qualify.agent_profile,'load',return_value=qualify.PROFILE), \
                patch.object(qualify.records,'fingerprint',return_value=(self.identity(),True)), \
                patch.object(qualify.records,'publish') as publish, \
                patch.object(sys,'argv',['qualify.py','qualify']), \
                patch.dict(os.environ,{'CONTAINER_HOST':'unix:///some/socket',name('NETWORK'):'offline'},clear=True):
            with self.assertRaisesRegex(qualify.GateError,'unavailable'):
                qualify.main()
            publish.assert_not_called()
            self.assertTrue(gate.cleanup.called)
            gate.qualify.side_effect = None
            gate.cleanup.side_effect = [None, qualify.GateError('cleanup unavailable')]
            with self.assertRaisesRegex(qualify.GateError, 'cleanup unavailable'):
                qualify.main()
            publish.assert_not_called()


@unittest.skipUnless(test_setting('RUNTIME_TESTS') == '1', 'requires disposable native rootless harness')
class QualificationRuntime(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.guard = tempfile.TemporaryDirectory(prefix='qualification-guard-', dir=test_setting('TEST_STATE_ROOT'))
        cls.addClassCleanup(cls.guard.cleanup)
        result = subprocess.run(['bash', str(ROOT/'network/build-guard.sh'), cls.guard.name],
            env=os.environ | {name('MAINTENANCE'):'1'}, capture_output=True, text=True, timeout=60)
        if result.returncode:
            raise RuntimeError(result.stderr)
        tag = PROFILE.image('proxy', 'qualification-test-' + uuid.uuid4().hex)
        cls.addClassCleanup(subprocess.run, ['podman', 'rmi', '--force', tag],
                            capture_output=True, timeout=30)
        result = subprocess.run(['podman', 'build', '--pull=never', '--tag', tag,
            '--file', str(ROOT/'network/Containerfile'), str(ROOT/'network')],
            capture_output=True, text=True, timeout=60)
        if result.returncode:
            raise RuntimeError(result.stdout + result.stderr)
        cls.proxy_image = subprocess.check_output(['podman', 'image', 'inspect',
            '--format', '{{.Id}}', tag], text=True).strip()

    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(prefix='qualification-', dir=test_setting('TEST_STATE_ROOT'))
        self.addCleanup(self.directory.cleanup)
        self.base = Path(self.directory.name)
        self.install = self.base/'installed'; self.install.mkdir(mode=0o700)
        (self.install/'network').mkdir(mode=0o700)
        shutil.copyfile(ROOT/PROFILE.wrapper, self.install/PROFILE.wrapper)
        # The wrapper may read its recipe and declared agent files on every launch.
        for relative in ('Containerfile', '.containerignore', *PROFILE.install_files):
            (self.install/relative).parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            shutil.copyfile(ROOT/relative, self.install/relative)
        (self.install/'agent/policies').mkdir(mode=0o700, parents=True)
        shutil.copyfile(ROOT/agent_profile.PROFILE, self.install/agent_profile.PROFILE)
        shutil.copyfile(POLICY_FILE, self.install/agent_profile.POLICY)
        for source in (ROOT/'network').glob('*.py'):
            shutil.copyfile(source, self.install/'network'/source.name)
        shutil.copyfile(ROOT/'network/resolv.conf', self.install/'network/resolv.conf')
        shutil.copytree(self.guard.name, self.install/'network/bin')
        self.project=self.base/'project'; self.project.mkdir()
        self.home=self.base/'home'; self.home.mkdir(mode=0o700)
        self.runtime=self.base/'egress'; self.runtime.mkdir(mode=0o700)
        self.env=dict(PATH=os.environ['PATH'], HOME=str(self.home),
            CONTAINER_HOST=os.environ['CONTAINER_HOST'])
        self.env.update({name('NETWORK'): 'offline', name('STATE_DIR'): str(self.base/'state'),
            name('NETWORK_RUNTIME_DIR'): str(self.runtime),
            name('IMAGE'): os.environ.get(name('IMAGE'), AGENT_IMAGE)})

    def command(self, *args, input=None, timeout=325):
        return subprocess.run(['bash', str(self.install/PROFILE.wrapper), *args],
            cwd=self.project, env=self.env, input=input, capture_output=True, text=True, timeout=timeout)

    def test_installed_offline_qualification_missing_stale_and_unsafe_reports(self):
        result=self.command('--container-shell', input='touch agent-started\n')
        self.assertNotEqual(result.returncode,0)
        self.assertIn('qualification',result.stderr)
        self.assertFalse((self.project/'agent-started').exists())
        result=self.command('--container-qualify')
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)
        self.assertIn('SANDBOX_QUALIFICATION_OK',result.stdout)
        paths=list((self.install/'qualification').glob('*.json'))
        self.assertEqual(len(paths),1)
        report=json.loads(paths[0].read_text())
        self.assertEqual(report['identity']['hardening']['memory'],268435456)
        self.assertEqual(report['identity']['hardening']['agent']['pids'],512)
        result=self.command('--container-shell',input='printf qualified-startup-ok\n')
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)
        self.assertIn('qualified-startup-ok',result.stdout)
        # An exported budget that differs from the qualified one needs requalification.
        self.env[name('PIDS_LIMIT')]='1024'
        result=self.command('--container-shell',input='touch agent-started\n')
        self.assertNotEqual(result.returncode,0)
        self.assertIn('agent budgets/lifetime',result.stderr)
        self.assertFalse((self.project/'agent-started').exists())
        self.env[name('PIDS_LIMIT')]='512'
        result=self.command('--container-shell',input='printf explicit-default-ok\n')
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)
        del self.env[name('PIDS_LIMIT')]
        helper=self.install/'network/platform_check.py'
        helper.chmod(0o666)
        result=self.command('--container-shell',input='touch agent-started\n')
        self.assertNotEqual(result.returncode,0)
        self.assertIn('network policy preflight failed',result.stderr)
        helper.chmod(0o644)
        paths[0].chmod(0o644)
        self.assertNotEqual(self.command('--container-shell',input='touch agent-started\n').returncode,0)
        paths[0].chmod(0o600)
        code=self.install/'network/qualification_probe.py'
        code.write_text(code.read_text()+'\n# changed enforcement fixture\n')
        self.assertNotEqual(self.command('--container-shell',input='touch agent-started\n').returncode,0)
        self.assertFalse((self.project/'agent-started').exists())

    def test_installed_provider_qualification_and_fixed_probe_cannot_run_application(self):
        image=self.proxy_image
        policy=self.install/'policy.json'; shutil.copyfile(POLICY_FILE,policy)
        self.env.update({name('NETWORK'):'provider',name('NETWORK_PROFILE'):WIDE_PROFILE,
            name('NETWORK_POLICY'):str(policy),name('EGRESS_IMAGE'):image})
        result=self.command('--container-qualify')
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)
        report=json.loads(next((self.install/'qualification').glob('*.json')).read_text())
        self.assertEqual(report['checks']['tls-mismatch-zero-bytes'],'passed')
        self.assertEqual(report['checks']['proxy-loss'],'passed')
        for args in (('--container-qualify','--container-shell'), ('--container-qualify-probe','touch','agent-started')):
            self.assertNotEqual(self.command(*args).returncode,0)
        result=self.command('--container-qualify-probe')
        self.assertNotEqual(result.returncode,0)
        self.assertFalse((self.project/'agent-started').exists())
        data=dict(schema=1,token='a'*32,workspace=str(self.project),addresses=['127.0.0.1','::1'],provider=True,tls=False)
        path=self.install/'bad-input.json'
        path.write_text(json.dumps(data | {'command':'touch agent-started'}))
        self.env[name('QUALIFICATION_INPUT')]=str(path)
        self.assertNotEqual(self.command('--container-qualify-probe').returncode,0)
        path=self.project/'writable-input.json'; path.write_text(json.dumps(data))
        self.env[name('QUALIFICATION_INPUT')]=str(path)
        self.assertNotEqual(self.command('--container-qualify-probe').returncode,0)
        self.assertFalse((self.project/'agent-started').exists())

    def test_ordinary_report_check_interruption_preserves_shutdown_budget(self):
        engine=shutil.which('podman')
        directory=self.base/'shim'; directory.mkdir()
        marker=self.base/'check-started'; counter=self.base/'host-query'
        script=directory/'podman'
        script.write_text("""#!/usr/bin/env python3
import os,pathlib,signal,sys,time
args=sys.argv[1:]
if args and args[0]=='info' and args[-1]=='{{json .Host}}':
 p=pathlib.Path(os.environ['QUALIFY_COUNTER'])
 if p.exists():
  signal.signal(signal.SIGTERM,signal.SIG_IGN)
  pathlib.Path(os.environ['QUALIFY_MARKER']).write_text(str(os.getpid()))
  time.sleep(300)
 p.touch()
os.execv(os.environ['QUALIFY_ENGINE'],[os.environ['QUALIFY_ENGINE'],*args])
""")
        script.chmod(0o700)
        env=self.env | dict(PATH=str(directory)+':'+self.env['PATH'], QUALIFY_ENGINE=engine,
                           QUALIFY_MARKER=str(marker),QUALIFY_COUNTER=str(counter))
        process=subprocess.Popen(['bash',str(self.install/PROFILE.wrapper),'--container-shell'],
            env=env,cwd=self.project,stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
        try:
            deadline=time.monotonic()+20
            while not marker.exists() and process.poll() is None and time.monotonic()<deadline:
                time.sleep(.02)
            self.assertTrue(marker.exists(),'ordinary check did not reach metadata inspection')
            started=time.monotonic(); process.terminate()
            stdout,stderr=process.communicate('touch agent-started\n',timeout=23)
            self.assertEqual(process.returncode,143,stdout+stderr)
            self.assertLess(time.monotonic()-started,21)
            self.assertFalse((self.project/'agent-started').exists())
            pid=int(marker.read_text())
            stat=Path(f'/proc/{pid}/stat')
            self.assertTrue(not stat.exists() or stat.read_text().split()[2]=='Z')
        finally:
            if process.poll() is None:
                process.kill(); process.communicate()

    def test_cancelled_gate_has_no_report_and_cleans_only_its_resources(self):
        process=subprocess.Popen(['bash',str(self.install/PROFILE.wrapper),'--container-qualify'],
            cwd=self.project,env=self.env,stdin=subprocess.DEVNULL,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
        try:
            deadline=time.monotonic()+30
            configs=[]
            while not configs and process.poll() is None and time.monotonic()<deadline:
                configs=list(self.base.glob(WORK_GLOB+'/shared/input.json'))
                time.sleep(.02)
            self.assertTrue(configs, 'gate did not reach owned fixture setup')
            token=json.loads(configs[0].read_text())['token']
            process.terminate()
            stdout,stderr=process.communicate(timeout=40)
            self.assertNotEqual(process.returncode,0,stdout+stderr)
            self.assertEqual(list((self.install/'qualification').glob('*.json')),[])
            result=subprocess.check_output(['podman','ps','--all','--filter',
                'label='+QUALIFICATION_LABEL+'='+token,'--format','{{.ID}}'],text=True).strip()
            self.assertEqual(result,'')
            self.assertEqual(list(self.base.glob(WORK_GLOB+'')),[])
        finally:
            if process.poll() is None:
                process.kill(); process.communicate()

    def test_cancelled_tls_gate_is_bounded_and_cleans_owned_resources(self):
        image=self.proxy_image
        policy=self.install/'policy.json'; shutil.copyfile(POLICY_FILE,policy)
        self.env.update({name('NETWORK'):'provider',name('NETWORK_PROFILE'):WIDE_PROFILE,
            name('NETWORK_POLICY'):str(policy),name('EGRESS_IMAGE'):image})
        # Instrument only this disposable installed fixture to hold the TLS
        # subprocess open after actual matching/mismatching handshake checks.
        probe=self.install/'network/qualification_probe.py'
        source=probe.read_text()
        source=source.replace("    print('qualification-proxy-loss-ready', flush=True)",
            "    Path('/workspace/cancel-tls-ready').touch()\n    __import__('time').sleep(60)\n"
            "    print('qualification-proxy-loss-ready', flush=True)")
        probe.write_text(source)
        process=subprocess.Popen(['bash',str(self.install/PROFILE.wrapper),'--container-qualify'],
            cwd=self.project,env=self.env,stdin=subprocess.DEVNULL,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
        try:
            deadline=time.monotonic()+100; markers=[]
            while not markers and process.poll() is None and time.monotonic()<deadline:
                markers=list(self.base.glob(WORK_GLOB+'/tls/project/cancel-tls-ready'))
                time.sleep(.02)
            self.assertTrue(markers,'gate did not reach controlled TLS stage')
            config=markers[0].parents[1]/'input.json'
            token=json.loads(config.read_text())['token']
            started=time.monotonic(); process.terminate()
            stdout,stderr=process.communicate(timeout=18)
            self.assertNotEqual(process.returncode,0,stdout+stderr)
            self.assertLess(time.monotonic()-started,15)
            self.assertEqual(list((self.install/'qualification').glob('*.json')),[])
            owned=subprocess.check_output(['podman','ps','--all','--filter',
                'label='+QUALIFICATION_LABEL+'='+token,'--format','{{.ID}}'],text=True).strip()
            self.assertEqual(owned,'')
            self.assertEqual(list(self.base.glob(WORK_GLOB+'')),[])
        finally:
            if process.poll() is None:
                process.kill(); process.communicate()

    def test_concurrent_gates_publish_complete_atomic_reports(self):
        children=[subprocess.Popen(['bash',str(self.install/PROFILE.wrapper),'--container-qualify'],
            cwd=self.project,env=self.env,stdin=subprocess.DEVNULL,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
            for _ in range(2)]
        try:
            for child in children:
                stdout,stderr=child.communicate(timeout=325)
                self.assertEqual(child.returncode,0,stdout+stderr)
            reports=list((self.install/'qualification').glob('*.json'))
            self.assertEqual(len(reports),1)
            value=json.loads(reports[0].read_text())
            records.validate_report(value,value['identity'])
            self.assertEqual(list(self.base.glob(WORK_GLOB+'')),[])
        finally:
            for child in children:
                if child.poll() is None:
                    child.terminate(); child.communicate(timeout=40)

    def test_record_publication_is_atomic_and_refuses_unsafe_paths(self):
        identity=QualificationContracts().identity()
        records.publish(self.install,identity,True,[])
        path=next((self.install/'qualification').glob('*.json'))
        old=path.read_bytes()
        with patch.object(records.os,'replace',side_effect=OSError('synthetic publication failure')):
            with self.assertRaises(OSError):
                records.publish(self.install,identity,True,[])
        self.assertEqual(path.read_bytes(),old)
        self.assertEqual(list(path.parent.glob('.qualification-*')),[])
        saved=path.parent/'saved'; path.rename(saved); path.symlink_to(saved.name)
        with self.assertRaises(ValueError):
            records.read(self.install,identity,[])
        path.unlink(); saved.rename(path); path.chmod(0o644)
        with self.assertRaises(ValueError):
            records.publish(self.install,identity,True,[])
        self.assertEqual(path.stat().st_mode & 0o777,0o644)

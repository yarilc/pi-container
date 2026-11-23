"""Per-agent check that the shared components equal the sandbox-container reference copy.

Complements the shared ``tests/test_alignment.py`` (identifier scan and
wrapper consistency) with a byte-identity check: ``network/``, ``setup/`` and
the shared tests must stay byte-identical to ``sandbox-container`` at the reference
tag; a defect is fixed there first and copied afterwards.
"""
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
REFERENCE_TAG = 'sandbox-ref-28'
REFERENCE_COMMIT = 'ba1ef1428a57625b70bb45d55cade5f08f46eecc'
SIBLING = ROOT.parent / 'sandbox-container'
# Shared directories whose complete file set is fixed by the manifest.
CLOSED_DIRECTORIES = ('launcher', 'network', 'setup')
SKIPPED_PARTS = ('__pycache__', 'bin')
MANIFEST = {
    'launcher/core.sh': '4d813d382e182e2edb9bb5cd69689f78f76fec9391f4004170c606ffe8e3611e',
    'launcher/windows/bootstrap.sh': '7b52801c1566f5ce045e11dacc33114ac16b8d9f9e9c45eab525d0fc24d9f8b1',
    'launcher/windows/core.ps1': '0d32ef75b3a723a3ecb8a8b477b875c3763d742728e6242614bbde5bafe7e802',
    'launcher/windows/enter.sh': '12c7844fddf9cf724b1f7fe3290e2e2b01de8459c1d9ceeb43901a5d53cada3f',
    'launcher/windows/install.ps1': 'fdb938da5a08059e1eb9760f3c7fc20fab68daddddd588d1566bb02a568e18b5',
    'launcher/windows/user-path.ps1': 'f72b1181925d8a1844d2e587ee0018f44b15ebc2b70c45df6f4e7bc912ef6458',
    'network/.containerignore': '938d84510789e940b804c8062c45c257d4a119ad55d21f60db57d6290590187c',
    'network/Containerfile': 'b909198e5027bc58ceca4e6076ea4b1a54faa592083e4c0190b2c671cc5b2f36',
    'network/README.md': '5e8c30704f4604f78b7c783bf66c824a62298d3db99e0a0979905fae505fe22d',
    'network/agent_budgets.py': '77e3260fd9367426b4d59d57c12024766c1a5b784037dfec1d4741d55f53f510',
    'network/agent_profile.py': 'edafa2bfddb6f1e8d9bb6ebb16eb4e8b13d868b22ef14bd30c8b777a1906af96',
    'network/build-guard.sh': 'e0cc2fce71feb01c447dcb4daf5194f65f098b8a4c9837f756de7e12345cc611',
    'network/control.py': 'f5845bf6a7e7aeda21040749c799a4c2057428e5e31942aedf80842b4e1dc325',
    'network/guard-build.Containerfile': '7c882fff4fe515aa07219392388a084fd972188d549e47be416730f9153f60ad',
    'network/guard.c': '56bea4256f96592d385011819d2acafd878edd0d769449b47493b58d8acc452e',
    'network/guard_landlock.h': '8d490d342fa3b037f494cb32578c204302bbb8208c20ee74f5486388110744d0',
    'network/guard_seccomp.h': 'c158d67589d1ba5e3b0e5188974865d881e31bd2eee19ec9a08f1993f4ca4e16',
    'network/mux.py': '1f30d2016f2d9463a1c23d9e3007a2cc14b66de931dd86229df73961d65bc72c',
    'network/platform_check.py': 'c8372fdf47e7036f3d34190074678a17d33dc68e21384a0571db5fc00185f4cd',
    'network/policy.py': '9b300a3052254993c9f4149a540d4565193c0dba09a34ac2350dada7b4cf097a',
    'network/proxy.py': '73b4ea218a50512a23eaf9d7e3eec606fcadb7e14b91097a0593af5cc19494e2',
    'network/proxy_hardening.py': 'b800545b4705a6753aa3097bdab41e64c99a28a919f0611c65218b75be3e652c',
    'network/qualification_peer.py': 'eaea202213ca9466dd8c904732b8a635bcfd20dcbcfcd5fe0a031cb9dd4dca0c',
    'network/qualification_probe.py': 'cab608f5be9e0ad9e2b07b353dcaf2a61e4cf6fbdfc5e8a6b480ccf430bc7a66',
    'network/qualification_proxy.py': 'fea115190b81f5c7bd4ddaa6be825e3a50d3c7cc44c0ae30b1e70d66f36d48ab',
    'network/qualification_records.py': '6ea65ffb4d2df068d4e5ea3b72875008b4d656fb65885db592114d8bfcdebf01',
    'network/qualification_runtime.py': 'a9395438a6ee7c3dcdcc74d366ca3f00b92c5c55c248687e25c96ac735b37ada',
    'network/qualify.py': 'c895831c7a404beab760153b5bb6640694d2ca81440c15e83cdcf7814917cdbd',
    'network/relay.py': '67f64f5a83994770f3bbac249d541f193dae3f494e20aa15a21cf2a44c0ce0ef',
    'network/release_acceptance.json': '50c7caa261f64c534af10d02d6420d5b08ffd20d1a8cc25a6321350bf186cefe',
    'network/resolv.conf': '8e40d95c29f83fe652b8a5d0dfda2ecfd94f9b51e0f406a517de1a3aa3fc6ad5',
    'network/revisions.py': 'fa35bcac26f5590c0d0b9477fea2773faa1f1eb285215e735e5cb8aa6b2b9cb1',
    'network/session.py': '8af31c257bb82f9d9e650667a6b7cef43ae32d579d5d4bf99e1ec835f686dded',
    'network/tls_client_hello.py': 'a4ce71c1710cb1dba7c9ad5889b16549b5d7ebb4a7ae7c2edbf96eab32771e80',
    'setup/common.py': '28161873afb60e02eb286baed9ef243719f87192d8eb6b103819f78161a6c70a',
    'setup/diagnostics.py': 'd6f2a81010f115f5631c829ccc70c39ba329b1baf44b393e34a33a884a3bdc3d',
    'setup/launch.py': '38f06d618e5650b3ecfd94127776daea96be4eac5ef4544f428518369a8a153e',
    'setup/setup.py': '18f0c64364edfdf984aab0ad153dfcd63c6ff5cc65143317dcda01a217457e44',
    'setup/smoke.py': '002b4fb42733cb22fdce8f488f9fa7e01f1cae718f4392094bb9bfc729fdcd4b',
    'setup/toolchains.py': '91e32207ee4ba116852eafd0690a95ca935f7668d03e5baabf0c224848b59ae8',
    'tests/fake_podman.py': '7648401807f8a66b6d55bb4efded1916d3d2def0b889cac1554a37bd74b73bdb',
    'tests/fixtures/agent/launcher.sh': 'd1093748a8d2b54150c3abf72461921798f00b56fe6349caf4b64fbe881ce3f4',
    'tests/fixtures/agent/policies/default.json': '4a990d9c90c90401c019faf5c7a96c083ae510b7a3507af584fec1f5bef8bb6f',
    'tests/fixtures/agent/profile.json': '25ea638dc7104e955b56b1c6663366c1a2d7280f92a04cb0997aece4b7d66d04',
    'tests/fixtures/shell-agent/launcher.sh': '0374bdeb8fec096a0b2b8eac9686eb85c8a2bb8b8e222744f877a89af1f4073b',
    'tests/fixtures/shell-agent/policies/default.json': 'a4a765ecaa63acb1f3aed3838b3f409a3c19dca57346ab284ce5ceda96b5f1fc',
    'tests/fixtures/shell-agent/profile.json': 'd254b6c0fdc5531c7fef98de074b206a753f4313394c4bfb2f0217134072376b',
    'tests/guard_bind_fixture.py': 'd6e4eb85cedb249ec9c6b4f2a026d14acbd5e1309a63ac036647be06781287cc',
    'tests/guard_mux_fixture.py': 'c641e419f5f2939c0c0af34d8a19dfcbcdf42302e0686e2d446bfad1bfc85f3d',
    'tests/guard_runtime_fixture.py': '73461452420305dfbacdb24ccb2336c490667f961e816f5b285ef15d35455597',
    'tests/guard_syscall_mock.c': '56ba41dcf49c0f07b40dff43b5527b697f5682beb3f6ed14827230f8d7c86670',
    'tests/idle_mux_fixture.py': 'a85aff09892732f71f1c8436465a9d531dd027eab7cdc158c9073005d6508d58',
    'tests/mux_failure_fixture.py': 'a53da415f54bf98cceca6e546d705969c69a4d5619f5b3584cb35214353669b6',
    'tests/mux_fault_boundary.py': 'faf7aaa356dabd64306df8f5c0cb4054f9d267263db653bc0359c3d2cf2672fd',
    'tests/network_fixture.py': '90311f5240f14c373dc83ce0d2c4d023c4aa247adcf361ccebfaa2009c3e3675',
    'tests/proxy_budget_fixture.py': 'cde9c888d3842045752a93ec1963110749a3d9cd4d48ef76d199e0b4847fea67',
    'tests/sandbox_profile.py': 'ca73c66b3dc2e814197ca714b4dbe8ce7c3c4063b8dfd48b864a6869a563b87f',
    'tests/test_agent_profile.py': '51072b5c037496f5ad057610247d508c03ebe07e6b855ab440f8b9179c0b3ea6',
    'tests/test_alignment.py': '1d0786b719a18ca7cbb7e6f6bea5b638edcd13b71db09b58012daf520e996cb2',
    'tests/test_guard.py': '0f4bd7a721805177a3b750c92b2db8fbf7e7580f6b65d819456f076e65341953',
    'tests/test_launcher.py': 'f9c5c3c6d0f74535c91de7e77678353ce178261281dd45175fc916e69797974f',
    'tests/test_mux.py': 'fb3a7cf8675d247c6609a337d56682d484cde6296e14ea939bfde70537cc8446',
    'tests/test_network_feasibility.py': '4cff9c50b996fd38f2b21b75abe73de77531e554522b04641fcb5288178d1e1c',
    'tests/test_network_policy.py': 'f57b3fe72deca821510855b6a474efb2e606471c4d231c210a699627e056f032',
    'tests/test_platform.py': 'e5e30cbb9edb3561e0a6cac67641ab27986ce9e6bd425e5be96976c39fb5fecf',
    'tests/test_qualification.py': '6de5a95fb1467a9bd63b980bc538ba272bacc2a424313f1d0628419ab023d37f',
    'tests/test_session.py': '4e04ca42bef3013f97ffc1bda683b07f7d7b46a1671f07880222cd7b7208c3e7',
    'tests/test_setup.py': '83448bf1558f8169470035abdf0e6b82f7686131f24de40416b44cfbfa8447c5',
    'tests/test_tls_client_hello.py': '7d8f889af0c4a8f6d40038bdbda915f3afa3adc08c47b5506a02180b595b7ccc',
    'tests/test_tls_proxy.py': '77f9dda900a8ee28ef76d018d862bd0475193f5b90840fd29005a04fe4403e83',
    'tests/test_toolchains.py': '1d9934b4ba5d23b4d071c69815a9036b40f432dee44235831bfa14ad8997e13c',
    'tests/test_windows_bootstrap.py': 'a1ac6c2d0d606f443104ab8ce4bdbfed6c390f617d79cd5660994bba1d015a46',
    'tests/test_windows_enter.py': 'c696a32b11e1b59ef695c71f8f8c9980a6caf8ffdec66c242a718f9b5a3ecb42',
    'tests/tls_binding_fixture.py': '062fe63ec1fc8ad399199a5f5823515070d5d1fa4ac62607f8722a61347f3331',
    'tests/windows/shim_tests.ps1': '60d75f473a1209458dab5ccc98e74b5b8a8fb791bbd996ba407f83da02bfb19a',
}


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def differences(root):
    """Changed, missing and extra shared files below ``root``."""
    found = []
    for name, expected in sorted(MANIFEST.items()):
        path = root / name
        if not path.is_file():
            found.append('missing ' + name)
        elif digest(path) != expected:
            found.append('changed ' + name)
    for directory in CLOSED_DIRECTORIES:
        for path in sorted((root / directory).rglob('*')):
            relative = path.relative_to(root)
            if path.is_file() and not any(part in SKIPPED_PARTS for part in relative.parts) \
                    and str(relative) not in MANIFEST:
                found.append('extra ' + str(relative))
    return found


def identifiers(root):
    return json.loads((root / 'agent/profile.json').read_text())['identifiers']


def literals(root, names):
    pattern = re.compile('|'.join(map(re.escape, names)), re.IGNORECASE)
    found = []
    for name in sorted(MANIFEST):
        for number, line in enumerate((root / name).read_text(errors='replace').splitlines(), 1):
            if pattern.search(line):
                found.append(f'{name}:{number}: {line.strip()[:120]}')
    return found


def scratch_copy(directory):
    copy = Path(directory)
    for name in (*CLOSED_DIRECTORIES, 'tests', 'agent'):
        if (ROOT / name).is_dir():
            shutil.copytree(ROOT / name, copy / name, ignore=shutil.ignore_patterns(*SKIPPED_PARTS))
    return copy


class ReferenceCopy(unittest.TestCase):
    def test_shared_files_match_the_reference_manifest(self):
        self.assertEqual(differences(ROOT), [])

    def test_manifest_detects_changed_missing_and_extra_files(self):
        with tempfile.TemporaryDirectory() as directory:
            copy = scratch_copy(directory)
            target = copy / 'network/control.py'
            target.write_bytes(target.read_bytes() + b' ')
            setup = copy / 'setup/common.py'
            setup.write_bytes(setup.read_bytes() + b' ')
            (copy / 'network/mux.py').unlink()
            (copy / 'network/local.py').write_text('')
            self.assertEqual(differences(copy), [
                'changed network/control.py', 'missing network/mux.py', 'changed setup/common.py',
                'extra network/local.py'])

    @unittest.skipUnless((ROOT / 'agent/profile.json').is_file(), 'agent profile not written yet')
    def test_shared_files_contain_no_agent_identifiers(self):
        self.assertEqual(literals(ROOT, identifiers(ROOT)), [])

    @unittest.skipUnless((ROOT / 'agent/profile.json').is_file(), 'agent profile not written yet')
    def test_scan_detects_an_injected_identifier(self):
        with tempfile.TemporaryDirectory() as directory:
            copy = scratch_copy(directory)
            target = copy / 'network/control.py'
            target.write_text(target.read_text() + '\n# ' + identifiers(ROOT)[0].title() + ' literal\n')
            found = literals(copy, identifiers(ROOT))
            self.assertEqual(len(found), 1)
            self.assertTrue(found[0].startswith('network/control.py:'))

    def test_sibling_checkout_at_the_reference_tag_matches(self):
        if not (SIBLING / '.git').exists():
            self.skipTest('no sibling sandbox-container checkout')
        commit = subprocess.run(['git', '-C', str(SIBLING), 'rev-parse', '--verify', '-q',
                                 REFERENCE_TAG + '^{commit}'], capture_output=True, text=True)
        if commit.returncode:
            self.skipTest('sibling checkout has no ' + REFERENCE_TAG)
        self.assertEqual(commit.stdout.strip(), REFERENCE_COMMIT)
        with tempfile.TemporaryDirectory() as directory:
            archive = subprocess.run(['git', '-C', str(SIBLING), 'archive', REFERENCE_TAG, *sorted(MANIFEST)],
                                     capture_output=True, check=True).stdout
            subprocess.run(['tar', '-x', '-C', directory], input=archive, check=True)
            self.assertEqual(differences(Path(directory)), [])
            result = subprocess.run(['diff', '-r', '-x', '__pycache__', '-x', 'bin', directory + '/network',
                                     str(ROOT / 'network')], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == '__main__':
    unittest.main()

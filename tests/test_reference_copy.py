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
REFERENCE_TAG = 'sandbox-ref-25'
REFERENCE_COMMIT = '6bed77040c3482591e36c9c3500bca89dec61941'
SIBLING = ROOT.parent / 'sandbox-container'
# Shared directories whose complete file set is fixed by the manifest.
CLOSED_DIRECTORIES = ('launcher', 'network', 'setup')
SKIPPED_PARTS = ('__pycache__', 'bin')
MANIFEST = {
    'launcher/core.sh': '61d8a6e0a6ddbf264c5cae5983078781c53bf9557c0d8de58c34d17923bcc296',
    'network/.containerignore': '938d84510789e940b804c8062c45c257d4a119ad55d21f60db57d6290590187c',
    'network/Containerfile': 'b909198e5027bc58ceca4e6076ea4b1a54faa592083e4c0190b2c671cc5b2f36',
    'network/README.md': '0e88d289d9eb9d3ba0d2c53540f407fb08dc74ac8e30f9b73e7ede021319fcf3',
    'network/agent_budgets.py': '36db8257878ca96c8a8968a5755b6ffd5cd9e794e8c72015252dba7d019862f8',
    'network/agent_profile.py': 'edafa2bfddb6f1e8d9bb6ebb16eb4e8b13d868b22ef14bd30c8b777a1906af96',
    'network/build-guard.sh': 'e0cc2fce71feb01c447dcb4daf5194f65f098b8a4c9837f756de7e12345cc611',
    'network/control.py': '050f0502d7e58195614d122760a70e376be1fb79ef30b38cc44bc456074418dd',
    'network/guard-build.Containerfile': '7c882fff4fe515aa07219392388a084fd972188d549e47be416730f9153f60ad',
    'network/guard.c': 'e1ee63205ca1bb15380ace9f994a28971abc193f69cf321460738b52604630d1',
    'network/guard_landlock.h': '8d490d342fa3b037f494cb32578c204302bbb8208c20ee74f5486388110744d0',
    'network/guard_seccomp.h': 'c158d67589d1ba5e3b0e5188974865d881e31bd2eee19ec9a08f1993f4ca4e16',
    'network/mux.py': '1f30d2016f2d9463a1c23d9e3007a2cc14b66de931dd86229df73961d65bc72c',
    'network/platform_check.py': 'c8372fdf47e7036f3d34190074678a17d33dc68e21384a0571db5fc00185f4cd',
    'network/policy.py': '9b300a3052254993c9f4149a540d4565193c0dba09a34ac2350dada7b4cf097a',
    'network/proxy.py': '73b4ea218a50512a23eaf9d7e3eec606fcadb7e14b91097a0593af5cc19494e2',
    'network/proxy_hardening.py': '4b473682a17f3f8812b507279cf8d760b9eb3857ea3c4f45115acdc5279090d8',
    'network/qualification_peer.py': 'eaea202213ca9466dd8c904732b8a635bcfd20dcbcfcd5fe0a031cb9dd4dca0c',
    'network/qualification_probe.py': '32cf37eb0f997e800776916e21fa73e4715ce94d35188bb102c47f8f9e263260',
    'network/qualification_proxy.py': 'fea115190b81f5c7bd4ddaa6be825e3a50d3c7cc44c0ae30b1e70d66f36d48ab',
    'network/qualification_records.py': '76ab8ea137756d7463ac893b00b44dbab5726b6adc9d1df080870fd61fc39a77',
    'network/qualification_runtime.py': 'a9395438a6ee7c3dcdcc74d366ca3f00b92c5c55c248687e25c96ac735b37ada',
    'network/qualify.py': 'c895831c7a404beab760153b5bb6640694d2ca81440c15e83cdcf7814917cdbd',
    'network/relay.py': '67f64f5a83994770f3bbac249d541f193dae3f494e20aa15a21cf2a44c0ce0ef',
    'network/release_acceptance.json': '50c7caa261f64c534af10d02d6420d5b08ffd20d1a8cc25a6321350bf186cefe',
    'network/resolv.conf': '8e40d95c29f83fe652b8a5d0dfda2ecfd94f9b51e0f406a517de1a3aa3fc6ad5',
    'network/revisions.py': 'fa35bcac26f5590c0d0b9477fea2773faa1f1eb285215e735e5cb8aa6b2b9cb1',
    'network/session.py': 'be4675c7155b070115492a26c7f4629bc2b709803092b6784ba9d7cb3e80ade6',
    'network/tls_client_hello.py': 'a4ce71c1710cb1dba7c9ad5889b16549b5d7ebb4a7ae7c2edbf96eab32771e80',
    'setup/common.py': '0d8b6312d715096b05f0a3f0864a19589d444fd8ab6a1eaced9ee386998d7c39',
    'setup/diagnostics.py': 'd6f2a81010f115f5631c829ccc70c39ba329b1baf44b393e34a33a884a3bdc3d',
    'setup/launch.py': '448c85e2278644ab577eaa55d49d029164e17eb4782264db65ce8a4b9237f1cf',
    'setup/setup.py': '2e28f702ec40952ead8f921bc58fb6d9af0a01f2134fc885aa18b1089cb53e49',
    'setup/smoke.py': '041031e22511f4373e20e32807605385c5964b34dc2533a58e8f63ebb2c5eb49',
    'setup/toolchains.py': '91e32207ee4ba116852eafd0690a95ca935f7668d03e5baabf0c224848b59ae8',
    'tests/fake_podman.py': '3b85f5adf2f657f3321e75c4074b4a15f580ce049540ed09d155fb5f3dd3b531',
    'tests/fixtures/agent/launcher.sh': '315e745aa4d572817e0d48151ed411f44dfad9fabf8ccf3334080acfa5531e68',
    'tests/fixtures/agent/policies/default.json': '4a990d9c90c90401c019faf5c7a96c083ae510b7a3507af584fec1f5bef8bb6f',
    'tests/fixtures/agent/profile.json': '25ea638dc7104e955b56b1c6663366c1a2d7280f92a04cb0997aece4b7d66d04',
    'tests/fixtures/shell-agent/launcher.sh': '642599db30beeb9d4b6679202de3a3161780265250c6d7ac3b78db887afaa13d',
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
    'tests/test_alignment.py': '5e8e1818bb101d5aab678b5399b9e0c98603d141d449f81c2a802e48a2ec38ca',
    'tests/test_guard.py': 'bad0772d868b8cac767355557b655b43b765eb83e79008065240d41f2c8f37fd',
    'tests/test_launcher.py': 'ada4a58270988fb471d3e07b04f0c3db456cee74ca0e199a821b9d0ae14332a4',
    'tests/test_mux.py': 'fb3a7cf8675d247c6609a337d56682d484cde6296e14ea939bfde70537cc8446',
    'tests/test_network_feasibility.py': '4cff9c50b996fd38f2b21b75abe73de77531e554522b04641fcb5288178d1e1c',
    'tests/test_network_policy.py': 'f57b3fe72deca821510855b6a474efb2e606471c4d231c210a699627e056f032',
    'tests/test_platform.py': 'e5e30cbb9edb3561e0a6cac67641ab27986ce9e6bd425e5be96976c39fb5fecf',
    'tests/test_qualification.py': '7d402017894a6a56fe76d2c8210239e56e3511003c9775ebe5dbbaeb3210ab2f',
    'tests/test_session.py': 'cf1a3ea3ea86be4a218eda0326437a36673400c27868f7bfe3c8c5b8b228752d',
    'tests/test_setup.py': '8cfa57cb8cb82866c018d042ec648018e8380f71c217d857a39b5045a9bb7a20',
    'tests/test_tls_client_hello.py': '7d8f889af0c4a8f6d40038bdbda915f3afa3adc08c47b5506a02180b595b7ccc',
    'tests/test_tls_proxy.py': '77f9dda900a8ee28ef76d018d862bd0475193f5b90840fd29005a04fe4403e83',
    'tests/test_toolchains.py': '1d9934b4ba5d23b4d071c69815a9036b40f432dee44235831bfa14ad8997e13c',
    'tests/tls_binding_fixture.py': '062fe63ec1fc8ad399199a5f5823515070d5d1fa4ac62607f8722a61347f3331',
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

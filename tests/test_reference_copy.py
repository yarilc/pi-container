"""Per-agent check that the shared components equal the Claude reference copy.

Complements the shared ``tests/test_alignment.py`` (identifier scan and
wrapper consistency) with a byte-identity check: ``network/``, ``setup/`` and
the shared tests must stay byte-identical to ``claude-container`` at the reference
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
REFERENCE_TAG = 'sandbox-ref-10'
REFERENCE_COMMIT = '0f6585f0973250a57398c0b187da4c99d2bfd09f'
SIBLING = ROOT.parent / 'claude-container'
# Shared directories whose complete file set is fixed by the manifest.
CLOSED_DIRECTORIES = ('network', 'setup')
SKIPPED_PARTS = ('__pycache__', 'bin')
MANIFEST = {
    'network/.containerignore': '79c1281ac59153265e2f1bad55781d5704d3f57f18ba2cdb3159f66ad1ee17a4',
    'network/Containerfile': 'b909198e5027bc58ceca4e6076ea4b1a54faa592083e4c0190b2c671cc5b2f36',
    'network/README.md': 'acf83595fb42e7911f99d94fbbca2c2c647a6a4e8bbeee72020a2de26adb37c1',
    'network/agent_budgets.py': 'cbd3cfded46d3bce280047b1e291df55ab74a87bf4af2a264796000307700cc7',
    'network/agent_profile.py': 'b15288578fbe8b5c7788640156b61b620f96fb809310a9d5f245eef361ecc763',
    'network/build-guard.sh': 'e0cc2fce71feb01c447dcb4daf5194f65f098b8a4c9837f756de7e12345cc611',
    'network/control.py': 'b0076acd05c462fe27d706a6439cbc742febcaa9aefe4a9a4f212a24bdaae370',
    'network/guard-build.Containerfile': 'dfd10429fd61bfb12387d616b0cb1f2b3c9d90e9718dd341207a496e83d63094',
    'network/guard.c': '2caf1a59dc6baf654af786efbb3d86a04cf76f859de1ea7ce4ee608f0e5c66bb',
    'network/guard_landlock.h': '8d490d342fa3b037f494cb32578c204302bbb8208c20ee74f5486388110744d0',
    'network/guard_seccomp.h': 'c158d67589d1ba5e3b0e5188974865d881e31bd2eee19ec9a08f1993f4ca4e16',
    'network/mux.py': '1f30d2016f2d9463a1c23d9e3007a2cc14b66de931dd86229df73961d65bc72c',
    'network/platform_check.py': 'c8372fdf47e7036f3d34190074678a17d33dc68e21384a0571db5fc00185f4cd',
    'network/policy.py': 'fc6c97073505e55d2f4081b799723055cfff9618fbc0e169cfbf5724ac234ca6',
    'network/proxy.py': 'dcadee4ae3638de3db9dba74c30c9de431a3625e38626565ebec40e6dc20c54f',
    'network/proxy_hardening.py': '0d2b755948f9615124bf421aa90c4e4d31d628c655f37f4ae01f0badc9fa010f',
    'network/qualification_peer.py': '4c00af4c616fd88733733b0d81915f68c4de0c5466ecb183bb86d595dd13780f',
    'network/qualification_probe.py': 'b83ebb9087a7ca3ae031a85aab282066f1a6c815933e27d1d350a277eb83bbda',
    'network/qualification_proxy.py': 'fea115190b81f5c7bd4ddaa6be825e3a50d3c7cc44c0ae30b1e70d66f36d48ab',
    'network/qualification_records.py': '69a67dbab109699261ca61f4ce0336e95eed1becf49cd749367810db673d0743',
    'network/qualification_runtime.py': '9fcd890a16c7f39335d33eae8b41b8fb68be515cb96e6185150070e2f7736da8',
    'network/qualify.py': '662dcf89a3de822836c349106bf55dd8a08178037dc27ab4e1629a08599a60dd',
    'network/relay.py': '67f64f5a83994770f3bbac249d541f193dae3f494e20aa15a21cf2a44c0ce0ef',
    'network/release_acceptance.json': '50c7caa261f64c534af10d02d6420d5b08ffd20d1a8cc25a6321350bf186cefe',
    'network/resolv.conf': '8e40d95c29f83fe652b8a5d0dfda2ecfd94f9b51e0f406a517de1a3aa3fc6ad5',
    'network/revisions.py': 'fa35bcac26f5590c0d0b9477fea2773faa1f1eb285215e735e5cb8aa6b2b9cb1',
    'network/session.py': '2e13f1fe9c4d9f5299abe00f0b8a0fc6f40c78eefceff2a0b79b0c4e170264e6',
    'network/tls_client_hello.py': 'a4ce71c1710cb1dba7c9ad5889b16549b5d7ebb4a7ae7c2edbf96eab32771e80',
    'setup/common.py': 'c17c8610755e741caf1b37a510d2d70c00770ba75dcce6ebaee4b51a23eb781a',
    'setup/diagnostics.py': 'd6f2a81010f115f5631c829ccc70c39ba329b1baf44b393e34a33a884a3bdc3d',
    'setup/launch.py': '72182ed789a6349fe3d660af88315c4665aa892bba4799b6a4e4969965baefc6',
    'setup/setup.py': '7dfe3e71a13b13dffc3c2dad36e262913f2226c4564c52691360319054589fc1',
    'setup/smoke.py': '696abeb7b8a991c8d916348300b8435e315c2973877805f03383c6665ce63da3',
    'tests/guard_bind_fixture.py': 'd6e4eb85cedb249ec9c6b4f2a026d14acbd5e1309a63ac036647be06781287cc',
    'tests/guard_mux_fixture.py': 'c641e419f5f2939c0c0af34d8a19dfcbcdf42302e0686e2d446bfad1bfc85f3d',
    'tests/guard_runtime_fixture.py': '73461452420305dfbacdb24ccb2336c490667f961e816f5b285ef15d35455597',
    'tests/guard_syscall_mock.c': '56ba41dcf49c0f07b40dff43b5527b697f5682beb3f6ed14827230f8d7c86670',
    'tests/idle_mux_fixture.py': 'a85aff09892732f71f1c8436465a9d531dd027eab7cdc158c9073005d6508d58',
    'tests/mux_failure_fixture.py': 'a53da415f54bf98cceca6e546d705969c69a4d5619f5b3584cb35214353669b6',
    'tests/mux_fault_boundary.py': 'faf7aaa356dabd64306df8f5c0cb4054f9d267263db653bc0359c3d2cf2672fd',
    'tests/network_fixture.py': '90311f5240f14c373dc83ce0d2c4d023c4aa247adcf361ccebfaa2009c3e3675',
    'tests/proxy_budget_fixture.py': 'cde9c888d3842045752a93ec1963110749a3d9cd4d48ef76d199e0b4847fea67',
    'tests/sandbox_profile.py': 'adf6dd51417ec62cf6c2ccc84b8789e41a4f8b8ba46d1be1635d3ab2445fa60e',
    'tests/test_agent_profile.py': '2c05729712341a6481390aadf775f573651d99ed6ec9243cc669863923727b1e',
    'tests/test_alignment.py': '4f1e68c087fe95abd34818385d7a12e1f36f86ca0d50e5dbfe57b22724de588c',
    'tests/test_guard.py': '78c623761899aee82e912888c2c769d86bf55bd445d47dfc2f09d4f5f1484f2c',
    'tests/test_mux.py': 'fb3a7cf8675d247c6609a337d56682d484cde6296e14ea939bfde70537cc8446',
    'tests/test_network_feasibility.py': '4cff9c50b996fd38f2b21b75abe73de77531e554522b04641fcb5288178d1e1c',
    'tests/test_network_policy.py': '27d42ed14dfa0fef9409dd6e9078d9f1215b9a77b9acc76306a852db82e096fc',
    'tests/test_platform.py': 'e5e30cbb9edb3561e0a6cac67641ab27986ce9e6bd425e5be96976c39fb5fecf',
    'tests/test_qualification.py': 'de1ef6d16975d1ab8939918ea2885f8d209f4ecc96fba8c28aaff44daf42c55d',
    'tests/test_session.py': 'f3b01c9965ee9785d6c910537485faa8cd3a11402b79b0cbb1401b1372e4df28',
    'tests/test_setup.py': '8dd963ab5bfa33c54d1a62ea23263b4da723188f84650dd712ab81ddcb262eb3',
    'tests/test_tls_client_hello.py': '7d8f889af0c4a8f6d40038bdbda915f3afa3adc08c47b5506a02180b595b7ccc',
    'tests/test_tls_proxy.py': '77f9dda900a8ee28ef76d018d862bd0475193f5b90840fd29005a04fe4403e83',
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
            self.skipTest('no sibling claude-container checkout')
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

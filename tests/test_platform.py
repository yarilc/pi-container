"""Eligibility covers capabilities and stable releases, never a distribution matrix."""
import copy
import importlib.util
from pathlib import Path
import unittest

spec = importlib.util.spec_from_file_location('sandbox_platform', Path(__file__).resolve().parents[1] / 'network/platform_check.py')
platform = importlib.util.module_from_spec(spec)
spec.loader.exec_module(platform)


class PlatformTests(unittest.TestCase):
    def test_usable_abi_is_required_independently_of_kernel_release(self):
        for abi in (3, 4, 9, 99):
            self.assertEqual(platform.validate_abi(abi), abi)
        for abi in (None, True, '3', -1, 0, 1, 2):
            with self.assertRaises(platform.PlatformError):
                platform.validate_abi(abi)

    def test_stable_server_versions_and_package_suffixes(self):
        for value in ('4.9', '4.9.0', '4.9.3', '4.9.3-1ubuntu0.1', '4.9.3+ds1', '5.0.0', '6.2.1+1.fc99', '99.0.0'):
            with self.subTest(version=value):
                self.assertGreaterEqual(platform.server_version(value), (4, 9, 0))
        for value in ('', '4.8.99', '4.9.0-rc1', '5.0.0-beta.1', '5.0.0-dev',
                      '5.0.0-vendor', 'v5.0.0', '5', '5.0.0\n', None, True):
            with self.subTest(version=value), self.assertRaises(platform.PlatformError):
                platform.server_version(value)

    def host(self):
        return dict(kernel='6.6.87.2-microsoft-standard-WSL2', arch='amd64',
                    security=dict(seccompEnabled=True, selinuxEnabled=False, apparmorEnabled=False))

    def validate(self, host, **changes):
        values = dict(version='4.9.3', backend='netavark', endpoint='unix:///run/podman/podman.sock',
                      engine='true linux true') | changes
        return platform.validate(host, **values)

    def test_native_and_wsl_with_active_security_modules_are_eligible(self):
        for kernel in ('6.6.87.2-microsoft-standard-WSL2', '6.8.0-ubuntu', '6.12.1-fedora', '7.0.0'):
            for selinux, apparmor in ((False, False), (True, False), (False, True), (True, True)):
                host = self.host()
                host['kernel'] = kernel
                host['security'].update(selinuxEnabled=selinux, apparmorEnabled=apparmor)
                result = self.validate(host, version='5.4.0')
                self.assertEqual(result['kernel'], kernel)
                self.assertEqual((result['selinux'], result['apparmor']), (selinux, apparmor))

    def test_unsupported_and_unverifiable_evidence_is_rejected(self):
        for change in (dict(engine='false linux true'), dict(engine='true linux false'),
                       dict(engine='true windows true'), dict(backend='cni'), dict(endpoint='ssh://host'),
                       dict(endpoint='unix:///'), dict(endpoint='unix://relative'), dict(version='4.8.0')):
            with self.subTest(change=change), self.assertRaises(platform.PlatformError):
                self.validate(self.host(), **change)
        for mutate in (lambda h: h.update(arch='arm64'), lambda h: h.pop('kernel'),
                       lambda h: h.update(kernel='\n'), lambda h: h.update(security=None),
                       lambda h: h['security'].update(seccompEnabled=False),
                       lambda h: h['security'].update(rootless=False),
                       lambda h: h['security'].pop('apparmorEnabled'),
                       lambda h: h['security'].update(selinuxEnabled='false')):
            host = copy.deepcopy(self.host()); mutate(host)
            with self.subTest(host=host), self.assertRaises(platform.PlatformError):
                self.validate(host)

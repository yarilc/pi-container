"""Copyability guard rails for the shared sandbox components.

``network/``, ``setup/`` and the shared tests are copied unchanged between
wrappers. They must not contain agent identifiers; every agent-specific value
comes from ``agent/profile.json``. The wrapper and agent image stay per agent
and must agree with the names the profile produces.
"""
from pathlib import Path
import re
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from sandbox_profile import PROFILE, ROOT
import agent_profile

SHARED_DIRECTORIES = ('network', 'setup')
SHARED_TESTS = (
    'tests/sandbox_profile.py', 'tests/test_alignment.py', 'tests/test_agent_profile.py',
    'tests/test_network_policy.py', 'tests/test_mux.py', 'tests/test_tls_client_hello.py',
    'tests/test_tls_proxy.py', 'tests/test_platform.py', 'tests/test_qualification.py',
    'tests/test_guard.py', 'tests/test_setup.py', 'tests/test_network_feasibility.py',
    'tests/guard_bind_fixture.py', 'tests/guard_mux_fixture.py', 'tests/guard_runtime_fixture.py',
    'tests/guard_syscall_mock.c', 'tests/idle_mux_fixture.py', 'tests/mux_failure_fixture.py',
    'tests/mux_fault_boundary.py', 'tests/network_fixture.py', 'tests/proxy_budget_fixture.py',
    'tests/tls_binding_fixture.py', 'tests/test_session.py', 'tests/test_toolchains.py',
)
SKIPPED_PARTS = ('__pycache__', 'bin')
# Exact (path, line) exceptions. Keep empty unless a reviewed reason exists.
ALLOWED = frozenset()
NEUTRAL = ('/opt/sandbox-egress', '/run/sandbox-egress', 'sandbox-egress-guard')
HELPER_OPERATIONS = ('prepare', 'start', 'agent-args', 'stop')
# In-line restricted lifecycle that belongs to network/session.py, never to a wrapper.
INLINE_LIFECYCLE = (
    r'network/control\.py', r'network/platform_check\.py', r'proxy_hardening\.py',
    r'sandbox-egress-guard', r'/opt/sandbox-egress', r'/run/sandbox-egress',
    r'--pids-limit=128', r'transport/ready', r'EGRESS_PROFILE=',
)


def inline_lifecycle(text):
    return [pattern for pattern in INLINE_LIFECYCLE if re.search(pattern, text)]


def shared_files(root):
    for directory in SHARED_DIRECTORIES:
        for path in sorted((root / directory).rglob('*')):
            if path.is_file() and not any(part in SKIPPED_PARTS for part in path.relative_to(root).parts):
                yield path
    for name in SHARED_TESTS:
        yield root / name


def violations(root, identifiers):
    pattern = re.compile('|'.join(map(re.escape, identifiers)), re.IGNORECASE)
    found = []
    for path in shared_files(root):
        relative = str(path.relative_to(root))
        for number, line in enumerate(path.read_text(errors='replace').splitlines(), 1):
            if pattern.search(line) and (relative, line.strip()) not in ALLOWED:
                found.append(f'{relative}:{number}: {line.strip()[:120]}')
    return found


class SharedComponentAlignment(unittest.TestCase):
    def test_shared_components_contain_no_agent_identifiers(self):
        self.assertEqual(violations(ROOT, PROFILE.identifiers), [])

    def test_scan_detects_an_injected_identifier(self):
        with tempfile.TemporaryDirectory() as directory:
            copy = Path(directory)
            for name in (*SHARED_DIRECTORIES, 'tests'):
                shutil.copytree(ROOT / name, copy / name, ignore=shutil.ignore_patterns('__pycache__'))
            target = copy / 'network/control.py'
            target.write_text(target.read_text() + '\n# ' + PROFILE.identifiers[0].title() + ' literal\n')
            found = violations(copy, PROFILE.identifiers)
            self.assertEqual(len(found), 1)
            self.assertTrue(found[0].startswith('network/control.py:'))

    def test_shared_test_inventory_exists(self):
        for name in SHARED_TESTS:
            self.assertTrue((ROOT / name).is_file(), name)


class WrapperConsistency(unittest.TestCase):
    def setUp(self):
        self.wrapper = (ROOT / PROFILE.wrapper).read_text()
        self.image = (ROOT / 'Containerfile').read_text()

    def test_wrapper_uses_every_profile_variable(self):
        for suffix in agent_profile.SUFFIXES:
            with self.subTest(suffix=suffix):
                self.assertIn(PROFILE.env(suffix), self.wrapper)
        for name in (PROFILE.config_dir_env, PROFILE.approval_bypass_env, *PROFILE.credential_envs):
            self.assertIn(name, self.wrapper)
        used = set(re.findall(r'\b' + re.escape(PROFILE.env_prefix) + r'_([A-Z0-9_]+)', self.wrapper))
        # Wrapper-only controls are allowed; derived names must be complete above.
        self.assertTrue(set(agent_profile.SUFFIXES) <= used)

    def test_wrapper_uses_profile_labels_images_and_home(self):
        # Egress and qualification labels are applied by the shared helper.
        self.assertIn(PROFILE.label('session'), self.wrapper)
        self.assertIn(PROFILE.images['agent'], self.wrapper)
        self.assertIn(PROFILE.home, self.wrapper)
        self.assertIn(PROFILE.command, self.wrapper)

    def test_wrapper_delegates_the_restricted_session_to_the_shared_helper(self):
        self.assertIn('network/session.py', self.wrapper)
        for operation in HELPER_OPERATIONS:
            self.assertRegex(self.wrapper, r'"\$\{session_helper\[@\]\}" ' + operation + r'\b')
        self.assertEqual(inline_lifecycle(self.wrapper), [])

    def test_inline_lifecycle_detection_detects_a_reintroduced_call(self):
        changed = self.wrapper + '\npython3 -I "$script_dir/network/control.py" snapshot\n'
        self.assertEqual(inline_lifecycle(changed), [r'network/control\.py'])

    def test_image_and_helper_use_neutral_internal_paths(self):
        helper = (ROOT / 'network/session.py').read_text()
        for path in NEUTRAL:
            self.assertIn(path, helper)
        self.assertIn('/opt/sandbox-egress/', self.image)
        legacy = re.compile(r'/(?:opt|run)/(?!sandbox-egress)[a-z0-9-]+-egress\b|\b(?!sandbox-)[a-z0-9]+-egress-guard\b')
        self.assertEqual(legacy.findall(self.wrapper), [])
        self.assertEqual(legacy.findall(self.image), [])

    def test_consistency_check_detects_a_mismatch(self):
        changed = self.wrapper.replace(PROFILE.env('NETWORK_POLICY'), PROFILE.env_prefix + '_POLICY_RENAMED')
        self.assertNotIn(PROFILE.env('NETWORK_POLICY'), changed)


if __name__ == '__main__':
    unittest.main()

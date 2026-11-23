"""Copyability guard rails for the shared sandbox components.

``network/``, ``setup/`` and the shared tests are copied unchanged between
wrappers. They must not contain agent identifiers; every agent-specific value
comes from ``agent/profile.json``. The thin entry script and the shared
launcher core run every wrapper; ``agent/launcher.sh`` and the agent image stay
per agent and must agree with the profile.
"""
from pathlib import Path
import re
import json
import shutil
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
# Alignment checks the checkout itself: its shared files, its wrapper and its image.
from sandbox_profile import PROFILE as FIXTURE_PROFILE, REAL_PROFILE as PROFILE, REAL_ROOT as ROOT
import agent_profile

SHARED_DIRECTORIES = ('network', 'setup', 'launcher')
SHARED_TESTS = (
    'tests/sandbox_profile.py', 'tests/test_alignment.py', 'tests/test_agent_profile.py',
    'tests/test_network_policy.py', 'tests/test_mux.py', 'tests/test_tls_client_hello.py',
    'tests/test_tls_proxy.py', 'tests/test_platform.py', 'tests/test_qualification.py',
    'tests/test_guard.py', 'tests/test_setup.py', 'tests/test_network_feasibility.py',
    'tests/guard_bind_fixture.py', 'tests/guard_mux_fixture.py', 'tests/guard_runtime_fixture.py',
    'tests/guard_syscall_mock.c', 'tests/idle_mux_fixture.py', 'tests/mux_failure_fixture.py',
    'tests/mux_fault_boundary.py', 'tests/network_fixture.py', 'tests/proxy_budget_fixture.py',
    'tests/tls_binding_fixture.py', 'tests/test_session.py', 'tests/test_toolchains.py',
    'tests/fixtures/agent/profile.json', 'tests/fixtures/agent/policies/default.json',
    'tests/fixtures/shell-agent/profile.json', 'tests/fixtures/shell-agent/policies/default.json',
    'tests/fixtures/agent/launcher.sh', 'tests/fixtures/shell-agent/launcher.sh', 'tests/fake_podman.py',
    'tests/test_launcher.py', 'tests/test_windows_bootstrap.py', 'tests/test_windows_enter.py',
    'tests/windows/shim_tests.ps1',
)
FIXTURE_FILES = 'tests/fixtures/'
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


def sibling_identifiers(root):
    """Identifiers of the wrapper checkouts next to this one, which shared files must not name either."""
    identifiers = set()
    for path in sorted(root.parent.glob('*/' + agent_profile.PROFILE)):
        if path.parent.parent.resolve() != root.resolve():
            # Only the identifiers: a sibling on another tag may not validate against this checkout's rules.
            identifiers.update(json.loads(path.read_text())['identifiers'])
    return sorted(identifiers)


def violations(root, identifiers):
    pattern = re.compile('|'.join(map(re.escape, identifiers)), re.IGNORECASE)
    found = []
    for path in shared_files(root):
        relative = str(path.relative_to(root))
        for number, line in enumerate(path.read_text(errors='replace').splitlines(), 1):
            if pattern.search(line) and (relative, line.strip()) not in ALLOWED:
                found.append(f'{relative}:{number}: {line.strip()[:120]}')
    return found


# Shared tests that may read the checkout's own profile: the profile view
# itself, the checkout checks, and the qualification gate run through the
# checkout's wrapper. Every other shared test uses the fixture profile.
REAL_READERS = ('tests/sandbox_profile.py', 'tests/test_alignment.py', 'tests/test_agent_profile.py',
                'tests/test_qualification.py')
REAL_NAMES = re.compile(r'\bREAL_(?:ROOT|PROFILE|WRAPPER|POLICY_FILE)\b|\breal_env\b')
NEUTRAL_NAME = re.compile(r'\bSANDBOX_[A-Z0-9_]+')


def real_profile_readers(root):
    return [name for name in SHARED_TESTS if name.endswith('.py') and name not in REAL_READERS
            and REAL_NAMES.search((root / name).read_text())]


def neutral_collisions(root, prefix):
    """Neutral SANDBOX_ names in shared files that fall inside the wrapper's own prefix."""
    names = {name for path in shared_files(root) for name in NEUTRAL_NAME.findall(path.read_text(errors='replace'))}
    return sorted(name for name in names if name.startswith(prefix + '_'))


def repository_files(root):
    """Tracked and new unignored files of a Git checkout, or every file of a plain copy."""
    listing = subprocess.run(['git', '-C', str(root), 'ls-files', '-z', '--cached', '--others', '--exclude-standard'],
                             capture_output=True, check=False)
    if listing.returncode == 0:
        return sorted(root / name for name in listing.stdout.decode().split('\0') if name and (root / name).is_file())
    return sorted(path for path in root.rglob('*') if path.is_file()
                  and not {'.git', '__pycache__'} & set(path.relative_to(root).parts))


def carriage_returns(root):
    """Text files with a carriage return; a file with a NUL byte counts as binary."""
    found = []
    for path in repository_files(root):
        data = path.read_bytes()
        if b'\r' in data and b'\0' not in data:
            found.append(str(path.relative_to(root)))
    return found


class LineEndings(unittest.TestCase):
    """Scripts also run from Windows checkouts, where Git may convert LF to CRLF."""

    def test_repository_text_files_have_no_carriage_return(self):
        self.assertEqual([], carriage_returns(ROOT))

    def test_carriage_return_is_detected(self):
        with tempfile.TemporaryDirectory() as directory:
            copy = Path(directory)
            (copy / 'launcher').mkdir()
            (copy / 'launcher/core.sh').write_bytes(b'set -e\r\ntrue\n')
            (copy / 'image.bin').write_bytes(b'\0\r\n')
            (copy / 'README.md').write_bytes(b'text\n')
            self.assertEqual(['launcher/core.sh'], carriage_returns(copy))


class SharedComponentAlignment(unittest.TestCase):
    def test_neutral_names_stay_outside_the_wrapper_prefix(self):
        self.assertEqual(neutral_collisions(ROOT, PROFILE.env_prefix), [])

    def test_neutral_collision_is_detected(self):
        with tempfile.TemporaryDirectory() as directory:
            copy = Path(directory)
            for name in (*SHARED_DIRECTORIES, 'tests'):
                shutil.copytree(ROOT / name, copy / name, ignore=shutil.ignore_patterns('__pycache__'))
            target = copy / 'network/control.py'
            prefix = 'SANDBOX' + '_COLLIDING'  # kept apart so this file does not collide itself
            self.assertEqual(neutral_collisions(copy, prefix), [])
            target.write_text(target.read_text() + '\n# ' + prefix + '_CASE\n')
            self.assertEqual(neutral_collisions(copy, prefix), [prefix + '_CASE'])

    def test_shared_tests_do_not_read_the_checkout_profile(self):
        self.assertEqual(real_profile_readers(ROOT), [])

    def test_checkout_profile_reader_is_detected(self):
        with tempfile.TemporaryDirectory() as directory:
            copy = Path(directory)
            shutil.copytree(ROOT / 'tests', copy / 'tests', ignore=shutil.ignore_patterns('__pycache__'))
            target = copy / 'tests/test_session.py'
            target.write_text(target.read_text() + '\nfrom sandbox_profile import REAL_PROFILE\n')
            self.assertEqual(real_profile_readers(copy), ['tests/test_session.py'])

    def test_shared_components_contain_no_agent_identifiers(self):
        self.assertEqual(violations(ROOT, PROFILE.identifiers), [])

    def test_shared_components_contain_no_sibling_identifiers(self):
        identifiers = sibling_identifiers(ROOT)
        if not identifiers:
            self.skipTest('no sibling wrapper checkout next to this one')
        self.assertEqual(violations(ROOT, identifiers), [])

    def test_scan_detects_an_injected_identifier(self):
        for name in ('network/control.py', 'launcher/windows/core.ps1', 'launcher/windows/bootstrap.sh',
                     'launcher/windows/enter.sh',
                     'launcher/windows/install.ps1', 'launcher/windows/user-path.ps1', 'tests/windows/shim_tests.ps1'):
            with self.subTest(file=name), tempfile.TemporaryDirectory() as directory:
                copy = Path(directory)
                for shared in (*SHARED_DIRECTORIES, 'tests'):
                    shutil.copytree(ROOT / shared, copy / shared, ignore=shutil.ignore_patterns('__pycache__'))
                target = copy / name
                target.write_text(target.read_text() + '\n# ' + PROFILE.identifiers[0].title() + ' literal\n')
                found = violations(copy, PROFILE.identifiers)
                self.assertEqual(len(found), 1)
                self.assertTrue(found[0].startswith(name + ':'))

    def test_fixture_identifiers_stay_in_the_fixtures(self):
        found = [line for line in violations(ROOT, FIXTURE_PROFILE.identifiers)
                 if not line.startswith(FIXTURE_FILES)]
        self.assertEqual(found, [])

    def test_shared_test_inventory_exists(self):
        for name in SHARED_TESTS:
            self.assertTrue((ROOT / name).is_file(), name)


# Derived variables that shared code reads itself; the launcher only documents them.
SHARED_READ = ('TOOLCHAINS_DIR',)
# Derived variables set by setup for the launcher, never by the operator.
INTERNAL = ('QUALIFICATION_INPUT',)
# Derived variables that only provider mode reads; a profile without
# authentication methods has no provider mode, so its help need not name them.
PROVIDER_ONLY = ('NETWORK_PROFILE', 'NETWORK_POLICY', 'NETWORK_RUNTIME_DIR', 'EGRESS_IMAGE')
ENTRY_SOURCE = 'source "$wrapper_dir/launcher/core.sh" "$wrapper_dir/agent/launcher.sh" "$@"'
# The thin PowerShell entry <name>.ps1: the same text in every wrapper.
POWERSHELL_ENTRY = '''# Thin Windows entry: identical in every wrapper. The shared shim
# (launcher/windows/core.ps1) does everything with this wrapper's profile;
# see docs/launcher-contract.md (Windows entry).
Set-StrictMode -Version 3
$ErrorActionPreference = 'Stop'
& ([IO.Path]::Combine($PSScriptRoot, 'launcher', 'windows', 'core.ps1')) -EntryDirectory $PSScriptRoot -Arguments $args -PipelineInput:$MyInvocation.ExpectingInput
exit $LASTEXITCODE
'''
# PowerShell files that Windows PowerShell 5.1 reads: ASCII only (no BOM needed).
POWERSHELL_SHARED = ('launcher/windows/core.ps1', 'launcher/windows/install.ps1', 'launcher/windows/user-path.ps1',
                     'tests/windows/shim_tests.ps1')
SCALARS = ('AGENT_NAME', 'AGENT_DISPLAY_NAME', 'AGENT_WRAPPER', 'AGENT_ENV_PREFIX', 'AGENT_LABEL_NAMESPACE',
           'AGENT_IMAGE', 'AGENT_PROXY_IMAGE', 'AGENT_HOME', 'AGENT_COMMAND', 'AGENT_EXEC', 'AGENT_CONFIG_DIR_ENV',
           'AGENT_CONFIG_HOME', 'AGENT_PRIVATE_SHARED_DIRS', 'AGENT_APPROVAL_BYPASS_ENV', 'AGENT_EXEC_TMP')
ARRAYS = ('AGENT_SHARED_DIRS', 'AGENT_INSTALL_FILES', 'AGENT_CREDENTIALS', 'AGENT_POLICY_HOSTS', 'AGENT_SESSION_ENV', 'AGENT_RESTRICTED_ENV',
          'AGENT_PROVIDER_ENV', 'AGENT_UNSET_ENV', 'AGENT_RESERVED_ENV')
DUMP = (r'''source "$1"; for name in ''' + ' '.join(SCALARS) + r'''; do printf '%s=%s\n' "$name" "${!name}"; done
for name in ''' + ' '.join(ARRAYS) + r'''; do declare -n items=$name; printf '%s=' "$name"
for item in "${items[@]}"; do printf '%s\037' "$item"; done; printf '\n'; unset -n items; done''')


def agent_part(path):
    """Values an agent launcher part declares, read by Bash itself."""
    result = subprocess.run(['bash', '-c', DUMP, 'dump', str(path)], capture_output=True, text=True, check=True)
    values = dict(line.split('=', 1) for line in result.stdout.splitlines())
    return {key: (value.split('\037')[:-1] if key in ARRAYS else value) for key, value in values.items()}


def expected_agent_part(profile, policy):
    credentials = sorted(name + '=' + profile.auth.get(item['authentication'], {}).get('credential_env', '')
                         for name, item in json.loads(policy.read_text())['profiles'].items())
    return {'AGENT_NAME': profile.name, 'AGENT_DISPLAY_NAME': profile.display_name, 'AGENT_WRAPPER': profile.wrapper,
            'AGENT_ENV_PREFIX': profile.env_prefix, 'AGENT_LABEL_NAMESPACE': profile.label_namespace,
            'AGENT_IMAGE': profile.images['agent'], 'AGENT_PROXY_IMAGE': profile.images['proxy'],
            'AGENT_HOME': profile.home, 'AGENT_COMMAND': profile.command, 'AGENT_EXEC': profile.exec,
            'AGENT_CONFIG_DIR_ENV': profile.config_dir_env, 'AGENT_CONFIG_HOME': profile.config_home,
            'AGENT_PRIVATE_SHARED_DIRS': '1' if profile.private_shared_dirs else '0',
            'AGENT_APPROVAL_BYPASS_ENV': profile.approval_bypass_env or '',
            'AGENT_EXEC_TMP': '1' if profile.exec_tmp else '0',
            'AGENT_SHARED_DIRS': list(profile.shared_dirs), 'AGENT_INSTALL_FILES': list(profile.install_files),
            'AGENT_CREDENTIALS': credentials,
            'AGENT_POLICY_HOSTS': sorted(item['policy_profile'] + '=' + ' '.join(item['hosts'])
                                         for item in profile.auth.values())}


def agent_part_mismatches(root):
    profile = agent_profile.load(root / agent_profile.PROFILE)
    declared = agent_part(root / 'agent/launcher.sh')
    for name in ('AGENT_CREDENTIALS', 'AGENT_POLICY_HOSTS'):
        declared[name] = sorted(declared.get(name, []))
    expected = expected_agent_part(profile, root / agent_profile.POLICY)
    missing = [name for name in SCALARS + ARRAYS if name not in declared]
    return missing + [name for name, value in expected.items() if declared.get(name) != value]


def core_code(core):
    """The core without its help text, which documents names but proves no use."""
    return re.sub(r"(?ms)^usage\(\) \{.*?^EOF\n", '', core, count=1)


def unread_settings(core):
    unused = SHARED_READ + (() if PROFILE.auth else PROVIDER_ONLY)
    code = core_code(core)
    return [suffix for suffix in agent_profile.SUFFIXES if suffix not in unused
            and not re.search(r'\bcfg_' + suffix + r'(?![A-Z_])', code)]


class LauncherConsistency(unittest.TestCase):
    def setUp(self):
        self.entry = (ROOT / PROFILE.wrapper).read_text()
        self.core = (ROOT / 'launcher/core.sh').read_text()
        self.image = (ROOT / 'Containerfile').read_text()

    def test_entry_script_is_thin_and_agent_neutral(self):
        self.assertIn(ENTRY_SOURCE, self.entry)
        for value in (PROFILE.name, PROFILE.env_prefix, PROFILE.home):
            self.assertNotIn(value, self.entry)
        code = [line for line in self.entry.splitlines() if line.strip() and not line.lstrip().startswith('#')]
        self.assertLessEqual(len(code), 14)

    def test_powershell_entry_is_the_fixed_thin_entry(self):
        self.assertEqual(sorted(path.name for path in ROOT.glob('*.ps1')), [PROFILE.name + '.ps1'])
        self.assertEqual((ROOT / (PROFILE.name + '.ps1')).read_text(), POWERSHELL_ENTRY)
        for value in (PROFILE.name, PROFILE.env_prefix, PROFILE.home):
            self.assertNotIn(value, POWERSHELL_ENTRY)
        code = [line for line in POWERSHELL_ENTRY.splitlines() if line.strip() and not line.startswith('#')]
        self.assertLessEqual(len(code), 4)

    def test_powershell_files_are_ascii(self):
        for name in (PROFILE.name + '.ps1', *POWERSHELL_SHARED):
            with self.subTest(file=name):
                self.assertTrue((ROOT / name).read_bytes().isascii())

    def test_agent_parts_match_their_profiles(self):
        from sandbox_profile import AGENT_FIXTURE, SHELL_FIXTURE
        self.assertEqual(agent_part_mismatches(ROOT), [])
        for fixture in (AGENT_FIXTURE, SHELL_FIXTURE):
            with self.subTest(fixture=fixture.name), tempfile.TemporaryDirectory() as directory:
                shutil.copytree(fixture, Path(directory) / 'agent')
                self.assertEqual(agent_part_mismatches(Path(directory)), [])

    def test_agent_part_mismatch_is_detected(self):
        with tempfile.TemporaryDirectory() as directory:
            copy = Path(directory)
            shutil.copytree(ROOT / 'agent', copy / 'agent')
            part = copy / 'agent/launcher.sh'
            part.write_text(part.read_text().replace('AGENT_HOME=' + PROFILE.home, 'AGENT_HOME=/elsewhere'))
            self.assertEqual(agent_part_mismatches(copy), ['AGENT_HOME'])

    def test_core_reads_every_profile_setting(self):
        self.assertEqual(unread_settings(self.core), [])
        renamed = self.core.replace('cfg_MEMORY_LIMIT', 'cfg_MEMORY_RENAMED')
        self.assertEqual(unread_settings(renamed), ['MEMORY_LIMIT'])

    def test_help_documents_every_operator_setting(self):
        result = subprocess.run(['bash', str(ROOT / PROFILE.wrapper), '--container-help'],
                                capture_output=True, text=True, env={'PATH': '/usr/bin:/bin', 'HOME': '/nonexistent'})
        self.assertEqual(result.returncode, 0, result.stderr)
        hidden = INTERNAL + (() if PROFILE.auth else PROVIDER_ONLY)
        documented = [PROFILE.env(suffix) for suffix in agent_profile.SUFFIXES if suffix not in hidden]
        self.assertEqual([name for name in documented if name not in result.stdout], [])

    def test_core_delegates_the_restricted_session_to_the_shared_helper(self):
        self.assertIn('network/session.py', self.core)
        # start and stop manage the provider proxy, which needs authentication methods.
        operations = HELPER_OPERATIONS if PROFILE.auth else ('prepare', 'agent-args')
        for operation in operations:
            self.assertRegex(self.core, r'"\$\{session_helper\[@\]\}" ' + operation + r'\b')
        self.assertEqual(inline_lifecycle(self.core), [])

    def test_inline_lifecycle_detection_detects_a_reintroduced_call(self):
        changed = self.core + '\npython3 -I "$script_dir/network/control.py" snapshot\n'
        self.assertEqual(inline_lifecycle(changed), [r'network/control\.py'])

    def test_image_and_helper_use_neutral_internal_paths(self):
        helper = (ROOT / 'network/session.py').read_text()
        for path in NEUTRAL:
            self.assertIn(path, helper)
        self.assertIn('/opt/sandbox-egress/', self.image)
        legacy = re.compile(r'/(?:opt|run)/(?!sandbox-egress)[a-z0-9-]+-egress\b|\b(?!sandbox-)[a-z0-9]+-egress-guard\b')
        self.assertEqual(legacy.findall(self.core), [])
        self.assertEqual(legacy.findall(self.image), [])

if __name__ == '__main__':
    unittest.main()

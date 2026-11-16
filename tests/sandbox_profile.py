"""Shared test view of the agent profiles; shared tests use no agent literals.

Module-level tests of the shared components run against a fixed, agent-neutral
fixture profile, so they behave the same in every wrapper. Shared modules load
their profile at import time from ``<root>/agent/profile.json``, so this module
builds a private fixture root once per test process (copies of ``network/``,
``setup/``, ``tests/`` and the per-wrapper build inputs, plus the fixture
``agent/``) and puts its ``network/`` first on ``sys.path``. Production code
never reads the fixture; no variable or argument selects it.

Tests that launch the checkout's own wrapper use ``REAL_ROOT``,
``REAL_PROFILE`` and ``REAL_WRAPPER`` instead, because each wrapper hard-codes
its own variable names.
"""
import atexit
import os
from pathlib import Path
import shutil
import sys
import tempfile

REAL_ROOT = Path(__file__).resolve().parents[1]
FIXTURES = REAL_ROOT / 'tests/fixtures'
# The provider fixture (two methods, approval bypass, agent variables) and the
# shell fixture (no methods, no approval bypass, empty policy profiles).
AGENT_FIXTURE = FIXTURES / 'agent'
SHELL_FIXTURE = FIXTURES / 'shell-agent'
SKIPPED = shutil.ignore_patterns('__pycache__', 'bin', 'fixtures')


def test_setting(name, default=None):
    """Neutral test-harness controls, for example SANDBOX_TEST_TMPDIR."""
    return os.environ.get('SANDBOX_' + name, default)


def fixture_root(fixture=AGENT_FIXTURE, parent=None):
    """Create a private root with the shared code and the given fixture ``agent/``.

    Runtime tests need host-visible paths, so the native state root is preferred.
    The caller owns the returned directory unless it is the module's own root.
    """
    parent = parent or test_setting('TEST_STATE_ROOT') or test_setting('TEST_TMPDIR')
    root = Path(tempfile.mkdtemp(prefix='sandbox-fixture-', dir=parent)).resolve()
    for name in ('network', 'setup', 'tests'):
        shutil.copytree(REAL_ROOT / name, root / name, ignore=SKIPPED)
    shutil.copytree(fixture, root / 'agent')
    for name in ('Containerfile', '.containerignore'):
        if (REAL_ROOT / name).exists():
            shutil.copyfile(REAL_ROOT / name, root / name)
    sys.path.insert(0, str(root / 'network'))
    import agent_profile
    sys.path.pop(0)
    profile = agent_profile.load(root / agent_profile.PROFILE)
    # A fixture wrapper cannot launch anything: wrappers are per-agent files.
    (root / profile.wrapper).write_text('#!/bin/bash\nprintf "fixture wrapper\\n" >&2\nexit 1\n')
    (root / profile.wrapper).chmod(0o755)
    return root


FIXTURE_ROOT = fixture_root()
atexit.register(shutil.rmtree, FIXTURE_ROOT, True)
ROOT = FIXTURE_ROOT
NETWORK = ROOT / 'network'
sys.path.insert(0, str(NETWORK))
import agent_profile  # noqa: E402

PROFILE = agent_profile.load()
REAL_PROFILE = agent_profile.load(REAL_ROOT / agent_profile.PROFILE)
REAL_WRAPPER = REAL_ROOT / REAL_PROFILE.wrapper
REAL_POLICY_FILE = REAL_ROOT / agent_profile.POLICY
RULES = PROFILE.policy_rules()
POLICY_FILE = ROOT / agent_profile.POLICY
WRAPPER = ROOT / PROFILE.wrapper
# The narrowest and widest authentication methods give one exact-host base
# profile and one multi-host base profile for policy tests.
NARROW_METHOD = min(PROFILE.auth, key=lambda method: (len(PROFILE.auth[method]['hosts']), method))
WIDE_METHOD = max(PROFILE.auth, key=lambda method: (len(PROFILE.auth[method]['hosts']), method))
NARROW_PROFILE = PROFILE.policy_profile(NARROW_METHOD)
WIDE_PROFILE = PROFILE.policy_profile(WIDE_METHOD)
HOST = PROFILE.auth[NARROW_METHOD]['hosts'][0]
GUARD = 'sandbox-egress-guard'
# Runtime tests run the checkout's real images; fixture image names are never
# built or pulled. The runner selects the image with the real wrapper variable.
AGENT_IMAGE = (os.environ.get(REAL_PROFILE.env('IMAGE')) or test_setting('TEST_IMAGE')
               or REAL_PROFILE.image('agent', 'latest'))
# The command of that real image, for runtime checks that execute it.
AGENT_COMMAND = REAL_PROFILE.command
# The native home of that real image, which wrappers always mount writable.
AGENT_HOME = REAL_PROFILE.home
PROXY_IMAGE = PROFILE.image('proxy', 'local')
NO_METHODS = 'the checkout profile declares no authentication method'


def env(suffix):
    """Fixture variable name, for example env('NETWORK')."""
    return PROFILE.env(suffix)


def real_env(suffix):
    """The checkout wrapper's variable name, for tests that launch it."""
    return REAL_PROFILE.env(suffix)

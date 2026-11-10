"""Shared test view of the agent profile; shared tests use no agent literals."""
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
NETWORK = ROOT / 'network'
sys.path.insert(0, str(NETWORK))
import agent_profile  # noqa: E402

PROFILE = agent_profile.load()
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
AGENT_IMAGE = PROFILE.image('agent', 'latest')
PROXY_IMAGE = PROFILE.image('proxy', 'local')


def env(suffix):
    """Wrapper variable name, for example env('NETWORK')."""
    return PROFILE.env(suffix)


def test_setting(name, default=None):
    """Neutral test-harness controls, for example SANDBOX_TEST_TMPDIR."""
    return os.environ.get('SANDBOX_' + name, default)

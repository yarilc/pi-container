"""Single source of the enforcement revisions shared by the protected components.

``network/guard.c`` and ``network/guard_landlock.h`` keep their own
``GUARD_REVISION`` and ``GUARD_REQUIRED_ABI`` defines so that the static guard build stays self-contained; tests/test_guard.py fails if
they differ from these values.
"""
GUARD_REVISION = 'abi3-seccomp-mux-v1'
GUARD_REQUIRED_ABI = 3
# Bumped whenever destination-binding behavior changes, so older proxies fail readiness.
TLS_ENFORCEMENT = 'tls-clienthello-sni-v2'

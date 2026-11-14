#!/usr/bin/env bash
# Synthetic wrapper contracts; no build, engine, or provider credentials.
set -Eeuo pipefail
script_dir=$(CDPATH='' cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)
# The toolchain library refuses world-writable ancestors such as /tmp, so the
# fixtures live in a private directory unless the caller provides one.
if [[ -z "${SANDBOX_TEST_TMPDIR:-}" ]]; then
    scratch_parent=${XDG_RUNTIME_DIR:-$HOME/.cache}
    mkdir -p -- "$scratch_parent"
    SANDBOX_TEST_TMPDIR=$(mktemp -d "$scratch_parent/pi-wrapper-tests.XXXXXX")
    export SANDBOX_TEST_TMPDIR
    trap 'rm -rf -- "$SANDBOX_TEST_TMPDIR"' EXIT
fi
python3 -B -m unittest discover -s "$script_dir/tests" -p test_wrapper.py -v "$@"

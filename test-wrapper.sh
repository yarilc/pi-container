#!/usr/bin/env bash
# Synthetic wrapper contracts; no build, engine, or provider credentials.
set -Eeuo pipefail
script_dir=$(CDPATH='' cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)
exec python3 -B -m unittest discover -s "$script_dir/tests" -p test_wrapper.py -v "$@"

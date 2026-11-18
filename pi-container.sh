#!/usr/bin/env bash
# Thin entry script: identical in every wrapper. The shared launcher core
# (launcher/core.sh) does everything with this wrapper's agent part
# (agent/launcher.sh); see docs/launcher-contract.md.
set -Eeuo pipefail
WRAPPER_INVOKED=${BASH_SOURCE[0]}
# Without GNU readlink the core reports the missing tool in its usual order.
WRAPPER_PATH=$(readlink -f -- "$WRAPPER_INVOKED" 2>/dev/null) || WRAPPER_PATH=''
if [[ -n "$WRAPPER_PATH" ]]; then
    wrapper_dir=${WRAPPER_PATH%/*}
elif [[ "$WRAPPER_INVOKED" == */* ]]; then
    wrapper_dir=${WRAPPER_INVOKED%/*}
else
    wrapper_dir=.
fi
# shellcheck source=launcher/core.sh
source "$wrapper_dir/launcher/core.sh" "$wrapper_dir/agent/launcher.sh" "$@"

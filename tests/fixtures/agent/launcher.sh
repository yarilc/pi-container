# Fixture agent part for the shared launcher tests: every data array and hook.
# Hooks append one line per call to FIXTURE_HOOK_LOG (when set), recording their
# inputs and whether session identity is visible to them.
# The core sources this file: it reads the AGENT_* data and hook outputs and
# defines the core state the hooks read.
# shellcheck shell=bash disable=SC2034,SC2154
AGENT_NAME=fixture-agent
AGENT_DISPLAY_NAME=Fixture
AGENT_WRAPPER=fixture-agent.sh
AGENT_ENV_PREFIX=FIXTURE_AGENT
AGENT_LABEL_NAMESPACE=io.fixture-agent
AGENT_IMAGE=localhost/fixture-agent
AGENT_PROXY_IMAGE=localhost/fixture-agent-egress
AGENT_HOME=/fixture-home
AGENT_COMMAND=fixture
AGENT_EXEC=/usr/local/bin/fixture
AGENT_CONFIG_DIR_ENV=FIXTURE_CONFIG_DIR
AGENT_CONFIG_HOME=.fixture
AGENT_SHARED_DIRS=(.config/openspec)
AGENT_PRIVATE_SHARED_DIRS=0
AGENT_APPROVAL_BYPASS_ENV=FIXTURE_AGENT_YOLO
AGENT_EXEC_TMP=1
AGENT_INSTALL_FILES=()
AGENT_CREDENTIALS=(fixture-api=FIXTURE_API_KEY fixture-account=)
AGENT_POLICY_HOSTS=("fixture-account=api.provider.test login.provider.test" "fixture-api=api.provider.test")
AGENT_SESSION_ENV=(FIXTURE_ALWAYS=1)
AGENT_RESTRICTED_ENV=(FIXTURE_TELEMETRY=0)
AGENT_PROVIDER_ENV=(FIXTURE_PROVIDER_ONLY=1)
AGENT_UNSET_ENV=(DBUS_SESSION_BUS_ADDRESS)
AGENT_RESERVED_ENV=(FIXTURE_FIXED)

fixture_record() {
    [[ -n "${FIXTURE_HOOK_LOG:-}" ]] || return 0
    printf '%s\t%s\ttoken=%s\tcontainer=%s\n' "$1" "${*:2}" \
        "${session_token:-unset}" "${container_id:-unset}" >>"$FIXTURE_HOOK_LOG"
}
fixture_fail() { [[ " ${FIXTURE_HOOK_FAIL:-} " != *" $1 "* ]]; }

agent_help() {
    fixture_record agent_help
    printf '  FIXTURE_AGENT_EXTRA  fixture agent variable read only by its hooks\n'
}
agent_validate() {
    fixture_record agent_validate "$@"
    fixture_fail agent_validate
}
agent_approval_bypass() {
    fixture_record agent_approval_bypass "$@"
    agent_bypass_args=(--fixture-bypass)
    agent_bypass_env=(FIXTURE_BYPASS=1)
    fixture_fail agent_approval_bypass
}
agent_command_args() {
    fixture_record agent_command_args "$@"
    agent_mode_args=(--fixture-mode "$1")
    fixture_fail agent_command_args
}
agent_environment() {
    fixture_record agent_environment "$@"
    read -r -a agent_env <<<"${FIXTURE_HOOK_ENV:-FIXTURE_FORWARDED FIXTURE_FIXED=1}"
    fixture_fail agent_environment
}
agent_mounts() {
    fixture_record agent_mounts "$@"
    read -r -a agent_mount_specs <<<"${FIXTURE_HOOK_MOUNTS:-}"
    fixture_fail agent_mounts
}
agent_build_args() {
    fixture_record agent_build_args "$@"
    agent_build_args=(FIXTURE_VERSION=1)
    read -r -a agent_build_inputs <<<"${FIXTURE_HOOK_BUILD_INPUTS:-}"
    fixture_fail agent_build_args
}

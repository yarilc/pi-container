# Fixture shell part for the shared launcher tests: data only, no hooks.
AGENT_NAME=fixture-shell
AGENT_DISPLAY_NAME='Fixture shell'
AGENT_WRAPPER=fixture-shell.sh
AGENT_ENV_PREFIX=FIXTURE_SHELL
AGENT_LABEL_NAMESPACE=io.fixture-shell
AGENT_IMAGE=localhost/fixture-shell
AGENT_PROXY_IMAGE=localhost/fixture-shell-egress
AGENT_HOME=/fixture-shell-home
AGENT_COMMAND=bash
AGENT_EXEC=/usr/local/bin/bash
AGENT_CONFIG_DIR_ENV=FIXTURE_SHELL_CONFIG_DIR
AGENT_CONFIG_HOME=.config/fixture-shell
AGENT_SHARED_DIRS=(.config/openspec)
AGENT_PRIVATE_SHARED_DIRS=0
AGENT_APPROVAL_BYPASS_ENV=
AGENT_EXEC_TMP=0
AGENT_INSTALL_FILES=()
AGENT_CREDENTIALS=()
AGENT_POLICY_HOSTS=()
AGENT_SESSION_ENV=(HISTFILE=/fixture-shell-home/.config/fixture-shell/bash_history)
AGENT_RESTRICTED_ENV=()
AGENT_PROVIDER_ENV=()
AGENT_UNSET_ENV=()
AGENT_RESERVED_ENV=()

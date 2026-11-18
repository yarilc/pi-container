# Pi agent part for the shared launcher core (launcher/core.sh). It mirrors
# agent/profile.json and agent/policies/default.json; tests/test_alignment.py
# compares them. See docs/launcher-contract.md in sandbox-container.
AGENT_NAME=pi-container
AGENT_DISPLAY_NAME=Pi
AGENT_WRAPPER=pi-container.sh
AGENT_ENV_PREFIX=PI_CONTAINER
AGENT_LABEL_NAMESPACE=io.pi-container
AGENT_IMAGE=localhost/pi-container
AGENT_PROXY_IMAGE=localhost/pi-egress
AGENT_HOME=/pi-home
AGENT_COMMAND=pi
AGENT_EXEC=/usr/local/bin/pi
AGENT_CONFIG_DIR_ENV=PI_CONTAINER_CONFIG_DIR
AGENT_CONFIG_HOME=.pi
AGENT_SHARED_DIRS=(.agents)
AGENT_PRIVATE_SHARED_DIRS=1
AGENT_APPROVAL_BYPASS_ENV=PI_CONTAINER_YOLO
AGENT_EXEC_TMP=0
# .version selects the Pi release (agent_build_args) and joins the build-inputs hash.
AGENT_INSTALL_FILES=(.version)
AGENT_CREDENTIALS=(anthropic-api=ANTHROPIC_API_KEY openai-api=OPENAI_API_KEY gemini-api=GEMINI_API_KEY
    openrouter-api=OPENROUTER_API_KEY)
AGENT_POLICY_HOSTS=("anthropic-api=api.anthropic.com" "openai-api=api.openai.com"
    "gemini-api=generativelanguage.googleapis.com" "openrouter-api=openrouter.ai")
AGENT_SESSION_ENV=()
# Pi's optional traffic stays off in offline and provider sessions. The core sets
# these after toolchain and forwarded variables and reserves them in those modes.
AGENT_RESTRICTED_ENV=(PI_OFFLINE=1 PI_SKIP_VERSION_CHECK=1 PI_TELEMETRY=0)
AGENT_PROVIDER_ENV=()
AGENT_UNSET_ENV=()
AGENT_RESERVED_ENV=()

# The physical ~/.gitconfig, set by agent_validate with the exact opt-in.
pi_gitconfig=''

# Runs before any engine query or state operation.
agent_validate() {
    pi_gitconfig=''
    if [[ "${PI_CONTAINER_GITCONFIG:-}" == 1 ]]; then
        local path=${HOME:-}/.gitconfig
        pi_gitconfig=$(readlink -f -- "$path" 2>/dev/null) && [[ -f "$pi_gitconfig" && ! -L "$pi_gitconfig" ]] \
            || { printf '%s: PI_CONTAINER_GITCONFIG=1 requires a regular file: %s\n' "$AGENT_NAME" "$path" >&2; return 1; }
        [[ "$pi_gitconfig" != *[:$'\n'$'\r']* ]] \
            || { printf '%s: PI_CONTAINER_GITCONFIG=1: the gitconfig path must not contain colon, CR or LF: %s\n' \
                "$AGENT_NAME" "$pi_gitconfig" >&2; return 1; }
    fi
    [[ "${PI_NPM_CACHE_SIZE:-256M}" =~ ^[1-9][0-9]{0,5}[kmgKMG]$ ]] \
        || { printf '%s: PI_NPM_CACHE_SIZE must be a positive size with a unit k, m or g, for example 256M\n' \
            "$AGENT_NAME" >&2; return 1; }
}

# The npm cache in every session; ~/.gitconfig read-only with the exact opt-in.
agent_mounts() {
    local home=$2
    agent_mount_specs=("tmpfs:$home/.npm:${PI_NPM_CACHE_SIZE:-256M}")
    [[ -z "$pi_gitconfig" ]] || agent_mount_specs+=("ro:$pi_gitconfig:$home/.gitconfig")
}

# Every build installs the Pi release named by the first line of .version.
agent_build_args() {
    local version=''
    [[ -f "$script_dir/.version" ]] && IFS= read -r version <"$script_dir/.version" || true
    version=${version//[[:space:]]/}
    [[ -n "$version" ]] || { printf '%s: .version is missing or empty\n' "$AGENT_NAME" >&2; return 1; }
    agent_build_args=("PI_VERSION=$version")
}

# Pi runs its tools without approval prompts: there is nothing to bypass.
agent_approval_bypass() {
    printf '%s: PI_CONTAINER_YOLO has no effect: Pi has no tool-approval layer and the container is the only boundary\n' \
        "$AGENT_NAME" >&2
}

agent_help() {
    printf '  PI_CONTAINER_YOLO       accepted (1, true or yes, case-insensitive; default:\n'
    printf '                          disabled) but has no effect: Pi has no tool-approval\n'
    printf '                          layer, so the container is the only boundary around\n'
    printf "                          Pi's tools. Pi's --approve trusts project-local files;\n"
    printf '                          it does not approve tools\n'
    printf '  PI_CONTAINER_GITCONFIG  exactly 1 mounts ~/.gitconfig read-only at\n'
    printf '                          /pi-home/.gitconfig (default: not mounted; it may hold\n'
    printf '                          credential helpers or tokens)\n'
    printf '  PI_NPM_CACHE_SIZE       noexec tmpfs size of /pi-home/.npm (default: 256M)\n'
    printf '  ANTHROPIC_API_KEY, OPENAI_API_KEY, GEMINI_API_KEY, OPENROUTER_API_KEY\n'
    printf '                          forwarded by name only to provider sessions using\n'
    printf '                          anthropic-api, openai-api, gemini-api or openrouter-api\n'
    printf '                          respectively, or to unrestricted sessions when\n'
    printf '                          PI_CONTAINER_ENV_VARS lists them\n'
    printf '\nOffline and provider sessions set PI_OFFLINE=1, PI_SKIP_VERSION_CHECK=1 and\n'
    printf 'PI_TELEMETRY=0; forwarded variables and Pi settings cannot override them.\n'
}

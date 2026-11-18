# pi-container

Run [Pi Coding Agent](https://pi.dev) transparently inside a **Podman container**,
with access to your Pi configuration (`~/.pi`), skills (`~/.agents`), and the
current project directory, with predictable host file ownership.

> By default, only `~/.pi`, `~/.agents` and the current working directory are
> mounted. `~/.gitconfig` is mounted read-only only with
> `PI_CONTAINER_GITCONFIG=1`. Other host config such as `~/.ssh` or `~/.config`
> is intentionally **not** exposed to the container.

## Requirements

- **Podman** ≥ 4.x (rootless mode, no `sudo` needed)
- Linux (including WSL2), GNU coreutils `timeout`, and native Linux storage for private state
- Python 3 for synthetic tests; the runtime runner provisions its own test tools

## Quick start

New users start with guided setup. It prepares a protected installation, the
images and guard under reviewed maintenance consent, qualification, and a
managed launcher that remembers the network mode:

```bash
git clone https://github.com/yarilc/pi-container.git
cd pi-container
bash ./pi-container.sh --container-setup   # interactive; must be used alone

cd /path/to/your/project
~/.local/bin/pi-container                   # the managed launcher printed by setup
```

See [docs/setup.md](docs/setup.md). An ordinary launch with an unset or empty
`PI_CONTAINER_NETWORK` stops with `setup required:` guidance; setup is never
started automatically. Offline sessions cannot reach any model provider.

### Direct operator launches

Operators can keep invoking the wrapper directly with an explicit mode:

```bash
# Every launch selects a network mode; unrestricted is the previous behavior
export PI_CONTAINER_NETWORK=unrestricted

# Build the image once, under explicit maintenance authorization
PI_CONTAINER_MAINTENANCE=1 ./pi-container.sh --container-build --version

# Use it anywhere, exactly like the `pi` command
cd /path/to/your/project
/path/to/pi-container/pi-container.sh "List the files in this directory"

# Or set up a convenience alias
alias pic='/path/to/pi-container/pi-container.sh'
pic --version
```

Building the image, including the first build, needs exact
`PI_CONTAINER_MAINTENANCE=1`. When `Containerfile`, `.containerignore`,
`.version`, `network/relay.py` or `network/mux.py` changes, the image is
stale: the launch stops until `--container-build` is run again under
maintenance. For restricted networking, see [Network modes](#network-modes).

## Optional host Podman API access

**⚠️ WARNING:** Mounting the host Podman socket gives the container full
control over the host's container runtime. The AI agent can use this to
create privileged containers, mount host filesystems, and effectively
escape container isolation. **This feature is OFF by default**.

To enable, set `PI_CONTAINER_PODMAN=1`:

```bash
PI_CONTAINER_PODMAN=1 pic "Debug the failing container"
```

The container includes the `podman` CLI so you can interact
with the **host's Podman service** from inside the container.

```bash
# Inside pi, or via `pic -p`:
podman ps       # Lists host containers
podman images   # Lists host images
```

### Podman socket architecture

Only exact `PI_CONTAINER_PODMAN=1` installs the client and enables delegation.
Unset, empty, `0`, `false`, `true`, `yes`, and all other values disable it;
migrate earlier truthy configurations to `1`.

Selection uses `PI_CONTAINER_PODMAN_SOCKET`, then explicit Unix `CONTAINER_HOST`, then
`${XDG_RUNTIME_DIR:-/run/user/<uid>}/podman/podman.sock`. The accessible socket
must be absolute, canonical, readable/writable, and report a rootless service
with an absolute `Host.RemoteSocket.Path`. Enabled verification failures stop
before image operations; no warning-only fallback or automatic service start
occurs. Start the rootless service yourself if needed, for example
`systemctl --user start podman.socket`.

The verified service reports the host-side bind source, which may differ from
the socket visible to a containerized caller. It is mounted at
`/run/podman/podman.sock`, with session
`CONTAINER_HOST=unix:///run/podman/podman.sock`. Disabled sessions explicitly
unset `CONTAINER_HOST`; `PI_ENV_VARS` cannot change this selection or inject a
named connection. Containerized callers must preserve host absolute workspace
and state paths. Use a same-host service; a Unix URI alone does not establish
host identity. Client/server version compatibility is still required.

Delegation gives the service user's authority over host containers and allows
further host mounts beyond the workspace. It is independent of native Pi
permission controls.

## Usage

### Wrapper modes

```bash
pic --container-help                 # also --wrapper-help; no prerequisites
pic --container-setup                # guided setup and managed launcher; alone
pic --container-build --version      # force refresh, then start Pi
pic --container-build                # refresh the image only, then exit
pic --container-shell                # Bash with the same sandbox and cleanup
pic --container-git-worktree         # expose the entire immediate parent
pic --container-toolchain list       # manage the toolchain library; first argument
```

Worktree mode keeps the physical original workdir but exposes siblings in the
immediate parent read/write. No higher ancestor is selected. It requires the
explicit flag and applies the sensitive-directory guard to the exposed parent.
Shell mode discards native Pi arguments; other modes strip only wrapper flags.
Native `--help` remains Pi's help.

### Session lifecycle

Names are reserved atomically through `podman create`, starting above the
highest matching suffix across running and stopped containers (`08` is decimal
8). At most 20 confirmed collisions are retried; existing containers are never
replaced. `CONTAINER_NAME` inside the session matches the reserved name.

Creation uses a private full-ID record. Attachment preserves stdin and EOF.
Application/attach exit codes, including 125, survive cleanup failures.
TERM/INT/HUP select 143/130/129; the first signal is forwarded once and later
signals neither replace it nor renew deadlines. Attached shutdown allows 5s
application grace. Each signal/removal control has a 5s timeout plus 1s forced
termination; local-client reaping allows TERM 5s then KILL 1s.
Interrupted creation allows 5s completion, TERM 5s, KILL 1s, then re-reads the
CID and attempts removal within 5s+1s (17s total phase budgets). Attached
shutdown has at most 23s of phase budgets, excluding scheduling overhead.

Only this invocation's verified full ID is removed. Missing/invalid ownership
is reported without deleting by name. Cancelling a local client does not prove
the server stopped creating the container; engine loss, late results, or SIGKILL
can leave resources requiring explicit inspection and cleanup. `PI_CONTAINER_RUN_TIMEOUT`
is Podman's native container lifetime option, independent of these budgets;
its exit status depends on the supported engine and application. The tested
rootless service returned 255 for a sleeping shell with a one-second lifetime;
this observation is not a portable exit-code guarantee.

### Interactive mode (default)

```bash
pic "Refactor the authentication module"
```

### Print mode (one-shot)

```bash
pic -p "Summarize this README"
```

### Select a model

```bash
pic --model sonnet "Review the test suite"
pic --model openai/gpt-4o "Write a proposal"
```

### Resume a previous session

```bash
pic -c                # Continue most recent session
pic -r                # Browse and resume
pic --session path    # Specific session file
```

### Custom tools / read-only mode

```bash
pic --tools read,grep,find,ls -p "Audit the codebase for security issues"
```

### Continue a session by name

```bash
pic --name "my-task" -p "Finish what I started"
```

### Non-interactive use (piped input, CI/CD)

```bash
echo "List files" | pic -p
```

TTY allocation requires both stdin and stdout to be terminals. Piped or file
input and EOF are retained even though the attach client runs in the background.

### Installing extensions

Community extensions (npm packages, git repos, or local paths) install into
the writable `~/.pi/agent/npm` (user scope) or `$PWD/.pi/npm` (project scope)
and persist across container runs:

```bash
pic install npm:pi-web-access
pic install git:github.com/user/pi-ext.git
pic install ./local/path
```

An ephemeral tmpfs is mounted at `~/.npm` for npm's cache so installs work
under the read-only root filesystem. Increase its size for large extensions:

```bash
PI_NPM_CACHE_SIZE=512M pic install npm:pi-web-access
```

## Tips

- **Alias in `~/.bashrc`**: `alias pic='/path/to/pi-container/pi-container.sh'`
- **Debug mode**: `PI_DEBUG=1 pic ...` to see verbose output
- **Custom image name**: `PI_CONTAINER_IMAGE=my-pi pic ...`
- **Rebuild the image**: `pic --container-build --version`
- **Interactive CLI args**: all arguments pass straight through to Pi — use `--help` to see Pi's full CLI, or `--wrapper-help` for wrapper-specific options
- **Multiple instances**: containers are named `<directory>-0`, `<directory>-1`, etc. Concurrent instances reserve above the highest existing suffix with bounded collision retries.

## Environment variables

### API keys

In `unrestricted` mode, the script forwards these environment variables to the
container **only if they are set and non-empty**. In `provider` mode only the
key of the selected profile is forwarded, and `offline` forwards none (see
[Provider mode](#provider-mode)):

| Variable | Purpose |
| --- | --- |
| `ANTHROPIC_API_KEY` | Anthropic / Claude API key |
| `OPENAI_API_KEY` | OpenAI API key |
| `GOOGLE_API_KEY` | Forwarded in unrestricted mode; Pi 0.80.8 reads `GEMINI_API_KEY` for Gemini, so list it in `PI_ENV_VARS` or use the `gemini-api` profile |

> ⚠️ **Security note:** API keys are passed as environment variables. They are
> visible in `podman inspect` output and inside the container's `/proc`.
> For production or shared systems, consider using `podman secret` instead.

### Custom environment variables

Skills, extensions, or other tools may require environment variables that the
wrapper does not hardcode (e.g. `GITHUB_TOKEN`, `DATABASE_URL`, a third-party
API key). Use `PI_ENV_VARS` to forward arbitrary variables **by name**.

`PI_ENV_VARS` is a space-separated list of variable **names**. Each name that
is set and non-empty in the host environment is forwarded to the container via
`-e NAME` (by name only, never as `NAME=value`), so secret values never appear
on the process command line. Podman still stores their values in container inspection metadata.
Variables that are unset or empty are skipped silently.

```bash
# Forward two secrets to the container
PI_ENV_VARS="GITHUB_TOKEN DATABASE_URL" pic "fix the bug"

# With the values exported in the current shell
export GITHUB_TOKEN=ghp_xxx
export DATABASE_URL=postgres://localhost/app
PI_ENV_VARS="GITHUB_TOKEN DATABASE_URL" pic "review the schema"

# Persist the list once in ~/.bashrc (values still exported per-session)
#   echo 'export PI_ENV_VARS="GITHUB_TOKEN DATABASE_URL"' >> ~/.bashrc
```

Names already handled explicitly by the wrapper (`HOME`, `TERM`, `EDITOR`,
`VISUAL`, `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, `GOOGLE_API_KEY`,
`HTTP_PROXY`, `HTTPS_PROXY`, `NO_PROXY`, `CONTAINER_NAME`, `CONTAINER_HOST`,
`CONTAINER_CONNECTION`) are skipped if listed in `PI_ENV_VARS`
to avoid duplicate forwarding.

> ⚠️ **Security note:** `PI_ENV_VARS` only forwards the *names*; the *values*
> come from the host environment and are still visible inside the container's
> `/proc` and in `podman inspect` output (same residual exposure as API keys).
> Do not list variables you do not need, and prefer the narrowest set possible.
> For highly sensitive, long-lived secrets on shared systems, consider
> `podman secret` instead.

### Proxy support

In `unrestricted` mode, `HTTP_PROXY`, `HTTPS_PROXY` and `NO_PROXY` set on the
host are forwarded to the container automatically. Restricted modes never
forward host proxy or CA variables.

### Other variables

| Variable | Purpose |
| --- | --- |
| `PI_CONTAINER_NETWORK` | Required network mode: `offline`, `provider` or `unrestricted`; see [Network modes](#network-modes) |
| `PI_CONTAINER_MAINTENANCE` | Exactly `1` authorizes image builds and proxy pulls |
| `PI_CONTAINER_CONFIG_DIR` | Private host directory replacing only `~/.pi`; conflicts with `PI_CONTAINER_STATE_DIR`. Inside the session it is always `/pi-home/.pi` |
| `PI_CONTAINER_TRUST_HOST_CA`, `PI_CONTAINER_CA_BUNDLE` | Opt-in host CA trust; see [Host CA trust](#host-ca-trust) |
| `PI_CONTAINER_IMAGE` | Override the container image name (default: `localhost/pi-container`) |
| `PI_DEBUG` | Set to any value to enable verbose debug output |
| `PI_CONTAINER_PODMAN` | Only exact `1` enables the client and verified host socket; all other values disable delegation |
| `PI_CONTAINER_PODMAN_SOCKET` | Absolute accessible socket override; then Unix `CONTAINER_HOST`, then `${XDG_RUNTIME_DIR:-/run/user/<uid>}/podman/podman.sock` |
| `PI_CONTAINER_STATE_DIR` | Private host directory holding `.pi` and `.agents` instead of `~/.pi` and `~/.agents`; see [Isolated state](#isolated-state) |
| `PI_CONTAINER_MEMORY_LIMIT` | Container memory limit (default: `4g`); see [Session hardening](#session-hardening-budgets-and-lifetime) |
| `PI_CONTAINER_CPU_LIMIT` | Container CPU limit (default: `2`) |
| `PI_CONTAINER_PIDS_LIMIT` | Container PID limit (default: `512`) |
| `PI_NPM_CACHE_SIZE` | Size of the ephemeral npm cache tmpfs at `/pi-home/.npm`, used by `pi install npm:<pkg>` (default: `256M`) |
| `PI_READONLY_CONFIG` | Set to `1` to mount `~/.pi` and `~/.agents` read-only (prevents persistence) |
| `PI_CONTAINER_GITCONFIG` | Exactly `1` mounts `~/.gitconfig` read-only from its physical file (default: not mounted). The opt-in fails if `~/.gitconfig` is not a regular file |
| `PI_MOUNT_GITCONFIG` | Deprecated alias with a warning: `1` mounts, `0` does not. Conflicting values with `PI_CONTAINER_GITCONFIG` are errors |
| `PI_CONTAINER_RUN_TIMEOUT` | Native Podman container lifetime in seconds, placed before the image (0 disables); independent of shutdown budgets |
| `PI_ENV_VARS` | Space-separated list of extra env var **names** to forward to the container (for skill/extension/tool secrets; forwarded by name only, never as `NAME=value`). See [Custom environment variables](#custom-environment-variables) |
| `PI_CONTAINER_ALLOW_UNSAFE_WORKSPACE` | Exactly `1` allows a refused sensitive workspace, with a warning (not recommended) |
| `TERM` | Terminal type (forwarded for TUI rendering) |
| `EDITOR`, `VISUAL` | Host editor preference (forwarded with fallback to `nano`) |

## Network modes

`PI_CONTAINER_NETWORK` is required for every launch; an unset or empty value
stops before any engine call or state change. Unknown values fail before image
operations, and a failed restricted launch never retries with unrestricted
networking. `PI_NETWORK` is rejected with migration guidance.

| Mode | Agent network | Podman delegation |
| --- | --- | --- |
| `offline` | Own loopback, pipes and connected socket pairs only; no model provider is reachable | Rejected |
| `provider` | As offline, plus the exact HTTPS host of one protected provider profile through an external proxy | Rejected |
| `unrestricted` | Ordinary runtime networking, the previous behavior | Exact `PI_CONTAINER_PODMAN=1` |

The restricted implementation is shared with `sandbox-container` and copied
unchanged from its tag `sandbox-ref-25`; see
[docs/network-contract.md](docs/network-contract.md) and
[network/README.md](network/README.md).

### Restricted prerequisites and qualification

Offline and provider modes require:

- host Python 3;
- a same-host Unix rootless Podman >= 4.9 service with Netavark;
- the standard OCI seccomp profile and usable Landlock ABI >= 3;
- a protected installation outside writable workspace and state trees;
- the static guard and its SHA-256 manifest in `network/bin`;
- a current local qualification report.

Run `--container-qualify` alone after preparation or relevant updates:

```bash
PI_CONTAINER_NETWORK=offline ./pi-container.sh --container-qualify
```

Qualification is bound to the boot, engine, security policy, code, images,
policy, profile, CA trust and hardening settings. A
reboot therefore requires requalification. An active SELinux or AppArmor policy
that cannot be identified forces the full gate on every launch. The shipped
release acceptance inventory is empty, so installations report
`locally-qualified`.

Restricted sessions receive no host proxy or CA variables, and
`PI_OFFLINE=1`, `PI_SKIP_VERSION_CHECK=1` and `PI_TELEMETRY=0` are set after
forwarding. Writable `~/.pi` settings cannot re-enable Pi's startup network
operations. Runtime `npm`/`pi install` package downloads and named Unix
sockets are unavailable: preinstall extensions in unrestricted mode or during
maintenance. Pi's tools and its TUI were verified under the guard; see [the validation record](docs/validation.md).

### Provider mode

Provider mode needs:

- `PI_CONTAINER_NETWORK_PROFILE`;
- `PI_CONTAINER_NETWORK_POLICY`, a protected absolute policy path, normally
  `agent/policies/default.json` of the installation;
- `PI_CONTAINER_NETWORK_RUNTIME_DIR`, a private native directory at its host
  path;
- `PI_CONTAINER_EGRESS_IMAGE`, the immutable proxy image ID or registry digest.

| Profile | Allowed host | Forwarded key |
| --- | --- | --- |
| `anthropic-api` | `api.anthropic.com` | `ANTHROPIC_API_KEY` |
| `openai-api` | `api.openai.com` | `OPENAI_API_KEY` |
| `gemini-api` | `generativelanguage.googleapis.com` | `GEMINI_API_KEY` |
| `openrouter-api` | `openrouter.ai` | `OPENROUTER_API_KEY` |

Only that key is forwarded. Subscription and browser-callback logins
(Claude Pro/Max, ChatGPT, Copilot), cloud providers, gateways, custom base URLs
and local model servers have no profile.

Limits:

- **Residual exfiltration.** The proxy binds the CONNECT host to the TLS server
  name of the initial and retried ClientHello. It cannot tell your credentials
  from an attacker's, so an injected agent can send workspace data to the
  allowed host with a foreign key or account. Only offline removes this
  channel.
- **Opaque application routing.** Matching SNI does not prove exclusive
  communication with your account. TLS 1.2 renegotiation is not inspected.
- **Hosted tools.** Provider-hosted tools such as web search run at the
  provider, outside this boundary.
- **Maintenance traffic.** Image pulls and build `RUN` steps happen outside
  runtime filtering.

### Operator build inputs

Prepare these under maintenance authorization (guided setup arrives with
`add-container-setup`):

```bash
export PI_CONTAINER_MAINTENANCE=1
tag=$(python3 -I network/agent_profile.py image toolchain development)
podman build --pull=never --tag "$tag" --file network/guard-build.Containerfile network
bash network/build-guard.sh "$PWD/network/bin"   # a protected native directory
podman build --pull=never --tag localhost/pi-egress:local --file network/Containerfile network
podman image inspect --format '{{.Id}}' localhost/pi-egress:local
```

### Host CA trust

`PI_CONTAINER_TRUST_HOST_CA=1` (or `true`/`yes`) mounts one bundle read-only at
`/pi-home/ca/bundle.pem`: `PI_CONTAINER_CA_BUNDLE`, or the first of
`/etc/ssl/certs/ca-certificates.crt` and `/etc/pki/tls/certs/ca-bundle.crt`.
The wrapper sets `SSL_CERT_FILE`, `REQUESTS_CA_BUNDLE`, `CURL_CA_BUNDLE` and
`NODE_EXTRA_CA_CERTS` to it. Pi on Node honors `NODE_EXTRA_CA_CERTS`.

## Toolchains

Sessions can use extra toolchains, such as Java, Go or Python, without Podman
access, an unrestricted network or a rebuilt image. The operator keeps a
toolchain library on the host. Every session sees it read-only, with `nosuid`
and `nodev`, at `/toolchains`. The library is shared by the Claude, Codex,
OpenCode, Pi and Antigravity wrappers. A toolchain adds no network, IPC or
privilege capability: it runs under the same restrictions as the rest of the
session.

- **Location:** `${XDG_DATA_HOME:-~/.local/share}/sandbox-toolchains`, or
  `PI_CONTAINER_TOOLCHAINS_DIR`. The launcher creates it private (`0700`) when
  it is missing. It must stay outside the workspace, the Pi state
  (`~/.pi` or `PI_CONTAINER_CONFIG_DIR`, `~/.agents`, or
  `PI_CONTAINER_STATE_DIR`, also with `PI_READONLY_CONFIG`) and the
  installation. A home directory exposed as the workspace with
  `PI_CONTAINER_ALLOW_UNSAFE_WORKSPACE=1` contains the default library, so that
  launch stops. Move the library with `PI_CONTAINER_TOOLCHAINS_DIR`, or omit it.
- **Disable:** `PI_CONTAINER_TOOLCHAINS=0` (or `false`, `no`) starts a session
  without the mount.
- **Live updates:** a toolchain added or removed on the host appears in
  running sessions without a restart.

### Managing the library

The operator runs these commands on the host; `--container-toolchain` must be
the first argument:

```bash
pic --container-toolchain add java21.json   # install or replace from a recipe
pic --container-toolchain list              # name, version, default, size, verified base
pic --container-toolchain remove java21
pic --container-toolchain verify [java21]   # rerun the checks on the current runtime image
```

- **Sources:** a toolchain is a relocatable directory tree, taken either from
  a path inside an OCI image referenced by `@sha256:` digest, or from a local
  archive with its SHA-256. The command never downloads archives.
- **Pulls:** pulling a missing image requires exact
  `PI_CONTAINER_MAINTENANCE=1`. Like image builds, the pull happens on the
  host, outside runtime filtering.
- **Extraction:** it rejects absolute paths, `..`, device nodes and links
  that leave the toolchain, and clears setuid and setgid bits.
- **Atomic changes:** changes take a library lock and replace directories
  atomically.
- **Check:** before accepting a toolchain, `add` runs the recipe's `check`
  command in the Pi runtime image (`PI_CONTAINER_IMAGE`), without network and
  with the session's identity and hardening. A toolchain that needs a newer C
  library than the image's glibc fails here. The manifest records the base
  image from the installed `Containerfile`. If that base changes, the
  toolchain stays visible but loses its default environment until `verify`
  succeeds, and the launcher prints one warning naming it. All five wrappers
  build from the same base, so a toolchain verified by another wrapper keeps
  its default environment here.

### Recipes

A recipe is a JSON file that the operator keeps and reviews:

| Key | Meaning |
| --- | --- |
| `schema`, `name`, `version` | `1`; `[a-z0-9][a-z0-9._-]*`; free version text |
| `source` | `{"image": "<ref>@sha256:<digest>", "path": "/abs/path"}` or `{"archive": "/abs/file.tar.xz", "sha256": "<hex>", "strip_components": 1}` |
| `path` | directories relative to the toolchain, added to `PATH` (default `["bin"]`) |
| `env` | variables: `{"toolchain": "<relative path>"}` or `{"value": "<literal>"}` |
| `requires` | other toolchains whose environment is loaded first |
| `notes` | short instructions shown to the agent in `toolchains.md` |
| `check` | command run in the runtime image before the toolchain is accepted |
| `default` | `true` adds the toolchain to new sessions' environment |

- **Protected variables:** recipes cannot set `PATH`, `HOME`, loader, proxy
  or CA variables, any `XDG_` variable (a wrapper may place its state with
  them) or `DBUS_SESSION_BUS_ADDRESS` (no session has a bus). These rules are
  the same in every wrapper. Each wrapper also protects its own variables:
  its prefix, configuration, approval and credential variables, such as
  `PI_CONTAINER_*`, `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, `GEMINI_API_KEY`
  and `OPENROUTER_API_KEY` here, and the agent's own variables that its
  profile lists in `native.protected_env`. For Pi these are every `PI_`,
  `ANTHROPIC_`, `OPENAI_`, `GEMINI_` and `OPENROUTER_` variable and
  `GOOGLE_API_KEY`. `add` rejects them. If another wrapper
  installed a toolchain that sets one, this wrapper leaves that variable out
  of its sessions and prints a warning naming the toolchain; the rest of the
  toolchain stays available. Pi's own session settings (`PI_OFFLINE`,
  `PI_SKIP_VERSION_CHECK`, `PI_TELEMETRY` in restricted sessions) are among
  them, and the launcher also sets them after the toolchain environment.
- **Default toolchains:** in new sessions, their `PATH` entries come **after**
  the image's. They never replace the runtime's own `node` or `python3`, which
  Pi and the image tools use.
- **Conflicts:** two default toolchains cannot share a command or a variable.
  Install a second version with `"default": false` and use it through its
  `env.sh`.
- **Writable locations:** every temporary filesystem in a Pi session is
  `noexec` (`/tmp`, `/var/tmp`, `/run`, the `/pi-home` tmpfs and
  `/pi-home/.npm`). Point caches to `/tmp` with literal values. A tool that
  runs files from its temporary directory must use a directory under the
  workspace, for example `GOTMPDIR` for `go test`; Maven's jansi prints a
  harmless native-library warning. With `PI_READONLY_CONFIG`, `~/.pi` and
  `~/.agents` are read-only too.
- **Dependency downloads** (Maven, npm, pip, Cargo, Go modules) need network
  access that provider and offline modes do not grant. Provide dependencies in
  the workspace, or use an unrestricted session.

The verified example recipes (Temurin 21, Maven 3.9, Go, Node.js 24,
Python 3.13 and Rust) are kept in the reference repository, in
[`sandbox-container/docs/toolchains/`](https://github.com/yarilc/sandbox-container/tree/main/docs/toolchains),
with their versions, digests, checksums and usage notes in its
[README "Toolchains" section](https://github.com/yarilc/sandbox-container#toolchains).
They do not depend on the agent.

### Telling the agent

The wrapper never edits `AGENTS.md` or other instruction files. The library
contains a generated `/toolchains/toolchains.md` with the usage rules and every
installed toolchain, plus a machine-readable `/toolchains/index.json`. Add one
line to the project's `AGENTS.md`, or to `~/.pi/agent/AGENTS.md`:

```markdown
Read /toolchains/toolchains.md before using or looking for build tools.
```

The agent then runs a toolchain in one command with
`. /toolchains/<name>/env.sh && <command>`. This form also works for
toolchains added after the session started.

SELinux and AppArmor enforcement were not tested with the library mount. On
hosts that enforce them, profile the tools you add.

## Mounts and security

### Permission model

Pi runs as your numeric UID/GID using `--userns=keep-id --user <uid>:<gid>`.
Files created on writable binds retain your host ownership. All capabilities
are dropped; no DAC_OVERRIDE, CHOWN, SETGID, or SETUID additions are used.
The root filesystem is read-only, with no-new-privileges and resource limits.

```text
Host UID/GID 1000:1000
  -> Linux rootless Podman, keep-id
  -> Pi UID/GID 1000:1000, no capabilities
  -> workspace and private state writes owned by 1000:1000
```

Every build and session first verifies a Linux rootless launch engine.
Local Podman and explicit same-host absolute Unix `CONTAINER_HOST` endpoints
are supported. Named connections, TCP/SSH, implicit remote contexts, and
Unix paths consisting only of slashes are rejected. `PI_ALLOW_ROOTFUL`
is removed and cannot bypass verification. Engine replies must be complete,
with no CR or extra records, including extra blank records.

Writable `~/.pi` and `~/.agents` must belong to you, allow read/write/traverse,
and grant no group/other permissions. Missing directories are created privately
with a scoped umask 077 before image operations. Existing state is never
chmodded, chowned, replaced, or populated from other credential stores.
If rejected, inspect and explicitly repair the named directory yourself or
relocate it to private native Linux storage and use a directory symlink.
Filesystems that ignore Unix modes cannot provide this privacy check.
Guided setup applies the same rule to `~/.agents` as to `~/.pi`
(`native.private_shared_dirs: true` in `agent/profile.json`). It stops before
image work, and the refusal names the path, the reason and, for a mode such as
`755` left by another tool, the fix `chmod 700 <path>`.
Read-only mode requires existing readable/traversable directories, without
requiring ownership/privacy/write access; their confidentiality remains yours
to manage. Missing read-only state fails without creating it.

### Dedicated home

Sessions use `HOME=/pi-home`, an ephemeral 64 MiB noexec tmpfs. Your `~/.pi`
and `~/.agents`, the npm cache tmpfs and the opted-in `~/.gitconfig` are
mounted below it, so Pi, extensions and Git find them as before; the
workspace keeps its host absolute path. Other files written in `/pi-home`
do not survive the session.

### Isolated state

`PI_CONTAINER_STATE_DIR=/absolute/path` keeps Pi state apart from your
everyday `~/.pi` and `~/.agents`. The directory holds its own `.pi` and
`.agents`:

- In the default writable mode the directory becomes the persistent
  `/pi-home`. It and its `.pi` and `.agents` are created privately when
  missing and must belong to you without group/other permissions.
- With `PI_READONLY_CONFIG=1`, its `.pi` and `.agents` must already exist and
  are mounted read-only below an ephemeral home.

The directory must not equal, contain or lie inside the workspace. No
credentials are copied; authenticate again inside an isolated state.

### Volume mounts

| Mount point | Purpose | Read-only mode |
| --- | --- | --- |
| `/pi-home/.pi` ← `~/.pi` | Pi configuration, auth, sessions, extensions | `PI_READONLY_CONFIG=1` |
| `/pi-home/.agents` ← `~/.agents` | Skills (prompt libraries) | `PI_READONLY_CONFIG=1` |
| `${PWD}` | Current working directory (same path inside and out) | Always writable |
| `/pi-home/.gitconfig` ← `~/.gitconfig` | Git identity, only with `PI_CONTAINER_GITCONFIG=1` | Always read-only |

The workspace uses `pwd -P`: its physical absolute source and destination
are identical, as is the working directory. State sources are resolved
physically and mounted at the existing HOME-relative destinations. No host
SELinux labels are changed automatically (`:z`/`:Z` are omitted). Access
failures require checking host policy and permissions explicitly; the wrapper
never disables confinement or repairs labels.

`~/.gitconfig` is not mounted by default because Git configuration often holds
credential helpers, URL tokens, `include` paths and signing-key references.
When the file exists and neither `PI_CONTAINER_GITCONFIG` nor
`PI_MOUNT_GITCONFIG` is set, the wrapper prints one notice;
`PI_CONTAINER_GITCONFIG=0` silences it. Alternatives to mounting it: set the
identity in the repository (`git config user.name ...`), or forward
`GIT_AUTHOR_NAME`, `GIT_AUTHOR_EMAIL`, `GIT_COMMITTER_NAME` and
`GIT_COMMITTER_EMAIL` by name with `PI_ENV_VARS`.

Temporary storage is declared explicitly with automatic read-only tmpfs
provisioning disabled. `/tmp` and `/var/tmp` are each 256 MiB, `/run` is 32 MiB,
and `~/.npm` defaults to 256 MiB (`PI_NPM_CACHE_SIZE` overrides it). All are
rw,nosuid,nodev,noexec. The first three use mode 1777; npm cache uses mode 0700
and your UID/GID. Delegated-client stores at `/var/lib/containers` (256 MiB)
and `/run/containers` (64 MiB) use the same hardening and private ownership.
Private tmpfs ownership uses Podman `U`; host binds never use recursive
ownership changes. Every temporary store disappears with the session.

> **Security note:** `~/.pi` and `~/.agents` are mounted **read-write by default**.
> A compromised agent could plant malicious extensions that persist across runs.
> Set `PI_READONLY_CONFIG=1` when working with untrusted prompts or projects.
> See [SECURITY.md](./SECURITY.md) for details.
>
> **npm cache:** An ephemeral tmpfs is mounted at `/pi-home/.npm` so that
> `pi install npm:<package>` works under the read-only root filesystem (npm
> defaults its cache to `~/.npm`, which would otherwise be unwritable). The
> cache is cleared when the container exits; installed extensions themselves
> persist in `~/.pi/agent/npm` (user scope) or `$PWD/.pi/npm` (project scope).
> Override the cache size with `PI_NPM_CACHE_SIZE` (default: `256M`).

### Container hardening

| Control | Implementation |
| --- | --- |
| Identity / capabilities | Caller UID/GID, keep-id, `--cap-drop=ALL`, no additions |
| Root filesystem | Read-only; explicit bounded `/tmp`, `/var/tmp`, `/run`, and npm cache; the engine's `/dev` and `devpts`, and an empty read-only `/dev/shm`; an empty read-only `/run/secrets` mask |
| Privilege escalation | `--security-opt=no-new-privileges` |
| Resource limits | 4 GiB memory, 2 CPUs, 512 processes (configurable), validated, each enforced when its cgroup controller is delegated, and checked after create |
| SELinux | Host labels and confinement remain unchanged |
| Sensitive workspace guard | Refuses `/`, system directories, `/tmp`, `$HOME` and `/mnt/<letter>` on physical paths (override: exact `PI_CONTAINER_ALLOW_UNSAFE_WORKSPACE=1`) |
| Rootless enforcement | Verified Linux rootless engine before image operations; no override |
| Signal handling | Owned full-ID lifecycle with finite cleanup phases; `--init` for reaping |
| Image build policy | Pinned inputs; a stale content hash stops the launch until `--container-build` |
| Conditional TTY | Only when stdin and stdout are terminals |
| Container naming | Sanitized `<dir>-<N>`, max existing suffix+1 including stopped containers; atomic create, at most 20 attempts |

> **Network egress is unrestricted by default.** An autonomous agent with
> network access and read access to mounted volumes (including
> `~/.pi/agent/auth.json`) could exfiltrate data if subverted by prompt
> injection. Use `PI_CONTAINER_NETWORK=offline`, or `provider` with one exact
> provider profile, to limit egress.
> See [SECURITY.md](./SECURITY.md).
>
> **Config directories (`~/.pi`, `~/.agents`) are writable by default.**
> A compromised agent could plant persistent extensions or skills. Use
> `PI_READONLY_CONFIG=1` to mount them read-only for untrusted tasks.
> See [SECURITY.md](./SECURITY.md) for details on this and other risks.

### Session hardening, budgets and lifetime

| Variable | Default | Accepted values |
| --- | --- | --- |
| `PI_CONTAINER_MEMORY_LIMIT` | `4g` | positive integer with unit `k`, `m` or `g`, up to 1 PiB |
| `PI_CONTAINER_CPU_LIMIT` | `2` | positive number with at most 3 decimals, up to 1024 |
| `PI_CONTAINER_PIDS_LIMIT` | `512` | integer from 1 to 4194304 |
| `PI_CONTAINER_RUN_TIMEOUT` | `0` (disabled) | whole seconds, at most 10 digits |
| `PI_CONTAINER_ALLOW_UNSAFE_WORKSPACE` | unset | exactly `1` permits a refused workspace |

Only an unset budget selects its default; no value disables a budget. Invalid
values stop with status 1 before any engine query or state creation. Each budget
is enforced only when the rootless engine delegates its cgroup v2 controller
(`memory`, `cpu`, `pids`), as reported by `podman info`
(`Host.CgroupControllers`). A missing controller leaves that budget unenforced:
the wrapper does not request it, prints a notice such as `pi-container: agent
CPU budget not enforced: cgroup controller cpu is not delegated to the rootless
engine`, and continues without a question. Provider proxies follow the same rule
for their 128-process and 256 MiB limits. Without the memory or process budget,
a session can exhaust host memory or processes for your user. After creating the
container the wrapper inspects it and starts it only when every enforced budget
equals its selected value and no unenforced budget is present; otherwise it
removes its own container and names the reported controllers. Restricted
qualification records the enforced set, so a change in delegation requires
requalification. Budgets and tmpfs sizes do not limit workspace or state storage
growth.

Podman 5 with crun 1.27 cannot attach a terminal to a read-only `/dev`, so
automatic read-only tmpfs provisioning stays enabled. The engine provides `/dev`
and a `devpts` at `/dev/pts` that allows pseudo-terminals, which interactive
tools such as `script`, `expect` or `tmux` need. An explicit `devpts` mount
would get `ptmxmode=000`, and no pseudo-terminal could be opened. Each session
mounts an empty read-only `/dev/shm`; tools that need POSIX shared memory there
are not supported. On Podman 5, `/dev` is the engine's writable tmpfs and is not
`noexec`, but no device can be created without capabilities. On Podman 4.9,
`/dev` stays read-only. An empty read-only tmpfs at `/run/secrets` masks
engine default mounts there (for example RHEL subscription certificates from
`mounts.conf`).

`PI_CONTAINER_RUN_TIMEOUT` sets Podman's native container lifetime,
independent of the wrapper's shutdown budgets. When it stops a session, the
wrapper prints a notice and keeps the engine client's exit status (255 on
Podman 4.9.3). The notice compares whole seconds, so with a 1-second limit a
fast non-zero exit can print it; the status is never altered.

The writable workspace, or the worktree parent, must not physically be `/`,
`/home`, `/root`, `/etc`, `/usr`, `/var`, `/bin`, `/sbin`, `/lib`, `/lib64`,
`/boot`, `/opt`, `/srv`, `/mnt`, `/media`, `/proc`, `/sys`, `/dev`, `/run`,
`/tmp`, the caller's physical home or a `/mnt/<letter>` drive root.
Descendants such as `/mnt/d/project` are allowed. Exact
`PI_CONTAINER_ALLOW_UNSAFE_WORKSPACE=1` permits a refused directory with a
warning; it relaxes no other check.

### Permissions

Pi runs its tools (read, bash, edit, write and extension tools) without
approval prompts, so the container is the only boundary around Pi's tools.
`PI_CONTAINER_YOLO` is accepted like the other wrappers' permission-bypass
switch (`0`, `1`, `true`, `false`, `yes` or `no`; other values fail) so that
setup and the managed launcher can save it. Pi 0.80.8 has no approval layer to
bypass: an enabled value only prints a warning that it has no effect yet, and a
disabled value is silent. Pi's `--approve`/`--no-approve` options decide
whether project-local files are trusted for a run; they do not approve tool
use.

## Included Tools

`Containerfile` builds the image on `docker.io/library/node:22-bookworm-slim`,
pinned by digest, with the toolset shared with the other wrappers: `bash`,
`bubblewrap`, `bzip2`, `ca-certificates`, `coreutils`, `curl`, `diffutils`,
`file`, `findutils`, `gawk`, `git`, `grep`, `jq`, `less`, `nano`, `patch`,
`podman`, `procps`, `python3`, `ripgrep`, `sed`, `tar`, `unzip`, `util-linux`,
`xz-utils` and `zip`. Pi (`@earendil-works/pi-coding-agent` at the version in
`.version`) and OpenSpec (`@fission-ai/openspec@1.16.0`) are installed from npm
at exact versions; npm verifies each package's registry integrity, and the
build fails unless `pi --version` and `openspec --version` report the recorded
versions. The Podman client is part of every image; host socket access stays
the separate `PI_CONTAINER_PODMAN=1` opt-in.

### Image build policy

The script computes a SHA-256 hash of `Containerfile`, `.containerignore`,
`.version`, `network/relay.py` and `network/mux.py`, and stores it as the `build-inputs-hash` label on the built image. The build
context contains only those five files.

- A missing image is built only under exact `PI_CONTAINER_MAINTENANCE=1`.
- A stale image (the label differs from the current inputs) stops the launch
  with a message naming `--container-build`; it is never rebuilt silently.
- `--container-build` always rebuilds from the pinned inputs. Used alone, it
  only rebuilds and exits; guided setup uses this form to build its candidate
  runtime image with the same build arguments and label.
- Debian packages are fetched over verified HTTPS only; image preparation needs
  outbound HTTPS (443) to the Debian, npm and container registries, not port 80.
- With `PI_CONTAINER_TRUST_HOST_CA=1`, the selected bundle is resolved before
  any build, including the build-only refresh, and passed to the build as the
  `build-ca` secret, so the package fetches verify on TLS-intercepting networks.
  It is never stored in a layer and is not a build input, so the
  `build-inputs-hash` label does not depend on it.
- The recipe declares no `WORKDIR`; a future one must be created by an earlier
  build step, so the engine never creates or chowns it at container start.

`PI_PULL_ALWAYS` is ignored with a warning: the base image is pinned by digest.
Weekly CI scans monitor the built image for CVEs.

### File layout

```text
pi-container/
├── Containerfile              # Image definition (pinned inputs)
├── pi-container.sh            # Entry point script (builds & runs)
├── .containerignore            # Build context allowlist
├── .version                    # Single source of truth for Pi version
├── test.sh                     # Disposable image build plus real checks
├── test-wrapper.sh             # Synthetic wrapper entrypoint (Python 3)
├── tests/                      # Fake engine, pin checks, real rootless acceptance
├── docs/validation.md          # Commands, results, and verification limits
├── .github/workflows/ci.yml   # CI pipeline
├── AGENTS.md                   # Repository guidelines
├── SECURITY.md                 # Vulnerability disclosure policy
├── LICENSE                     # MIT license
├── .gitignore
└── README.md                   # This file
```

### Updating pinned image inputs

`.version` records Pi's version; `Containerfile` records `OPENSPEC_VERSION`
and the base image digest. `tests/test_image_pins.py` rejects
floating inputs, `@latest`, version ranges and piped install scripts. To update:

1. Change `.version`, or the recorded version or digest in `Containerfile`.
2. Rebuild explicitly with `pic --container-build --version`.
3. Rerun `./test-wrapper.sh` and `./test.sh`.
4. Record the tested versions with the date in `docs/validation.md`.

Your session history, auth tokens, and settings in `~/.pi/agent/` are preserved
because they live on the host filesystem and are mounted into the container.
After `git pull`, a changed `Containerfile` or `.version` makes the next launch
ask for `--container-build`.

#### What survives a rebuild

| Data | Location | Survives `podman rmi`? |
| --- | --- | --- |
| Session history | `~/.pi/agent/sessions/` (host) | ✅ Yes |
| Auth tokens | `~/.pi/agent/auth.json` (host) | ✅ Yes |
| Settings | `~/.pi/agent/settings.json` (host) | ✅ Yes |
| Extensions | `~/.pi/agent/extensions/` (host) | ✅ Yes |
| Skills | `~/.agents/skills/` (host) | ✅ Yes |
| Global npm packages | inside image | ❌ Reinstalled on rebuild |
| System packages (git, rg) | inside image | ❌ Reinstalled on rebuild |

> **⚠️ Persistence vector:** Because extensions, skills, sessions, auth tokens,
> and settings survive on the host filesystem, a compromised agent could write
> malicious extensions or skills that persist across container rebuilds and even
> execute on host-native `pi` invocations. Use `PI_READONLY_CONFIG=1` when working
> with untrusted content. See [SECURITY.md](./SECURITY.md).

## Troubleshooting

| Symptom | Likely cause | Fix |
| --- | --- | --- |
| `EACCES: permission denied` on a bind | Host permissions or SELinux policy | Inspect host access/policy explicitly; the wrapper does not relabel or weaken confinement |
| `podman: command not found` | Podman not installed | [Install Podman](https://podman.io/docs/installation) |
| Pi hangs on non-interactive use | `-t` flag allocated without TTY | Script now auto-detects TTY and omits `-t` when not available |
| `pi: command not found` | npm install failed | Rebuild: `podman rmi pi-container && ./pi-container.sh --version` |
| `.version` missing or empty | Version file absent | Ensure `.version` contains the Pi version (e.g., `0.79.8`); the wrapper now fails hard if absent |
| Slow first start | apt + npm install during build | One-time cost; subsequent runs use cached image |
| API key not recognized | Empty key forwarded | Script now only forwards keys that are set and non-empty |
| `Image pi-container is stale for the current inputs` | `Containerfile`, `.version`, `network/relay.py` or `network/mux.py` changed | Run `pic --container-build --version` |
| Permission denied on volume | Rootful Podman (sudo) | Run without `sudo` (rootless mode) |
| Read-only config error | `PI_READONLY_CONFIG=1` and Pi needs to write | Disable `PI_READONLY_CONFIG` for tasks that install extensions |
| `npm error ENOENT ... mkdir '~/.npm'` during `pi install` | npm cache dir on the read-only rootfs | Fixed: the wrapper mounts an ephemeral tmpfs at `~/.npm`. Raise the cap with `PI_NPM_CACHE_SIZE=512M` for large extensions |

## Verification

```bash
./test-wrapper.sh                      # synthetic wrapper tests, no engine or credentials
bash tests/run-runtime.sh              # unrestricted real rootless checks
bash tests/run-runtime.sh --wrapper    # wrapper tests in the runner (executable /tmp)
bash tests/run-runtime.sh --shared     # shared sandbox suites from sandbox-container
bash tests/run-runtime.sh --network    # restricted modes with real rootless Podman
bash tests/run-runtime.sh --guard      # guard fixtures (needs the toolchain image)
bash tests/run-runtime.sh --setup      # shared setup tests from sandbox-container
bash tests/run-runtime.sh --setup-runtime  # real setup acceptance, no credentials
./test.sh                              # builds a disposable image, then runs the real checks
```

Further modes: `--qualification`, `--network-feasibility`, `--network-policy`,
`--mux` and `--guard-idle`.

Synthetic and real results, with their limitations, are recorded in
[the validation record](docs/validation.md). See [CONTRIBUTING.md](./CONTRIBUTING.md)
for lint commands.

## Migrating from earlier releases

Earlier names keep working as deprecated aliases. Each prints one warning, and
setting an old and a new name to different values is an error.

| Earlier name | Current name |
| --- | --- |
| `PI_IMAGE_NAME` | `PI_CONTAINER_IMAGE` |
| `PI_ENABLE_PODMAN` | `PI_CONTAINER_PODMAN` |
| `PI_PODMAN_SOCKET` | `PI_CONTAINER_PODMAN_SOCKET` |
| `PI_MEMORY_LIMIT` | `PI_CONTAINER_MEMORY_LIMIT` |
| `PI_CPU_LIMIT` | `PI_CONTAINER_CPU_LIMIT` |
| `PI_PIDS_LIMIT` | `PI_CONTAINER_PIDS_LIMIT` |
| `PI_RUN_TIMEOUT` | `PI_CONTAINER_RUN_TIMEOUT` |
| `PI_ALLOW_UNSAFE_PWD` | `PI_CONTAINER_ALLOW_UNSAFE_WORKSPACE` |
| `PI_MOUNT_GITCONFIG` | `PI_CONTAINER_GITCONFIG` |

Network egress port (`add-network-egress`):

- Every launch needs `PI_CONTAINER_NETWORK`. Set `unrestricted` to keep the
  previous networking.
- `PI_NETWORK` is no longer supported: `PI_NETWORK=none` becomes
  `PI_CONTAINER_NETWORK=offline`; other values become `unrestricted`.
- Image builds, including the first, need `PI_CONTAINER_MAINTENANCE=1`.
- The default image name is `localhost/pi-container`, the same local image.
- An empty `PI_CONTAINER_STATE_DIR` now selects shared state.

Guided setup (`add-container-setup`):

- New users run `bash ./pi-container.sh --container-setup` once and then use
  the managed launcher. A direct launch without `PI_CONTAINER_NETWORK` now
  stops with `setup required:` guidance instead of only naming the variable.
- `--container-build` used alone now rebuilds the image and exits; add Pi
  arguments, such as `--version`, to rebuild and then start a session.
- `PI_CONTAINER_YOLO` accepts only `0`, `1`, `true`, `false`, `yes` or `no`;
  other values fail. Disabled values no longer print a warning.

Bun removal (`remove-bun`):

- The image no longer offers Bun. `PI_ENABLE_BUN` and `PI_BUN_VERSION` have
  no effect and print no warning; projects that need Bun run it outside the
  sandbox.
- The staleness hash changed: rerun `--container-setup`, or
  `pic --container-build --version` for a direct launch.

Behavior changes:

- Budget variables set to an empty value, `max`, zero or a unit such as `4gb`
  now fail instead of falling back to defaults or reaching Podman.
- Only exact `1` overrides the sensitive-workspace refusal; earlier any
  nonempty `PI_ALLOW_UNSAFE_PWD` value did.
- `/tmp` and `/mnt/<letter>` drive roots are now refused like the other
  sensitive directories.
- Sessions start only when the engine applied the budgets; hosts need
  delegated rootless cgroup v2 `cpu`, `memory` and `pids` controllers.
- `~/.gitconfig` is mounted only with `PI_CONTAINER_GITCONFIG=1`.
- Sessions use `HOME=/pi-home`; state is mounted below it from the same host
  directories, and other files written in the home are ephemeral.
- The image is pinned and built once more after upgrading: run
  `pic --container-build --version`. A stale image no longer rebuilds
  automatically.
- `PI_PULL_ALWAYS` is ignored with a warning; image inputs are recorded in
  `Containerfile`.

## Security

See [SECURITY.md](./SECURITY.md) for the vulnerability disclosure policy and
known security considerations.

## License

MIT — see [LICENSE](./LICENSE).

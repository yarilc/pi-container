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

See [docs/setup.md](docs/setup.md). A launch with an unset or empty
`PI_CONTAINER_NETWORK` selects `provider`, the default; without a protected
installation or the provider settings that setup saves, it stops with
`setup required:` guidance before any engine call. Setup is never started
automatically. Offline sessions cannot reach any model provider.

### Direct operator launches

Operators can keep invoking the wrapper directly with an explicit mode:

```bash
# A direct launch from a checkout selects unrestricted networking explicitly
export PI_CONTAINER_NETWORK=unrestricted

# Build the image once, under explicit maintenance authorization, and exit
PI_CONTAINER_MAINTENANCE=1 ./pi-container.sh --container-build

# Use it anywhere, exactly like the `pi` command
cd /path/to/your/project
/path/to/pi-container/pi-container.sh "List the files in this directory"

# Or set up a convenience alias
alias pic='/path/to/pi-container/pi-container.sh'
pic --version
```

Building the image, including the first build, needs exact
`PI_CONTAINER_MAINTENANCE=1`. When `Containerfile`, `.containerignore`,
`network/relay.py`, `network/mux.py` or `.version` changes, the image is
stale: the launch stops until `--container-build` is run again under
maintenance. For restricted networking, see [Network modes](#network-modes).
For running container-based tests through a private session engine (replacing
host Podman delegation), see [Container tests](#container-tests).

## Usage

### Wrapper modes

```bash
pic --container-help                 # no prerequisites
pic --container-setup                # guided setup and managed launcher; alone
pic --container-build --version      # refresh the image, then start Pi
pic --container-build                # refresh the image only, then exit
pic --container-shell -c 'make test' # Bash with the same sandbox; gets its arguments
pic --container-git-worktree         # expose the entire immediate parent
pic --container-toolchain list       # manage the toolchain library; first argument
```

Worktree mode keeps the physical original workdir but exposes siblings in the
immediate parent read/write. No higher ancestor is selected. It requires the
explicit flag and applies the sensitive-directory guard to the exposed parent.
Shell mode passes the remaining arguments to Bash; other modes strip only
wrapper flags. Native `--help` remains Pi's help. `--container-build` without Pi
arguments, also together with `--container-shell` or
`--container-git-worktree`, validates every setting, builds the image and exits
without a session.

### Session lifecycle

Names are reserved atomically through `podman create`, starting above the
highest matching suffix across running and stopped containers (`08` is decimal
8). At most 20 confirmed collisions are retried; existing containers are never
replaced. `CONTAINER_NAME` inside the session matches the reserved name.

Creation uses a private full-ID record, cross-checked with the ID that
`podman create` prints. Attachment preserves stdin and EOF.
Application/attach exit codes, including 125, survive cleanup failures.

A signal starts shutdown at once, also while the container is being created.
TERM/INT/HUP select 143/130/129; the first signal is forwarded once to the
owned container and later signals neither replace it nor restart shutdown.
Shutdown has one 20-second deadline: after forwarding the signal, the wrapper
allows at most 5 seconds for graceful exit, then attempts forced removal. Each
shutdown engine call is bounded by the time left, and local create/attach
clients are terminated and reaped within the deadline. An interrupted creation
is recovered through the CID record, the create output and the session
ownership label, and never starts Pi. Read-only engine queries are bounded by a
timeout; builds and normal sessions are not.

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
- **Custom image name**: `PI_CONTAINER_IMAGE=my-pi pic ...`
- **Rebuild the image**: `PI_CONTAINER_MAINTENANCE=1 pic --container-build`
- **Interactive CLI args**: all arguments pass straight through to Pi — use `--help` to see Pi's full CLI, or `--container-help` for wrapper-specific options
- **Multiple instances**: containers are named `<directory>-0`, `<directory>-1`, etc. Concurrent instances reserve above the highest existing suffix with bounded collision retries.

## Environment variables

### API keys

In `provider` mode the wrapper forwards, by name, only the key of the selected
profile, and `offline` forwards none (see [Provider mode](#provider-mode)).
Unrestricted sessions get a key only when `PI_CONTAINER_ENV_VARS` lists it:

| Variable | Profile |
| --- | --- |
| `ANTHROPIC_API_KEY` | `anthropic-api` |
| `OPENAI_API_KEY` | `openai-api` |
| `GEMINI_API_KEY` | `gemini-api` |
| `OPENROUTER_API_KEY` | `openrouter-api` |

```bash
PI_CONTAINER_NETWORK=unrestricted PI_CONTAINER_ENV_VARS=ANTHROPIC_API_KEY pic
```

> ⚠️ **Security note:** API keys are passed as environment variables. They are
> visible in `podman inspect` output and inside the container's `/proc`.
> For production or shared systems, consider using `podman secret` instead.

### Custom environment variables

Skills, extensions, or other tools may require environment variables that the
wrapper does not hardcode (e.g. `GITHUB_TOKEN`, `DATABASE_URL`, a third-party
API key). Use `PI_CONTAINER_ENV_VARS` to forward arbitrary variables **by name**.

`PI_CONTAINER_ENV_VARS` is a list of variable **names** separated by
whitespace. Each name that is set and non-empty in the host environment is
forwarded to the container via `--env NAME` (by name only, never as
`NAME=value`), so secret values never appear on the process command line.
Podman still stores their values in container inspection metadata. Variables
that are unset or empty are skipped silently; an invalid name stops the launch
before any engine call.

```bash
# Forward two secrets to the container
PI_CONTAINER_ENV_VARS="GITHUB_TOKEN DATABASE_URL" pic "fix the bug"

# With the values exported in the current shell
export GITHUB_TOKEN=ghp_xxx
export DATABASE_URL=postgres://localhost/app
PI_CONTAINER_ENV_VARS="GITHUB_TOKEN DATABASE_URL" pic "review the schema"
```

Names the launcher sets itself (`HOME`, `USER`, `TERM`, `COLORTERM`, `LANG`,
`LC_ALL`, `EDITOR`, `VISUAL`, `PATH`, `CONTAINER_NAME`, `CONTAINER_HOST`,
`CONTAINER_CONNECTION`, the CA variables and `PI_CONTAINER_CONFIG_DIR`) are
skipped with one notice each. Restricted sessions also skip the proxy and CA
variables and Pi's optional-traffic settings; provider sessions skip another
profile's key.

> ⚠️ **Security note:** `PI_CONTAINER_ENV_VARS` only forwards the *names*; the *values*
> come from the host environment and are still visible inside the container's
> `/proc` and in `podman inspect` output (same residual exposure as API keys).
> Do not list variables you do not need, and prefer the narrowest set possible.
> For highly sensitive, long-lived secrets on shared systems, consider
> `podman secret` instead.

### Session environment and proxy support

Every session receives `USER`, `EDITOR=nano`, `VISUAL=nano`, and by name
`TERM`, `COLORTERM`, `LANG` and `LC_ALL` when set; host editor settings are not
kept. In `unrestricted` mode, `HTTP_PROXY`, `HTTPS_PROXY`, `ALL_PROXY`,
`NO_PROXY` and their lowercase forms set on the host are also forwarded by name,
the session runs with `--init` and sees its container name as `CONTAINER_NAME`.
In offline and provider sessions the confined guard plays the role of
`--init`: Ctrl+C and the shutdown signals reach Pi, and the session ends with
Pi's status.
Restricted modes never forward host proxy or CA variables.

### Other variables

| Variable | Purpose |
| --- | --- |
| `PI_CONTAINER_NETWORK` | Network mode: `offline`, `provider` or `unrestricted`; unset or empty selects `provider`. See [Network modes](#network-modes) |
| `PI_CONTAINER_MAINTENANCE` | Exactly `1` authorizes image builds and proxy pulls |
| `PI_CONTAINER_CONFIG_DIR` | Private host directory replacing only `~/.pi`; conflicts with `PI_CONTAINER_STATE_DIR`. Inside the session it is always `/pi-home/.pi` |
| `PI_CONTAINER_TRUST_HOST_CA`, `PI_CONTAINER_CA_BUNDLE` | Opt-in host CA trust; see [Host CA trust](#host-ca-trust) |
| `PI_CONTAINER_IMAGE` | Override the container image name (default: `localhost/pi-container:latest`) |
| `PI_CONTAINER_ENGINE_IMAGE` | Override the session container engine image name (default: `localhost/pi-container-engine:latest`) |
| `PI_CONTAINER_TOOLCHAINS` | `0`, `false` or `no` omits `/toolchains` and disables the session container engine (default: enabled) |
| `PI_CONTAINER_TOOLCHAINS_DIR` | Toolchain library shared by the wrappers (default: `${XDG_DATA_HOME:-~/.local/share}/sandbox-toolchains`) |
| `PI_CONTAINER_STATE_DIR` | Private host directory holding `.pi` and `.agents` instead of `~/.pi` and `~/.agents`; see [Isolated state](#isolated-state) |
| `PI_CONTAINER_MEMORY_LIMIT` | Container memory limit (default: `4g`); see [Session hardening](#session-hardening-budgets-and-lifetime) |
| `PI_CONTAINER_CPU_LIMIT` | Container CPU limit (default: `2`) |
| `PI_CONTAINER_PIDS_LIMIT` | Container PID limit (default: `512`) |
| `PI_NPM_CACHE_SIZE` | Size of the ephemeral npm cache tmpfs at `/pi-home/.npm`, used by `pi install npm:<pkg>` (default: `256M`); from Windows it needs `PI_CONTAINER_ENV_VARS`, see [Windows with Podman machine](#windows-with-podman-machine) |
| `PI_CONTAINER_READONLY_STATE` | `1`, `true` or `yes` (any case) mounts the existing `.pi` and `.agents` read-only (prevents persistence) |
| `PI_CONTAINER_GITCONFIG` | Exactly `1` mounts `~/.gitconfig` read-only from its physical file (default: not mounted). The opt-in fails if `~/.gitconfig` is not a regular file |
| `PI_CONTAINER_YOLO` | Accepted boolean with no effect; see [Permissions](#permissions) |
| `PI_CONTAINER_RUN_TIMEOUT` | Native Podman container lifetime in seconds, placed before the image (0 disables); independent of shutdown budgets |
| `PI_CONTAINER_ENV_VARS` | Extra host variable **names**, separated by whitespace, forwarded by name only, never as `NAME=value`. See [Custom environment variables](#custom-environment-variables) |
| `PI_CONTAINER_ALLOW_UNSAFE_WORKSPACE` | Exactly `1` allows a refused sensitive workspace, with a warning (not recommended) |
| `TERM`, `COLORTERM`, `LANG`, `LC_ALL` | Forwarded by name when set |
| `EDITOR`, `VISUAL` | Always `nano` in the session |

Host Podman delegation was removed: exact `PI_CONTAINER_PODMAN=1` stops every
launch and build-only refresh with migration guidance pointing to image
toolchains ([Container tests](#container-tests)), while other values of
`PI_CONTAINER_PODMAN` and `PI_CONTAINER_PODMAN_SOCKET` are ignored. Earlier
names (`PI_IMAGE_NAME`, `PI_ENABLE_PODMAN`, `PI_PODMAN_SOCKET`,
`PI_MEMORY_LIMIT`, `PI_CPU_LIMIT`, `PI_PIDS_LIMIT`, `PI_RUN_TIMEOUT`,
`PI_ALLOW_UNSAFE_PWD`, `PI_MOUNT_GITCONFIG`, `PI_ENV_VARS`,
`PI_READONLY_CONFIG`, `PI_NETWORK`, `PI_PULL_ALWAYS`, `PI_DEBUG`) and
`--wrapper-help` have no effect and print no notice; use the names above.

## Network modes

An unset or empty `PI_CONTAINER_NETWORK` selects `provider`; without a
protected installation or the provider settings that setup saves, the launch
stops with `setup required:` guidance before any engine call or state change.
Unknown values fail before image operations, and a failed restricted launch
never retries with unrestricted networking.

| Mode | Agent network | Session container engine |
| --- | --- | --- |
| `offline` | Own loopback, pipes and connected socket pairs only; no model provider is reachable | Private engine inside the offline namespace when the library holds images; no host socket |
| `provider` (default) | As offline, plus the exact HTTPS host of one protected provider profile through an external proxy | Private engine inside the provider namespace when the library holds images; no host socket |
| `unrestricted` (explicit only) | Ordinary runtime networking | Private engine inside the session namespace when the library holds images; no host socket |

The restricted implementation is shared with `sandbox-container` and copied
unchanged from its tag `sandbox-ref-36`; see
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

Qualification is bound to the boot, engine, security policy, code (including
`launcher/core.sh` and `agent/launcher.sh`), images, policy, profile, CA trust
and hardening settings, and to the resolved mode, including the provider
default. A
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

Guided setup prepares these; an operator can prepare them by hand under
maintenance authorization:

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

With a Podman machine on Windows, the host is the machine: it must first
import the CAs that Windows trusts
([Trusting a host CA on Windows](#trusting-a-host-ca-on-windows)).

## Toolchains

Sessions can use extra toolchains, such as Java, Go or Python, without host
Podman access, an unrestricted network or a rebuilt image. The operator keeps a
toolchain library on the host. Every session sees it read-only, with `nosuid`
and `nodev`, at `/toolchains`. The library is shared by the Claude, Codex,
OpenCode, Pi and Antigravity wrappers and the reference shell. A toolchain adds
no network, IPC or privilege capability: it runs under the same restrictions as
the rest of the session.

- **Location:** `${XDG_DATA_HOME:-~/.local/share}/sandbox-toolchains`, or
  `PI_CONTAINER_TOOLCHAINS_DIR`. The launcher creates it private (`0700`) when
  it is missing. It must stay outside the workspace, the Pi state
  (`~/.pi` or `PI_CONTAINER_CONFIG_DIR`, `~/.agents`, or
  `PI_CONTAINER_STATE_DIR`, also with `PI_CONTAINER_READONLY_STATE`) and the
  installation. A home directory exposed as the workspace with
  `PI_CONTAINER_ALLOW_UNSAFE_WORKSPACE=1` contains the default library, so that
  launch stops. Move the library with `PI_CONTAINER_TOOLCHAINS_DIR`, or omit it.
- **Disable:** `PI_CONTAINER_TOOLCHAINS=0` (or `false`, `no`) starts a session
  without the mount and without a session container engine.
- **Live updates:** a toolchain added or removed on the host appears in
  running sessions without a restart.

### Managing the library

The operator runs these commands on the host; `--container-toolchain` must be
the first argument:

```bash
pic --container-toolchain add java21            # install or replace a catalog recipe
pic --container-toolchain add ~/recipes/x.json  # install or replace an operator recipe
pic --container-toolchain list                  # installed toolchains, then the catalog
pic --container-toolchain remove java21
pic --container-toolchain verify [java21]       # rerun the checks on the current runtime image
```

An argument without `/` that does not end in `.json` names a recipe of the
release's catalog (see [Recipes](#recipes)); any other argument is a recipe
file. `list` shows the name, version, default flag, size, requirements and
verified base of each installed toolchain, then the catalog recipes that are
not installed.

- **Sources:** a toolchain is a relocatable directory tree, assembled from one
  or more sources: a path inside an OCI image referenced by `@sha256:` digest,
  an HTTPS archive URL with its SHA-256, or a local archive with its SHA-256.
  A toolchain can also, or only, provide container images for the session
  container engine (see [Images](#images)); `list` shows them with the others,
  and `remove` deletes images no other toolchain lists, once no session engine
  runs.
- **Operator recipes:** keep them outside project directories, for example in
  `~/recipes`. A session can write its workspace and state directories, so an
  agent could have written a recipe found there: `add` refuses a recipe file
  inside the directory it runs from (its parent, when setup saved the worktree
  scope) or inside a state directory, before fetching anything. Catalog names
  are not affected, and neither are the local archives that a recipe pins by
  SHA-256.
- **Fetching:** `add` fetches what the recipe names by itself and prints each
  image and URL first. It pulls a missing image and downloads archive URLs
  without `PI_CONTAINER_MAINTENANCE`, because the content is fixed by its
  digest or SHA-256 and no code runs while it is fetched and extracted.
  Downloads use HTTPS only and follow redirects only to HTTPS. They trust the
  host CA bundle that setup saved when host CA trust is enabled, and the system
  trust otherwise, and they use the host's proxy variables. Like image builds,
  pulls and downloads happen on the host, outside runtime filtering. `add`
  never builds an image; image builds still require maintenance.
- **Extraction:** every archive is checked against its SHA-256 before anything
  is extracted, and is extracted from a private copy in the library, so a local
  archive changed afterwards cannot reach the toolchain. Extraction rejects
  absolute paths, `..`, device nodes and links that leave the toolchain, and
  clears setuid and setgid bits. A file that two sources provide fails the
  command.
- **Atomic changes:** changes take a library lock and replace directories
  atomically.
- **Check:** before accepting a toolchain, `add` runs the recipe's `check`
  command in the Pi runtime image (`PI_CONTAINER_IMAGE`), without network and
  with the session's identity and hardening (starting in `/` so no
  working-directory chown occurs). A toolchain that needs a newer C library
  than the image's glibc fails here. The manifest records the base image from
  the installed `Containerfile`.
- **After an update:** when `--container-setup` selects a new release, it
  reruns the check of every installed toolchain verified on another base,
  records the new base when the check passes, and prints any failure without
  blocking setup. Until a toolchain passes `verify` on the new base, it stays
  visible but loses its default environment, and the launcher prints one
  warning naming it. All five wrappers build from the same base, so a toolchain
  verified by another wrapper keeps its default environment here.

### Recipes

A recipe is a JSON file in the shipped release catalog
(`setup/toolchain-catalog/`) or kept and reviewed by the operator outside
writable mounts:

| Key | Meaning |
| --- | --- |
| `schema`, `name`, `version` | `2` (schema `1` with single `source` still supported); `[a-z0-9][a-z0-9._-]*`; free version text |
| `sources` | ordered list of `{"image": "<ref>@sha256:<digest>", "path": "/abs/path"}`, `{"url": "https://...", "sha256": "<hex>", ...}`, or `{"archive": "/abs/file.tar.xz", "sha256": "<hex>", ...}` (with optional `strip_components`, `subpath`, `into`) |
| `images` | container images for the session container engine (see [Images](#images)) |
| `path` | directories relative to the toolchain, added to `PATH` (default `["bin"]` when `sources` are present) |
| `env` | variables: `{"toolchain": "<relative path>"}` or `{"value": "<literal>"}` |
| `requires` | other toolchains whose environment is loaded first |
| `notes` | short instructions shown to the agent in `toolchains.md` |
| `check` | command run in the runtime image before the toolchain is accepted |
| `default` | `true` adds the toolchain to new sessions' environment (`false` required for image-only recipes) |

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
  harmless native-library warning. `/run` is not writable by the session
  user. With `PI_CONTAINER_READONLY_STATE`, `~/.pi` and `~/.agents` are
  read-only too.
- **Dependency downloads** (Maven, npm, pip, Cargo, Go modules) need network
  access that provider and offline modes do not grant. Provide dependencies in
  the workspace, or use an unrestricted session.

#### Images

A recipe can also list container images. Sessions started while the library
holds at least one image get a private container engine that runs them
([Container tests](#container-tests)). Each image is one of:

| Image | Form |
| --- | --- |
| Registry image | `"<ref>@sha256:<digest>"`; a reference without a digest is refused |
| Local image | `{"local": "sha256:<full image ID>", "name": "localhost/<name>[:tag]"}` |

```json
{"schema": 2, "name": "postgres16", "version": "16.4", "default": false,
 "images": ["docker.io/library/postgres@sha256:<digest>"],
 "check": ["podman", "run", "--rm", "--network=none", "docker.io/library/postgres@sha256:<digest>", "postgres", "--version"]}
```

- **Store:** `add` keeps the images in the library's image store, `.images`,
  through a helper container of the engine image (`localhost/pi-container-engine:latest`).
  Registry images are pulled on the host, with host CA trust when setup enabled
  it, and keep both their index and platform digests. A local image is copied
  from the host engine by its full ID (`podman image inspect --format '{{.Id}}' <image>`)
  and named as the recipe says; `add` fails if the host engine has no image with
  that ID. An image several toolchains list is stored once.
- **Image-only recipes** have no `sources`, `path` or `env`, and `default` must
  be `false`; `toolchains.md` lists their images with a `podman run` example.
- **Check:** for a recipe with images, `check` runs in the runtime image against
  a temporary engine like a session's, without network, so a check that runs
  the image proves it runs offline.
- **Live updates:** an image added while sessions run is usable by their engines
  at once. Removing an image, or replacing a toolchain with one that drops an
  image, waits until no session engine runs: the command fails and names the
  running sessions.
- **Catalog recipes** never list local images.
- **Cleanup:** image layers in `.images` can belong to your subordinate IDs, as in
  any rootless Podman storage. Remove image toolchains with `remove`, which
  deletes their layers through the helper; deleting the directory directly needs
  `podman unshare rm -rf`.

The shipped catalog recipes (`setup/toolchain-catalog/`) pin these versions and
sources:

| Name | Version | Source | Default | Notes |
| --- | --- | --- | --- | --- |
| `java21` | Temurin 21.0.13 | image `eclipse-temurin@sha256:0a3f3298…`, `/opt/java/openjdk` | yes | `JAVA_HOME` |
| `maven3.9` | 3.9.16 | image `maven@sha256:99e61abc…`, `/usr/share/maven` | yes | requires `java21`; local repository in `/tmp/m2`; harmless jansi warning |
| `go` | 1.27.4 | image `golang@sha256:4fa7c968…`, `/usr/local/go` | yes | `GOTOOLCHAIN=local`; caches in `/tmp`; `go test` needs `GOTMPDIR` in the workspace |
| `node24` | 24.22.3 | archive `node-v24.22.3-linux-x64.tar.xz` from `nodejs.org` | no | the image's Node.js 22 stays first |
| `python3.13` | 3.13.18 | python-build-standalone `20261110` `install_only` archive from GitHub | no | the image's `python3` stays first; virtual environments in the workspace |
| `rust` | 1.100.0 | `rustc`, `cargo` and `rust-std` (host and `x86_64-unknown-linux-musl`) archives from `static.rust-lang.org` | yes | target `x86_64-unknown-linux-musl` linked by `rust-lld`; crates with build scripts or procedural macros fail |

### Telling the agent

The wrapper never edits `AGENTS.md` or other instruction files. The library
contains a generated `/toolchains/toolchains.md` with the usage rules and every
installed toolchain (including image references and `podman run` examples), plus
a machine-readable `/toolchains/index.json`. Add one line to the project's
`AGENTS.md`, or to `~/.pi/agent/AGENTS.md`:

```markdown
Read /toolchains/toolchains.md before using or looking for build tools.
```

The agent then runs a toolchain in one command with
`. /toolchains/<name>/env.sh && <command>`. This form also works for
toolchains added after the session started.

SELinux and AppArmor enforcement were not tested with the library mount. On
hosts that enforce them, profile the tools you add.

## Container tests

Sessions never receive the host Podman API. When the toolchain library holds at
least one image toolchain, every session instead gets a private, rootless
Podman engine of its own (`localhost/pi-container-engine:latest`), in every
network mode. The engine shares the session's network namespace, so its
containers have the session's egress: an offline session's containers reach
nothing outside, and a provider session's containers reach only what the proxy
policy allows. The session reaches its engine at
`CONTAINER_HOST=tcp://127.0.0.1:2375`, also given as `DOCKER_HOST` for
Docker-API clients such as Testcontainers. The engine runs the library's images
offline by their pinned references, mounts only the workspace (at the same
path) and the library's read-only image store, holds no secrets, and is removed
with its storage when the session ends. Without images in the library, or with
`PI_CONTAINER_TOOLCHAINS=0`, there is no engine and `CONTAINER_HOST` and
`DOCKER_HOST` are absent from the session, including image or engine defaults.

```bash
pic --container-toolchain add ~/recipes/postgres16.json   # see Images
pic --container-shell -c 'podman run --rm --network=none docker.io/library/postgres@sha256:<digest> postgres --version'
```

- **Engine image preparation:** guided setup builds the engine image from
  `launcher/engine/Containerfile` and writes the derived seccomp profile to
  `launcher/engine/seccomp.json` in the release. For direct checkout runs,
  prepare the engine image under maintenance:
  `podman build --pull=never --tag localhost/pi-container-engine:latest launcher/engine`.
- **Images:** add them as toolchains ([Images](#images)). In offline and
  provider sessions the engine pulls nothing; in unrestricted sessions it can
  also pull, and pulled or built images stay in the session's storage. An image
  added during a session is usable at once; the first image needs a new
  session, because a session without library images starts without an engine.
- **Workspace:** a container that bind-mounts a path inside the workspace sees
  the workspace files, and files its root creates there belong to you. Any
  other path a nested container mounts is the engine's own file system, never
  the host's.
- **Isolation:** each nested container has its own process view and host name
  (its container ID). Two sessions have separate engines and never see each
  other's containers.
- **Lifetime:** the launcher starts the engine before Pi, waits until it
  answers as a rootless engine, and removes it with its storage when the
  session ends, also after a signal. A later launch removes the engine of a
  launch that was killed.
- **Budgets:** the engine gets the session's memory, CPU and process budgets,
  checked like the agent's; together the session can therefore use twice the
  agent's budget, and the launch says so. On the process rlimit fallback the
  engine's first process sets the limit before anything else, and the launch
  reads it from that process before the session starts; the engine and
  everything it runs share that one limit. Explicit `--memory` or
  `--pids-limit` limits on nested containers apply for every cgroup controller
  the engine has (see **Systemd containers and nested limits** below); a limit
  that needs a controller the engine lacks fails, and the container does not
  start.
- **Hardening exceptions:** the engine container is the one container that
  relaxes the standard policy, only as nested rootless containers and image
  operations need: `SETUID` and `SETGID` for the user-namespace helpers and
  `SYS_CHROOT` for layer extraction and builds (with no-new-privileges kept
  on), the FUSE and TUN devices, an unmasked procfs, SELinux labelling
  disabled, a seccomp profile derived from the host's default that also allows
  `sethostname` and `setdomainname`, and a startup step that delegates the
  engine's own cgroup subtree. That step is the engine's first process: it
  starts as the root of the engine's user namespace (never you) with `CHOWN` as
  well, hands the subtree to the unprivileged `podman` user, and then runs
  everything else as that user. Afterwards no engine process runs as root, and
  `CHOWN` stays only in the bounding set, where no-new-privileges keeps it
  unreachable. The engine user is mapped to you (`--userns=keep-id:uid=1000,gid=1000`),
  which needs 65535 subordinate IDs in one contiguous range. The engine image
  declares these four capabilities (`SETUID`, `SETGID`, `SYS_CHROOT` and
  `CHOWN`) in its `io.containers.capabilities` label, so Podman starts the
  engine without a capability error. A tool that needs more privilege is
  unsupported.
- **Systemd containers and nested limits:** on an eligible engine, nested
  containers get cgroups of their own, so an image that starts systemd runs it
  as PID 1:

  ```bash
  # an image toolchain whose image starts /sbin/init, such as a Rocky Linux 9 init image
  podman run --detach --name target --systemd=always docker.io/rockylinux/rockylinux@sha256:<digest>
  podman exec target timeout 120 sh -c 'until systemctl is-system-running | grep -qE "^(running|degraded)$"; do sleep 1; done'
  podman exec target systemd-run --unit=probe --property=Type=oneshot /bin/true
  ```

  An engine is eligible when its cgroup namespace is private and its cgroup v2
  root is mounted read-write with `nsdelegate` and belongs to the root of its
  user namespace. This holds for native Linux with the `systemd` cgroup manager
  and for the Windows Podman machine (`cgroupfs`); no host change is needed.
  Explicit nested limits apply for each controller the engine has: `memory` and
  `pids` where the rootless engine delegates them (native Linux with `systemd`);
  the Windows Podman machine delegates none, so explicit nested limits fail
  there and systemd resource-control unit settings (such as `MemoryMax=` or
  `TasksMax=`) have no effect. The engine's own limit files, and so the session
  budgets, stay unwritable from the engine and from nested containers. When an
  engine is ineligible (for example on a host with cgroup v1), the launch
  announces `systemd containers and explicit limits for nested containers are
  unavailable` with the reason, and the session starts without them. Systemd
  containers and cgroup delegation are untested under enforcing SELinux or
  active AppArmor profiles.
- **Host `/sys` in the session:** the session joins the engine's network
  namespace, and a rootless container that joins another namespace cannot mount
  a sysfs of its own: Podman bind-mounts the host's `/sys` read-only instead. A
  session with an engine therefore sees the host's network interfaces in
  `/sys/class/net` (names, MAC addresses, link state and counters), while its
  network namespace still has only loopback, as `/proc/net/dev` shows.

Migration: host Podman delegation (`PI_CONTAINER_PODMAN=1`, with
`PI_CONTAINER_PODMAN_SOCKET`) was removed. Exact `PI_CONTAINER_PODMAN=1` stops
every launch with migration guidance, other values are ignored, and
`--container-setup` drops saved delegation settings. Add the images your tests
need as toolchains ([Images](#images)); the next session has its engine.

## Windows with Podman machine

On Windows, `pi-container.ps1` starts the sandbox from PowerShell on the
rootless engine of a Podman machine that Podman Desktop created with the WSL
provider. The session runs inside the machine's WSL distribution
(`podman-machine-default`, user `user`), in the PID and mount namespaces where
the machine runs systemd and its Podman service, as the machine's own login
shells do. The entry uses neither `podman.exe` nor the machine's SSH or
Windows API connection, so it works while other WSL distributions, such as
Ubuntu, are running.

Prerequisites:

- Windows PowerShell 5.1 or PowerShell 7, with a policy that allows local
  scripts, for example `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned`;
- a rootless Podman machine with the WSL provider, created with Podman
  Desktop, and started by Podman (Podman Desktop or `podman machine start`)
  before setup and sessions;
- `sudo` without a password for the machine's user, which Podman machines
  provide: sessions and setup enter the machine's systemd namespaces with
  `sudo nsenter`, as its login shells do (`/usr/local/bin/enterns`);
- a checkout of this repository in a folder on a Windows drive, with LF line
  endings. The repository's `.gitattributes` keeps them LF even with
  `core.autocrlf=true`; [docs/setup.md](docs/setup.md) explains how to fix an
  older CRLF checkout.

Run setup once from the checkout, in an interactive PowerShell window:

```powershell
cd C:\Work\pi-container
.\pi-container.ps1 --container-setup
```

Setup runs the guided setup inside the machine distribution. The release,
preferences and images are installed there, in `~/.local/lib/pi-container`.
Its output leaves out the Linux shell guidance; the entry prints how to start
sessions. Setup finds the machine's own Podman service, so it offers provider
networking, the default, with the four API key methods, and offline and
unrestricted networking, as on Linux.

Every method uses an API key. Set `$env:ANTHROPIC_API_KEY = '...'` in
PowerShell before `pi-container.ps1`, or `OPENAI_API_KEY`, `GEMINI_API_KEY` or
`OPENROUTER_API_KEY` for the `openai`, `gemini` and `openrouter` methods; setup
names the variable of the method it saved. The entry forwards the key by name,
and setup stores none. Pi's state stays in the machine user's `~/.pi` and
`~/.agents` in shared state mode, separate from Pi on Windows. Rerun setup
after updating the checkout, and after the machine is recreated. To run the
sandbox as a command without keeping the checkout, install it instead
([Install as a command](#install-as-a-command)).

Start sessions from a project directory on a Windows drive:

```powershell
cd C:\Work\my-project
C:\Work\pi-container\pi-container.ps1
C:\Work\pi-container\pi-container.ps1 --container-shell -c 'git status'
C:\Work\pi-container\pi-container.ps1 --container-help
```

The project is mounted at its drive path, for example `/mnt/c/Work/my-project`.
A launch is refused before any engine query in these cases:

- the machine is stopped: the entry does not start its distribution, because
  `wsl.exe` would start it without the user's runtime directory
  `/run/user/<uid>`, where no `podman` command works. Start the machine with
  Podman Desktop or `podman machine start`;
- the distribution runs without that directory, because `wsl.exe` alone
  started it. Run `wsl --terminate podman-machine-default`, then start the
  machine with Podman. Setup refuses both states too;
- `sudo` asks the machine's user for a password, so the entry cannot enter the
  machine's systemd namespaces. Setup refuses it too;
- the location is a network share, a path inside a WSL distribution, a drive
  the distribution does not mount, or not a file system path;
- the project or the worktree parent contains the checkout, or lies inside it;
- the project is a Windows system or profile folder (see
  [Session hardening, budgets and lifetime](#session-hardening-budgets-and-lifetime)).

The exit status, the terminal and Ctrl+C work as on Linux. Closing the window
also ends the session and removes its container. The machine's engine uses
the `cgroupfs` manager: the memory and CPU budgets are not enforced, and the
process budget uses the process rlimit, as the launch notices state (see
[Session hardening, budgets and lifetime](#session-hardening-budgets-and-lifetime)).

| Variable | Meaning |
| --- | --- |
| `PI_CONTAINER_NETWORK` | `provider`, `offline` or `unrestricted` for one launch (default: the mode setup saved); a restricted mode needs a setup that prepared it |
| `PI_CONTAINER_WSL_DISTRO` | WSL distribution (default `podman-machine-default`) |
| `PI_CONTAINER_WSL_USER` | user in the distribution (default `user`) |
| `PI_CONTAINER_WSL_INSTALLATION` | absolute installation path in the distribution, when setup used another one |

Set them with `$env:NAME = 'value'`. The entry forwards to the launcher in the
distribution, by name, the other `PI_CONTAINER_*` variables whose names use
only letters, digits and `_`, the four method keys `ANTHROPIC_API_KEY`,
`OPENAI_API_KEY`, `GEMINI_API_KEY` and `OPENROUTER_API_KEY`, and the names
listed in `PI_CONTAINER_ENV_VARS`. `PI_CONTAINER_CONFIG_DIR` is forwarded only
when it holds a distribution path (starting with `/`): a Windows path is
skipped with a notice, and the directory saved by setup applies. It forwards
no other Windows variable, so `PI_NPM_CACHE_SIZE` applies from Windows only
when `PI_CONTAINER_ENV_VARS` lists it, for example
`$env:PI_CONTAINER_ENV_VARS = 'PI_NPM_CACHE_SIZE'`; the listed name also
reaches the session, as on Linux. Path values, such as
`PI_CONTAINER_STATE_DIR`, are distribution paths, such as `/home/user/...`.
`PI_CONTAINER_GITCONFIG=1` mounts the machine user's `~/.gitconfig`, not the
one on Windows.

Limits on Windows:

- No host Podman delegation, as on Linux: `PI_CONTAINER_PODMAN=1` is refused
  with migration guidance, and a release whose setup saved delegation asks to
  rerun setup from Windows. Sessions with image toolchains get their private
  container engine in the machine ([Container tests](#container-tests)).
- PowerShell pipeline input, such as
  `'x' | .\pi-container.ps1 --container-shell -c cat`, is refused, because
  PowerShell alters it. Redirect a file from `cmd.exe` instead:
  `cmd /c "powershell -File C:\Work\pi-container\pi-container.ps1 --container-shell -c cat < input.txt"`.
- PowerShell parses the arguments first. Quote a `--` meant for Pi or Bash
  (`'--'`), values with commas (`'a,b'`), numbers whose spelling matters
  (`'007'`) and arguments of the form `-x:y`. The encoded arguments are
  limited to 32766 characters.
- A variable with an empty value counts as unset.
- `podman machine stop` (`wsl --terminate`) ends running sessions.
- After the machine starts, the folder of its first session may stay in use
  by a WSL process until `wsl --shutdown`, so Windows cannot delete that
  folder meanwhile.
- Projects on a Windows drive go through drvfs, which is slow on large trees.
  Git for Windows clones with `core.autocrlf=true` look modified to Git in the
  session: set `core.autocrlf=false` for the project, or give it a
  `.gitattributes`.
- Bitdefender's Advanced Threat Control (`Atc4.Detection`) has blocked the
  operator validation script `tools/windows-validate.ps1` of
  `sandbox-container`, and quarantined files while validation bundles were
  extracted with `tar`, for example `tests/fixtures/shell-agent/launcher.sh`,
  which only the Linux tests use. Setup, the installer and sessions ran with it
  active, and another Windows system with other antivirus products ran the
  validation without problems. Run the validation script with the checkout
  folder excluded, or with the protection paused for the run, as your
  administrator allows. Setup and the entry fail when a file they need is
  missing: restore it from the quarantine, and report the false positive to
  the vendor.

### Trusting a host CA on Windows

Setup and sessions run in the machine, so host CA trust uses a bundle of the
machine, not the Windows certificate store. On a network that intercepts TLS
(a corporate proxy that re-signs certificates), the machine trusts the
interception CA only when Podman imports the Windows store into it. Without
it, image pulls and builds in the machine and HTTPS requests in sessions fail
with a certificate verification error. With Podman 6.0 or later, enable the
import once. `podman machine set` fails while the machine runs, so stop it
first:

```powershell
podman machine stop
podman machine set --import-native-ca
podman machine start
```

The import happens at every machine start: Podman copies the CAs that Windows
trusts into the machine and runs `update-ca-trust`, so the machine's system
bundle contains them. Restart the machine after Windows gains a new CA.

Then run setup and answer yes to "Trust a host CA bundle?". Keep the bundle
setup proposes, the machine's system bundle (see
[Host CA trust](#host-ca-trust)): setup passes it to the image builds and saves
it for sessions. Rerun setup after the machine is recreated, and enable the
import again on the new machine.

### Toolchains on Windows

The [toolchain](#toolchains) commands run from PowerShell like the other
options, from any directory outside the checkout:

```powershell
pi-container --container-toolchain add java21
pi-container --container-toolchain add C:\Users\me\recipes\x.json
pi-container --container-toolchain list
```

- **Location:** the library lives inside the Podman machine's distribution, in
  `~/.local/share/sandbox-toolchains` of the machine user, or in
  `PI_CONTAINER_TOOLCHAINS_DIR` (a distribution path). Every wrapper that runs
  in the machine shares it. Recreating the machine removes it: after the new
  setup, add the toolchains again.
- **Windows paths:** a recipe path or a local archive path in a recipe written
  as a Windows drive path (`C:\...` or `C:/...`) is translated to its drive
  mount in the machine. Network shares, paths inside a WSL distribution and
  drives that the distribution does not mount are refused. Keep your recipes
  outside project folders (see [Managing the library](#managing-the-library)).
- **Network:** pulls and downloads run inside the machine. On a network that
  re-signs TLS, they trust the CA that `podman machine set --import-native-ca`
  adds to the machine (see [Trusting a host CA on Windows](#trusting-a-host-ca-on-windows)).

### Install as a command

Instead of setup from the checkout, you can install the entry for your
Windows account:

```powershell
cd C:\Work\pi-container
.\pi-container.ps1 --container-install
```

The install copies the entry, the Windows scripts and every file that setup
needs into `%LOCALAPPDATA%\Programs\pi-container`. It then adds that
folder to your user `PATH` (`HKCU\Environment`, no administrator rights; the
other entries and their `%VAR%` references stay as they are) and runs setup
from the copy. The installer announces the `PATH` change before making it;
nothing is written to the PowerShell profile or system-wide. Afterwards the
checkout can be deleted, and a new PowerShell window runs the command from any
project directory:

```powershell
cd C:\Work\my-project
pi-container
pi-container --container-shell -c 'git status'
pi-container --container-setup
```

New PowerShell windows and new Windows Terminal tabs find the command; the
window or tab that ran the install may not. When setup fails after the copy,
the copy and the `PATH` entry stay; finish with
`pi-container --container-setup`.

To update, run `--container-install` again from a newer checkout or download.
It replaces the installed files, removes the ones the new version no longer
has, and runs setup. Do not update while a setup runs from the installed
copy. The installed command refuses to install itself. An
interrupted install leaves the copy marked incomplete: the command then
refuses to start sessions until the next install completes. Two installs never
run at once.

`pi-container --container-uninstall` (also from a checkout) removes the
`PATH` entry and the installed copy. The installation inside the Podman machine
stays until the machine is reset. A folder still used by a WSL process is
reported; `wsl --shutdown` releases it.

The scripts are not signed. The installer writes new local files, so the
installed command runs under the default `RemoteSigned` policy. A downloaded
zip keeps the Mark of the Web on its files: run its first install as
`powershell -ExecutionPolicy Bypass -File .\pi-container.ps1 --container-install`,
or `Unblock-File` its files first. Running the installer is your decision to
trust that source. Policies stricter than `RemoteSigned`, such as `AllSigned`,
are unsupported.

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
are supported. Named connections, TCP/SSH (including the Podman machine
connection that `podman.exe` uses), implicit remote contexts, and Unix paths
consisting only of slashes are rejected. On Windows, the PowerShell entry runs
the sandbox inside the Podman machine instead; see
[Windows with Podman machine](#windows-with-podman-machine). `PI_ALLOW_ROOTFUL`
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

Sessions use `HOME=/pi-home`, an ephemeral 512 MiB noexec tmpfs. Your `~/.pi`
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
- With `PI_CONTAINER_READONLY_STATE=1`, its `.pi` and `.agents` must already
  exist and are mounted read-only below an ephemeral home.

The value must be absolute, without colon, CR or LF, and conflicts with a
nonempty `PI_CONTAINER_CONFIG_DIR`. The directory must not equal, contain or
lie inside the workspace. Every child the launcher uses below it, and the CA
mount parent, must stay inside it and be private. The npm cache tmpfs is
mounted at `/pi-home/.npm` also over an isolated home. No credentials are
copied; authenticate again inside an isolated state.

### Volume mounts

| Mount point | Purpose | Read-only mode |
| --- | --- | --- |
| `/pi-home/.pi` ← `~/.pi` | Pi configuration, auth, sessions, extensions | `PI_CONTAINER_READONLY_STATE=1` |
| `/pi-home/.agents` ← `~/.agents` | Skills (prompt libraries) | `PI_CONTAINER_READONLY_STATE=1` |
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
Only exact `PI_CONTAINER_GITCONFIG=1` mounts it, from its physical file; the
opt-in stops before any engine call when `~/.gitconfig` is not a regular file or
its physical path contains a colon, CR or LF. Alternatives to mounting it: set
the identity in the repository (`git config user.name ...`), or forward
`GIT_AUTHOR_NAME`, `GIT_AUTHOR_EMAIL`, `GIT_COMMITTER_NAME` and
`GIT_COMMITTER_EMAIL` by name with `PI_CONTAINER_ENV_VARS`.

Temporary storage is declared explicitly. `/tmp` and `/var/tmp` are each
512 MiB with mode 1777, `/run` is 32 MiB and not writable by the session user,
the shared-state home is 512 MiB with mode 1777, and `~/.npm` defaults to
256 MiB (`PI_NPM_CACHE_SIZE`, a size with unit `k`, `m` or `g`, overrides it;
an invalid size stops the launch before any engine call). All are
rw,nosuid,nodev,noexec; the npm cache uses mode 0700 and your UID/GID.
Private tmpfs ownership uses Podman `U`; host binds never use recursive
ownership changes. Every temporary store disappears with the session.

> **Security note:** `~/.pi` and `~/.agents` are mounted **read-write by default**.
> A compromised agent could plant malicious extensions that persist across runs.
> Set `PI_CONTAINER_READONLY_STATE=1` when working with untrusted prompts or projects.
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
| Identity / capabilities | Caller UID/GID, keep-id, `--cap-drop=all`, no additions |
| Root filesystem | Read-only; explicit bounded `/tmp`, `/var/tmp`, `/run`, and npm cache; the engine's `/dev` and `devpts`, and an empty read-only `/dev/shm`; an empty read-only `/run/secrets` mask |
| Privilege escalation | `--security-opt=no-new-privileges` |
| Resource limits | 4 GiB memory, 2 CPUs, 512 processes (configurable), validated, each enforced when its cgroup controller is delegated, and checked after create |
| SELinux | Host labels and confinement remain unchanged |
| Sensitive workspace guard | Refuses `/`, system directories, `/tmp`, `$HOME` and `/mnt/<letter>` on physical paths (override: exact `PI_CONTAINER_ALLOW_UNSAFE_WORKSPACE=1`) |
| Rootless enforcement | Verified Linux rootless engine before image operations; no override |
| Signal handling | Owned full-ID lifecycle; shutdown within one 20-second deadline; `--init` for reaping in unrestricted sessions |
| Image build policy | Pinned inputs; a stale content hash stops the launch until `--container-build` |
| Conditional TTY | Only when stdin and stdout are terminals |
| Container naming | Sanitized `<dir>-<N>`, max existing suffix+1 including stopped containers; atomic create, at most 20 attempts |

> **Unrestricted networking has no egress limit.** An autonomous agent with
> network access and read access to mounted volumes (including
> `~/.pi/agent/auth.json`) could exfiltrate data if subverted by prompt
> injection. The default `provider` mode limits egress to one exact provider
> profile, and `offline` removes it.
> See [SECURITY.md](./SECURITY.md).
>
> **Config directories (`~/.pi`, `~/.agents`) are writable by default.**
> A compromised agent could plant persistent extensions or skills. Use
> `PI_CONTAINER_READONLY_STATE=1` to mount them read-only for untrusted tasks.
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
for their 128-process and 256 MiB limits. After creating the container the
wrapper inspects it and starts it only when every enforced budget equals its
selected value and no unenforced budget is present; otherwise it removes its own
container and names the reported controllers. Restricted qualification records
the enforced set, so a change in delegation requires requalification. Budgets
and tmpfs sizes do not limit workspace or state storage growth.

A rootless engine applies cgroup limits only through the `systemd` cgroup
manager (`podman info --format '{{.Host.CgroupManager}}'`). With `cgroupfs`,
for example on a Podman machine on WSL, the engine reports every controller but
ignores the limits. The sandbox therefore treats no controller as delegated: it
prints `agent memory budget not enforced: the rootless engine uses the cgroupfs
cgroup manager, which applies no cgroup limits` and the matching CPU line, and
the process budget uses the fallback below.

The process budget has a fallback. Without the `pids` controller, the agent
container's first process sets its soft and hard process rlimit to the
selected budget, and the notice reads `agent process budget enforced through the
process rlimit (512 tasks of the session user, threads included)`:

- **Where it is set.** The container starts with a fixed `/bin/sh` step,
  `{ ulimit -u N 2>/dev/null || ulimit -p N; } && exec <program>`, before Pi,
  the shell or, in restricted modes, the guard runs (dash names the limit `-p`).
  If the limit cannot be set, the container stops before anything else runs,
  and each launch checks that the created container starts with this step.
- **Per session.** Linux 5.14 and later count the limit per user namespace, and
  the step sets it inside the container's own. The wrapper never uses
  `--ulimit nproc`: the engine applies that limit before it creates the
  container's user namespace, and the kernel then checks every fork against
  the processes of all your containers together.
- **Not raisable.** The session cannot raise the limit, because it has no
  capabilities. Its own shell and init process count against it, so slightly
  fewer than `N` processes are left for commands.
- **Availability.** The fallback applies only when the engine reports kernel
  5.14 or later (`podman info --format '{{.Host.Kernel}}'`). Older or
  unrecognized kernels may count every process of your user, so the process
  budget then stays unenforced, and the notice names the reason. The memory and
  CPU budgets have no fallback. The provider proxy's and session engine's
  process budgets use the same fallback. Which mechanism enforces each process
  budget is part of the restricted qualification identity, and each launch
  checks the created container's startup step and absence of an engine-applied
  process rlimit.

Risk: without the memory or process budget, a session can exhaust host memory
or processes for your user; without a CPU budget it can saturate every CPU.
Delegating the controllers (for example a systemd
`Delegate=cpu cpuset io memory pids` drop-in for `user@.service`) restores full
enforcement, but the sandbox never requires it.

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
Descendants such as `/mnt/d/project` are allowed.

On a WSL drive mount, it also must not be one of these Windows folders, in any
letter case, because drvfs ignores case:

- `/mnt/<drive>/Users`;
- a profile, `/mnt/<drive>/Users/<name>`, its `Documents`, its `OneDrive`
  (also `OneDrive - <organization>`) or `OneDrive/Documents`, which hold the
  PowerShell profile and modules;
- anything inside the profile's `AppData`, which holds the startup folder;
- `/mnt/<drive>/Windows`;
- `/mnt/<drive>/Program Files` or `/mnt/<drive>/Program Files (x86)`;
- `/mnt/<drive>/ProgramData`.

Apart from `AppData`, only these exact folders are refused. A project below
them, such as `/mnt/c/Users/me/projects/app` or
`/mnt/c/Users/me/Documents/GitHub/app`, is accepted. In worktree mode, however, a
project placed directly in a profile is refused, because its parent is the
profile.

Exact `PI_CONTAINER_ALLOW_UNSAFE_WORKSPACE=1` permits a refused directory with a
warning; it relaxes no other check.

No session receives a host Podman socket. A session's private container engine
mounts only the workspace and the library's read-only image store, so its
containers stay inside the project-only filesystem boundary and the session's
network boundary ([Container tests](#container-tests)).

### Permissions

Pi 1.5.2 runs its tools (read, bash, edit, write and extension tools) without
approval prompts, so the container is the only boundary around Pi's tools.
`PI_CONTAINER_YOLO` is accepted like the other wrappers' permission-bypass
switch (`0`, `1`, `true`, `false`, `yes` or `no`; other values fail) so that
setup and the managed launcher can save it. Pi has no approval layer to
bypass: an enabled value only prints a notice that it has no effect, a
disabled value is silent, and neither changes the engine arguments. Shell mode
and the qualification probe ignore it. Pi's `--approve`/`--no-approve` options decide
whether project-local files are trusted for a run; they do not approve tool
use.

In print mode, the default `ask` setting skips protected project resources
without a saved trust decision. Pass `--approve` to load them for one run,
including project `.agents/skills`. Use `/trust` in the interactive UI to save
a decision under `~/.pi/agent/trust.json`.

Pi's `mcp` command and opt-in `codemode` tool run inside the container. MCP
clients use the selected network profile. The MCP OAuth callback listener can
bind on the container's private loopback.

## Included Tools

`Containerfile` builds the image on `docker.io/library/node:22-bookworm-slim`,
pinned by digest, with the toolset shared with the other wrappers: `bash`,
`bubblewrap`, `bzip2`, `ca-certificates`, `coreutils`, `curl`, `diffutils`,
`file`, `findutils`, `gawk`, `git`, `grep`, `jq`, `less`, `nano`, `patch`,
`podman`, `procps`, `python3`, `ripgrep`, `sed`, `tar`, `unzip`, `util-linux`,
`xz-utils` and `zip`. Pi (`@earendil-works/pi-coding-agent` at the version in
`.version`) and OpenSpec (`@fission-ai/openspec@2.0.0`) are installed from npm
at exact versions; npm verifies each package's registry integrity, and the
build fails unless `pi --version` and `openspec --version` report the recorded
versions. The Podman client is part of every image so sessions can talk to
their private container engine when image toolchains are installed
([Container tests](#container-tests)); host Podman socket delegation was
removed.

OpenSpec 2.0.0 uses the project's `.agents/skills` directory. In Pi, trust the
project to use commands such as `/skill:openspec-propose`.

Pi 1.x renamed `azure-openai-responses` to `azure` and changed extension APIs.
The standard profiles cover Anthropic, OpenAI, Gemini and OpenRouter. Review
the upstream changelog before reusing custom providers or old extensions.
[Pi 1.5.2 changelog](https://github.com/earendil-works/pi/blob/v1.5.2/packages/coding-agent/CHANGELOG.md)

### Image build policy

The launcher core computes a SHA-256 hash over `Containerfile`,
`.containerignore`, `network/relay.py`, `network/mux.py` and `.version`, and
stores it as the `build-inputs-hash` label on the built image. The build
context contains only those five files. Pi's agent part passes the first line
of `.version` as `PI_VERSION` to every build; a launch stops before any image
operation when `.version` is missing or empty. A build pulls the exact `FROM`
base first, then runs with `--pull=never` and the docker format, without a
timeout.

- A missing image is built only under exact `PI_CONTAINER_MAINTENANCE=1`.
- A stale image (the label differs from the current inputs) stops the launch
  with a message naming `--container-build`; it is never rebuilt silently.
- `--container-build` always rebuilds from the pinned inputs, keeping the
  layer cache. Used without Pi arguments, it validates every launch setting,
  rebuilds and exits; guided setup uses this form to build its candidate
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

The base image is pinned by digest. Weekly CI scans monitor the built image for
CVEs.

### File layout

```text
pi-container/
├── Containerfile              # Image definition (pinned inputs)
├── pi-container.sh            # Thin entry script shared by every wrapper
├── pi-container.ps1           # Windows PowerShell entry for Podman machine
├── launcher/core.sh           # Shared launcher core (from sandbox-container)
├── launcher/engine/           # Shared session container engine image and entry
├── launcher/windows/          # Shared Windows Podman machine helpers
├── setup/                     # Guided setup, engine prep, and toolchain catalog
├── network/                   # Egress proxy, policy, guard, and mux helpers
├── agent/launcher.sh          # Pi's agent part: profile data and hooks
├── agent/profile.json         # Pi profile for the shared components
├── agent/policies/            # Pi provider egress policy profiles
├── .containerignore           # Build context allowlist
├── .version                   # Single source of truth for Pi version
├── test.sh                    # Disposable image build plus real checks
├── test-wrapper.sh            # Synthetic wrapper entrypoint (Python 3)
├── tests/                     # Fake engine, pin checks, real rootless acceptance
├── docs/validation.md         # Commands, results, and verification limits
├── .github/workflows/ci.yml   # CI pipeline
├── AGENTS.md                  # Repository guidelines
├── SECURITY.md                # Vulnerability disclosure policy
├── LICENSE                    # MIT license
├── .gitignore
└── README.md                  # This file
```

### Updating pinned image inputs

`.version` records Pi's version; `Containerfile` records `OPENSPEC_VERSION`
and the base image digest. `tests/test_image_pins.py` rejects
floating inputs, `@latest`, version ranges and piped install scripts. To update:

1. Change `.version`, or the recorded version or digest in `Containerfile`.
2. Rebuild explicitly with `PI_CONTAINER_MAINTENANCE=1 pic --container-build`.
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
> execute on host-native `pi` invocations. Use `PI_CONTAINER_READONLY_STATE=1` when working
> with untrusted content. See [SECURITY.md](./SECURITY.md).

## Troubleshooting

| Symptom | Likely cause | Fix |
| --- | --- | --- |
| `EACCES: permission denied` on a bind | Host permissions or SELinux policy | Inspect host access/policy explicitly; the wrapper does not relabel or weaken confinement |
| `podman: command not found` | Podman not installed | [Install Podman](https://podman.io/docs/installation) |
| Pi hangs on non-interactive use | `-t` flag allocated without TTY | Script now auto-detects TTY and omits `-t` when not available |
| `pi: command not found` | npm install failed | Rebuild: `PI_CONTAINER_MAINTENANCE=1 ./pi-container.sh --container-build` |
| `.version` missing or empty | Version file absent | Ensure `.version` contains the Pi version (e.g., `1.5.2`); the launch stops before any image operation without it |
| Slow first start | apt + npm install during build | One-time cost; subsequent runs use cached image |
| API key not recognized | Key not forwarded | Provider mode forwards only the selected profile's key; unrestricted mode needs `PI_CONTAINER_ENV_VARS` to list it |
| `image ... is stale for the current build inputs` | `Containerfile`, `.containerignore`, `.version`, `network/relay.py` or `network/mux.py` changed | Run `PI_CONTAINER_MAINTENANCE=1 pic --container-build` |
| Permission denied on volume | Rootful Podman (sudo) | Run without `sudo` (rootless mode) |
| Read-only config error | `PI_CONTAINER_READONLY_STATE=1` and Pi needs to write | Disable `PI_CONTAINER_READONLY_STATE` for tasks that install extensions |
| `npm error ENOENT ... mkdir '~/.npm'` during `pi install` | npm cache dir on the read-only rootfs | Fixed: the wrapper mounts an ephemeral tmpfs at `~/.npm`. Raise the cap with `PI_NPM_CACHE_SIZE=512M` for large extensions |

## Verification

```bash
./test-wrapper.sh                      # synthetic wrapper tests, no engine or credentials
bash tests/run-runtime.sh              # unrestricted real rootless checks
bash tests/run-runtime.sh --wrapper    # shared launcher and Pi wrapper tests (fake engine)
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

## Shared sandbox components and the agent profile

`network/`, `setup/`, `launcher/` and the shared tests come unchanged from the
reference repository `sandbox-container` (tag `sandbox-ref-36`) and are shared
with the Claude, Codex, Antigravity and OpenCode wrappers. They contain no
Pi-specific names. `launcher/core.sh` is the whole launcher: `pi-container.sh`
is the thin entry script every wrapper shares, and `agent/launcher.sh` holds the
profile values the core needs plus Pi's five hooks (`docs/launcher-contract.md`
in `sandbox-container`):

- `agent_validate` checks the `PI_CONTAINER_GITCONFIG=1` opt-in and
  `PI_NPM_CACHE_SIZE` before any engine or state operation;
- `agent_mounts` adds the `~/.npm` tmpfs and the opted-in read-only gitconfig;
- `agent_build_args` passes `PI_VERSION` from `.version`;
- `agent_approval_bypass` prints the `PI_CONTAINER_YOLO` notice;
- `agent_help` documents these variables and the provider keys.

The shared launcher tests (`tests/test_launcher.py`, with the fake engine
`tests/fake_podman.py`), session engine tests (`tests/test_engine.py`),
toolchain library tests (`tests/test_toolchains.py`), terminal probe
(`tests/guard_terminal_probe.py`), setup tests (`tests/test_setup.py`), Windows
entry tests (`tests/test_windows_bootstrap.py`, `tests/test_windows_enter.py`),
and network/session suites run the shared components (`launcher/engine/`,
`setup/engine.py`, `setup/toolchain-catalog/`, and the rest of `launcher/`,
`setup/`, and `network/`) against fixture agent parts; `tests/test_wrapper.py`
covers only Pi's part. Every other agent-specific value is declared in
`agent/profile.json`. The changes for users of earlier versions are listed in
[CHANGELOG.md](CHANGELOG.md).

## Security

See [SECURITY.md](./SECURITY.md) for the vulnerability disclosure policy and
known security considerations.

## License

MIT — see [LICENSE](./LICENSE).

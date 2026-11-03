# pi-container

Run [Pi Coding Agent](https://pi.dev) transparently inside a **Podman container**,
with access to your Pi configuration (`~/.pi`), skills (`~/.agents`), and the
current project directory, with predictable host file ownership.

> By default, only `~/.pi`, `~/.agents`, the current working directory, and (if
> present) `~/.gitconfig` are mounted. Other host config such as `~/.ssh` or
> `~/.config` is intentionally **not** exposed to the container.

## Requirements

- **Podman** ≥ 4.x (rootless mode, no `sudo` needed)
- Linux (including WSL2), GNU coreutils `timeout`, and native Linux storage for private state
- Python 3 for synthetic tests; the runtime runner provisions its own test tools

## Quick start

```bash
git clone https://github.com/yarilc/pi-container.git
cd pi-container

# Use it anywhere, exactly like the `pi` command
cd /path/to/your/project
/path/to/pi-container/pi-container.sh "List the files in this directory"

# Or set up a convenience alias
alias pic='/path/to/pi-container/pi-container.sh'
pic --version
```

On first run the script builds the container image automatically (~2 minutes).
Subsequent runs start instantly. The image is rebuilt automatically whenever
`Containerfile` **or** `.version` changes (detected via content hash).

## How it works

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
Read-only mode requires existing readable/traversable directories, without
requiring ownership/privacy/write access; their confidentiality remains yours
to manage. Missing read-only state fails without creating it.

### Volume mounts

| Mount point | Purpose | Read-only mode |
| --- | --- | --- |
| `${HOME}/.pi` | Pi configuration, auth, sessions, extensions | `PI_READONLY_CONFIG=1` |
| `${HOME}/.agents` | Skills (prompt libraries) | `PI_READONLY_CONFIG=1` |
| `${PWD}` | Current working directory (same path inside and out) | Always writable |
| `${HOME}/.gitconfig` | Git identity (if present) | `PI_MOUNT_GITCONFIG=0` to skip |

The workspace uses `pwd -P`: its physical absolute source and destination
are identical, as is the working directory. State sources are resolved
physically and mounted at the existing HOME-relative destinations. No host
SELinux labels are changed automatically (`:z`/`:Z` are omitted). Access
failures require checking host policy and permissions explicitly; the wrapper
never disables confinement or repairs labels.

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
> **npm cache:** An ephemeral tmpfs is mounted at `${HOME}/.npm` so that
> `pi install npm:<package>` works under the read-only root filesystem (npm
> defaults its cache to `~/.npm`, which would otherwise be unwritable). The
> cache is cleared when the container exits; installed extensions themselves
> persist in `~/.pi/agent/npm` (user scope) or `$PWD/.pi/npm` (project scope).
> Override the cache size with `PI_NPM_CACHE_SIZE` (default: `256M`).

## Usage

### Wrapper modes

```bash
pic --container-help                 # also --wrapper-help; no prerequisites
pic --container-build --version      # force refresh, then start Pi
pic --container-shell                # Bash with the same sandbox and cleanup
pic --container-git-worktree         # expose the entire immediate parent
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
can leave resources requiring explicit inspection and cleanup. `PI_RUN_TIMEOUT`
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

## Environment variables

### API keys

The script forwards these environment variables to the container **only if
they are set and non-empty**:

| Variable | Purpose |
| --- | --- |
| `ANTHROPIC_API_KEY` | Anthropic / Claude API key |
| `OPENAI_API_KEY` | OpenAI API key |
| `GOOGLE_API_KEY` | Google / Gemini API key |

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

If `HTTP_PROXY`, `HTTPS_PROXY`, or `NO_PROXY` are set on the host, they are
forwarded to the container automatically.

### Other variables

| Variable | Purpose |
| --- | --- |
| `PI_IMAGE_NAME` | Override the container image name (default: `pi-container`) |
| `PI_DEBUG` | Set to any value to enable verbose debug output |
| `PI_ENABLE_PODMAN` | Only exact `1` enables the client and verified host socket; all other values disable delegation |
| `PI_PODMAN_SOCKET` | Absolute accessible socket override; then Unix `CONTAINER_HOST`, then `${XDG_RUNTIME_DIR:-/run/user/<uid>}/podman/podman.sock` |
| `PI_ENABLE_BUN` | Nonempty enables Bun (legacy behavior); use `1` to bake the Bun runtime into the image (opt-in). See [Bun runtime](#bun-runtime-opt-in) |
| `PI_BUN_VERSION` | Bun release tag to install when `PI_ENABLE_BUN=1` (default: `bun-v1.3.14`) |
| `PI_MEMORY_LIMIT` | Container memory limit (default: `4g`) |
| `PI_CPU_LIMIT` | Container CPU limit (default: `2`) |
| `PI_PIDS_LIMIT` | Container PID limit (default: `512`) |
| `PI_NPM_CACHE_SIZE` | Size of the ephemeral npm cache tmpfs at `~/.npm`, used by `pi install npm:<pkg>` (default: `256M`) |
| `PI_NETWORK` | Container network mode, e.g. `none` to block all egress (default: full access) |
| `PI_READONLY_CONFIG` | Set to `1` to mount `~/.pi` and `~/.agents` read-only (prevents persistence) |
| `PI_MOUNT_GITCONFIG` | Set to `0` to skip mounting `~/.gitconfig` (default: `1`, mount if present) |
| `PI_PULL_ALWAYS` | Set to `1` to force `podman build --pull=always` |
| `PI_RUN_TIMEOUT` | Native Podman container lifetime in seconds, placed before the image (0 disables); independent of shutdown budgets |
| `PI_ENV_VARS` | Space-separated list of extra env var **names** to forward to the container (for skill/extension/tool secrets; forwarded by name only, never as `NAME=value`). See [Custom environment variables](#custom-environment-variables) |
| `PI_ALLOW_UNSAFE_PWD` | Set to `1` to allow running from sensitive directories (not recommended) |
| `TERM` | Terminal type (forwarded for TUI rendering) |
| `EDITOR`, `VISUAL` | Host editor preference (forwarded with fallback to `nano`) |

## Container hardening

| Control | Implementation |
| --- | --- |
| Identity / capabilities | Caller UID/GID, keep-id, `--cap-drop=ALL`, no additions |
| Root filesystem | Read-only; explicit bounded `/tmp`, `/var/tmp`, `/run`, and npm cache |
| Privilege escalation | `--security-opt=no-new-privileges` |
| Resource limits | `--memory=4g`, `--cpus=2`, `--pids-limit=512` (configurable) |
| SELinux | Host labels and confinement remain unchanged |
| Sensitive PWD guard | Refuses to run from `/`, `$HOME`, `/etc`, etc. (override: `PI_ALLOW_UNSAFE_PWD`) |
| Rootless enforcement | Verified Linux rootless engine before image operations; no override |
| Signal handling | Owned full-ID lifecycle with finite cleanup phases; `--init` for reaping |
| Stale image detection | Content-hash comparison against Containerfile and `.version` |
| Conditional TTY | Only when stdin and stdout are terminals |
| Container naming | Sanitized `<dir>-<N>`, max existing suffix+1 including stopped containers; atomic create, at most 20 attempts |

> **Network egress is unrestricted by default.** An autonomous agent with
> network access and read access to mounted volumes (including
> `~/.pi/agent/auth.json`) could exfiltrate data if subverted by prompt
> injection. Use `PI_NETWORK=none` (or a restricted network) to limit egress.
> See [SECURITY.md](./SECURITY.md).
>
> **Config directories (`~/.pi`, `~/.agents`) are writable by default.**
> A compromised agent could plant persistent extensions or skills. Use
> `PI_READONLY_CONFIG=1` to mount them read-only for untrusted tasks.
> See [SECURITY.md](./SECURITY.md) for details on this and other risks.

## Podman host integration (opt-in)

**⚠️ WARNING:** Mounting the host Podman socket gives the container full
control over the host's container runtime. The AI agent can use this to
create privileged containers, mount host filesystems, and effectively
escape container isolation. **This feature is OFF by default**.

To enable, set `PI_ENABLE_PODMAN=1`:

```bash
PI_ENABLE_PODMAN=1 pic "Debug the failing container"
```

The container includes the `podman` CLI so you can interact
with the **host's Podman service** from inside the container.

```bash
# Inside pi, or via `pic -p`:
podman ps       # Lists host containers
podman images   # Lists host images
```

### Podman socket architecture

Only exact `PI_ENABLE_PODMAN=1` installs the client and enables delegation.
Unset, empty, `0`, `false`, `true`, `yes`, and all other values disable it;
migrate earlier truthy configurations to `1`.

Selection uses `PI_PODMAN_SOCKET`, then explicit Unix `CONTAINER_HOST`, then
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
further host mounts beyond the workspace. It is independent of Bun and native
Pi permission controls.

## Bun runtime (opt-in)

[Bun](https://bun.sh/) is a fast JavaScript runtime, bundler, test runner,
and package manager. Skills, extensions, or projects may require it. The
runtime is **off by default** and added only when requested.

To enable, set `PI_ENABLE_BUN=1`:

```bash
PI_ENABLE_BUN=1 pic "Run the test suite with bun"
```

The wrapper rebuilds the image with the Bun binary included (via the
`INSTALL_BUN` build arg). Bun is installed as a single, dependency-free
binary in `/usr/local/bin/bun`, so it is on `PATH` and requires **no writes
to `$HOME` at runtime** (compatible with the read-only root filesystem).

```bash
# Inside pi:
bun --version    # Bun version
bun install      # Install project dependencies
bun test         # Run tests via Bun's test runner
```

### Pinning a Bun version

The Bun release tag defaults to `bun-v1.3.14` and can be overridden with
`PI_BUN_VERSION`:

```bash
PI_BUN_VERSION=bun-v1.2.0 PI_ENABLE_BUN=1 pic ...
```

Disabling `PI_ENABLE_BUN` rebuilds without the Bun binary (smaller image).
The Bun version is folded into the stale-image hash, so changing
`PI_BUN_VERSION` triggers a rebuild automatically.

## Stale image detection

The script computes a SHA-256 hash of the `Containerfile`, `.containerignore`,
`.version`, Podman/Bun selection, and selected Bun version, and stores it as a label (`build-inputs-hash`) on the built
image. On each run it recomputes the hash and rebuilds the image automatically
if any of these files has changed. This ensures you never accidentally run with
an outdated image after modifying the Containerfile, changing build context
rules, or bumping the Pi version in `.version`.

> **Note:** The base image (`node:22-bookworm-slim`) uses a mutable tag and is
> not included in the hash. To force a fresh build and base image pull, use
> `PI_PULL_ALWAYS=1 pic --container-build --version`. Weekly CI scans
> monitor the built image for CVEs.

## File layout

```text
pi-container/
├── Containerfile              # Image definition
├── pi-container.sh            # Entry point script (builds & runs)
├── .containerignore            # Build context exclusions
├── .version                    # Single source of truth for Pi version
├── test.sh                     # Image smoke tests
├── test-wrapper.sh             # Synthetic wrapper entrypoint (Python 3)
├── tests/                      # Fake engine and real rootless acceptance
├── docs/validation.md          # Commands, results, and verification limits
├── .github/workflows/ci.yml   # CI pipeline
├── SECURITY.md                 # Vulnerability disclosure policy
├── LICENSE                     # MIT license
├── .gitignore
└── README.md                   # This file
```

## Updating

Pi and the container image are separate artifacts that can be updated independently.

### Update Pi to the latest version

Pi version is controlled by the `.version` file (single source of truth):

```bash
echo "0.80.0" > .version
```

The stale-image detection monitors both `Containerfile` and `.version`.
Changing `.version` automatically triggers a rebuild on the next run.

If you prefer a manual rebuild:

```bash
podman rmi pi-container
./pi-container.sh --version
```

Your session history, auth tokens, and settings in `~/.pi/agent/` are preserved
because they live on the host filesystem and are mounted into the container.

### Update the wrapper script and Containerfile

```bash
cd /path/to/pi-container
git pull
```

After pulling changes, the stale-image detection will rebuild automatically
on the next run.

### What survives a rebuild

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

## Tips

- **Alias in `~/.bashrc`**: `alias pic='/path/to/pi-container/pi-container.sh'`
- **Debug mode**: `PI_DEBUG=1 pic ...` to see verbose output
- **Custom image name**: `PI_IMAGE_NAME=my-pi pic ...`
- **Rebuild the image**: `podman rmi pi-container` (or change `Containerfile` to trigger auto-rebuild)
- **Interactive CLI args**: all arguments pass straight through to Pi — use `--help` to see Pi's full CLI, or `--wrapper-help` for wrapper-specific options
- **Multiple instances**: containers are named `<directory>-0`, `<directory>-1`, etc. Concurrent instances reserve above the highest existing suffix with bounded collision retries.

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
| Image is stale | Containerfile changed | Automatic detection triggers rebuild |
| Permission denied on volume | Rootful Podman (sudo) | Run without `sudo` (rootless mode) |
| Read-only config error | `PI_READONLY_CONFIG=1` and Pi needs to write | Disable `PI_READONLY_CONFIG` for tasks that install extensions |
| `npm error ENOENT ... mkdir '~/.npm'` during `pi install` | npm cache dir on the read-only rootfs | Fixed: the wrapper mounts an ephemeral tmpfs at `~/.npm`. Raise the cap with `PI_NPM_CACHE_SIZE=512M` for large extensions |

## Security

See [SECURITY.md](./SECURITY.md) for the vulnerability disclosure policy and
known security considerations.

## License

MIT — see [LICENSE](./LICENSE).

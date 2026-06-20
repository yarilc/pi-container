# pi-container

Run [Pi Coding Agent](https://pi.dev) transparently inside a **Podman container**,
with access to your Pi configuration (`~/.pi`), skills (`~/.agents`), and the
current project directory — no permission headaches.

> Note: only `~/.pi`, `~/.agents`, the current working directory, and (if
> present) `~/.gitconfig` are mounted. Other host config such as `~/.ssh` or
> `~/.config` is intentionally **not** exposed to the container.

## Requirements

- **Podman** ≥ 4.x (rootless mode, no `sudo` needed)
- Linux (works on WSL2 as well)

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

The main challenge with running CLI tools inside a container is **file ownership**:
files created inside the container (sessions, config, git repos) must be owned by
your host user, not by a container-internal user like `root` or `node`.

```text
┌─────────────────────────────────────┐
│  Host (you, UID 1000)               │
│                                     │
│  rootless Podman user namespace     │
│  ┌─────────────────────────────────┐│
│  │ Container (root / UID 0)        ││
│  │                                 ││
│  │  pi process runs as root        ││
│  │  ↓                              ││
│  │  Podman maps UID 0 → UID 1000   ││
│  │  ↓                              ││
│  │  Files on mounted volumes       ││
│  │  are owned by host user (you!)  ││
│  └─────────────────────────────────┘│
└─────────────────────────────────────┘
```

**Key insight:** Pi runs as `root` inside the container. Rootless Podman
transparently maps the container's root (UID 0) to your host UID, so every
file written to any mounted volume ends up with your ownership on the host.

To reduce risk, capabilities are dropped to a minimum set
(`DAC_OVERRIDE`, `CHOWN`, `SETGID`, `SETUID`) and the container's root
filesystem is mounted read-only with a small tmpfs for `/tmp`.

### Volume mounts

| Mount point | Purpose | Read-only mode |
|---|---|---|
| `${HOME}/.pi` | Pi configuration, auth, sessions, extensions | `PI_READONLY_CONFIG=1` |
| `${HOME}/.agents` | Skills (prompt libraries) | `PI_READONLY_CONFIG=1` |
| `${PWD}` | Current working directory (same path inside and out) | Always writable |
| `${HOME}/.gitconfig` | Git identity (if present) | `PI_MOUNT_GITCONFIG=0` to skip |

All mounts (except `.gitconfig`) use **bind mounts** at **identical paths** inside the container,
with **SELinux labels** (`:Z`) for compatibility with enforcing SELinux systems.
On non-SELinux systems the `:Z` flag is harmless.

> **Security note:** `~/.pi` and `~/.agents` are mounted **read-write by default**.
> A compromised agent could plant malicious extensions that persist across runs.
> Set `PI_READONLY_CONFIG=1` when working with untrusted prompts or projects.
> See [SECURITY.md](./SECURITY.md) for details.

## Usage

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

When stdin is not a terminal (e.g. pipes, CI pipelines), the `-t` flag is
automatically omitted, allowing clean non-interactive usage.

## Environment variables

### API keys

The script forwards these environment variables to the container **only if
they are set and non-empty**:

| Variable | Purpose |
|---|---|
| `ANTHROPIC_API_KEY` | Anthropic / Claude API key |
| `OPENAI_API_KEY` | OpenAI API key |
| `GOOGLE_API_KEY` | Google / Gemini API key |

> ⚠️ **Security note:** API keys are passed as environment variables. They are
> visible in `podman inspect` output and inside the container's `/proc`.
> For production or shared systems, consider using `podman secret` instead.

### Proxy support

If `HTTP_PROXY`, `HTTPS_PROXY`, or `NO_PROXY` are set on the host, they are
forwarded to the container automatically.

### Other variables

| Variable | Purpose |
|---|---|
| `PI_IMAGE_NAME` | Override the container image name (default: `pi-container`) |
| `PI_DEBUG` | Set to any value to enable verbose debug output |
| `PI_ENABLE_PODMAN` | Set to `1` to mount the host Podman socket (opt-in, dangerous) |
| `PI_MEMORY_LIMIT` | Container memory limit (default: `4g`) |
| `PI_CPU_LIMIT` | Container CPU limit (default: `2`) |
| `PI_PIDS_LIMIT` | Container PID limit (default: `512`) |
| `PI_NETWORK` | Container network mode, e.g. `none` to block all egress (default: full access) |
| `PI_READONLY_CONFIG` | Set to `1` to mount `~/.pi` and `~/.agents` read-only (prevents persistence) |
| `PI_MOUNT_GITCONFIG` | Set to `0` to skip mounting `~/.gitconfig` (default: `1`, mount if present) |
| `PI_PULL_ALWAYS` | Set to `1` to force `podman build --pull=always` |
| `PI_RUN_TIMEOUT` | Timeout in seconds for `podman run` (default: 0 = no timeout, e.g. `3600` for 1h) |
| `PI_ALLOW_ROOTFUL` | Set to `1` to allow running under rootful Podman (not recommended) |
| `PI_ALLOW_UNSAFE_PWD` | Set to `1` to allow running from sensitive directories (not recommended) |
| `TERM` | Terminal type (forwarded for TUI rendering) |
| `EDITOR`, `VISUAL` | Host editor preference (forwarded with fallback to `nano`) |

## Container hardening

| Control | Implementation |
|---|---|
| Capabilities | `--cap-drop=ALL`, only `DAC_OVERRIDE`, `CHOWN`, `SETGID`, `SETUID` added back |
| Root filesystem | `--read-only` with `--tmpfs /tmp:noexec,nosuid,size=256M` |
| Privilege escalation | `--security-opt=no-new-privileges` |
| Resource limits | `--memory=4g`, `--cpus=2`, `--pids-limit=512` (configurable) |
| SELinux | `:Z` label on `~/.pi`, `~/.agents`, and `$PWD` mounts |
| Sensitive PWD guard | Refuses to run from `/`, `$HOME`, `/etc`, etc. (override: `PI_ALLOW_UNSAFE_PWD`) |
| Rootless enforcement | Refuses rootful Podman (override: `PI_ALLOW_ROOTFUL`) |
| Signal handling | `--init` for signal forwarding and zombie reaping |
| Stale image detection | Content-hash comparison against Containerfile and `.version` |
| Conditional TTY | `-t` only when stdin is a terminal |

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

When `PI_ENABLE_PODMAN=1` is set, the wrapper automatically rebuilds the image
with the `podman` CLI included (via the `INSTALL_PODMAN` build arg) and mounts
the host Podman socket into the container. Disabling `PI_ENABLE_PODMAN`
rebuilds without the `podman` client (smaller image).

```text
┌───────────────────────────────────────────┐
│  Host                                      │
│  ┌───────────────────────────────────────┐ │
│  │ Podman socket:                        │ │
│  │   /run/user/1000/podman/podman.sock  │ │
│  └──────────────┬────────────────────────┘ │
│                 │ bind mount (opt-in)       │
│  ┌──────────────▼────────────────────────┐ │
│  │ Container (Pi)                        │ │
│  │   CONTAINER_HOST=unix://.../socket    │ │
│  │   podman ps   → talks to host socket  │ │
│  └───────────────────────────────────────┘ │
└───────────────────────────────────────────┘
```

### Prerequisites

Ensure the Podman socket is active on the host:

```bash
systemctl --user enable --now podman.socket
```

### Limitations

- **Version compatibility:** The `podman` client in the container (Debian
  Bookworm package) must be compatible with the host's podman server.
  Version differences may cause API incompatibilities.
- **Service must be running:** The script does not start the Podman service
  automatically. Use `systemctl --user start podman.socket` to ensure it is
  active.

## Stale image detection

The script computes a SHA-256 hash of the `Containerfile`, `.containerignore`,
**and** `.version` and stores it as a label (`build-inputs-hash`) on the built
image. On each run it recomputes the hash and rebuilds the image automatically
if any of these files has changed. This ensures you never accidentally run with
an outdated image after modifying the Containerfile, changing build context
rules, or bumping the Pi version in `.version`.

> **Note:** The base image (`node:22-bookworm-slim`) uses a mutable tag and is
> not included in the hash. To force a fresh base image pull, set
> `PI_PULL_ALWAYS=1` or manually `podman pull` the base image. Weekly CI scans
> monitor the built image for CVEs.

## File layout

```text
pi-container/
├── Containerfile              # Image definition
├── pi-container.sh            # Entry point script (builds & runs)
├── .containerignore            # Build context exclusions
├── .version                    # Single source of truth for Pi version
├── test.sh                     # Image smoke tests
├── test-wrapper.sh             # Wrapper-logic tests (fake podman, no build)
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
|---|---|---|
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

## Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| `EACCES: permission denied` on `~/.pi/...` | SELinux context missing | Add `:Z` to volume mounts (already included in the script) |
| `podman: command not found` | Podman not installed | [Install Podman](https://podman.io/docs/installation) |
| Pi hangs on non-interactive use | `-t` flag allocated without TTY | Script now auto-detects TTY and omits `-t` when not available |
| `pi: command not found` | npm install failed | Rebuild: `podman rmi pi-container && ./pi-container.sh --version` |
| `.version` missing or empty | Version file absent | Ensure `.version` contains the Pi version (e.g., `0.79.8`); the wrapper now fails hard if absent |
| Slow first start | apt + npm install during build | One-time cost; subsequent runs use cached image |
| API key not recognized | Empty key forwarded | Script now only forwards keys that are set and non-empty |
| Image is stale | Containerfile changed | Automatic detection triggers rebuild |
| Permission denied on volume | Rootful Podman (sudo) | Run without `sudo` (rootless mode) |
| Network egress warning on start | API key set without `PI_NETWORK` | Set `PI_NETWORK=none` to suppress (and restrict egress) |
| Read-only config error | `PI_READONLY_CONFIG=1` and Pi needs to write | Disable `PI_READONLY_CONFIG` for tasks that install extensions |

## Security

See [SECURITY.md](./SECURITY.md) for the vulnerability disclosure policy and
known security considerations.

## License

MIT — see [LICENSE](./LICENSE).

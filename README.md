# pi-container

Run [Pi Coding Agent](https://pi.dev) transparently inside a **Podman container**,
with full access to your local configuration, skills, and project files — no
permission headaches.

## Requirements

- **Podman** ≥ 4.x (rootless mode, no `sudo` needed)
- Linux (works on WSL2 as well)

## Quick start

```bash
git clone <this-repo>
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
`Containerfile` changes (detected via content hash).

## How it works

### Permission model

The main challenge with running CLI tools inside a container is **file ownership**:
files created inside the container (sessions, config, git repos) must be owned by
your host user, not by a container-internal user like `root` or `node`.

```
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

| Mount point | Purpose |
|---|---|
| `${HOME}/.pi` | Pi configuration, auth, sessions, extensions |
| `${HOME}/.agents` | Skills (prompt libraries) |
| `${PWD}` | Current working directory (same path inside and out) |

All three mounts use **bind mounts** at **identical paths** inside the container,
with **SELinux labels** (`:Z`) for compatibility with enforcing SELinux systems.
On non-SELinux systems the `:Z` flag is harmless.

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
| `TERM` | Terminal type (forwarded for TUI rendering) |
| `EDITOR`, `VISUAL` | Host editor preference (forwarded with fallback to `vi`) |

## Container hardening

| Control | Implementation |
|---|---|
| Capabilities | `--cap-drop=ALL`, only `DAC_OVERRIDE`, `CHOWN`, `SETGID`, `SETUID` added back |
| Root filesystem | `--read-only` with `--tmpfs /tmp:noexec,nosuid,size=256M` |
| Privilege escalation | `--security-opt=no-new-privileges` |
| Resource limits | `--memory=4g`, `--cpus=2`, `--pids-limit=512` |
| SELinux | `:Z` label on all volume mounts |
| Stale image detection | Content-hash comparison against Containerfile |
| Conditional TTY | `-t` only when stdin is a terminal |

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

### How it works

When `PI_ENABLE_PODMAN=1` is set, the wrapper script checks for the
host's Podman socket at `/run/user/<uid>/podman/podman.sock`.
If the socket exists (Podman service must be running), it is mounted
into the container and `CONTAINER_HOST` is set so Podman commands
inside the container talk directly to the host's Podman daemon.

```
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

The script computes a SHA-256 hash of the `Containerfile` and stores it as a
label on the built image. On each run it recomputes the hash and rebuilds the
image automatically if the file has changed. This ensures you never
accidentally run with an outdated image after modifying the Containerfile.

## File layout

```
pi-container/
├── Containerfile              # Image definition
├── pi-container.sh            # Entry point script (builds & runs)
├── .containerignore            # Build context exclusions
├── .version                    # Single source of truth for Pi version
├── test.sh                     # Smoke tests
├── .github/workflows/ci.yml   # CI pipeline
├── SECURITY.md                 # Vulnerability disclosure policy
├── LICENSE                     # MIT license
├── .gitignore
└── README.md                   # This file
```

## Updating

Pi and the container image are separate artifacts that can be updated independently.

### Update Pi to the latest version

```bash
# Edit Containerfile and change the PI_VERSION build arg:
#   ARG PI_VERSION=<new-version>
# Then rebuild:
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
on the next run. If you prefer a manual rebuild:

```bash
podman rmi pi-container
./pi-container.sh --version
```

### Pin a specific Pi version

Pi version is controlled by the `.version` file (single source of truth):

```bash
echo "0.80.0" > .version
```

The script and Containerfile both read from this file. The version will stay
fixed until you change it again.

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

## Tips

- **Alias in `~/.bashrc`**: `alias pic='/path/to/pi-container/pi-container.sh'`
- **Debug mode**: `PI_DEBUG=1 pic ...` to see verbose output
- **Custom image name**: `PI_IMAGE_NAME=my-pi pic ...`
- **Rebuild the image**: `podman rmi pi-container` (or change `Containerfile` to trigger auto-rebuild)
- **Interactive CLI args**: all arguments pass straight through — use `--help` to see Pi's full CLI

## Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| `EACCES: permission denied` on `~/.pi/...` | SELinux context missing | Add `:Z` to volume mounts (already included in the script) |
| `podman: command not found` | Podman not installed | Install Podman: https://podman.io/docs/installation |
| Pi hangs on non-interactive use | `-t` flag allocated without TTY | Script now auto-detects TTY and omits `-t` when not available |
| `pi: command not found` | npm install failed | Rebuild: `podman rmi pi-container && ./pi-container.sh --version` |
| Slow first start | apt + npm install during build | One-time cost; subsequent runs use cached image |
| API key not recognized | Empty key forwarded | Script now only forwards keys that are set and non-empty |
| Image is stale | Containerfile changed | Automatic detection triggers rebuild |
| Permission denied on volume | Rootful Podman (sudo) | Run without `sudo` (rootless mode) |

## Security

See [SECURITY.md](./SECURITY.md) for the vulnerability disclosure policy and
known security considerations.

## License

MIT — see [LICENSE](./LICENSE).

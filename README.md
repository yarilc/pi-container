# pi-container

Run [Pi Coding Agent](https://pi.dev) transparently inside a **Podman container**, with full access to your local configuration, skills, and project files — no permission headaches.

## Requirements

- **Podman** ≥ 4.x (rootless mode, no `sudo` needed)
- Linux (works on WSL2 as well)

## Quick start

```bash
git clone <this-repo>
cd pi-container

# Make the script executable (first time only)
chmod +x pi-container.sh

# Use it anywhere, exactly like the `pi` command
cd /path/to/your/project
/path/to/pi-container/pi-container.sh "List the files in this directory"

# Or set up a convenience alias
alias pic='/path/to/pi-container/pi-container.sh'
pic --version
```

On first run the script builds the container image automatically (~2 minutes).
Subsequent runs start instantly.

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
No `--userns=keep-id`, no `--user`, no permission workarounds needed.

### Volume mounts

| Mount point | Purpose |
|---|---|
| `${HOME}/.pi` | Pi configuration, auth, sessions, extensions |
| `${HOME}/.agents` | Skills (prompt libraries) |
| `${PWD}` | Current working directory (same path inside and out) |

All three mounts use **bind mounts** at **identical paths** inside the container,
so tools like `git`, `rg`, and `pi` itself see a filesystem that looks exactly
like the host.

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

## Environment variables

The script forwards these environment variables to the container (if set):

| Variable | Purpose |
|---|---|
| `ANTHROPIC_API_KEY` | Anthropic / Claude API key |
| `OPENAI_API_KEY` | OpenAI API key |
| `GOOGLE_API_KEY` | Google / Gemini API key |
| `HOME` | Your home directory (for mounts) |
| `TERM` | Terminal type (TUI rendering) |

To add more (e.g. `DEEPSEEK_API_KEY`, `MISTRAL_API_KEY`), edit the
`podman run` command in `pi-container.sh` and add:

```bash
-e "DEEPSEEK_API_KEY=${DEEPSEEK_API_KEY:-}"
```

## File layout

```
pi-container/
├── Containerfile        # Image definition (builds the pi environment)
├── pi-container.sh      # Entry point script (builds & runs)
├── .containerignore     # Build context exclusions
└── README.md            # This file
```

## Updating

Pi and the container image are separate artifacts that can be updated independently.

### Update Pi to the latest version

Pi is installed inside the image via `npm install -g @earendil-works/pi-coding-agent`
during the build. To get a newer version:

```bash
podman rmi pi-container
./pi-container.sh --version
```

The script rebuilds the image, pulling the latest Pi from npm. Your session history,
auth tokens, and settings in `~/.pi/agent/` are preserved because they live on the
host filesystem and are mounted into the container.

### Update the wrapper script and Containerfile

```bash
cd /path/to/pi-container
git pull
```

After pulling changes to `Containerfile` or `pi-container.sh`, rebuild the image:

```bash
podman rmi pi-container
./pi-container.sh --version
```

### Pin a specific Pi version

If you need a stable, pinned version for your team, add a version tag to the
`npm install` line in `Containerfile`:

```dockerfile
RUN npm install -g --ignore-scripts @earendil-works/pi-coding-agent@0.79.1
```

Then rebuild. The version will stay fixed until you change the tag and rebuild again.

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
- **Rebuild the image**: `podman rmi pi-container` — the script will rebuild on next run
- **Keep the image up to date**: remove and re-run to get the latest Pi version
- **Interactive CLI args**: all arguments pass straight through — use `--help` to see Pi's full CLI

## Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| `EACCES: permission denied` on `~/.pi/...` | Process runs as wrong UID | Rebuild image without `USER` directive (default uses root) |
| Podman hangs with `--userns=keep-id` | Bug in Podman 4.9 on WSL | Script does not use `--userns=keep-id` — relies on default rootless mapping |
| `pi: command not found` | npm install failed | Rebuild: `podman rmi pi-container && ./pi-container.sh --version` |
| Slow first start | apt + npm install during build | One-time cost; subsequent runs use cached image |

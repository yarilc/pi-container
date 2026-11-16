# Interactive sandbox setup

The durable contract is [container-setup](../openspec/specs/container-setup/spec.md).
It is copied unchanged from `sandbox-container` at tag `sandbox-ref-20`
(`setup/`); Pi values come from `agent/profile.json`. The archived change
`openspec/changes/archive/<date>-add-container-setup/` retains the design, tasks
and delta specifications.

Setup is the mandatory first step for new users. Run
`bash ./pi-container.sh --container-setup` from a reviewed checkout,
as the non-root Linux/WSL user who will use the sandbox. Podman and its rootless
dependencies must already be installed. Host Python 3, Bash and GNU coreutils
are also required. Setup needs terminal stdin/stdout; redirected answers and
combinations with launch flags or Pi arguments are rejected. Help is always
available through `--container-help` without loading preferences or using Podman.

## Choices and preparation

The prompts cover network access, the API-key authentication method for online
use, shared/fresh isolated state, delegation, permission bypass, worktree scope,
host CA trust, installation/command paths and the Podman endpoint. The methods
`anthropic`, `openai`, `gemini` and `openrouter` select the protected profiles
`anthropic-api`, `openai-api`, `gemini-api` and `openrouter-api` from the
packaged policy. Setup never asks for the key itself. First-run setup defaults
to provider mode with the `anthropic` method, shared state, permission bypass
off, current workspace only, delegation off and CA trust off.

Pi 0.80.8 has no tool-approval layer: its tools run without prompts and the
container is the only boundary. The permission-bypass question is kept so the
managed launcher can save `PI_CONTAINER_YOLO=0` or `1` as for the other
wrappers. `0` is silent; `1` prints a warning that the setting has no effect
yet.
Accept defaults with Enter; invalid choices are requested again. Existing saved
choices are offered for review on rerun, including a previously selected offline
mode. The managed launcher applies the saved network choice. Ordinary direct
invocation with `PI_CONTAINER_NETWORK` unset or empty stops with setup
guidance before runtime prerequisite checks, engine queries or state creation.
Setup is never started automatically. An explicit empty network override on a
managed invocation also receives this refusal; remove the override to use the
saved choice. Offline mode cannot reach any model provider.

After the worktree question, setup asks for the agent budgets and lifetime:
`Agent memory limit` (default `4g`), `Agent CPU limit` (default `2`),
`Agent process limit` (default `512`) and `Session lifetime in seconds, 0
disables` (default `0`). Invalid answers are explained and asked again; `0`,
`-1`, `max` and unitless memory are rejected, so a budget cannot be disabled.
The setup plan lists the values. They are saved in schema 2 preferences and
supplied by the managed launcher as `PI_CONTAINER_MEMORY_LIMIT`,
`PI_CONTAINER_CPU_LIMIT`, `PI_CONTAINER_PIDS_LIMIT` and
`PI_CONTAINER_RUN_TIMEOUT` unless those are exported. Smoke and
qualification use the saved values. To change a budget, rerun setup; an
exported different value makes restricted launches stop until
`--container-qualify` is run with the same environment. Preferences saved by an
earlier release (schema 1) are read with the default budgets proposed.

Setup smoke, qualification and optional login run in a private temporary
workspace, never in the directory from which setup was started. Ordinary
launches refuse sensitive workspace roots such as `/`, your home, system
directories and WSL drive roots unless exact
`PI_CONTAINER_ALLOW_UNSAFE_WORKSPACE=1` is set.

Operators can still invoke a manually prepared wrapper with explicit `offline`,
`provider` or `unrestricted` mode. All existing prerequisites, protected paths,
qualification and authority checks apply. Image maintenance additionally
requires exact `PI_CONTAINER_MAINTENANCE=1`; that consent alone does not select
a mode. Help and standalone setup/qualification retain their own dispatch checks.
Standalone `--container-qualify` keeps its offline default when no mode is set
and can run only fixed controls, never a supplied application command.

Earlier versions of this wrapper needed no runtime-mode selection; since
`add-network-egress` a direct launch needs an explicit `PI_CONTAINER_NETWORK`
(`unrestricted` keeps the previous networking), and an ordinary missing-mode
launch now stops with setup guidance. Managed launchers supply the saved mode.
Install an updated protected wrapper through setup, or update and requalify a
manual restricted installation: changing the wrapper invalidates its old
qualification identity. Activation and last-working-release rollback are
unchanged.

Provider mode authorizes CONNECT hostname/address and requires matching SNI in
the initial TLS ClientHello, and in the retried ClientHello after a TLS 1.3
HelloRetryRequest, before forwarding client bytes. TLS 1.2 renegotiation is
encrypted and not inspected. It preserves
end-to-end certificate verification. ECH (including GREASE), missing/malformed or
different names and inspection timeout/overflow fail closed. Encrypted HTTP
Host/authority, shared-service routing and provider forwarding remain opaque;
this does not guarantee exclusive access to your provider account. Allowed
services can still receive session data.

Selecting provider mode prints a residual-exfiltration notice listing the hosts
of each method (`anthropic: api.anthropic.com`; `openai: api.openai.com`;
`gemini: generativelanguage.googleapis.com`; `openrouter: openrouter.ai`) and asks `Acknowledge that allowed provider hosts can
receive data sent with foreign credentials? (yes/no)`. Destination binding cannot
tell your credentials from attacker-supplied ones, so a prompt-injected agent can
send workspace data to an allowed host with a foreign API key or account. Answering
`no` returns to the network-mode question; no other mode is chosen for you. The
acknowledgement is required on every setup run that selects provider mode,
including the delegation-conflict network change, and is not saved. Only offline
mode removes this channel; see
[Residual exfiltration](network-contract.md#residual-exfiltration-to-allowed-services).

The candidate image and protected release must both implement
`tls-clienthello-sni-v2`; missing/old enforcement identity fails readiness before
agent startup and candidate activation. Deploy matching code and image together.
Unsupported clients require a supported non-ECH configuration; failures never
trigger unchecked tunneling. A rollback to a historical release also removes
this guarantee; use offline mode if the stronger boundary is required until a
compatible candidate passes. Existing maintenance consent and rollback remain
in force.

Restricted modes admit native Linux and WSL2 x86_64 with usable Landlock ABI >= 3,
rootless same-host Unix Netavark/Podman >= 4.9 and standard OCI seccomp, followed
by mandatory local qualification. There are no exact kernel pins or server upper
bounds. Enabled SELinux/AppArmor is permitted without guaranteeing compatibility;
denials stop preparation while policies stay active. Setup diagnoses missing
Podman, UID/GID mappings/helpers, runtime directories and unsupported engines.
Fix those host prerequisites separately. Setup never installs host packages,
uses sudo, edits subordinate-ID mappings, enables lingering, changes WSL init,
disables security policy or silently selects unrestricted networking.

Every agent container, in every mode, and every provider proxy drops all
capabilities and enables no-new-privileges. Setup smoke verifies zero capability
sets, no-new-privileges and the effective agent `memory.max`, `pids.max` and
`cpu.max` in every mode, so rootless cgroup v2 `cpu`, `memory` and `pids`
controllers must be delegated. Provider proxies additionally receive 256 MiB and
128 processes.
The installed wrapper verifies the effective limits and proxy hardening before
its smoke agent starts. An unavailable controller, ignored limit or incompatible
image makes setup incomplete and preserves the previous working release.
Inspect controller delegation and image compatibility separately; setup never
adds privileges, changes host security policy or removes limits to proceed.

Before activation, setup runs `--container-qualify` against its protected
candidate using fixed disposable IP/IPC/TLS controls and no real credentials.
Only a complete passing result is published atomically under the release's
private `qualification/` directory. A failed or interrupted candidate keeps the
previous release selected. Authentication remains a separate status.

Existing managed installations must rerun setup. Manually prepared installations
can invoke `--container-qualify` alone with their existing explicit environment
configuration; this command never starts an ordinary Pi session or grants
maintenance. Help and unrestricted launches do not require a report.

The toolchain library (`adopt-sandbox-ref-16`) changes the wrapper and adds
`setup/toolchains.py` to the installed and qualified code, so rerun
`--container-setup` after upgrading. Setup does not manage toolchains: the
operator adds them with `--container-toolchain`, and every session mounts the
library read-only at `/toolchains` (see the README "Toolchains" section).

For the provider idle-channel fix, rerun setup from the updated reviewed checkout
and explicitly approve maintenance and image refresh so both the runtime and
proxy images contain the same updated multiplex receiver. Install the matching
protected release and let normal qualification regenerate reports for its changed
code and immutable image identities; an old report must not be copied or reused.
The guard ABI and mux wire version remain unchanged. Relaunch existing sessions:
their preconnected channel cannot be repaired after closure. The optional
`bash tests/run-runtime.sh --guard-idle` check documented in `network/README.md`
verifies reuse after a real 305-second pause without authentication. Rollback
uses the retained last-working release and its normal qualification checks;
the previous receiver still has the five-minute inactivity defect.

Reports bind kernel/boot, ABI, engine/backend/security artifacts, protected code,
immutable images, selected policy/profile, CA trust and hardening. Relevant changes
require requalification. Unobservable active LSM policy state forces a new gate
each ordinary launch rather than unsafe reuse. Missing/stale/unsafe reports and
unavailable required controls block launch; permissions are not repaired.
Setup distinguishes `locally-qualified` from an exact `release-measured` record.
Local success is not a claim about every native distribution, LSM or auth flow.

For restricted launch or optional delegation, setup verifies the selected
same-host rootless Unix service. `default` derives the socket from the current
`XDG_RUNTIME_DIR` (or `/run/user/<uid>`) on every invocation; an explicit
`unix:///absolute/socket` is retained literally. `local` is available for
unrestricted launch without delegation. TCP/SSH, named contexts and implicitly
remote engines remain unsupported. Bind/build paths must exist at their real
absolute paths on that same Linux host, including when running from a container.

When available, setup can run `systemctl --user enable --now podman.socket`
after separate confirmation. This persistent user-service change does not
delegate the socket to the application. Without a working user manager, setup
prints foreground `podman system service --time=0` instructions and stays
incomplete until an endpoint is verified. It does not leave a background daemon
or repair an administrator-owned `/run` directory. A service enabled before
later cancellation is reported and retained, since other clients may use it.

Review the settings and image plan before approving preparation. A separate
refresh question allows rebuilding prepared images/guard. Builds and pulls are
host maintenance: their network traffic, including build-time package downloads,
is outside runtime egress filtering even when the chosen session mode is offline.
Consent grants exact maintenance authorization only to these preparation
commands. It is not saved or enabled for subsequent ordinary launches.

Pi's profile declares `install.runtime_build: "wrapper"`. When no suitable
runtime image exists, or refresh is approved, setup runs the installed
release's `pi-container.sh --container-build` alone with the candidate tag and
the scoped maintenance authorization. That build-only operation uses the same
`PI_VERSION` (from the installed `.version`) and `build-inputs-hash` label as
an ordinary launch, starts no session, and exits; setup then inspects the candidate's immutable identity. A reused
`localhost/pi-container:latest` keeps its labels: if they are stale for the
installed inputs, the smoke check stops with the stale-image message, and a
rerun with refresh rebuilds through the wrapper. `.version` is installed with
the release because the profile lists it in `install.files`.

Every mode needs a runtime image; restricted modes also need the static guard
and its digest manifest. Provider additionally needs the immutable proxy image,
selected policy and private egress runtime directory. Setup reuses inspected
artifacts when suitable and prepares missing ones from the existing recipes.
Compiler tools are installed only in the pinned toolchain image. Compilation
uses that immutable image without networking. Failed recipe/package acquisition
does not change pins automatically; resolve the reported maintenance stage and
rerun. Unrestricted mode skips the guard/toolchain/proxy, and offline skips the
provider proxy/authentication.

## Managed installation and launch

Default paths:

- Installation: `$HOME/.local/lib/pi-container` on native Linux storage.
- Command: `$HOME/.local/bin/pi-container`.
- Egress state: `$HOME/.local/state/pi-egress`.
- Optional fresh isolated home: `$HOME/.local/share/pi-container/home`.

Source may be on a Windows mount; installation, private state and executable
guard output need permission-enforcing native storage with protected ancestors.
Setup copies an explicit input manifest, never a whole checkout or credentials.
Group/other-writable ancestors, unsafe existing modes and paths overlapping the
writable workspace/worktree/state are rejected without recursive repairs.
An existing safe flat manual installation can coexist with managed releases.
An absent installation directory is created with mode `0700`. An existing
caller-owned `0755` installation root is accepted without changing its mode:
installation code requires write protection, while credential/state directories
and managed releases retain their private permission checks. Invalid ownership
or inaccessible existing roots are diagnosed before maintenance confirmation.

Each `releases/<id>/` contains its runtime/setup/build inputs and private
versioned `setup.json`. `current` selects the active release. Setup holds
`.setup.lock` during preparation/activation and publishes the pointer only after
the candidate smoke check passes. A failed candidate is removed; the last
working release and credential state are preserved. Concurrent setup fails with
a busy message. Remove a stale empty `.setup.lock` only after confirming that
no setup process is active. An unrelated command file or reserved-path symlink
is never overwritten.

Use the absolute completion command, or add its directory to PATH yourself:

```bash
cd /path/to/my-project
"$HOME/.local/bin/pi-container"
"$HOME/.local/bin/pi-container" --container-shell
"$HOME/.local/bin/pi-container" --container-setup
```

Setup does not edit shell startup files. If the command directory is absent from
PATH, the plan and completion output
show a shell-quoted `export PATH=/absolute/command/directory:"$PATH"` command and
suggest adding that line to the appropriate shell startup file for persistence.
The managed command loads validated
non-secret JSON and execs the installed wrapper; preferences are never sourced
as shell code. It preserves current directory, stdin, arguments, terminal and
exit/signal handling. Settings provide defaults only for variables absent from
the environment. Explicit values, including empty values, take precedence and
must pass normal validation. A nonempty `PI_CONTAINER_CONFIG_DIR` conflicts with an
isolated home; unset it deliberately rather than expecting setup to discard it.

The installation and command remain outside writable mounts on every managed
launch, including unrestricted mode. A future worktree parent containing them
is rejected with relocation guidance. Rerun setup to change saved workspace
scope, or invoke the installed wrapper directly for per-invocation choices.
The invoked command's own path is checked as well as the configured path,
including relative invocation, copied dispatchers and symlink aliases. A command
or alias inside the effective writable workspace/state is rejected before launch.
When setup changes the managed command path, it retires the previous owned
command after publishing the new one. A retirement/publication failure restores
the previous activation and leaves the previous command intact. The plan names
the command to be retired; unrelated files are never removed.

Existing dispatchers from before this path-check protocol are upgraded
atomically by setup. Such a dispatcher can still request help/setup, but normal
launch against the new helper fails closed until the upgrade. Run setup from the
updated checkout to install both matching components; no image refresh is needed.
Direct `pi-container.sh` retains its existing environment-based behavior and
does not load a global configuration. Managed help bypasses preferences and
Python, including when preferences are corrupt. Setup rerun uses saved choices;
to repair invalid JSON, first review/restore the affected file or use a reviewed
checkout and a different installation root.

Rerunning from the installed command reconfigures that installed source version.
To install updated source, run setup from the reviewed updated checkout and
select the same installation root. Runtime images use distinct candidate tags;
proxy references are immutable IDs. An explicitly authorized ordinary
`--container-build` still operates on the selected named runtime image and is
separate from setup's release transaction.

The previous release is retained. For rollback, stop setup updates, take the
same installation lock, inspect the previous release and its `setup.json`, then
atomically replace `current` with a symlink to that release. Alternatively run
the prior manual wrapper with its explicit environment. Never delete state to
roll back. Automatic pruning is not provided. New image tags and enabled user
sockets can remain after failure; setup reports persistent effects and does not
remove shared engine resources or undo service enablement automatically.
If rolling back across a command-path or dispatcher-protocol change, restore
the matching command/configuration as well; changing only `current` does not
recreate a retired command or adapt an older launch helper's interface.

## Readiness and authentication

Setup smoke-checks the actual installed wrapper with the selected state, network
and CA settings, without credentials in its environment or a model request. It
checks the Pi executable and that `PI_CONTAINER_CONFIG_DIR` names a writable
configuration directory (`/pi-home/.pi`) in the session; restricted smoke also exercises enforced Unix
socket denial, direct egress denial, own-loopback/pair compatibility and, for
provider mode, the confined proxy deny path. ABI query success alone is not
accepted. Failure prevents activation and returns nonzero.

Completion distinguishes:

| Result | Meaning |
| --- | --- |
| `Sandbox: ready`, authentication pending | Installation/smoke passed; login/key configuration still needs user action. Setup returns zero. |
| `Sandbox: ready`, authentication not applicable | Offline sandbox is usable without provider authentication. |
| setup incomplete | A prerequisite/preparation/smoke step failed. Setup returns nonzero and leaves the last activated release selected. |

Pi's four profiles use API keys, so setup always finishes provider mode
with `Authentication pending` and names the variable to supply
(`ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, `GEMINI_API_KEY` or
`OPENROUTER_API_KEY`). Setup does not collect or save a key, and makes no model
request. Provider launches forward only the key of the saved profile, by name;
supply it through your normal private secret mechanism when launching. A key
stored in `~/.pi/agent/auth.json` also works, because the profile restricts
hosts, not credential sources. Subscription, browser-callback and OAuth logins
(`/login`) are unsupported in restricted modes: no port is published.

In unrestricted mode, setup prints the shared hint that environment-key
forwarding is the provider mechanism; unrestricted launches forward
`ANTHROPIC_API_KEY`, `OPENAI_API_KEY` and `GOOGLE_API_KEY` by name (Pi reads
`GEMINI_API_KEY` for Gemini; list it in `PI_ENV_VARS`).

The wrapper reclassifies Podman 4.3's successful `Should restart: false` message
as informational (`INFO[...]` or `level=info`), preserving its timestamp and
message. All other stderr bytes, including actual restart-check errors, remain
unchanged; interactive prompts do not wait for a newline. The host-side adapter
is installed by setup and its owned process shares the wrapper shutdown budget.
Legacy direct unrestricted installations lacking host Python or the adapter keep
their original Podman diagnostics instead of gaining a Python prerequisite.

## Verification

Synthetic tests use fake engines, PTYs and disposable native state:

```bash
python3 -m unittest discover -s tests -p test_setup.py -v
bash tests/run-runtime.sh --setup       # container-provided Python/native storage
bash tests/run-runtime.sh --setup-runtime  # opt-in real rootless setup acceptance
bash tests/run-runtime.sh --qualification  # installed-path gate and report checks
```

Runtime checks use existing prepared images, disposable installation/state and
an existing same-host service; they do not enable user services or access real
credentials. Real systemd activation and optional real login require a user to
accept their respective setup prompts. Record unexercised variants as unavailable
in `docs/validation.md` and retain the optional status of a real API-key request.

The `container-setup` requirement coverage is:

| Requirement | Verification |
| --- | --- |
| Dedicated interactive setup invocation | PTY early-dispatch, mixed-argument/pipeline rejection and help precedence tests |
| Workflow questionnaire with explicit defaults | Default/retry/conflict PTY checks; saved-choice rerun; real provider/offline/unrestricted paths |
| Optional authority requires deliberate selection | Delegation conflict questionnaire; separate service confirmation; saved worktree/TTY checks |
| Installed host prerequisites only | Missing command, unsupported context/platform and strict failed/malformed engine-response tests |
| User-scoped Podman service preparation | Synthetic accepted/declined/unavailable systemd and exact-endpoint tests; real existing-service reuse |
| Reviewed setup mutations and maintenance | Declined plan has no filesystem/image mutation; scoped maintenance/environment tests |
| Protected complete installation | Native manifest copy from Windows checkout; path/ancestor/overlap/state/privacy checks |
| Mode-specific image and guard preparation | Inspection/recipe pin/build failure/guard preflight tests; real compilation and provider/offline/unrestricted smoke |
| Persistent non-secret managed launch preferences | Schema/privacy/secret rejection, empty overrides, argv/stdin/cwd/TTY/status/signal and future-mount tests |
| Credential-preserving authentication assistance | Synthetic direct-terminal login success/failure/cancellation and absent-key cases; real login separately opt-in |
| Verified readiness with separate authentication status | Actual installed guard, proxy deny path, CA off/on, version/shell and explicit pending/not-applicable results |
| Repeatable setup with owned recovery | Lock/publication/interruption/container cleanup tests; real rerun and failed-candidate rollback |

Adversarial regression checks additionally cover managed-command relocation,
retirement failure/rollback, legacy dispatcher upgrade and writable aliases.
Timeout checks include an already-exited group leader and a descendant that
closes pipes on TERM while continuing to run. Tests use a separate Linux
subreaper to collect their own orphaned descendants without leaving zombies.

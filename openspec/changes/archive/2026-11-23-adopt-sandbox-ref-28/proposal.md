# Proposal

## Why

Pi runs on `sandbox-ref-25`. Claude, Codex, Antigravity and OpenCode adopted
`sandbox-ref-28` on 2026-11-22 and 2026-11-23. Pi is the last wrapper. The
three tags since `sandbox-ref-25` bring:

- **`sandbox-ref-26`:** the budgets rule.
  - Only the `systemd` cgroup manager delegates controllers.
  - Without the `pids` controller, the process budget falls back to the
    process rlimit.
  - The shared launcher files pass ShellCheck.
- **`sandbox-ref-27`:** Windows support on a Podman machine.
  - The PowerShell entry, the shim, the bootstrap, the namespace helper and
    the installer.
  - Offline and provider networking in the machine, with the guard as the
    confined init of restricted sessions.
  - Setup changes for the machine, and API key variables forwarded from
    Windows.
- **`sandbox-ref-28`:** setup started from Windows names the API key steps for
  PowerShell.

Without these tags, Pi has two gaps:

- On a `cgroupfs` engine, which applies no budget, Pi reports the budgets as
  enforced.
- Pi cannot run from Windows.

## What Changes

- **Adopt the tag.** `tools/propagate.py` adopts `sandbox-ref-28` from
  `sandbox-ref-25`. The dry run of 2026-11-23 gave this plan:
  - update 22 shared files;
  - add 8: the `launcher/windows/` files and the Windows tests;
  - rewrite 8 tag references: 3 in `docs/network-contract.md`, 2 in
    `README.md`, 1 each in `AGENTS.md`, `CONTRIBUTING.md` and
    `docs/setup.md`;
  - move the manifest.
- **Files outside the copied directories,** handled as in the other wrappers:
  - `pi-container.ps1`, the thin Windows entry, copied byte for byte from
    `sandbox-container.ps1`;
  - `.gitattributes`, followed by an LF renormalization.
- **Pi's agent part** already carries the reference's ShellCheck header, so it
  does not change.
- **Pi's own tests** change only where the shared changes alter what they
  check:
  - `tests/test_setup_wrapper.py` is identical to Codex's file before Codex's
    adoption. It takes the adapted version that the other wrappers now share.
  - The budget checks of `tests/test_runtime.py` follow the engine's delegated
    controllers and process mechanism, as in the other wrappers.

  A failure caused by shared code pauses the change for a fix in the
  reference.
- **Pi's documentation** (`README.md`, `docs/setup.md`, `AGENTS.md`):
  - a Windows section adapted to Pi:
    - provider is the default, with the four API key methods;
    - `$env:<KEY>` supplies the selected method's key;
    - `PI_NPM_CACHE_SIZE`, the one Pi setting outside the `PI_CONTAINER_*`
      names, reaches a session from Windows only when `PI_CONTAINER_ENV_VARS`
      lists it;
    - `PI_CONTAINER_GITCONFIG=1` mounts the machine's `~/.gitconfig`;
    - the installer;
    - host CA trust with `--import-native-ca`;
    - the Windows limits, including Bitdefender;
  - the process rlimit fallback and the `cgroupfs` budgets;
  - the guard as the confined init;
  - the setup changes.
- **Parity tables:**
  - Pi's row names `sandbox-ref-28`, with this adoption's results;
  - every other row matches `sandbox-container`;
  - Pi's row is copied into the reference and the other wrappers.
- **Validation on Windows** with Pi, by the operator:
  - setup in provider mode with an API key method;
  - a Pi session with tool use;
  - `PI_NPM_CACHE_SIZE` through `PI_CONTAINER_ENV_VARS`;
  - `windows-validate -Checkout` on both PowerShell editions, including
    `-Install` and `-StopMachine`.

## Capabilities

### New Capabilities

- `windows-launcher`: the reference capability, copied as is. It runs Pi from
  PowerShell in a Podman machine's WSL distribution.
- `windows-installation`: the reference capability, copied as is. It installs
  the Windows entry for one Windows user.

### Modified Capabilities

- `container-isolation`:
  - budgets follow the controllers the engine delegates;
  - the process budget falls back to the process rlimit;
  - the documented hardening controls include that fallback.
- `container-session`: the budget notices name the reason or the rlimit
  mechanism, and the qualification identity includes the process budget
  mechanism.
- `container-setup`:
  - the questionnaire and saved budgets with the fallback;
  - recovery tags;
  - setup without a launch service;
  - carriage-return checks;
  - setup started by the Windows entry, with the PowerShell authentication
    steps;
  - the service endpoint proposed for restricted modes.
- `network-egress`: the proxy process budget falls back to the rlimit, and the
  guard runs restricted sessions as a confined init.
- `shared-launcher`:
  - ShellCheck;
  - the shared Windows shim and bootstrap;
  - the thin PowerShell entry;
  - LF line endings;
  - PSScriptAnalyzer;
  - the bootstrap tests;
  - Pi's npm cache size from the Windows entry needs `PI_CONTAINER_ENV_VARS`.
- `workspace-mounts`: Windows system and profile folders are sensitive
  workspace roots.

## Impact

- **Code:** only these files change:
  - the shared files;
  - `pi-container.ps1` and `.gitattributes`;
  - the two adapted tests.
- **Installations:** the installed core, setup and guard change, so every Pi
  installation reruns `--container-setup`.
- **Behavior on Linux:**
  - On a `cgroupfs` engine, the launch notices state that the memory and CPU
    budgets are not enforced and that the process budget uses the rlimit.
  - Restricted sessions run under the guard as init, so Ctrl+C reaches Pi at
    once.
- **Repositories:** the adoption is in `pi-container`. `sandbox-container` and
  the other wrappers get only the parity row. After it, every wrapper is on
  `sandbox-ref-28`.
- **Dependency:** `sandbox-ref-28` already exists. The other four adoptions
  give the pattern.

# Design

## Context

Pi adopted `sandbox-ref-25` on 2026-11-18 and pinned Pi 1.5.2 (`.version`)
and OpenSpec 2.0.0 the same day. Its runtime and egress images are its own and
stay as they are. The tag changes no Pi build input.

**Dry run.** `tools/propagate.py ../pi-container sandbox-ref-25
sandbox-ref-28` (2026-11-23) gave this plan:

- **Update:**
  - `launcher/core.sh`;
  - `network/README.md`, `agent_budgets.py`, `control.py`, `guard.c`,
    `proxy_hardening.py`, `qualification_probe.py`,
    `qualification_records.py` and `session.py`;
  - `setup/common.py`, `launch.py`, `setup.py` and `smoke.py`;
  - `tests/fake_podman.py` and both fixture `launcher.sh`;
  - `tests/test_alignment.py`, `test_guard.py`, `test_launcher.py`,
    `test_qualification.py`, `test_session.py` and `test_setup.py`.
- **Add:**
  - the five `launcher/windows/` files;
  - `tests/test_windows_bootstrap.py` and `tests/test_windows_enter.py`;
  - `tests/windows/shim_tests.ps1`.
- **Rewrite:** 2 references in `README.md`, 1 each in `AGENTS.md`,
  `CONTRIBUTING.md` and `docs/setup.md`, and 3 in `docs/network-contract.md`.
  Pi is the last wrapper on `sandbox-ref-25`, so the 3 are the tag line and
  Pi's own row.
- **Move:** the manifest to `ba1ef14`.
- **Runner modes listed:** `--shared`, `--setup`, `--setup-runtime`,
  `--qualification`, `--guard` and `--network`.

**ShellCheck today.** `tools/shellcheck.sh ../pi-container` reports findings
only in `launcher/core.sh` (14) and both fixtures (32 and 25), which the tag
replaces. Pi's agent part already starts with
`# shellcheck shell=bash disable=SC2034,SC2154`.

**Pi's own tests.**

- `tests/test_setup_wrapper.py` is byte for byte the file Codex had before its
  adoption. Claude, Codex, Antigravity and OpenCode now share one adapted
  version.
- In `tests/test_runtime.py`, `test_effective_hardening_and_budgets` reads
  `memory.max`, `pids.max` and `cpu.max` and asserts all three budgets.
  `test_process_limit_enforced` spawns 80 children from Node under a process
  budget of 32.
- `test_build_context_excludes_sensitive_and_unknown_inputs` checks file
  presence, not modes, so the defect fixed in Antigravity does not apply.

**Pi specifics on Windows.** The shim reads every wrapper-specific value from
`agent/profile.json`:

- `native.command` is `pi`, so `tools/windows-validate.ps1` runs its cases
  with `--container-shell`.
- The four methods (`anthropic`, `openai`, `gemini`, `openrouter`) are API key
  methods. The shim forwards their keys by name, and setup started from
  Windows names `$env:<KEY>`. Subscription and browser-callback logins stay
  unsupported, as on Linux.
- The shim forwards `PI_CONTAINER_*`, the method keys and the names in
  `PI_CONTAINER_ENV_VARS`. Pi's agent part reads one more setting,
  `PI_NPM_CACHE_SIZE`, which therefore reaches the distribution from Windows
  only when the list names it. Pi has no other host variable of its own.
- `native.config_dir_env` is `PI_CONTAINER_CONFIG_DIR`, forwarded only with a
  distribution path. Shared state is the machine user's `~/.pi` and
  `~/.agents`. `PI_CONTAINER_GITCONFIG=1` mounts the machine user's
  `~/.gitconfig`.
- `.version` is an install file of the profile, so setup's manifest, which the
  installer copies, includes it.
- On 2026-11-23 the operator used an OpenRouter key for OpenCode on Windows.

**Images.** The runner's engine has no `localhost/pi-container:latest`. Its
only `setup-*` image, `9ed2a78259d9`, has `build-inputs-hash` `7797baa9…`, the
hash of the Pi 0.80.8 image. The 1.5.2 pin record gives `c6fd471d…`. The
guard toolchain exists only under a `setup-*` tag.

## Goals / Non-Goals

**Goals:**

- Pi runs on the `sandbox-ref-28` shared files. Beyond the two adapted tests,
  no Pi-specific code changes.
- Pi works from Windows on a Podman machine, in provider mode with an API key
  method, with the installer.
- The README states how `PI_NPM_CACHE_SIZE` reaches a session from Windows.
- Every wrapper, and the parity tables of all six repositories, state
  `sandbox-ref-28`.

**Non-Goals:**

- Forwarding `PI_NPM_CACHE_SIZE` from Windows without `PI_CONTAINER_ENV_VARS`,
  or renaming it under `PI_CONTAINER_*`. Either is a separate change.
- Delegation on Windows and macOS.
- The provider profiles still pending on Linux.

## Decisions

1. **Adopt with the tool, from `sandbox-ref-25` directly.** Commit this change
   directory on `main`, then run the dry run and `--apply`. `--apply` creates
   `adopt-sandbox-ref-28`.
2. **Hand-copied files on the same branch.**
   - `sandbox-container.ps1` becomes `pi-container.ps1`, byte for byte.
   - `.gitattributes` is copied. The adoption's uncommitted files are set
     aside with a named stash; then, on a clean tree,
     `git rm -r -q --cached . && git reset --hard` rewrites the working files.
   - The shared alignment tests then check the entry, ASCII and line endings.
3. **Pi's agent part stays as it is.** It already has the reference header and
   passes ShellCheck.
4. **Pi's own tests.**
   - `tests/test_setup_wrapper.py` takes the shared adapted file byte for byte,
     because the files matched before.
   - `tests/test_runtime.py` follows the same rule in its own structure:
     - an `engine_budgets()` helper reads the delegated controllers and the
       process mechanism through `network/agent_budgets.py`;
     - the hardening script tolerates a missing controller file and also
       prints the process rlimit, and `test_effective_hardening_and_budgets`
       asserts each budget by its mechanism, plus the launch notices;
     - `test_process_limit_enforced` uses a budget of 128 with 200 children,
       and is skipped when no mechanism applies.
   - Any other failure caused by a shared behavior change is fixed in Pi's test
     on the same branch. A failure in shared code pauses the change for a
     reference fix and a new tag.
5. **Parity rows after `--apply`.** No other wrapper is on `sandbox-ref-25`,
   so no row needs restoring. Check that every other row equals
   `sandbox-container`'s. Task 4.1 sets Pi's own row.
6. **Docs adapted, not copied.** The Codex text for the shared behavior moves
   into Pi's layout.
   - **`README.md`:**
     - a new `## Windows with Podman machine` section before
       `## Mounts and security`, with `### Trusting a host CA on Windows` and
       `### Install as a command`. It covers:
       - the provider default and the four API key methods with `$env:<KEY>`;
       - `pi-container.ps1` and the `PI_CONTAINER_*` variables;
       - `PI_NPM_CACHE_SIZE` through `PI_CONTAINER_ENV_VARS`, with distribution
         paths for the state variables;
       - `PI_CONTAINER_GITCONFIG`, which mounts the machine's `~/.gitconfig`;
       - the Windows limits, with Bitdefender;
     - the rejected-connection sentence points to the Windows section;
     - `### Host CA trust` gets the Podman machine note;
     - the guard as the confined init, next to the `--init` of unrestricted
       sessions;
     - `PI_NPM_CACHE_SIZE` in "Other variables" points to the Windows section;
     - in `### Session hardening, budgets and lifetime`:
       - the `systemd` and `cgroupfs` managers;
       - the process rlimit fallback, with its risk;
       - the Windows sensitive folders.
   - **`docs/setup.md`:**
     - the Windows setup and the authentication steps from Windows;
     - setup without a launch service;
     - the carriage-return check;
     - candidate tags;
     - the service endpoint for restricted modes;
     - the budget plan, replacing the stale statement that the controllers
       must be delegated.
   - **`AGENTS.md`:** `pi-container.ps1`, the Windows files, the ShellCheck and
     PowerShell checks, the Windows sensitive roots, and the cgroup manager and
     rlimit rule.
7. **Validation on this runner,** in Pi's checkout:
   - `python3 -m unittest tests.test_reference_copy tests.test_alignment` next
     to the `sandbox-container` checkout, with the sibling check not skipped;
   - the unit discovery in the disposable test container;
   - `bash tests/run-runtime.sh` in each of these modes:
     - `--wrapper`, `--shared`, `--setup` and `--setup-runtime`;
     - `--qualification`, `--guard` and `--network`;
     - the default runtime run;
   - from `sandbox-container`, `bash tools/shellcheck.sh ../pi-container` and
     `bash tools/powershell.sh ../pi-container`;
   - `git diff --check`.

   The runner's image is stale, so rebuild it first with
   `PI_CONTAINER_NETWORK=unrestricted PI_CONTAINER_MAINTENANCE=1
   pi-container.sh --container-build`, with host CA trust and the session's CA
   bundle behind the runner's TLS interception. For `--guard`, tag the guard
   toolchain as `development`. Record the image and the toolchain. The suites
   run one at a time, and not while the operator validates on Windows: the
   timing-sensitive shared tests failed under that load in the earlier
   adoptions.
8. **Validation on Windows.** The operator gets a bundle with snapshots of
   `pi-container` and `sandbox-container`, and these steps:
   1. `.\pi-container.ps1 --container-setup` with provider networking and the
      method of a key the operator has, such as `openrouter`. Check that setup
      names `$env:<KEY>` and `pi-container.ps1`, with no distribution path.
      The first setup builds the Pi images in the machine.
   2. A session from a project folder, with `$env:<KEY>` set: one prompt that
      reads a file of the folder, which runs a tool, then quit. Note the exit
      status. `podman ps -a` must list no container of the session.
   3. The npm cache size: with `$env:PI_NPM_CACHE_SIZE = '1g'`,
      `--container-shell -c 'df -h /pi-home/.npm'` shows 256M, then 1.0G once
      `$env:PI_CONTAINER_ENV_VARS = 'PI_NPM_CACHE_SIZE'` is set.
   4. `sandbox-container\tools\windows-validate.ps1 -Checkout
      C:\Work\pi-container`:
      - on Windows PowerShell 5.1 with `-Install -StopMachine`;
      - on PowerShell 7 without them.

   Each summary is copied after its run. A failed step pauses the change for a
   decision between a documented Windows limit and a fix.
9. **Parity rows across repositories.**
   - Pi's row names "Adopted `sandbox-ref-28`", with this adoption's results.
   - After the merge, Pi's row is copied into `sandbox-container` and the four
     other wrappers, one commit on `main` each.

## Risks / Trade-offs

- [Three tags at once widen the validation surface.] → Every runner mode that
  the tool lists runs, including `--guard`, plus `--wrapper` and the default
  runtime run.
- [`PI_NPM_CACHE_SIZE` needs an extra step on Windows.] → The README says so
  and Windows step 3 checks it.
- [The first build in the machine downloads Pi through the TLS
  interception.] → The bundle README requires
  `podman machine set --import-native-ca` and the host CA answer.
- [Installed qualification reports no longer match.] → After the merge, the
  operator reruns `--container-setup` on the Linux hosts and on Windows.
- [Timing-sensitive shared tests fail under load.] → Decision 7 runs the suites
  alone and records any rerun.
- [Two shared-code defects surfaced when the first Windows setup ran under
  load: candidate-tag cleanup crashes on a `podman image exists` timeout, and
  a timed-out qualification probe leaves its container.] → The operator
  decided to fix them in a dedicated `sandbox-container` change. This adoption
  records them and does not wait for that fix.

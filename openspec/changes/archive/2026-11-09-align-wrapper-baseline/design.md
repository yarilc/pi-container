# Design

## Context

After `narrow-exposed-state`, `pi-container.sh` (about 480 lines) runs in this order:

1. parses the options, with `--wrapper-help` as an alias;
2. reads `.version` and sets `image=${PI_IMAGE_NAME:-pi-container}`;
3. resolves the workspace and the worktree parent, and applies a sensitive-directory guard whose override is any nonempty `PI_ALLOW_UNSAFE_PWD`. The guard does not refuse `/tmp` or `/mnt/<letter>`;
4. resolves the gitconfig opt-in;
5. checks the tools and verifies the engine, with delegation through exact `PI_ENABLE_PODMAN=1` and `PI_PODMAN_SOCKET`;
6. validates state;
7. builds or checks the image for staleness;
8. passes `--memory=${PI_MEMORY_LIMIT:-4g} --cpus=${PI_CPU_LIMIT:-2} --pids-limit=${PI_PIDS_LIMIT:-512}` without validation, and `--timeout "$PI_RUN_TIMEOUT"` when nonempty;
9. reserves a name with `podman create` and attaches with `podman start`.

There are no ownership labels; owned IDs come from private `--cidfile` records.

Pi 0.80.8 (`pi --help`, measured on the current image on 2026-11-09):

- it has no tool-approval option;
- `--approve`/`-a` means "Trust project-local files for this run", and `--no-approve` ignores them.

Reference: the Codex, Antigravity and OpenCode budget, guard and lifetime blocks, which are identical apart from the prefix.

## Goals / Non-Goals

**Goals:**

- Same names, semantics, messages and verification as the other wrappers, without breaking existing scripts silently.
- All validation before the first engine query or state creation.
- An `AGENTS.md` and a help layout that match the other wrappers.

**Non-Goals:**

- Renaming `PI_ENABLE_BUN`, `PI_BUN_VERSION`, `PI_PULL_ALWAYS` and `PI_NPM_CACHE_SIZE`. They depend on the image design that `align-runtime-image` changes (A03/A06).
- Renaming `PI_NETWORK`, which becomes `PI_CONTAINER_NETWORK` with the Wave 3 port (C01).
- `PI_READONLY_CONFIG`, `PI_ENV_VARS` and `PI_DEBUG`, which keep their names. Their semantics are already aligned or specific to Pi, and renaming them is a separate cleanup.
- The base image digest, home and state (A03–A05), and ownership labels (C05).

## Decisions

### D1: Alias resolution

A helper `select_setting NEW OLD [switch]` runs right after option parsing:

- **New name set:** use it. If the old name is also set, compare the two. Exact-`1` switches are compared by meaning; other settings by text. A difference dies with `<OLD> and <NEW> conflict; set only <NEW>`, and equal values warn once.
- **Only the old name set:** warn `pi-container: <OLD> is deprecated; use <NEW>` and use its value.
- **Neither set:** leave the setting unset, so defaults still apply only to unset variables.

The helper records whether the result came from an unset variable, which the budgets need. It applies to all eight pairs.

`PI_ALLOW_UNSAFE_PWD` is a switch, so its old "any nonempty" meaning is not carried over: only `1` enables the override. The deprecation warning says so.

### D2: Budgets and lifetime

The Codex block is copied with the `PI_CONTAINER_` names and the `pi-container:` prefix:

- **Memory:** `^[1-9][0-9]{0,15}[kmgKMG]$`, converted to bytes and capped at 2^50.
- **CPU:** `^[0-9]{1,4}(\.[0-9]{1,3})?$`, converted to nano-CPUs, with a value above 0 and at most 1024.
- **Processes:** 1 to 4194304.
- **Lifetime:** `^(0|[1-9][0-9]{0,9})$`, at most 2^31-1.

`podman_args` uses the normalized values: `--memory=<bytes> --cpus=<text> --pids-limit=<n>`, plus `--timeout <n>` when the lifetime is above 0.

After the create loop and before `podman start`, a bounded `podman inspect --type container --format '{{.HostConfig.Memory}} {{.HostConfig.NanoCpus}} {{.HostConfig.PidsLimit}}'` must equal the expected triple. Otherwise the wrapper dies with the cgroup v2 diagnostic, and the existing EXIT cleanup removes the owned container. `started_at=$SECONDS` and the notice `pi-container: session lifetime limit reached (N s); exit status S` follow Codex.

### D3: Guard

The existing guard is replaced with the reference one. The `case` covers `/`, `/home`, `/root`, `/etc`, `/usr`, `/var`, `/bin`, `/sbin`, `/lib`, `/lib64`, `/boot`, `/opt`, `/srv`, `/mnt`, `/media`, `/proc`, `/sys`, `/dev`, `/run` and `/tmp`, plus the physical home and `^/mnt/[A-Za-z]$`. The override is exact `1` and prints the reference warning. The guard stays where it is, before engine queries, and Pi's resolution of `physical_home` is kept.

### D4: YOLO

There is no switch. A nonempty `PI_CONTAINER_YOLO` prints `pi-container: PI_CONTAINER_YOLO has no effect; Pi has no tool-approval layer and the container is the only boundary`, and nothing else changes.

### D5: Help, README and AGENTS.md

**Help** follows the Codex layout:

- usage and `Container options:` (with `--wrapper-help` noted as an alias);
- the lifecycle paragraph;
- `Environment:`, with every `PI_CONTAINER_*` variable and its default, the remaining `PI_*` variables, and a "Deprecated names" list;
- the security paragraph, including the no-approval statement.

**README:** the top-level sections are reordered into the common order:

- intro;
- requirements and rootless Podman setup;
- optional Podman API access;
- usage, which contains the existing wrapper modes, session lifecycle and usage examples;
- environment;
- mounts and security, with a new "Session hardening, budgets and lifetime" subsection and "Permissions";
- included tools: Bun, stale image detection, updating;
- verification;
- migration.

Content moves verbatim except for renamed variables. A sentence-level check against the previous file confirms that nothing is lost.

**`AGENTS.md`** is new, in Codex's "Repository Guidelines" structure:

- Project Structure;
- Build, Test, and Development Commands (`./test-wrapper.sh`, `bash tests/run-runtime.sh`, `./test.sh`, ShellCheck, hadolint, markdownlint);
- Coding Style;
- Testing Guidelines;
- OpenSpec Workflow, with the `# Spec Delta` and markdownlint conventions;
- Commit & Pull Request Guidelines;
- Security & Configuration, with the A10 controls.

It states that documentation is in English and that user communication follows the user's instructions.

### D6: Tests

**`tests/fake_podman.py`** answers the budget inspection, configurable through `FAKE_AGENT_BUDGETS` and `FAKE_INSPECT_STATUS`.

**`tests/test_wrapper.py`** gets:

- the alias table, with old alone, new alone, equal values, conflicts, and switch normalization;
- budgets: defaults, overrides and every rejected form, with no engine call;
- inspection mismatch and failure, removing only the owned container without start;
- the guard: each refused root, `/tmp`, `/mnt/d` refused while a project below it is accepted, the worktree parent, a symlink to `/etc`, and exact versus non-exact override, including the old alias;
- the lifetime argument and notice;
- the YOLO warning with unchanged arguments;
- help content.

Existing cases that use old names move to the new names, plus one alias case.

**`tests/test_runtime.py` and `tests/run-runtime.sh`** use the new names and add:

- effective capabilities, `NoNewPrivs` and cgroup v2 values, with default and overridden budgets, with and without delegation;
- process-limit enforcement;
- lifetime expiry with the notice and the observed status, and an early exit;
- a refused home workspace.

## Risks / Trade-offs

- **Scripts that set empty budget variables or nonstandard units (for example `4gb` or `512MiB`) now fail.** The error names the variable and the format, and the README migration covers it.
- **`PI_ALLOW_UNSAFE_PWD=yes` no longer overrides.** The deprecation warning states that only `1` works.
- **Hosts without delegated cgroup controllers.** Pi already passed the budgets, so such hosts failed at create before; now the failure is explicit, and the inspection also catches engines that ignore the limits.
- **Reordering the README loses content.** The sentence-level check guards against it.

## Migration Plan

1. Implement on branch `align-wrapper-baseline`. Unit suites run in the runner container, and real-engine checks with `bash tests/run-runtime.sh`.
2. Users keep their variables, with warnings, or switch to the `PI_CONTAINER_*` names. No rebuild is needed.
3. Rollback: revert the merge.

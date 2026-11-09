# Proposal: Align the Pi wrapper with the common baseline

## Why

Pi already has the strongest hardening of the five wrappers: capability drop, no-new-privileges, memory, CPU and process limits, a sensitive-directory guard and a lifetime limit. But it uses different names and semantics.

**Variable names:**

- `PI_IMAGE_NAME`, `PI_ENABLE_PODMAN`, `PI_PODMAN_SOCKET`;
- `PI_MEMORY_LIMIT`, `PI_CPU_LIMIT`, `PI_PIDS_LIMIT`, `PI_RUN_TIMEOUT`;
- `PI_ALLOW_UNSAFE_PWD`.

**Semantics:**

- budgets and the lifetime are passed to Podman unvalidated, and empty values silently select defaults;
- nothing checks that the engine applied the budgets;
- the guard accepts any nonempty override and does not refuse `/tmp` or WSL drive roots;
- no notice is printed when the lifetime limit stops a session.

Pi also has no `AGENTS.md`, and its help and README use a different layout. Unlike the other agents, Pi 0.80.8 runs its tools without asking for approval. Its only trust option, `--approve`, controls whether project-local files are trusted; it does not approve tools. The YOLO question therefore needs a documented answer rather than a switch.

This change closes todo A01, A02, A08 and A11, apart from the base digest, which belongs with the image work.

## What Changes

- **No YOLO switch (A01):** Pi has no tool-approval layer to bypass, so the outer container is the only boundary. Help, README and `AGENTS.md` state this, and that `--approve` is a different control. If `PI_CONTAINER_YOLO` is set, the wrapper prints a warning that it has no effect.
- **BREAKING (deprecated aliases kept), common names (A02, A11):**

  | Old name | New name |
  | --- | --- |
  | `PI_IMAGE_NAME` | `PI_CONTAINER_IMAGE` |
  | `PI_ENABLE_PODMAN` | `PI_CONTAINER_PODMAN` (exact `1`) |
  | `PI_PODMAN_SOCKET` | `PI_CONTAINER_PODMAN_SOCKET` |
  | `PI_MEMORY_LIMIT` | `PI_CONTAINER_MEMORY_LIMIT` |
  | `PI_CPU_LIMIT` | `PI_CONTAINER_CPU_LIMIT` |
  | `PI_PIDS_LIMIT` | `PI_CONTAINER_PIDS_LIMIT` |
  | `PI_RUN_TIMEOUT` | `PI_CONTAINER_RUN_TIMEOUT` |
  | `PI_ALLOW_UNSAFE_PWD` | `PI_CONTAINER_ALLOW_UNSAFE_WORKSPACE` |

  - Each old name still works and prints one deprecation warning.
  - Setting an old and a new name to different values, after normalization, stops with status 1 before engine queries.
  - `--wrapper-help` stays an alias of `--container-help`.
- **BREAKING, budgets (A11):** budgets follow Claude `sandbox-ref-2`.
  - Defaults are `4g`, `2` and `512`, and only an unset variable selects the default.
  - Values are validated before any engine query. Memory is a positive integer with unit `k`, `m` or `g`, CPU has at most 3 decimals up to 1024, and the process limit is 1 to 4194304.
  - Empty, zero, negative, `max` and malformed values stop with status 1.
  - After create and before start, the wrapper inspects the container and requires the configured limits to equal the selected budgets. A mismatch removes the owned container and names cgroup v2 controller delegation.
- **BREAKING, sensitive workspaces (A11):** the guard uses Claude's refused set on physical paths, which adds `/tmp` and `/mnt/<letter>` drive roots. Only the exact value `1` overrides it, with a warning; formerly any nonempty value did. The old `PI_ALLOW_UNSAFE_PWD` is honored only with `1`.
- **Lifetime (A11):** `PI_CONTAINER_RUN_TIMEOUT` accepts whole seconds up to 10 digits, and `0` or unset disables it. A lifetime stop prints a notice and keeps the client's exit status.
- **Documentation (A08):**
  - wrapper help uses the common "Container options / Environment" layout with every variable and default;
  - the README follows the common section order, adds the session hardening section and the migration from the old names, and moves the existing content;
  - a new `AGENTS.md` follows the common "Repository Guidelines" structure. It states that documentation is in English and that user communication follows the user's instructions.
- **Kept controls (A10):** capability drop, no-new-privileges, noexec temporary storage, the pinned Pi version, CI with hadolint and Trivy, and by-name forwarding stay unchanged.

## Capabilities

### New Capabilities

- `workspace-mounts`: refusal of sensitive workspace roots and the exact override. This is the common capability name; the existing workspace bind requirement stays in `container-isolation`.

### Modified Capabilities

- `container-launcher`:
  - common option and variable names with deprecated aliases;
  - the no-approval-layer statement;
  - wrapper help layout.
- `container-isolation`:
  - validated, verified budgets and their documentation;
  - the workspace bind requirement refers to the new guard.
- `container-podman-access`: `PI_CONTAINER_PODMAN` and `PI_CONTAINER_PODMAN_SOCKET` replace the old names, which become aliases.
- `container-session`: the lifetime limit with the notice.

## Impact

- **Wrapper:** `pi-container.sh` gets an alias resolution block, budget, lifetime and guard validation, post-create inspection, the lifetime notice and the help text.
- **Tests:** `tests/test_wrapper.py`, `tests/fake_podman.py` (budget inspection), `tests/test_runtime.py` and `tests/run-runtime.sh`, which use the new names.
- **Documentation:** `README.md`, the new `AGENTS.md`, `SECURITY.md`, `CONTRIBUTING.md`, `CHANGELOG.md`, `docs/validation.md`, `todo.md`.
- **Users:**
  - old variable names keep working with warnings;
  - empty or malformed budgets now fail;
  - `PI_ALLOW_UNSAFE_PWD` values other than `1` no longer override;
  - launching from `/tmp` or a drive root needs the override;
  - hosts without delegated cgroup v2 controllers can no longer start sessions.

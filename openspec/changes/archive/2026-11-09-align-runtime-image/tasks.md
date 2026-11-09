# Tasks

## 1. Image (A03, A11)

- [x] 1.1 Rewrite `Containerfile` per D1 and reduce `.containerignore` to the three inputs. Build with and without Bun. Verify:
  - `pi --version` reports 0.80.8, `openspec --version` 1.16.0 and, in the Bun build, `bun --version` 1.3.14;
  - every toolset command and `podman` exist;
  - a deliberately wrong `PI_VERSION` fails the build;
  - hadolint with `.hadolint.yaml` passes.
- [x] 1.2 Add `tests/test_image_pins.py`. Verify that it passes, and that it fails on mutated copies: a tag-only base, `@latest`, an unversioned package, a `curl | bash` installer, or a missing toolset package.

## 2. Wrapper (A04, A05, A06)

- [x] 2.1 Implement the build policy (D2): new hash inputs, a stale image stops, a missing image builds, build arguments without `INSTALL_PODMAN` and `BUN_VERSION`, and warnings for `PI_BUN_VERSION` and `PI_PULL_ALWAYS`. Update `tests/fake_podman.py`. Verify with wrapper tests:
  - stale label exits 1 naming `--container-build`, with no build or create;
  - missing image builds;
  - explicit build passes only `PI_VERSION` and `INSTALL_BUN`;
  - `PI_ENABLE_BUN` changes the hash;
  - one warning for each ignored variable.
- [x] 2.2 Implement the dedicated home (D3). Verify with wrapper tests: `HOME=/pi-home`, the tmpfs home, and state, npm and gitconfig at their fixed destinations; no host-home destination remains; the workspace bind is unchanged.
- [x] 2.3 Implement `PI_CONTAINER_STATE_DIR` (D4). Verify with wrapper tests:
  - writable mode creates the directory and its `.pi` and `.agents` privately and binds it at `/pi-home`, with no host state mount;
  - read-only mode mounts its `.pi` and `.agents` read-only and creates nothing;
  - relative, empty, insecure, foreign-owned and workspace-overlapping values exit 1 with no engine call;
  - host `~/.pi` is untouched.

## 3. Real-engine checks

- [x] 3.1 Update `tests/test_runtime.py`, `tests/run-runtime.sh` and `test.sh` per D5. Verify that `./test.sh` (Bun build) and `bash tests/run-runtime.sh` pass with no credentials or model requests, including:
  - the home layout;
  - Pi, npm extension installation and Git;
  - isolated persistence;
  - the tool inventory and OpenSpec;
  - the delegated client;
  - Bun 1.3.14;
  - every existing check.

## 4. Documentation and evidence

- [x] 4.1 Update help, README (image and toolset, "Updating pinned image inputs", build policy, home layout, isolated state, migration), `AGENTS.md`, SECURITY.md and CHANGELOG.md. Verify that a help test lists `PI_CONTAINER_STATE_DIR` and the ignored variables, and that markdownlint and `git diff --check` pass.
- [x] 4.2 Run the full unit suite in the runner container, `bash -n`, ShellCheck, hadolint, `./test.sh` and `bash tests/run-runtime.sh`. Add a dated `docs/validation.md` section covering the baseline comparison, npm facts, results, initial failures and reruns, and pinned versions. Verify that `openspec validate align-runtime-image --strict` passes.
- [x] 4.3 Mark A03, A04, A05, A06 and A10 and the digest part of A11 in `todo.md`, and note that Wave 2 is complete for all five wrappers. Verify that the notes name the change and the evidence section.

## Workflow follow-up

- Archive, commit and merge when the user asks; the user pushes.
- Wave 2 is then complete; next is Wave 3 (network port) starting with Codex.

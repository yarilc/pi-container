# Design

## Context

See proposal.md for the motivation.

`ci.yml` has three jobs, and each has a local equivalent or a weak effect:

| Job | What it runs | Local equivalent today |
| --- | --- | --- |
| `lint` | ShellCheck, hadolint on three Containerfiles, markdownlint on `README.md` | `AGENTS.md`, Build, Test, and Development Commands: `tools/shellcheck.sh` from `sandbox-container`, and hadolint and markdownlint through containers, on more files than the CI |
| `test` | `test-wrapper.sh`, 14 unittest modules, `test.sh` with a rootless Podman service on the runner | the same commands, run in the working session (`AGENTS.md`, Change workflow and validation environments) |
| `scan` | Trivy on the runtime and egress images, on push and weekly | none; `exit-code: '0'` and an empty `.trivyignore`, so it reports and never fails |

`dependabot.yml` opens weekly PRs for the actions and for the `docker` ecosystem, that is the base image digest. Pinned inputs already change only through a change, as described in "Updating pinned image inputs" in the README.

## Goals / Non-Goals

**Goals:**
- The repository has no hosted pipeline and no file that only a pipeline reads.
- No document describes the CI, Trivy or Dependabot as current behavior.

**Non-Goals:**
- Adding a hosted pipeline elsewhere, or a replacement CVE scanner.
- Rewriting history: past `CHANGELOG.md` entries and earlier `docs/validation.md` sections.
- Changing GitHub repository settings, which are outside the repository files.

## Decisions

### D1. Remove CVE scanning entirely, `.trivyignore` included

The scan never gated a change, and none of the other five wrappers scans. A local Trivy command in `AGENTS.md` would be one more maintained section, for a check that nothing enforces.

The user did not answer the question in explore mode; this is the recommendation given there. If the user wants a local scan, the alternative is a `podman run … aquasec/trivy image …` line in `AGENTS.md`, with `.trivyignore` kept. That changes 1.1, 2.1 and 2.4 only.

### D2. What the documents say instead

- **`AGENTS.md`, Security & Configuration:** keep the hardening list and replace "CI with hadolint and Trivy" with "Containerfiles that pass hadolint", pointing to the lint commands above.
- **`CONTRIBUTING.md`:**
  - the linters line drops "(optional, run in CI)" and says that `AGENTS.md` runs them through containers;
  - the pull-request step "CI must pass (lint, test, scan)" becomes running the tests and linters of `AGENTS.md` in the working environment.
- **`README.md`:**
  - "Weekly CI scans monitor the built image for CVEs." becomes a pointer to "Updating pinned image inputs", where the base image digest is updated;
  - the `.github/workflows/ci.yml` line leaves the file layout.
- **`SECURITY.md`, Supply Chain:** drop the Trivy sentence and the paragraph on GitHub Actions and Dependabot. The rest of the section already states that every input is pinned and checked by `tests/test_image_pins.py`.
- **`CHANGELOG.md`:** one bullet under Unreleased, `### Removed`.

Two mentions of CI stay, because neither describes this repository's pipeline:
- the README heading "Non-interactive use (piped input, CI/CD)", which describes the user's own CI;
- `docs/validation.md`, lines 76-78, part of a past session record.

## Risks / Trade-offs

- [No automatic signal for new CVEs in the base image or Debian packages] → the operator updates the pinned inputs through a change ("Updating pinned image inputs"). D1 names the local alternative if this proves too little.
- [Open Dependabot PRs and Dependabot alerts stay on GitHub] → listed under follow-up after closure, for the user.
- [markdownlint cannot run in the session: no image in the engine, no network] → recorded in `docs/validation.md` as unavailable, and under follow-up after closure.

# Proposal

## Why

pi-container is the only repository of the sandbox family with GitHub pipelines: `.github/workflows/ci.yml` (lint, tests, Trivy scan) and `.github/dependabot.yml` (weekly update PRs for actions and the base image). The other five wrappers have none. The family's rule is that a change is validated in the working session, and every lint and test that the CI runs is already documented as a local command in `AGENTS.md`. The Trivy scan never gates anything (`exit-code: '0'`, empty `.trivyignore`). The pipelines are an extra, hosted maintenance surface that the family does not use.

## What Changes

- Remove `.github/workflows/ci.yml`, `.github/dependabot.yml`, and `.trivyignore`, whose only reader is the CI's Trivy step.
- Align the documents that describe the CI as part of the project:
  - `AGENTS.md`, Security & Configuration: "CI with hadolint and Trivy" becomes the local hadolint lint;
  - `CONTRIBUTING.md`: the prerequisites line "(optional, run in CI)" and the pull-request step "CI must pass (lint, test, scan)";
  - `README.md`: the sentence on weekly CI scans of the base image, and the `.github/workflows/ci.yml` entry in the file layout;
  - `SECURITY.md`, Supply Chain: the weekly Trivy scans, the SHA-pinned GitHub Actions, and Dependabot.
- Add an entry under `### Removed` in the Unreleased section of `CHANGELOG.md`. Historical entries stay as they are.
- Add a section to `docs/validation.md` with this change's working-session checks and the checks the session cannot run. Earlier sections record past sessions, including the GitHub-hosted CI they mention, and stay as they are.
- No behavior of the wrapper, the image, or the shared core changes.

## Capabilities

### New Capabilities

### Modified Capabilities

None. No requirement in `openspec/specs/` mentions CI, Trivy or Dependabot. "Verifiable operational documentation" in `container-launcher` names the documents, not the pipelines. The change sets `skip_specs: true`.

## Impact

- Files removed: `.github/workflows/ci.yml`, `.github/dependabot.yml`, `.trivyignore`.
- Files edited: `AGENTS.md`, `CONTRIBUTING.md`, `README.md`, `SECURITY.md`, `CHANGELOG.md`, `docs/validation.md`.
- The reference `sandbox-container` does not propagate `.github`, and no test of pi-container reads it. Shared code and alignment are unaffected.
- GitHub: after the push, no workflow runs and Dependabot opens no version-update PRs. Dependabot PRs that are already open, and Dependabot security alerts, are repository settings outside the repository files, so they remain for the user to close or disable.

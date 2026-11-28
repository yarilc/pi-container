# Tasks

## 1. Remove the pipelines

- [x] 1.1 Remove `.github/workflows/ci.yml`, `.github/dependabot.yml` and `.trivyignore` with `git rm` (D1), so that no `.github` directory is left. Verify that `git ls-files .github .trivyignore` prints nothing and that `test -e .github` fails.

## 2. Align the documents (D2)

- [x] 2.1 In `AGENTS.md`, Security & Configuration, replace "and CI with hadolint and Trivy" with Containerfiles that pass hadolint, pointing to the lint commands in Build, Test, and Development Commands. Keep the rest of the hardening list unchanged. Verify with `git grep -n -i -e trivy -e '\bCI\b' AGENTS.md`, which prints nothing.
- [x] 2.2 In `CONTRIBUTING.md`:
  - the linters prerequisite says that `AGENTS.md` runs them through containers, instead of "(optional, run in CI)";
  - the pull-request step "CI must pass (lint, test, scan)" becomes running the tests and linters of `AGENTS.md` in the working environment.

  Verify with `git grep -n -w CI CONTRIBUTING.md`, which prints nothing.
- [x] 2.3 In `README.md`:
  - replace "Weekly CI scans monitor the built image for CVEs." with a pointer to "Updating pinned image inputs";
  - remove the `.github/workflows/ci.yml` line from the file layout.

  Verify with `git grep -n -e '\.github' -e 'CI scan' README.md`, which prints nothing, and check that the heading "Non-interactive use (piped input, CI/CD)" is unchanged.
- [x] 2.4 In `SECURITY.md`, Supply Chain, drop the weekly Trivy sentence and the paragraph on SHA-pinned GitHub Actions and Dependabot. Keep the pinned-input text and the pointer to "Updating pinned image inputs". Verify with `git grep -n -i -e trivy -e dependabot -e 'github actions' SECURITY.md`, which prints nothing.
- [x] 2.5 In `CHANGELOG.md`, add one bullet under Unreleased, `### Removed`: the GitHub pipelines (`ci.yml`, `dependabot.yml`) and `.trivyignore`, with lints and tests run locally as described in `AGENTS.md`. Verify that the bullet is inside the Unreleased section and that the older entries are unchanged (`git diff CHANGELOG.md` shows one added bullet only).

## 3. Integration checks and record

- [x] 3.1 Check that nothing still describes the pipelines, and that the repository's checks pass:
  - `git grep -n -i -e '\.github' -e dependabot -e trivy -e '\bCI\b' -- ':!openspec/changes'` matches only:
    - the historical entries of `CHANGELOG.md`, below Unreleased;
    - the earlier sections of `docs/validation.md`;
    - the README heading "Non-interactive use (piped input, CI/CD)";
    - unrelated host names such as `api.github.com`;
  - `python3 -B -m unittest tests.test_reference_copy tests.test_alignment -v` passes on the host Python, with the sibling checkouts present;
  - `git diff --check` passes;
  - `openspec validate remove-github-pipelines --strict` passes.
- [x] 3.2 Add the section "Removal of the GitHub pipelines (`remove-github-pipelines`): 2026-11-28" at the end of `docs/validation.md`. It holds:
  - the environment line and a table of the 3.1 results;
  - markdownlint as unavailable in the session (no `markdownlint-cli2` and no tool image in the session engine, no network to pull one);
  - a "Follow-up after closure" list with each item marked pending.

  Verify by reading the new section against the format of the `sandbox-ref-36` section: blank lines around headings, lists and the table.

## Follow-up after closure

- Run markdownlint on the edited Markdown with the `AGENTS.md` container command, on a host that has the image.
- After the push, check on GitHub that the new commit starts no workflow run.
- Close the Dependabot PRs that are still open.
- Decide whether to turn off Dependabot alerts and security updates in the repository settings.

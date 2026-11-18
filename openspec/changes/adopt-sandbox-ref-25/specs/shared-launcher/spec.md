# Spec Delta

## Purpose

Defines how Pi's launcher is built from the shared Bash core of the `sandbox-container` reference and Pi's own agent part, so launcher behavior is specified, fixed and tested once for all wrappers.

## ADDED Requirements

### Requirement: Launcher runs on the shared core
`pi-container.sh` SHALL be the thin entry script of the reference. It SHALL be identical to the reference's `sandbox-container.sh` after the wrapper name is replaced, and SHALL only source `launcher/core.sh` with `agent/launcher.sh` and its arguments. `launcher/core.sh` SHALL be a byte-identical copy from the adopted reference tag, recorded in the reference-copy manifest. Pi SHALL NOT keep launcher logic outside the core and its agent part.

#### Scenario: Core edited in this wrapper
- **WHEN** `launcher/core.sh` differs from the adopted reference tag
- **THEN** the reference-copy test fails naming the file

#### Scenario: Entry script compared with the reference
- **WHEN** `pi-container.sh` is compared with the reference entry script after replacing the wrapper name
- **THEN** they are identical

### Requirement: Pi agent launcher part
`agent/launcher.sh` SHALL hold Pi's profile data for the core, consistent with `agent/profile.json` and `agent/policies/default.json`, including a credential entry for each policy profile of the default policy. Pi's hooks SHALL be `agent_validate`, `agent_mounts`, `agent_build_args`, `agent_approval_bypass` and `agent_help`. Every other hook SHALL use the core default.

#### Scenario: Profile and launcher part disagree
- **WHEN** `agent/launcher.sh` and `agent/profile.json` or the default policy declare different values for the same property
- **THEN** the shared alignment test fails naming the property

#### Scenario: Credential entries
- **WHEN** the alignment test reads `AGENT_CREDENTIALS`
- **THEN** it lists `anthropic-api=ANTHROPIC_API_KEY`, `openai-api=OPENAI_API_KEY`, `gemini-api=GEMINI_API_KEY` and `openrouter-api=OPENROUTER_API_KEY`

#### Scenario: Help documents the agent variables
- **WHEN** `--container-help` runs without Podman or `.version`
- **THEN** after the common variables it lists `PI_CONTAINER_YOLO`, `PI_CONTAINER_GITCONFIG`, `PI_NPM_CACHE_SIZE` and each profile's credential with its forwarding rule, and states that the container is the only boundary around Pi's tools

### Requirement: Pi session settings from the agent part
The agent part SHALL make every build receive `PI_VERSION` from the first line of the installed `.version`; a launch SHALL stop before any image operation when `.version` is missing or empty. Offline and provider sessions SHALL receive `PI_OFFLINE=1`, `PI_SKIP_VERSION_CHECK=1` and `PI_TELEMETRY=0` after toolchain and forwarded variables.

#### Scenario: Version from the installation
- **WHEN** a launch builds the image and `.version` holds `0.80.8`
- **THEN** the build receives `--build-arg PI_VERSION=0.80.8`, and `.version` is one of the hashed build inputs

#### Scenario: Restricted settings win
- **WHEN** a toolchain sets `PI_TELEMETRY=1` or `PI_CONTAINER_ENV_VARS` lists `PI_OFFLINE` in an offline or provider session
- **THEN** the session has `PI_TELEMETRY=0` and `PI_OFFLINE=1`
- **AND** the forwarding list skips `PI_OFFLINE` with a notice

### Requirement: Pi npm cache from the agent part
Every session SHALL have a `noexec` tmpfs at `/pi-home/.npm` of `PI_NPM_CACHE_SIZE` (default `256M`). An invalid size SHALL stop the launch before any engine operation.

#### Scenario: Npm cache size
- **WHEN** `PI_NPM_CACHE_SIZE=1g` is set
- **THEN** `/pi-home/.npm` is a 1 GiB `noexec` tmpfs
- **AND** a value such as `lots` stops the launch before any engine query naming the variable

### Requirement: Pi launcher tests cover only Pi's part
Pi's launcher behavior SHALL be tested by the shared `tests/test_launcher.py` and `tests/fake_podman.py`, copied unchanged from the reference tag. `tests/test_wrapper.py` SHALL test only Pi's hooks, agent data, credential rules per policy profile and shipped policy inventories. A Pi launcher case that the shared tests do not cover SHALL be added to the reference first, not kept as a wrapper copy.

#### Scenario: Wrapper runtime tests
- **WHEN** `bash tests/run-runtime.sh --wrapper` runs
- **THEN** it runs both `tests/test_launcher.py` and `tests/test_wrapper.py` against this checkout

#### Scenario: Disposable acceptance image
- **WHEN** `test.sh` prepares its disposable image
- **THEN** it builds it through `pi-container.sh --container-build`, so the image carries the core's `build-inputs-hash`

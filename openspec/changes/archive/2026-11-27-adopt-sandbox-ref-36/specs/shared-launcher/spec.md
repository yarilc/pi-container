# Spec Delta

## MODIFIED Requirements

### Requirement: Pi launcher tests cover only Pi's part

Pi's launcher behavior (including leftover delegation refusal, session container engine wiring, and budgets) SHALL be tested by the shared `tests/test_launcher.py` and `tests/fake_podman.py`, copied unchanged from `sandbox-ref-36`. `tests/test_wrapper.py` SHALL test only Pi's hooks, agent data, credential rules per policy profile, and shipped policy inventories. A Pi launcher case that the shared tests do not cover SHALL be added to the reference first, not kept as a wrapper copy.

#### Scenario: Wrapper runtime tests

- **WHEN** `bash tests/run-runtime.sh --wrapper` runs
- **THEN** it runs both `tests/test_launcher.py` and `tests/test_wrapper.py` against this checkout

#### Scenario: Disposable acceptance image

- **WHEN** `test.sh` prepares its disposable image
- **THEN** it builds it through `pi-container.sh --container-build`, so the image carries the core's `build-inputs-hash`

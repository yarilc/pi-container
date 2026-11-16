# Spec Delta

## ADDED Requirements

### Requirement: Guard runtime test uses the wrapper's native home
The shared guard runtime test SHALL run the real Pi image with the wrapper's own native home mounted writable, as the launcher does, so that an agent command that writes to its home at startup runs under the production guard.

#### Scenario: Agent command writes to its home
- **WHEN** `bash tests/run-runtime.sh --guard` runs the production guard with the Pi image and its command creates directories under its native home
- **THEN** the guarded production-container test passes without a read-only file system error

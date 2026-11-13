## MODIFIED Requirements

### Requirement: Caller identity without additional capabilities

Sessions SHALL use keep-id user namespaces and the caller's numeric UID/GID, drop all capabilities without additions, and retain no-new-privileges and configured resource limits. Pi, npm extension installation and Git SHALL operate without namespace-root privileges using the declared writable locations.

#### Scenario: Non-root workflow

- **WHEN** a caller starts a session and writes workspace/state files, installs an npm extension, or commits a disposable Git change
- **THEN** the process and resulting files use the caller's identity and no DAC_OVERRIDE, CHOWN, SETGID, or SETUID capability is added.

## MODIFIED Requirements

### Requirement: Protected complete installation
Setup SHALL prepare all files needed for the selected workflow in a native installation outside writable workspace, worktree-parent and state trees. Those files include the shared launcher core and the agent launcher part.

Setup SHALL validate ownership, ancestor permissions and overlaps, and SHALL create missing private directories. It SHALL refuse unsafe existing paths without recursive permission repair, credential imports, relabeling or added privileges.

Managed launches SHALL verify the entry script, the launcher core and the agent launcher part as protected files. Setup and its smoke checks SHALL ignore host values of `PI_CONTAINER_ENV_VARS` and `PI_CONTAINER_READONLY_STATE`.

#### Scenario: Checkout on a Windows mount
- **WHEN** setup runs from a checkout on a permission-emulating Windows filesystem and the user selects a valid native installation
- **THEN** it copies the required installation inputs to native storage and validates them there
- **AND** it does not require executing a compiled guard on the source mount

#### Scenario: Unsafe installation or state path
- **WHEN** a chosen path has unsafe ancestors, cannot enforce private permissions or overlaps an application-writable mount
- **THEN** setup identifies the path and fails without modifying existing permissions or claiming completion

#### Scenario: Installed launcher core
- **WHEN** setup completes an installation
- **THEN** the release contains `launcher/core.sh` and `agent/launcher.sh` as protected files, and a managed launch refuses a release where either is writable by others

### Requirement: Runtime image built through the Pi wrapper
Setup SHALL build a new runtime image by running the installed release's `pi-container.sh --container-build` without Pi arguments, under maintenance authorization and with the candidate image tag, then inspect the candidate's immutable identity. The profile SHALL declare no `install.runtime_build` field: every wrapper's setup builds this way. The build SHALL use the same build arguments and `build-inputs-hash` label as a launch and start no session. A reused runtime image SHALL keep its labels. When host CA trust is enabled, setup SHALL pass the trust selection and the selected bundle to that build, and the wrapper SHALL give the bundle to its runtime build only as the non-persisted `build-ca` secret.

#### Scenario: Fresh runtime build
- **WHEN** approved setup has no reusable runtime image
- **THEN** the wrapper builds the candidate tag with Pi from `.version` and a `build-inputs-hash` label that matches the installed inputs
- **AND** the managed launcher and the smoke check accept the image without a staleness stop

#### Scenario: Build failure
- **WHEN** the wrapper build fails or the candidate tag cannot be inspected afterwards
- **THEN** setup reports the runtime build stage and leaves the last working installation selected

#### Scenario: Stale reusable image
- **WHEN** the reusable runtime image carries a staleness label that does not match the installed inputs
- **THEN** the smoke check stops with the stale-image message instead of declaring the sandbox ready, and a rerun with refresh rebuilds it through the wrapper

#### Scenario: Bun is not selected by setup
- **WHEN** setup runs, or a managed launch starts, with `PI_ENABLE_BUN` set in the operator's environment
- **THEN** the setup-built image matches the launch's inputs, so neither setup nor the launch stops as stale
- **AND** the image contains no Bun

#### Scenario: Wrapper-built runtime with host CA trust
- **WHEN** setup prepares the runtime image with host CA trust enabled
- **THEN** the wrapper's build receives the selected bundle as the `build-ca` secret, and the built image contains neither the bundle nor its temporary copy

#### Scenario: Wrapper-built runtime without host CA trust
- **WHEN** setup prepares the runtime image with host CA trust disabled
- **THEN** the wrapper's build receives no build secret and no host CA bundle

### Requirement: Persistent non-secret managed launch preferences
Setup SHALL save versioned non-secret preferences and a managed launcher usable from any workspace without exports. Preferences and launcher code SHALL stay outside application-writable mounts and be validated before use. The launcher SHALL preserve arguments, stdin, terminal handling and the current directory. Direct invocation SHALL accept explicit runtime modes. An unset or empty effective mode SHALL select Pi's provider default, which needs the provider settings or gets setup guidance.

#### Scenario: New terminal and workspace
- **WHEN** the user invokes the managed launcher in a new terminal from a separate workspace
- **THEN** the saved network, profile, state, service, CA and approval choices apply without modifying shell startup files
- **AND** the current directory determines the mounted workspace and container working directory

#### Scenario: Explicit environment overrides
- **WHEN** a supported runtime variable is explicitly present in the launch environment
- **THEN** its value, including an empty value, takes precedence over the saved default
- **AND** the effective configuration still passes existing conflict, privacy and enforcement checks

#### Scenario: Unsafe or malformed preferences
- **WHEN** managed preferences are untrusted, invalid or use an unsupported schema
- **THEN** the launcher fails before image operations or container creation without evaluating their contents as shell code

#### Scenario: Invoked dispatcher or alias is writable
- **WHEN** an invocation uses a dispatcher copy or a symlink chain with any entry inside a writable workspace or state mount
- **THEN** launch fails before application execution even if the configured command and final symlink target are protected
- **AND** relative paths and dot-dot components are interpreted with filesystem symlink semantics

#### Scenario: Legacy managed dispatcher needs migration
- **WHEN** an old managed dispatcher cannot identify its actual invocation path to the installed helper
- **THEN** normal launch fails with setup guidance while help and setup remain available
- **AND** setup atomically upgrades the recognized dispatcher without overwriting unrelated command files

#### Scenario: Saved mode supplies launch configuration
- **WHEN** a validated managed launcher supplies saved offline, provider or unrestricted mode and there is no network environment override
- **THEN** the wrapper uses that mode instead of its default
- **AND** existing mode-specific readiness and qualification checks still determine whether an application can start

#### Scenario: Empty network override is not replaced
- **WHEN** an operator explicitly sets `PI_CONTAINER_NETWORK` to an empty value for a managed launch whose saved mode is offline or unrestricted
- **THEN** the empty value overrides the saved mode and the wrapper applies its provider default, with setup guidance when the provider settings are missing
- **AND** it does not silently restore the saved mode

#### Scenario: Explicit direct operator workflow
- **WHEN** an operator invokes the wrapper directly with a valid nonempty network mode and its required configuration
- **THEN** it proceeds through existing runtime checks without requiring managed preferences
- **AND** mode selection alone does not authorize maintenance, delegation or restricted qualification

# container-setup Specification

## Purpose

Provide an interactive, repeatable host-side procedure that prepares a usable Pi sandbox, builds its runtime image through the Pi wrapper, persists non-secret working preferences and reports remaining prerequisites, including the provider API key to supply, honestly.

## Requirements

### Requirement: Dedicated interactive setup invocation
`--container-setup` SHALL run a dedicated setup operation before normal runtime preflight. It SHALL require an interactive terminal, reject combinations with launch options or Pi arguments, and never start an ordinary Pi session implicitly. Wrapper help SHALL remain side effect free and describe setup.

#### Scenario: Setup before runtime configuration exists
- **WHEN** an interactive user requests setup with missing provider settings or an absent image
- **THEN** the questionnaire and prerequisite diagnosis run without requiring those settings first
- **AND** setup is not forwarded to Pi

#### Scenario: Unattended or ambiguous invocation
- **WHEN** setup has no interactive terminal or is combined with shell, build, worktree or Pi arguments
- **THEN** it fails with usage guidance before mutations or image operations

#### Scenario: Help takes precedence
- **WHEN** wrapper help is requested together with setup and invalid configuration
- **THEN** help succeeds without loading managed preferences, prompting or requiring Podman

### Requirement: Workflow questionnaire with explicit defaults

Setup SHALL explain and collect network mode, provider authentication method when relevant, state sharing, installation paths, host CA trust, permission bypass and workspace scope. First-run defaults SHALL select provider networking, the first authentication method of the profile (`anthropic` for Pi), shared state and disabled optional authority. Existing saved choices SHALL be offered for review on rerun. When no same-host launch service is available, the network choice SHALL follow the rule for setup without a launch service instead.

#### Scenario: First setup choices

- **WHEN** the user reviews first-run defaults on a host where a same-host launch service is reachable or can be started
- **THEN** network options distinguish offline, provider-restricted and unrestricted use, and provider questions list the four API-key methods with their hosts
- **AND** accepting the first-run network/authentication defaults selects provider/`anthropic` without requiring the key to be set yet
- **AND** shared host credentials, isolated fresh state, worktree-parent exposure and permission bypass are explained before selection

#### Scenario: Provider selected

- **WHEN** the user chooses provider mode and the `openrouter` method without `OPENROUTER_API_KEY` set, and a same-host launch service is reachable or can be started
- **THEN** setup selects the protected `openrouter-api` profile and reports authentication as pending
- **AND** each other method selects its own separate profile

#### Scenario: Previously saved network mode

- **WHEN** setup is rerun with a saved configuration, including explicit offline mode, and a same-host launch service is reachable or can be started
- **THEN** the saved network mode remains the proposed choice instead of the first-run provider default

### Requirement: Optional authority requires deliberate selection

Setup SHALL explain and require explicit selection of unrestricted networking, permission bypass, worktree-parent exposure and host CA trust. Setup SHALL NOT offer host Podman delegation. Enabling the host launch service SHALL NOT implicitly grant its socket to the application.

#### Scenario: Restricted networking and delegation conflict

- **WHEN** a rerun finds saved preferences that enable delegation, with any network mode
- **THEN** setup explains that delegation was removed and that image toolchains replace it, and saves the preferences without it
- **AND** it never silently broadens networking

#### Scenario: Launch service without delegation

- **WHEN** setup enables the API service for restricted launch
- **THEN** no saved setting grants its socket, or any other Podman socket, to the application

### Requirement: Installed host prerequisites only
Setup SHALL check that Podman is installed and the chosen engine supports Linux rootless operation. It SHALL diagnose missing user-session, rootless, native-storage and selected-mode dependencies with actionable guidance. It SHALL NOT install host packages, invoke privilege escalation, edit subordinate ID ranges, enable lingering or modify system-wide WSL configuration.

#### Scenario: Podman missing or rootless unavailable
- **WHEN** Podman is absent or the engine cannot operate rootlessly
- **THEN** setup stops before image operations and reports the prerequisite and next action
- **AND** no package manager, sudo command or rootful fallback runs

#### Scenario: Unsupported restricted platform
- **WHEN** the selected restricted mode fails the existing platform or enforcement prerequisites
- **THEN** setup reports that mode as unavailable and does not publish a ready configuration or select unrestricted mode automatically

### Requirement: User-scoped Podman service preparation
When the selected workflow needs a same-host Unix Podman service, setup SHALL reuse a verified endpoint or offer to enable and start `podman.socket` through a working systemd user session. Service changes SHALL require confirmation. The resulting endpoint SHALL pass existing rootless verification before image operations or container creation.

#### Scenario: User socket activation accepted
- **WHEN** a service is required, the systemd user manager is usable and the user confirms enablement
- **THEN** setup enables and starts the user socket and verifies the exact selected Unix endpoint
- **AND** it reports the persistent user-service change

#### Scenario: Existing explicit service
- **WHEN** the user selects an existing same-host Unix endpoint
- **THEN** setup validates and uses that endpoint without replacing it or enabling an unrelated socket
- **AND** unsupported remote or named contexts remain rejected

#### Scenario: No working systemd user session
- **WHEN** a needed service is unavailable and user socket activation is unavailable or declined
- **THEN** setup prints the applicable foreground-service and runtime-directory instructions and reports incomplete setup until an endpoint is verified
- **AND** it does not start an unmanaged background daemon or change the host init system

### Requirement: Reviewed setup mutations and maintenance
Setup SHALL show selected settings, paths, service changes and required image acquisition/builds before applying them. It SHALL obtain explicit consent for mutations and maintenance, explaining that host pulls and build steps are outside runtime network filtering. Maintenance authorization SHALL be limited to approved setup operations and never persisted as a launch default.

#### Scenario: Review declined
- **WHEN** the user declines the proposed filesystem/image changes before preparation
- **THEN** no installation is activated and no image pull or build occurs
- **AND** any previously approved service change is reported separately

#### Scenario: Approved build
- **WHEN** the user approves preparation requiring image builds
- **THEN** only the approved maintenance operations receive exact maintenance authorization
- **AND** ordinary subsequent launches still require separate authorization for missing-image builds or refreshes

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

### Requirement: Mode-specific image and guard preparation

Setup SHALL inspect or prepare the runtime image and the additional components required by the selected mode. Every mode SHALL also receive the session engine image (`localhost/pi-container-engine:latest`), built from its digest-pinned base, and the engine seccomp profile derived from the engine host's default profile. Restricted modes SHALL receive a validated static guard and digest manifest; provider mode SHALL also receive a valid selected policy, private runtime directory and immutable proxy image identity. Existing suitable artifacts SHALL be reused unless refresh is approved.

#### Scenario: Fresh provider setup

- **WHEN** provider setup is approved with no prepared artifacts
- **THEN** setup prepares the pinned build inputs, toolchain, runtime, engine and proxy images, compiles the guard and validates its manifest and policy
- **AND** launch preferences refer to an inspected immutable proxy image rather than an unresolved local tag

#### Scenario: Offline or unrestricted setup

- **WHEN** setup prepares offline mode
- **THEN** it prepares the runtime, the guard and the engine image without requiring a provider proxy image or authentication
- **AND** unrestricted setup requires neither the restricted guard nor provider proxy components

#### Scenario: Preparation fails

- **WHEN** an image build, image inspection, guard compilation or validation fails
- **THEN** setup reports the failed stage and leaves the last working installation selected
- **AND** it does not substitute a different policy, toolchain or network mode

#### Scenario: Engine image and profile recorded

- **WHEN** setup prepares any mode
- **THEN** the installation records the engine image identity and the engine seccomp profile, and a later setup reuses them unless their inputs or the engine host's default profile changed

### Requirement: Persistent non-secret managed launch preferences

Setup SHALL save versioned non-secret preferences (schema 3) and a managed launcher usable from any workspace without exports. Preferences and launcher code SHALL stay outside application-writable mounts and be validated before use. The launcher SHALL preserve arguments, stdin, terminal handling and the current directory. Direct invocation SHALL accept explicit runtime modes. An unset or empty effective mode SHALL select Pi's provider default, which needs the provider settings or gets setup guidance. The saved workspace scope SHALL apply only to session launches: host management commands such as `--container-toolchain` SHALL reach the wrapper with their arguments unchanged.

#### Scenario: New terminal and workspace

- **WHEN** the user invokes the managed launcher in a new terminal from a separate workspace
- **THEN** the saved network, profile, state, service, CA, workspace-scope and approval choices apply without modifying shell startup files
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
- **AND** mode selection alone does not authorize maintenance or restricted qualification

#### Scenario: Toolchain command with the saved worktree scope

- **WHEN** setup saved the worktree scope and the operator runs the managed launcher with `--container-toolchain list`, on Linux or through the Windows entry
- **THEN** the toolchain command lists the library and no session starts
- **AND** a session started by the same launcher still mounts the parent of the current directory

### Requirement: Credential-preserving authentication assistance
Setup SHALL offer the profile's API-key methods and SHALL NOT copy credentials, collect or persist API keys or tokens in setup preferences, or call a model. Authentication SHALL use the chosen installed sandbox and preserve its selected network and CA policies. When a profile has no interactive login method, setup SHALL report authentication as pending with the variable to supply.

#### Scenario: API key unavailable
- **WHEN** an API-key method is selected but its variable is not set
- **THEN** sandbox preparation can complete with authentication explicitly pending and instructions for supplying the key through the existing runtime mechanism
- **AND** no paid model request is made automatically

#### Scenario: Method names the forwarded key
- **WHEN** the operator selects `anthropic`, `openai`, `gemini` or `openrouter`
- **THEN** setup saves the matching protected profile and names `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, `GEMINI_API_KEY` or `OPENROUTER_API_KEY` as the next authentication action
- **AND** it publishes no port and adds no host-network exception for a browser callback

### Requirement: Verified readiness with separate authentication status
Setup SHALL declare the selected sandbox ready only after installed-path checks, engine verification, artifact validation and a smoke launch succeed through the actual selected runtime path. Restricted candidates SHALL additionally pass the installation enforcement gate and publish its protected matching report before activation. Completion output SHALL separately report authentication as verified, pending or not applicable, provide the launch/rerun commands and identify PATH requirements.

#### Scenario: Sandbox smoke check succeeds
- **WHEN** the selected installation passes its smoke check
- **THEN** setup reports sandbox readiness and the resolved managed launch command
- **AND** a version or shell smoke check alone does not imply authenticated provider success

#### Scenario: Login or optional authentication check skipped
- **WHEN** the sandbox is usable but authentication was skipped, unavailable or failed
- **THEN** setup reports sandbox ready and authentication pending with the appropriate next command
- **AND** it does not claim a working authenticated model request

#### Scenario: Enforcement check fails
- **WHEN** the restricted gate cannot install required enforcement, fails a required control or cannot publish a protected matching report
- **THEN** setup reports incomplete setup, returns nonzero and does not activate the candidate installation

#### Scenario: Setup repeats qualification after relevant updates
- **WHEN** setup prepares changed kernel, engine/backend, security-policy state, protected enforcement code, container hardening or effective image/policy identities
- **THEN** it reruns qualification for the candidate and preserves the previous activation until successful report publication
- **AND** interruption or failed revalidation never replaces the previous report with an apparent pass

#### Scenario: Local qualification and measured acceptance differ
- **WHEN** a candidate passes locally on a combination without recorded full release acceptance
- **THEN** setup identifies it as locally qualified and not release-measured
- **AND** active SELinux/AppArmor is reported without guaranteeing compatibility or claiming authentication success

### Requirement: Repeatable setup with owned recovery

Rerunning setup SHALL review saved choices and reuse valid artifacts. Activation SHALL preserve the previous working installation until the candidate passes validation. Cancellation, interruption or failure SHALL remove only setup-owned temporary resources, preserve credentials and unrelated containers, and report persistent changes already made. Concurrent setup runs SHALL NOT overwrite each other's activation.

#### Scenario: Rerun or interrupted update

- **WHEN** setup is rerun unchanged or interrupted while preparing an update
- **THEN** unchanged suitable artifacts need no rebuild and the last activated launcher remains usable
- **AND** any created images or enabled user socket remaining after interruption are reported without deleting shared resources

#### Scenario: Abandoned candidate tags

- **WHEN** setup fails, is cancelled or is interrupted after it tagged images `setup-<release>` for its candidate release
- **THEN** it removes those tags before exiting, keeps every other tag of the same images and the tags of retained releases and other installation roots, and reports an image left without a name with the command that removes it

#### Scenario: Competing activation

- **WHEN** another setup already holds the target installation's update lock
- **THEN** setup exits with an actionable busy message without modifying that installation

#### Scenario: Unrelated launcher exists

- **WHEN** the desired command path contains a file not owned by this setup
- **THEN** setup offers a different path or stops without overwriting that file

#### Scenario: Managed command path changes

- **WHEN** a validated candidate chooses a different physical command entry
- **THEN** activation retires the previous owned command only after publishing the new command
- **AND** retirement or publication failure restores the previous activation and command
- **AND** two path spellings of the same physical entry do not cause its removal

#### Scenario: Group leader exits before timeout cleanup

- **WHEN** a setup-owned process group has surviving descendants after its leader exits or its captured pipes close
- **THEN** timeout or interruption cleanup terminates the remaining owned group within bounded teardown time
- **AND** the primary timeout/interruption remains the reported outcome

### Requirement: Protected installation qualification records
Qualification SHALL produce a versioned non-secret report outside all application-writable mounts, bound to the actual engine/host and enforcement inputs. It SHALL record required check outcomes, control evidence and environment identities. Only a complete successful result SHALL authorize the matching restricted workflow; agent-controlled settings SHALL NOT manufacture qualification.

#### Scenario: Successful atomic publication
- **WHEN** the candidate completes every mandatory gate check
- **THEN** setup publishes the protected matching report atomically before activating the candidate
- **AND** the report identifies kernel/boot, architecture, ABI, engine/backend, security policy, guard/code, images, mode/profile/policy, hardening and gate revision
- **AND** it contains no credentials, model content or authentication URLs

#### Scenario: Invalid or unsafe report
- **WHEN** a report is missing, malformed, incomplete, stale, symlink-escaped or accessible through an application-writable mount
- **THEN** it cannot establish readiness and setup reports the reason without repairing existing permissions

#### Scenario: Manual protected installation
- **WHEN** an operator prepares restricted assets without the managed setup workflow
- **THEN** an explicit qualification operation can generate the same report using only protected fixtures and disposable synthetic state
- **AND** normal application execution cannot use that operation to bypass report validation

### Requirement: Agent profile in the protected installation
Setup SHALL install the agent profile and its provider policy file together with the shared sandbox components, validate them in the native installation, and use them as qualification inputs. Rollback SHALL restore the profile matching the restored installation.

#### Scenario: Installation from a checkout
- **WHEN** setup prepares a native installation from a checkout
- **THEN** it copies and validates the profile and provider policy with the other protected inputs before candidate qualification and activation

#### Scenario: Rollback after failed activation
- **WHEN** setup restores a previous installation after a failed update
- **THEN** the restored profile, policy, code and qualification report belong to the same installation

#### Scenario: Declared agent installation files
- **WHEN** setup prepares a Pi installation
- **THEN** it also installs `.version`, which the profile declares in `install.files` and the wrapper reads on every launch, and qualification binds it as installed code

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

### Requirement: Provider residual exfiltration acknowledgement
When provider mode is selected, setup SHALL show a residual-exfiltration notice before authentication questions. The notice SHALL state that the allowed hosts of the selected profile can receive workspace data sent with attacker-supplied credentials. Setup SHALL require explicit acknowledgement. Declining SHALL return to the network-mode choice and SHALL NOT select another mode on the operator's behalf. The acknowledgement is not stored.

#### Scenario: Operator acknowledges the notice
- **WHEN** the operator selects provider mode and acknowledges the notice
- **THEN** setup continues with the authentication question
- **AND** the setup plan and saved preferences are otherwise unchanged

#### Scenario: Operator declines the notice
- **WHEN** the operator selects provider mode and declines the acknowledgement
- **THEN** setup asks for the network mode again, with no mode silently substituted
- **AND** no installation, image or state mutation has occurred

#### Scenario: Rerun or non-provider mode
- **WHEN** setup is rerun with saved provider mode, or offline or unrestricted mode is selected
- **THEN** a provider selection asks for the acknowledgement again
- **AND** offline and unrestricted selections do not show the provider notice

### Requirement: Setup collects agent resource budgets and session lifetime
Setup SHALL ask for the agent memory, CPU and process budgets and the optional session lifetime. It SHALL validate each answer with the same rules as the wrapper and repeat the question after an invalid answer. First-run defaults SHALL be `4g`, `2`, `512` and `0` (disabled). On rerun, the saved values SHALL be proposed. The setup plan SHALL list the selected values before confirmation.

#### Scenario: First setup accepts defaults
- **WHEN** the user accepts the proposed budget and lifetime answers on first setup
- **THEN** the saved preferences contain memory `4g`, CPU `2`, processes `512` and lifetime `0`
- **AND** the setup plan shows these values before the apply confirmation

#### Scenario: Invalid answer is asked again
- **WHEN** the user answers `0`, `max`, `-1` or a unitless memory value to a budget question
- **THEN** setup explains the accepted format and asks the same question again without saving anything

#### Scenario: Rerun proposes saved values
- **WHEN** setup is rerun after saving memory `8g` and lifetime `3600`
- **THEN** those values are the proposed answers

### Requirement: Saved budgets govern managed launches and verification

The managed launcher SHALL supply the saved budgets and lifetime through `PI_CONTAINER_MEMORY_LIMIT`, `PI_CONTAINER_CPU_LIMIT`, `PI_CONTAINER_PIDS_LIMIT` and `PI_CONTAINER_RUN_TIMEOUT` when these are absent from the launch environment. An explicitly present variable SHALL take precedence. Setup smoke and qualification SHALL use the saved values for every budget the engine can enforce, through its cgroup controller or the process rlimit fallback.

#### Scenario: Managed launch uses saved budgets

- **WHEN** the user launches through the managed command with no budget variables exported
- **THEN** the agent container receives the saved budgets and lifetime
- **AND** a restricted launch matches the qualification report produced by setup

#### Scenario: Explicit override differs from qualified values

- **WHEN** the user exports `PI_CONTAINER_MEMORY_LIMIT=16g` for a restricted managed launch qualified with `4g`
- **THEN** the override is used and the qualification check stops the launch with requalification guidance

#### Scenario: Smoke verifies saved values

- **WHEN** setup runs its installed smoke check
- **THEN** the smoke compares the effective cgroup limits of every cgroup-enforced budget with the saved budgets, not with ambient environment values
- **AND** when the process budget uses the rlimit fallback, it compares the effective soft and hard process rlimit with the saved process budget
- **AND** it requires every budget whose controller is missing to have no cgroup limit

#### Scenario: Setup plan names unenforced budgets

- **WHEN** setup runs on an engine that does not delegate the `cpu` controller
- **THEN** the setup plan lists the CPU budget as not enforced, with the missing controller, and setup continues without an extra question

#### Scenario: Setup plan names the process rlimit fallback

- **WHEN** setup runs on an engine that does not delegate the `pids` controller, on a host that counts the process rlimit per container
- **THEN** the setup plan lists the process budget as enforced through the process rlimit, with the missing controller, and setup continues without an extra question

#### Scenario: Setup plan names a cgroup manager without limits

- **WHEN** setup runs on a rootless engine with the `cgroupfs` cgroup manager that reports every controller
- **THEN** the setup plan lists no enforced cgroup budget, names the `cgroupfs` manager as the reason for the memory and CPU budgets, and lists the process budget mechanism
- **AND** setup continues without an extra question

### Requirement: Preferences without budgets are migrated
Setup SHALL read saved preferences from earlier schema versions that lack budget and lifetime fields. It SHALL fill in the first-run defaults as proposed answers. New installations SHALL always be saved with the current schema. Unknown fields or unsupported schema versions SHALL still be rejected.

#### Scenario: Rerun from an earlier installation
- **WHEN** setup is rerun over an installation whose preferences use the previous schema
- **THEN** setup proposes the default budgets and lifetime and saves the activated release with the current schema

#### Scenario: Unsupported schema
- **WHEN** preferences declare an unknown schema version or contain an unknown field
- **THEN** setup and the launcher fail before image operations, as before

### Requirement: Host CA trust covers setup package fetches
When host CA trust is enabled, setup SHALL give the selected CA bundle to the runtime image and guard toolchain builds only as a non-persisted build secret, so their HTTPS package fetches verify on TLS-intercepting networks. Without host CA trust, setup SHALL pass no host CA to any build. The proxy build SHALL never receive it.

#### Scenario: Toolchain build on a TLS-intercepting network
- **WHEN** setup prepares the guard toolchain with host CA trust enabled and a bundle containing the interception CA
- **THEN** the toolchain package fetches verify against that bundle and the build completes
- **AND** the toolchain image contains neither the bundle nor its temporary copy

#### Scenario: Host CA trust disabled
- **WHEN** setup prepares images with host CA trust disabled
- **THEN** no build receives a host CA bundle, and the toolchain build verifies only against the base image's certificates

### Requirement: Setup without a launch service offers only unrestricted networking

Before asking for the network mode, setup SHALL check, read-only, whether a same-host Unix launch service answers at `CONTAINER_HOST`, the saved endpoint or the default endpoint, and whether a usable systemd user manager could start one. When neither holds, setup SHALL offer only unrestricted networking, explain why and require explicit confirmation.

#### Scenario: Host without systemd user manager or service

- **WHEN** setup runs where no launch service answers and `systemctl --user` is missing or fails, as in a Podman machine distribution on WSL
- **THEN** setup states that offline and provider networking need a same-host service and that none is available or startable
- **AND** it asks for explicit confirmation of unrestricted networking and saves the local engine as the launch endpoint

#### Scenario: Local endpoint leaves CONTAINER_HOST unset

- **WHEN** the saved launch endpoint is the local engine
- **THEN** the smoke check and managed launches run Podman without `CONTAINER_HOST`, and the launcher treats an empty `CONTAINER_HOST` or `CONTAINER_CONNECTION` as unset, because Podman treats a set variable as a remote context even when it is empty

#### Scenario: Confirmation declined

- **WHEN** the user declines unrestricted networking in that situation
- **THEN** setup ends with status 1 without changes and explains how to make a service available: start a same-host Podman service, or set `CONTAINER_HOST` to its Unix endpoint, then rerun setup

#### Scenario: Saved restricted mode without a service

- **WHEN** setup is rerun with saved offline networking and no service is reachable or startable any longer
- **THEN** setup does not propose offline, states that the saved mode cannot be kept, and changes to unrestricted only after explicit confirmation

#### Scenario: Service reachable or startable

- **WHEN** a launch service answers at one of the checked endpoints, or a usable systemd user manager exists
- **THEN** setup offers every mode the profile allows, as before

#### Scenario: Explanation names no runtime directory

- **WHEN** setup explains how to make a service available
- **THEN** the explanation refers to the setup guide and names no socket path derived from `XDG_RUNTIME_DIR`

### Requirement: Installation inputs with carriage returns are refused

Before copying installation inputs into a new release, setup SHALL refuse any input file that contains a carriage return byte. The refusal SHALL name the file, explain that release files must have LF line endings, point to the repository's `.gitattributes` and the renormalization step, and leave the last working installation selected.

#### Scenario: CRLF checkout

- **WHEN** an installation input in the checkout contains CRLF line endings
- **THEN** setup stops with status 1 naming that file and the renormalization step, before creating the release

#### Scenario: LF checkout

- **WHEN** every installation input has LF line endings
- **THEN** setup copies the inputs as before

### Requirement: Setup started by the Windows entry

When the Windows entry starts setup, setup SHALL omit the shell `PATH` guidance and the managed-command lines for launching and reviewing setup from its plan and summary, and SHALL state that the Windows entry starts sessions. Its pending authentication steps SHALL name `<name>.ps1` and PowerShell's `$env:`, not the managed command. Setup started from a Linux shell SHALL keep that guidance.

#### Scenario: Setup from the Windows entry

- **WHEN** the user runs `<name>.ps1 --container-setup`, or `--container-install` runs setup from the installed copy
- **THEN** the setup output contains no `export PATH=` line, no shell startup file and no distribution path of the managed command, and the entry then prints how to start sessions

#### Scenario: Login postponed from the Windows entry

- **WHEN** setup started by the Windows entry selects a method with login arguments and the user declines the login
- **THEN** the next authentication action is `<name>.ps1` followed by the login arguments, with no distribution path

#### Scenario: API key method from the Windows entry

- **WHEN** setup started by the Windows entry selects a method with a credential variable `<KEY>`
- **THEN** it says to set `$env:<KEY>` in PowerShell before running `<name>.ps1`

#### Scenario: Setup from a Linux shell

- **WHEN** setup runs from a Linux shell whose `PATH` lacks the managed command directory
- **THEN** it prints the `export PATH=` guidance and the managed-command lines as before

### Requirement: Restricted modes propose a service endpoint

When the selected workflow needs a same-host Unix service and the saved launch endpoint is the local engine, setup SHALL propose `default` as the launch endpoint instead of the saved value.

#### Scenario: From unrestricted to offline

- **WHEN** a rerun moves an installation that saved unrestricted networking and the local endpoint to offline networking, and the user accepts the proposed endpoint
- **THEN** setup saves the `default` endpoint without refusing the answer first

#### Scenario: Unrestricted rerun

- **WHEN** a rerun keeps unrestricted networking
- **THEN** setup still proposes the saved local endpoint

### Requirement: Saved delegation preferences are migrated

Setup SHALL accept saved preferences that enable delegation or name a delegation socket. It SHALL drop both settings, say what replaces them, and save preferences without them. The managed launcher SHALL refuse saved preferences that still enable delegation before any engine query, with guidance to rerun setup.

#### Scenario: Rerun with saved delegation

- **WHEN** setup runs over preferences that enable delegation in unrestricted mode
- **THEN** it keeps the other saved choices as proposals, states that delegation was removed, and the saved result has no delegation or delegation socket

#### Scenario: Launch with saved delegation

- **WHEN** a managed launch reads preferences that still enable delegation, because setup was not rerun
- **THEN** it exits nonzero before any engine query, asking to rerun setup

### Requirement: Setup re-verifies the toolchain library

After setup prepares the runtime image of a new release, it SHALL rerun the check of every installed toolchain whose verified base differs from that release's base, and record the new base for each check that passes. A failed check SHALL NOT fail setup: setup SHALL name the toolchain and its failure, and the toolchain SHALL keep its previous verified base.

#### Scenario: Base changed by an update

- **WHEN** a default toolchain was verified on the previous base and setup installs a release with a new base
- **THEN** setup reruns its check, and new sessions get its default environment without a manual `verify`

#### Scenario: Check fails after an update

- **WHEN** the rerun check of a toolchain fails on the new runtime image
- **THEN** setup completes with its usual result, names the toolchain and the failed check, and new sessions give that toolchain no default environment, with the launcher's usual warning

#### Scenario: Nothing to re-verify

- **WHEN** no toolchain is installed, or every installed toolchain was verified on the new base
- **THEN** setup runs no toolchain check

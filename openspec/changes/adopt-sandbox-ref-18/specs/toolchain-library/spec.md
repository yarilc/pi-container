# Spec Delta

## MODIFIED Requirements

### Requirement: Verified against the runtime image
Before accepting a toolchain, `add` SHALL run the recipe's check command with the toolchain's `env.sh` in the wrapper's runtime image, without network, with the session's identity and hardening, and with the working directory set to `/`, and SHALL fail if it fails. The manifest SHALL record the digest-pinned base image named by the installed `Containerfile`. `verify` SHALL rerun the check and update that record.

#### Scenario: Incompatible toolchain
- **WHEN** the check command fails in the runtime image, for example because the toolchain needs a newer C library
- **THEN** `add` fails, shows the command output, and the library is unchanged

#### Scenario: Verified base recorded
- **WHEN** `add` succeeds
- **THEN** the manifest names the base image digest from the installed `Containerfile` and the verification date

#### Scenario: Check on a host with a domain UID
- **WHEN** `add` or `verify` runs as a caller whose UID cannot be used for an engine-side chown under `--userns=keep-id`, with a runtime image whose `WORKDIR` is missing from its layers
- **THEN** the check container starts in `/`, and the engine creates no working directory

### Requirement: Session variables are protected from toolchains
A toolchain SHALL NOT set a variable that the session or a wrapper owns. Profile variables are the running wrapper's prefix, configuration, approval-bypass and credential variables, and the agent variables its profile declares; every other protected variable is neutral and the same in every wrapper. `add` SHALL reject both. `launch-env` SHALL fail on a neutral variable in the index, and SHALL leave a profile variable out of the session with one warning naming the toolchain and the variable.

#### Scenario: Other session variables stay protected
- **WHEN** a recipe sets `HOME`, `PATH`, an `LD_` variable, a proxy or CA variable, the profile's configuration variable, or a variable with the wrapper's or the `SANDBOX_` prefix
- **THEN** `add` fails naming the variable as protected

#### Scenario: Agent variable in a recipe
- **WHEN** a recipe sets a variable that the profile declares as an agent variable, or one that starts with a declared agent prefix, for example `PI_OFFLINE` or `ANTHROPIC_BASE_URL` in Pi
- **THEN** `add` fails naming the variable as protected, and the library is unchanged

#### Scenario: XDG variable in a recipe
- **WHEN** a recipe sets `XDG_DATA_HOME`, `XDG_CONFIG_HOME`, `XDG_CACHE_HOME`, `XDG_STATE_HOME`, `XDG_RUNTIME_DIR` or another `XDG_` variable
- **THEN** `add` fails naming the variable as protected, and the library is unchanged

#### Scenario: Bus variable in a recipe
- **WHEN** a recipe sets `DBUS_SESSION_BUS_ADDRESS`
- **THEN** `add` fails naming the variable as protected in every wrapper, and the library is unchanged

#### Scenario: XDG variable in an existing index
- **WHEN** the library index lists a default toolchain with an `XDG_` variable
- **THEN** `launch-env` fails with an invalid-environment error, and the session does not start with that variable

#### Scenario: Another wrapper's variable in the shared index
- **WHEN** the shared index lists a default toolchain that sets a variable protected only by the current wrapper's profile, for example its credential or an agent variable, because another wrapper installed it
- **THEN** `launch-env` succeeds without that variable, still emits the toolchain's `PATH` entries and other variables, and prints one warning naming the toolchain and the variable

#### Scenario: Wrapper state location kept
- **WHEN** a wrapper places its state with XDG variables, and default toolchains are installed
- **THEN** new sessions keep the wrapper's XDG values

## ADDED Requirements

### Requirement: Agent variables are declared in the profile
The agent profile SHALL be able to declare the variables and variable prefixes that the agent reads, as an optional list. The profile loader SHALL reject an entry that is not a valid variable name or prefix, a duplicate, or an entry that names a neutral protected variable. A profile without the list SHALL keep the previous protection.

#### Scenario: Valid declaration
- **WHEN** a profile declares `PI_` and `GOOGLE_API_KEY`
- **THEN** the profile loads, and both are profile variables for the toolchain library

#### Scenario: Invalid declaration
- **WHEN** a profile declares an entry with a lowercase name, a space, a duplicate, or `PATH`
- **THEN** the profile loader fails naming the field

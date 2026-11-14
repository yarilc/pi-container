# Spec Delta

## MODIFIED Requirements

### Requirement: Session variables are protected from toolchains

A toolchain SHALL NOT set a variable that the session or a wrapper owns. Profile variables are the running wrapper's prefix, configuration, approval-bypass and credential variables; every other protected variable is neutral and the same in every wrapper. `add` SHALL reject both. `launch-env` SHALL fail on a neutral variable in the index, and SHALL leave a profile variable out of the session with one warning naming the toolchain and the variable.

#### Scenario: Other session variables stay protected

- **WHEN** a recipe sets `HOME`, `PATH`, an `LD_` variable, a proxy or CA variable, the profile's configuration variable, or a variable with the wrapper's or the `SANDBOX_` prefix
- **THEN** `add` fails naming the variable as protected

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

- **WHEN** the shared index lists a default toolchain that sets a variable protected only by the current wrapper's profile, for example its credential, because another wrapper installed it
- **THEN** `launch-env` succeeds without that variable, still emits the toolchain's `PATH` entries and other variables, and prints one warning naming the toolchain and the variable

#### Scenario: Wrapper state location kept

- **WHEN** a wrapper places its state with XDG variables, and default toolchains are installed
- **THEN** new sessions keep the wrapper's XDG values

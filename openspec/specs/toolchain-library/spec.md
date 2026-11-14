# toolchain-library Specification

## Purpose

Let the operator supply extra toolchains to agent sessions from a host library shared by all wrappers, read-only and without Podman access, network changes or session restarts.

## Requirements

### Requirement: Shared operator-managed library

The toolchain library SHALL be one host directory shared by all wrappers, `${XDG_DATA_HOME:-$HOME/.local/share}/sandbox-toolchains` unless `PI_CONTAINER_TOOLCHAINS_DIR` names another absolute path. It SHALL be caller-owned and private (`0700`), and SHALL NOT be, contain or lie inside the workspace, a state directory or the installation. Only the operator's `--container-toolchain` command SHALL change it.

#### Scenario: Default location

- **WHEN** neither `XDG_DATA_HOME` nor `PI_CONTAINER_TOOLCHAINS_DIR` is set
- **THEN** the library is `$HOME/.local/share/sandbox-toolchains` for every wrapper

#### Scenario: Unsafe library rejected

- **WHEN** the library is group- or world-accessible, owned by another user, or overlaps the workspace, a state directory or the installation
- **THEN** the session launch fails before any container or image operation, naming the library path
- **AND** the toolchain command fails the same way for an unsafe mode or owner, or an overlap with the installation or a state directory

### Requirement: Relocatable toolchains from pinned sources

A toolchain SHALL be described by an operator recipe with a name, a version, one source, relative `PATH` entries, environment variables, required toolchains, notes for the agent, a check command and a default flag. The source SHALL be a subpath of an OCI image referenced by `@sha256:` digest, or a local archive file with its SHA-256. An environment value SHALL be a path relative to the toolchain root or a literal. Names SHALL match `[a-z0-9][a-z0-9._-]{0,63}`.

#### Scenario: Image source without digest

- **WHEN** a recipe names an image by tag only
- **THEN** `add` fails without pulling or changing the library

#### Scenario: Archive checksum mismatch

- **WHEN** the archive's SHA-256 differs from the recipe
- **THEN** `add` fails and the library is unchanged

#### Scenario: Unsafe archive content

- **WHEN** the source contains absolute paths, parent traversal, device nodes or links that resolve outside the toolchain root
- **THEN** `add` fails and the library is unchanged

#### Scenario: Literal environment value

- **WHEN** a recipe sets `GOCACHE` to the literal `/tmp/go-build` and `JAVA_HOME` to the toolchain root
- **THEN** `env.sh` exports `/tmp/go-build` and `/toolchains/<name>` respectively
- **AND** a value containing a newline or a NUL character is rejected

#### Scenario: Extracted permissions

- **WHEN** a toolchain is installed
- **THEN** its files belong to the caller, keep their executable bits, and have no setuid or setgid bit

### Requirement: Toolchain command on the host

`--container-toolchain` SHALL be used alone with `add <recipe>`, `list`, `remove <name>` or `verify [<name>]`. It SHALL run on the host without starting an agent session. `add` with an image source SHALL require exact `PI_CONTAINER_MAINTENANCE=1` when the image must be pulled. Changes SHALL be serialized by a library lock and applied atomically, so that a reader sees either the previous or the new toolchain and index, never a partial one.

#### Scenario: Pull without maintenance

- **WHEN** `add` needs to pull an image and `PI_CONTAINER_MAINTENANCE` is not exactly `1`
- **THEN** the command fails naming the maintenance variable, without pulling

#### Scenario: Concurrent changes

- **WHEN** two `--container-toolchain` commands change the library at the same time
- **THEN** they run one after the other and the index lists the result of both

#### Scenario: Replace and remove

- **WHEN** `add` installs a name that already exists, or `remove` deletes one
- **THEN** the old directory is replaced or removed only after the new state is complete, and the index is regenerated

#### Scenario: Required toolchains

- **WHEN** a recipe requires a toolchain that is not installed, or `remove` targets a toolchain that another one requires
- **THEN** the command fails naming the missing or dependent toolchain, and the library is unchanged

### Requirement: Verified against the runtime image

Before accepting a toolchain, `add` SHALL run the recipe's check command with the toolchain's `env.sh` in the wrapper's runtime image, without network and with the session's identity and hardening, and SHALL fail if it fails. The manifest SHALL record the digest-pinned base image named by the installed `Containerfile`. `verify` SHALL rerun the check and update that record.

#### Scenario: Incompatible toolchain

- **WHEN** the check command fails in the runtime image, for example because the toolchain needs a newer C library
- **THEN** `add` fails, shows the command output, and the library is unchanged

#### Scenario: Verified base recorded

- **WHEN** `add` succeeds
- **THEN** the manifest names the base image digest from the installed `Containerfile` and the verification date

### Requirement: Self-describing library for the agent

The library SHALL contain a generated `toolchains.md` and `index.json`, and each toolchain SHALL contain a manifest and an `env.sh`. `toolchains.md` SHALL state the usage rules: the toolchains are read-only, the agent must not install toolchains or system packages, and it should ask the operator for missing ones. It SHALL list each toolchain with its version, commands, environment, required toolchains, notes, `env.sh` usage and verified base.

#### Scenario: One instruction is enough

- **WHEN** an agent is told only to read `/toolchains/toolchains.md`
- **THEN** that file gives it the installed toolchains and the exact command form `. /toolchains/<name>/env.sh && <command>`

#### Scenario: env.sh sets the toolchain environment

- **WHEN** a session runs `. /toolchains/<name>/env.sh`
- **THEN** that shell has the environment of each required toolchain, then the toolchain's own `PATH` entries first and its environment variables set

#### Scenario: Notes reach the agent

- **WHEN** a recipe has notes, such as setting `GOTMPDIR` under the workspace for `go test`
- **THEN** `toolchains.md` shows them in that toolchain's entry

### Requirement: Read-only session mount with live updates

Every session SHALL mount the library at `/toolchains` read-only with `nosuid` and `nodev`, unless `PI_CONTAINER_TOOLCHAINS=0` is set. The launcher SHALL create the library privately when it is missing. A toolchain added or removed on the host SHALL become visible to running sessions without a restart. The mount SHALL add no network, IPC or socket access.

#### Scenario: Toolchain added during a session

- **WHEN** the operator adds a toolchain while a provider-mode session is running
- **THEN** the session can run its check command through `env.sh` without a restart, under the same network restrictions

#### Scenario: Library is read-only for the agent

- **WHEN** a process in the session tries to create, change or remove a file under `/toolchains`
- **THEN** the operation fails

#### Scenario: Mount disabled

- **WHEN** `PI_CONTAINER_TOOLCHAINS=0` is set
- **THEN** the session has no `/toolchains` mount and no toolchain environment

### Requirement: Default toolchain environment for new sessions

A new session SHALL receive, appended after the runtime image's `PATH`, the `PATH` entries of every default toolchain whose verified base matches the installed `Containerfile`, and its environment variables. Default entries SHALL NOT shadow commands of the runtime image. A toolchain verified on another base SHALL get no default environment, and the launcher SHALL print one warning naming it and `verify`.

#### Scenario: Default toolchain on PATH

- **WHEN** a default toolchain verified for the current base is installed and a session starts
- **THEN** its commands run by name and its environment variables are set

#### Scenario: Default toolchain does not replace the agent's runtime

- **WHEN** a default Node.js or Python toolchain is installed and a session starts
- **THEN** `node` and `python3` still resolve to the runtime image's versions, and the toolchain's versions are used through `env.sh` or by their full path

#### Scenario: Base changed since verification

- **WHEN** the installed `Containerfile` names a base different from a toolchain's verified base
- **THEN** that toolchain stays visible under `/toolchains` but gets no default environment, and the launcher warns once naming it and `verify`

### Requirement: Default toolchains do not conflict

`add` SHALL reject a default toolchain whose commands or environment variable names overlap with another default toolchain. A non-default toolchain SHALL be usable only through its `env.sh` or full paths.

#### Scenario: Conflicting defaults

- **WHEN** `add` installs a second default toolchain that also provides `java` or sets `JAVA_HOME`
- **THEN** it fails and names the conflicting toolchain; the recipe can set `default: false` and the toolchain is then used through `env.sh`

### Requirement: Untested security modules are documented

Documentation SHALL state that the toolchain library was not tested with SELinux or AppArmor enforcement, and that tools must be profiled by the operator on such hosts.

#### Scenario: Operator reads the toolchain documentation

- **WHEN** an operator reads the README toolchain section
- **THEN** it states that SELinux and AppArmor enforcement are untested for the library mount

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

### Requirement: Pi session settings win over toolchain variables

The Pi launcher SHALL pass the default toolchain environment before its own session variables, so that the variables it sets itself keep their values even when a toolchain names them outside the protected set. In restricted sessions these include `PI_OFFLINE`, `PI_SKIP_VERSION_CHECK` and `PI_TELEMETRY`.

#### Scenario: Toolchain sets a Pi setting

- **WHEN** a default toolchain's index entry sets `PI_TELEMETRY=1` and a restricted session starts
- **THEN** the session still has `PI_TELEMETRY=0`, `PI_OFFLINE=1` and `PI_SKIP_VERSION_CHECK=1`

# Spec Delta

## ADDED Requirements

### Requirement: Host Git configuration requires exact opt-in

The wrapper SHALL mount the caller's `~/.gitconfig` read-only at the same path only when `PI_CONTAINER_GITCONFIG` is exactly `1`, using the physical file as source. Any other value SHALL leave it unmounted. An opt-in without a regular `~/.gitconfig` file SHALL stop with status 1 naming the variable and the path, before any engine query or state creation. No other host Git configuration file SHALL be mounted.

#### Scenario: Default launch with an existing gitconfig

- **WHEN** `~/.gitconfig` exists and neither `PI_CONTAINER_GITCONFIG` nor `PI_MOUNT_GITCONFIG` is set
- **THEN** the generated engine arguments contain no mount of `~/.gitconfig`

#### Scenario: Exact opt-in

- **WHEN** `PI_CONTAINER_GITCONFIG=1` is set and `~/.gitconfig` is a regular file or a symlink to one
- **THEN** its physical file is mounted read-only at `$HOME/.gitconfig`, and a write attempt inside the session fails

#### Scenario: Non-exact opt-in

- **WHEN** `PI_CONTAINER_GITCONFIG` is `true`, `yes`, empty or any value other than `1`
- **THEN** `~/.gitconfig` is not mounted

#### Scenario: Opt-in without a file

- **WHEN** `PI_CONTAINER_GITCONFIG=1` is set and `~/.gitconfig` is missing or not a regular file
- **THEN** the wrapper exits with status 1 naming the variable and path, with no engine query or state creation

### Requirement: Deprecated gitconfig variable

`PI_MOUNT_GITCONFIG` SHALL remain a deprecated alias that prints one stderr warning naming `PI_CONTAINER_GITCONFIG`. Alone, `1` SHALL behave as the opt-in and `0` as the default. Values other than `0` and `1` SHALL stop with status 1 before engine queries.

#### Scenario: Old opt-in value

- **WHEN** only `PI_MOUNT_GITCONFIG=1` is set and `~/.gitconfig` exists
- **THEN** the file is mounted read-only and stderr contains one deprecation warning

#### Scenario: Conflicting values

- **WHEN** `PI_MOUNT_GITCONFIG=0` and `PI_CONTAINER_GITCONFIG=1` are both set, or `PI_MOUNT_GITCONFIG=1` and `PI_CONTAINER_GITCONFIG` is set to another value
- **THEN** the wrapper exits with status 1 naming both variables, before any engine query

### Requirement: Gitconfig migration notice

When neither `PI_CONTAINER_GITCONFIG` nor `PI_MOUNT_GITCONFIG` is set and `~/.gitconfig` exists, the wrapper SHALL print one stderr notice that the file is no longer mounted by default and how to opt in. The notice SHALL NOT include file contents and SHALL NOT change the exit status.

#### Scenario: Notice and silence

- **WHEN** `~/.gitconfig` exists and no variable is set
- **THEN** one notice naming `PI_CONTAINER_GITCONFIG=1` is printed and the session starts
- **AND** setting `PI_CONTAINER_GITCONFIG=0` suppresses the notice

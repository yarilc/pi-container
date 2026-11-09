# workspace-mounts Specification

## Purpose

Define which host directories may be exposed read/write as the Pi session workspace, refusing sensitive roots unless the operator explicitly overrides the refusal.

## Requirements

### Requirement: Sensitive workspace roots are refused

The wrapper SHALL refuse to mount a sensitive directory as the writable workspace. It SHALL compare the physical mount source, after `--container-git-worktree` parent selection, against `/`, the caller's physical home, fixed system directories and single-letter WSL drive roots under `/mnt`. Refusal SHALL precede engine queries, state creation and image operations. Descendants of refused directories SHALL remain allowed.

#### Scenario: Refused system directories

- **WHEN** the physical mount source is `/`, `/home`, `/root`, `/etc`, `/usr`, `/var`, `/bin`, `/sbin`, `/lib`, `/lib64`, `/boot`, `/opt`, `/srv`, `/mnt`, `/media`, `/proc`, `/sys`, `/dev`, `/run` or `/tmp`
- **THEN** the wrapper exits with status 1 before any engine query

#### Scenario: Launch from the home directory

- **WHEN** the caller launches the wrapper with the current directory equal to their physical home
- **THEN** the wrapper exits with status 1 and a message naming the refused path and suggesting a project subdirectory
- **AND** no engine query, state directory or image operation occurs

#### Scenario: Worktree parent is sensitive

- **WHEN** the caller launches with `--container-git-worktree` from a directory whose immediate parent is their physical home
- **THEN** the wrapper refuses the parent mount

#### Scenario: Symlinked path resolves to a sensitive root

- **WHEN** the current directory is reached through a symlink whose physical target is `/etc`
- **THEN** the wrapper refuses the workspace using the physical path

#### Scenario: WSL drive root

- **WHEN** the caller launches from `/mnt/d`
- **THEN** the wrapper refuses it, while `/mnt/d/Workspace/project` is accepted

#### Scenario: Ordinary project directory

- **WHEN** the caller launches from a project directory that is not in the refused set
- **THEN** the workspace mount proceeds unchanged

### Requirement: Explicit unsafe workspace override

`PI_CONTAINER_ALLOW_UNSAFE_WORKSPACE=1` SHALL be the only value that permits a refused workspace. When it is used, the wrapper SHALL print a stderr warning naming the exposed path before continuing. Any other value SHALL leave the refusal in force. The override SHALL NOT relax any other mount, state or engine check.

#### Scenario: Exact override

- **WHEN** the caller sets `PI_CONTAINER_ALLOW_UNSAFE_WORKSPACE=1` and launches from a refused directory
- **THEN** the wrapper warns that the sensitive directory is explicitly exposed read/write and continues startup

#### Scenario: Non-exact override

- **WHEN** the variable is set to `true`, `yes` or any value other than `1`
- **THEN** the refusal remains in force

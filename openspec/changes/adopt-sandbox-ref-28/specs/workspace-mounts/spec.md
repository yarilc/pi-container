# Spec Delta

## MODIFIED Requirements

### Requirement: Sensitive workspace roots are refused

The wrapper SHALL refuse to mount a sensitive directory as the writable workspace. It SHALL compare the physical mount source, after `--container-git-worktree` parent selection, against `/`, the caller's physical home, fixed system directories, single-letter WSL drive roots under `/mnt` and, case-insensitively, the Windows system and profile folders on those drives. Refusal SHALL precede engine queries, state creation and image operations. Descendants of refused directories SHALL remain allowed, except folders inside a Windows profile's `AppData`.

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

#### Scenario: Windows system and profile folders

- **WHEN** the physical mount source is `/mnt/<drive>/Users`, `/mnt/<drive>/Users/<name>`, `/mnt/<drive>/Users/<name>/Documents`, `/mnt/<drive>/Users/<name>/OneDrive` (also `OneDrive - <organization>`) or its `Documents`, `/mnt/<drive>/Users/<name>/AppData` or any folder inside it, `/mnt/<drive>/Windows`, `/mnt/<drive>/Program Files`, `/mnt/<drive>/Program Files (x86)` or `/mnt/<drive>/ProgramData`, for any single drive letter and any profile name
- **THEN** the wrapper exits with status 1 naming the refused path, before any engine query

#### Scenario: Windows folders in another letter case

- **WHEN** the physical mount source is `/mnt/c/users/YARI` or `/mnt/C/PROGRAM FILES`
- **THEN** the wrapper refuses it like the canonical spelling

#### Scenario: Project below a Windows profile

- **WHEN** the caller launches from `/mnt/c/Users/me/projects/app` or `/mnt/c/Users/me/Documents/GitHub/app`
- **THEN** the workspace mount proceeds, while `--container-git-worktree` from `/mnt/c/Users/me/app` is refused because the parent is the profile

#### Scenario: Folders where Windows runs user code

- **WHEN** the caller launches from `/mnt/c/Users/me/Documents`, which holds the PowerShell profile and modules, or from `/mnt/c/Users/me/AppData/Roaming/Microsoft/Windows/Start Menu/Programs/Startup`
- **THEN** the wrapper refuses it, because code written there would run on Windows outside the sandbox

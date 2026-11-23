# Spec Delta

## Purpose

Lets Windows users install the PowerShell entry once per user, run it as a
command from any project directory, update it from a newer source and remove
it, without administrator rights and without keeping the checkout. Here
`<P>` is the profile's variable prefix and `<name>` the profile name.

## ADDED Requirements

### Requirement: Self-contained installed copy
`<name>.ps1 --container-install` SHALL copy into `%LOCALAPPDATA%\Programs\<name>` the thin entry, the shared Windows scripts and every input that setup copies into a release, taken from the source the entry runs from. The installed copy SHALL be enough to run setup, help and launches after the source is deleted.

#### Scenario: Install from a checkout
- **WHEN** the user runs `.\<name>.ps1 --container-install` from a checkout
- **THEN** `%LOCALAPPDATA%\Programs\<name>` holds `<name>.ps1`, the shared Windows scripts and every setup input, with the same bytes as the source

#### Scenario: Source deleted after install
- **WHEN** the checkout is deleted after a successful install
- **THEN** `<name> --container-setup`, `<name> --container-help` and launches still work from the installed copy

### Requirement: Setup runs from the installed copy
After copying, the install SHALL run setup from the installed copy, in the same terminal and with the same checks as `--container-setup`. When setup fails, the installed copy and the `PATH` entry SHALL stay, and the message SHALL say to rerun `<name> --container-setup`.

#### Scenario: First install
- **WHEN** the user completes the setup questions after the copy
- **THEN** the machine installation is created from the installed copy, and the entry says to open a new PowerShell window and run `<name>` from a project directory

#### Scenario: Setup declined after the copy
- **WHEN** the user declines unrestricted networking during that setup
- **THEN** the install exits with status 1, the installed copy and the `PATH` entry remain, and the message names `<name> --container-setup`

### Requirement: Command on the user PATH
The install SHALL add the install folder to the user's `PATH`, once, keeping every other entry and its unexpanded `%VAR%` references, and SHALL announce the change before making it. It SHALL need no administrator rights and SHALL change no system-wide setting and no PowerShell profile.

#### Scenario: Command in a new window
- **WHEN** the user opens a new PowerShell window after the install and runs `<name> -c true` from a project directory
- **THEN** the session starts from that directory

#### Scenario: Existing PATH entries
- **WHEN** the user's `PATH` holds `%USERPROFILE%\AppData\Local\Microsoft\WindowsApps` and the install folder is already listed
- **THEN** after the install the reference is still unexpanded and the install folder is listed exactly once

### Requirement: Update from a newer source
Running `--container-install` again from another source SHALL replace the installed copy with that source's files, remove installed files that the source no longer has, and rerun setup. Running it from the installed copy itself SHALL be refused with status 1 before any change.

#### Scenario: Newer checkout
- **WHEN** the user runs `--container-install` from a checkout with a newer shim
- **THEN** the installed copy matches the new checkout and setup runs again

#### Scenario: Install from the installed copy
- **WHEN** the user runs `<name> --container-install` through the `PATH`
- **THEN** the entry exits with status 1 asking to run the install from a checkout or downloaded copy

### Requirement: Interrupted or concurrent install
An install that stops before it completes SHALL leave a state that the next install repairs, and the installed entry SHALL refuse to start sessions from an incomplete copy. A second install SHALL be refused with status 1 while one is running.

#### Scenario: Copy interrupted
- **WHEN** an install is interrupted while it copies files
- **THEN** `<name>` refuses to launch, naming the incomplete installation, and the next `--container-install` completes it

#### Scenario: Two installs at once
- **WHEN** a second `--container-install` starts while the first one is copying
- **THEN** the second exits with status 1 and the first completes

### Requirement: Checks before an install
Before changing anything, the install SHALL refuse with status 1: a source whose installed files contain a carriage return, a stopped machine or one that `wsl.exe` alone started, a source inside the install folder, and an install folder that is a reparse point or not owned by the current user.

#### Scenario: CRLF source
- **WHEN** the source was cloned with `core.autocrlf=true` without the repository's `.gitattributes`
- **THEN** the install exits with status 1 naming the first affected file and the renormalization step, and nothing is copied

#### Scenario: Junction as install folder
- **WHEN** `%LOCALAPPDATA%\Programs\<name>` is a junction to another folder
- **THEN** the install exits with status 1 naming it, and writes nothing through it

#### Scenario: Stopped machine
- **WHEN** the Podman machine is stopped
- **THEN** the install exits with status 1 asking to start it, before copying

### Requirement: Uninstall
`<name> --container-uninstall`, given alone, SHALL remove the install folder's `PATH` entry and the installed copy, and SHALL state that the installation inside the Podman machine stays until the machine is reset. When a file or folder is in use, it SHALL report what remains and how to remove it, with status 1.

#### Scenario: Uninstall
- **WHEN** the user runs `<name> --container-uninstall`
- **THEN** the `PATH` no longer lists the install folder, the folder is gone, and the message names the machine installation that remains

#### Scenario: Folder in use
- **WHEN** a WSL process keeps a folder of the installed copy as its current directory
- **THEN** the uninstall removes the `PATH` entry, exits with status 1, and names the folder with `wsl --shutdown` as the way to release it

### Requirement: Unsigned scripts and the Mark of the Web
The installed copy SHALL run under the `RemoteSigned` execution policy without unblocking, because the install writes new local files. The documentation SHALL state that the scripts are unsigned and that a downloaded source needs one `-ExecutionPolicy Bypass` run or `Unblock-File` before its first install.

#### Scenario: Downloaded source
- **WHEN** the source folder came from a downloaded zip and the policy is `RemoteSigned`
- **THEN** `powershell -ExecutionPolicy Bypass -File .\<name>.ps1 --container-install` installs it, and later `<name>` runs without a policy override

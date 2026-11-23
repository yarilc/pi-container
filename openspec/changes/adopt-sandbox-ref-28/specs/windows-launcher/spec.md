# Spec Delta

## Purpose

Lets Windows users run the sandbox from PowerShell on the local rootless engine
of a Podman machine's WSL distribution, without another distribution and
without the machine's SSH or API connection. Here `<P>` is the profile's
variable prefix, `<name>` the profile name and "the entry" the wrapper's
`<name>.ps1` together with the shared shim it runs.

## ADDED Requirements

### Requirement: Ordinary launches run the managed installation in the machine distribution
The entry SHALL run every ordinary launch through the managed installation in
the selected WSL distribution, as the selected user, starting the bootstrap of
that installation's current release. It SHALL use no other WSL distribution and
neither the machine's SSH connection nor its Windows API connection, and SHALL
run no checkout script inside the distribution for an ordinary launch.
Restricted modes SHALL use the distribution's own Unix launch service.

#### Scenario: Another distribution is active
- **WHEN** an Ubuntu distribution is running and the user launches the entry from a project directory
- **THEN** the session starts on the machine distribution's local rootless engine

#### Scenario: Release bootstrap only
- **WHEN** an ordinary launch runs after setup
- **THEN** the distribution executes the bootstrap, the namespace helper and the wrapper from the protected release, not from the Windows checkout
- **AND** the release contains the bootstrap and the helper as protected files

### Requirement: Machine distribution and user selection
The entry SHALL use the `podman-machine-default` distribution and the `user` account unless `<P>_WSL_DISTRO` or `<P>_WSL_USER` names another. It SHALL refuse a name outside letters, digits, `.`, `_` and `-`. A missing distribution or user SHALL stop the launch with status 1 and guidance to create the machine with Podman Desktop.

#### Scenario: Default machine
- **WHEN** neither variable is set
- **THEN** the launch runs in `podman-machine-default` as `user`

#### Scenario: Missing distribution
- **WHEN** the selected distribution is not registered in WSL
- **THEN** the entry exits with status 1 naming the distribution and the Podman Desktop machine guidance, before running anything in WSL

#### Scenario: Missing user
- **WHEN** the selected user does not exist in the distribution
- **THEN** the entry exits with status 1 naming the user and the distribution

#### Scenario: Invalid name
- **WHEN** `<P>_WSL_DISTRO` contains a space or a quote
- **THEN** the entry exits with status 1 before running `wsl.exe`

### Requirement: Machine started by Podman
Setup and ordinary launches SHALL run only in a distribution that Podman started. When the selected distribution is not running, the entry SHALL exit with status 1 without starting it and ask to start the machine with Podman Desktop or `podman machine start`. When the distribution runs without the user's runtime directory `/run/user/<uid>`, as after a start by `wsl.exe` alone, setup and the bootstrap SHALL exit with status 1 before any Podman command.

#### Scenario: Stopped machine
- **WHEN** the machine is stopped and its distribution is not running
- **THEN** setup and the launch exit with status 1 naming `podman machine start`, and the distribution stays stopped

#### Scenario: Distribution started by WSL alone
- **WHEN** the distribution was started by `wsl.exe` and `/run/user/<uid>` is missing or not writable
- **THEN** setup and the launch exit with status 1 before any Podman command, asking to run `wsl --terminate <distro>` and then `podman machine start`

#### Scenario: Help with a stopped machine
- **WHEN** `--container-help` runs while the distribution is not running
- **THEN** the entry prints the Windows part and the machine guidance, exits with status 0 and leaves the distribution stopped

### Requirement: Installation location and missing installation
The entry SHALL look for the installation at `.local/lib/<name>` under the selected user's home, or at the absolute distribution path in `<P>_WSL_INSTALLATION`. When the installation or its current release is missing, the entry SHALL exit with status 1 and a message naming `<name>.ps1 --container-setup`, without running setup.

#### Scenario: Machine reset
- **WHEN** the machine was recreated after setup and the user launches the entry
- **THEN** it exits with status 1 asking to rerun `<name>.ps1 --container-setup`

#### Scenario: Custom installation directory
- **WHEN** setup installed into `/home/user/sandbox` and `<P>_WSL_INSTALLATION=/home/user/sandbox` is set
- **THEN** the launch uses that installation

### Requirement: Setup from the Windows checkout
`<name>.ps1 --container-setup` SHALL run the interactive setup of the folder the entry runs from, a checkout or the installed copy, inside the selected distribution, which installs the release, preferences, images and managed command there. Combined with any other argument, the entry SHALL refuse it with usage guidance before running WSL. After setup, the entry SHALL state that sessions start with `<name>.ps1` from a project directory.

#### Scenario: First setup on Windows
- **WHEN** the user runs `<name>.ps1 --container-setup` in an interactive terminal
- **THEN** setup prompts in that terminal and the installation is created in the distribution, outside the Windows checkout

#### Scenario: Setup with other arguments
- **WHEN** `--container-setup` is combined with `--container-shell`
- **THEN** the entry exits with status 1 and usage guidance, and WSL runs nothing

#### Scenario: Setup from the installed copy
- **WHEN** the user runs `<name> --container-setup` through the `PATH` after an install
- **THEN** setup copies its inputs from `%LOCALAPPDATA%\Programs\<name>`

### Requirement: Windows entry help
`--container-help` SHALL take precedence over every other argument. The entry SHALL print the Windows variables `<P>_WSL_DISTRO`, `<P>_WSL_USER` and `<P>_WSL_INSTALLATION`, the supported modes and the install and uninstall options, then the checkout's wrapper help from the distribution. Help SHALL create no state and query no engine. When the distribution cannot run, it SHALL print the Windows part and the machine guidance and exit with status 0.

#### Scenario: Help with a machine
- **WHEN** the user runs `<name>.ps1 --container-help`
- **THEN** the output contains the Windows variables, `--container-install` and `--container-uninstall`, followed by the wrapper help, and the status is 0

#### Scenario: Help without a machine
- **WHEN** the distribution is not registered
- **THEN** the Windows part and the machine guidance are printed, and the status is 0

### Requirement: Arguments reach Bash unchanged
Each argument given to the entry SHALL reach Bash in the session as the same string, in the same order, including empty values, spaces, quotes, backslashes and non-ASCII text. No argument value SHALL appear on the `wsl.exe` command line. Arguments whose encoded form exceeds 32766 characters, the largest value one Windows environment variable carries through WSL on both PowerShell versions, SHALL fail with status 1 before WSL runs. An argument that is a PowerShell array SHALL be refused.

#### Scenario: Quotes and empty values
- **WHEN** the user runs `<name>.ps1 -c 'printf "<%s>" "$@"' x '' 'a "b" c\'`
- **THEN** Bash receives `-c`, the script, `x`, an empty string and `a "b" c\` as separate arguments

#### Scenario: Non-ASCII argument
- **WHEN** an argument contains `è` and an emoji
- **THEN** Bash receives the same UTF-8 text

#### Scenario: Oversized arguments
- **WHEN** the encoded arguments exceed 32766 characters
- **THEN** the entry exits with status 1 naming the limit, and WSL runs nothing

#### Scenario: Unquoted comma
- **WHEN** the user passes `a,b` unquoted, which PowerShell turns into an array
- **THEN** the entry exits with status 1 asking to quote the argument

### Requirement: Environment forwarded by name to the distribution
The entry SHALL forward to the launcher in the distribution, with unchanged values: validly named `<P>_*` variables except `<P>_WSL_*`; the profile's configuration-directory variable holding a distribution path; its approval-bypass and credential variables; and the names in `<P>_ENV_VARS`. It SHALL forward no other Windows variable, ignore the user's `WSLENV`, never forward a name the distribution environment depends on, and leave the PowerShell session's environment as it was.

#### Scenario: Launch settings from PowerShell
- **WHEN** `$env:<P>_MEMORY_LIMIT='2g'` is set in PowerShell
- **THEN** the launcher in the distribution receives `<P>_MEMORY_LIMIT=2g`

#### Scenario: Listed variable
- **WHEN** `<P>_ENV_VARS` is `GH_TOKEN` and `GH_TOKEN` is set in PowerShell
- **THEN** the session receives `GH_TOKEN` by name under the launcher's forwarding rules

#### Scenario: Name reserved by the distribution
- **WHEN** `<P>_ENV_VARS` lists `PATH`
- **THEN** the entry does not forward it and prints one notice naming it

#### Scenario: Credential variable of an authentication method
- **WHEN** the profile's API method declares `credential_env` `<KEY>`, `<KEY>` is set in PowerShell, and the user launches a provider session that uses that method
- **THEN** the launcher in the distribution receives `<KEY>` with its value, and the session receives it as on Linux

#### Scenario: Credential variable not set
- **WHEN** `<KEY>` is unset or empty in PowerShell
- **THEN** the entry does not forward it

#### Scenario: Unrelated Windows variable
- **WHEN** `USERPROFILE` is set and not listed
- **THEN** the distribution does not receive it

#### Scenario: Session environment restored
- **WHEN** the launch ends, successfully or not
- **THEN** `WSLENV` and every variable the entry set have their previous values in the PowerShell session

#### Scenario: Name that would split WSLENV
- **WHEN** a Windows variable named `<P>_X:BASH_ENV/u` is set
- **THEN** the entry does not forward it, prints a notice naming it, and `BASH_ENV` does not reach the distribution

#### Scenario: Windows path in the configuration-directory variable
- **WHEN** the profile's configuration-directory variable holds a Windows path, such as one set for the native agent
- **THEN** the entry does not forward it and prints a notice, so the configuration directory saved by setup applies

### Requirement: Empty Windows variables count as unset
The entry SHALL treat a variable with an empty value as unset and SHALL NOT forward it, on both PowerShell versions.

#### Scenario: Empty value in PowerShell 7
- **WHEN** PowerShell 7 holds `<P>_MEMORY_LIMIT` with an empty value
- **THEN** the launcher in the distribution does not receive `<P>_MEMORY_LIMIT`, as with Windows PowerShell 5.1, where assigning an empty value removes the variable

### Requirement: Windows working directory translation
The entry SHALL use PowerShell's current file system location as the launch directory, translated to its drive mount in the distribution. It SHALL refuse with status 1 and a specific message, before any engine query, a location that is not a file system path, a UNC path, a path inside a WSL distribution and a drive not mounted in the distribution.

#### Scenario: Drive path with spaces
- **WHEN** the location is `C:\Work\my project`
- **THEN** the session's working directory is `/mnt/c/Work/my project`

#### Scenario: Network share
- **WHEN** the location is `\\server\share\project`
- **THEN** the entry refuses network paths

#### Scenario: Path inside a WSL distribution
- **WHEN** the location is `\\wsl.localhost\Ubuntu\home\me\project`
- **THEN** the entry refuses it and suggests a project on a Windows drive

#### Scenario: Drive not mounted
- **WHEN** the location is on a mapped network drive that the distribution does not mount
- **THEN** the entry refuses it naming the drive

#### Scenario: Registry location
- **WHEN** the location is `HKCU:\Software`
- **THEN** the entry refuses it as not a file system path

### Requirement: Entry directory stays outside writable mounts
A launch through the entry SHALL be refused with status 1, before any engine query, when the workspace mount, after worktree parent selection from the argument or the saved preference, or another writable mount contains the entry's directory or lies inside it. Paths on drive mounts SHALL be compared case-insensitively.

#### Scenario: Launch from the checkout
- **WHEN** the user launches the entry from its own checkout directory or a subdirectory
- **THEN** the launch is refused naming the entry's directory

#### Scenario: Saved worktree scope
- **WHEN** setup saved the worktree scope and the checkout is a sibling of the current project
- **THEN** the launch is refused, because the mounted parent contains the checkout

#### Scenario: Sibling without worktree scope
- **WHEN** the checkout is a sibling of the current project and worktree scope is off
- **THEN** the launch proceeds

#### Scenario: Different letter case
- **WHEN** the location is `c:\WORK\Sandbox-Container` and the checkout is `C:\Work\sandbox-container`
- **THEN** the launch is refused

### Requirement: Exit status, terminal and interruption through the entry
The entry SHALL return the launch's exit status. An interactive console SHALL give the session a terminal, and Ctrl+C SHALL reach the session as one interrupt followed by the bounded shutdown. Closing the console window SHALL also end the session with the bounded shutdown, which continues in the distribution after `wsl.exe` has ended.

#### Scenario: Exit status
- **WHEN** the session runs `exit 7`
- **THEN** the entry's exit code is 7

#### Scenario: Interrupt
- **WHEN** the user presses Ctrl+C during an interactive session
- **THEN** the application receives one interrupt and no container of the session remains

#### Scenario: Window closed
- **WHEN** the user closes the console window during a session
- **THEN** no container of the session remains

### Requirement: Pipeline input refused, redirected input unchanged
The entry SHALL refuse PowerShell pipeline input with status 1, because PowerShell alters it. Input redirected at the process level SHALL reach the session unchanged.

#### Scenario: Pipeline input
- **WHEN** the user runs `'text' | .\<name>.ps1 -c cat`
- **THEN** the entry exits with status 1 explaining that pipeline input is unsupported, before running WSL
- **AND** the reason is that Windows PowerShell 5.1 adds a byte order mark and replaces non-ASCII characters, and both versions append a CRLF line ending

#### Scenario: Redirected input
- **WHEN** the user runs `cmd /c "powershell -File <name>.ps1 -c cat < input.bin"`
- **THEN** the session reads the bytes of `input.bin` unchanged, NUL and CR included

### Requirement: Checkout line endings checked before setup
Before running setup or an install, the entry SHALL refuse a checkout whose Bash entry, launcher core or agent launcher part contains a carriage return, with status 1 and a message explaining that the checkout must have LF line endings and how to renormalize it.

#### Scenario: Checkout converted to CRLF
- **WHEN** the checkout was cloned with `core.autocrlf=true` before `.gitattributes` existed
- **THEN** `--container-setup` exits with status 1 naming the first affected file and the renormalization step

#### Scenario: Install from a CRLF checkout
- **WHEN** the same checkout runs `--container-install`
- **THEN** the entry exits with status 1 naming the first affected file, before copying anything

### Requirement: Supported PowerShell versions
The entry SHALL run on Windows PowerShell 5.1 and PowerShell 7 with only built-in modules, and SHALL need no administrator rights. Its files SHALL contain only ASCII characters.

#### Scenario: Windows 11 Home default shell
- **WHEN** the entry runs in Windows PowerShell 5.1 with a policy that allows local scripts
- **THEN** setup, help and launches behave as in PowerShell 7

### Requirement: Install and uninstall options used alone
`--container-install` and `--container-uninstall` SHALL each be refused with status 1 and usage guidance, before running WSL or changing any file, when combined with any other argument. `--container-uninstall` SHALL act on the per-user installation whether the entry runs from it or from a checkout.

#### Scenario: Install with other arguments
- **WHEN** the user runs `<name>.ps1 --container-install -c true`
- **THEN** the entry exits with status 1 naming `--container-install` alone, and nothing is copied

#### Scenario: Uninstall from a checkout
- **WHEN** the installed copy is damaged and the user runs `.\<name>.ps1 --container-uninstall` from a checkout
- **THEN** the per-user installation and its `PATH` entry are removed as from the installed command

### Requirement: Sessions and setup in the machine's systemd namespaces
Sessions and setup that the entry starts SHALL run as the selected user in the PID and mount namespaces of the machine's systemd, as the machine's login shells do, with the environment, working directory, standard streams and exit status unchanged and `XDG_RUNTIME_DIR=/run/user/<uid>`. When systemd is the distribution's PID 1, they SHALL run directly. When `sudo` needs a password, the entry SHALL exit with status 1 before any Podman command.

#### Scenario: One engine for sessions and the machine
- **WHEN** a session started by the entry runs its container
- **THEN** the machine's launch service can run a command in that container and remove it
- **AND** the session's podman and the service use one rootless user namespace

#### Scenario: Setup probe
- **WHEN** the machine that Podman started serves its rootless API at `/run/user/<uid>/podman/podman.sock` and the user runs `<name>.ps1 --container-setup`
- **THEN** setup finds that service and offers every network mode that the profile allows

#### Scenario: Socket of another distribution
- **WHEN** another WSL distribution serves a Podman socket under `/mnt/wslg/runtime-dir/podman/`
- **THEN** neither setup nor a launch from the entry uses it

#### Scenario: Password required
- **WHEN** `sudo` in the distribution asks the user for a password
- **THEN** setup and the launch exit with status 1 naming passwordless `sudo` as a machine requirement, before any Podman command
- **AND** `<name>.ps1 --container-help`, which queries no engine, still prints the help without `sudo`

#### Scenario: Environment kept
- **WHEN** a launch forwards `<P>_NETWORK`, a configuration directory and a 30000-character argument
- **THEN** the wrapper receives them unchanged inside the namespaces, and no file of the transport remains

### Requirement: Network modes from setup, without delegation
On Windows the entry SHALL pass `<P>_NETWORK` unset, `unrestricted`, `offline` or, when the profile declares authentication methods, `provider` to the launcher, and SHALL accept `--container-qualify`. It SHALL exit with status 1, before running WSL, when `<P>_PODMAN` enables delegation. The launcher in the distribution SHALL apply its usual checks to restricted modes.

#### Scenario: Offline session
- **WHEN** setup prepared offline networking in the machine and the user launches the entry from a project directory
- **THEN** the session starts with `network mode=offline` through the machine's launch service and has no network access

#### Scenario: Provider session
- **WHEN** an agent wrapper's setup prepared provider networking in the machine
- **THEN** the session starts with `network mode=provider` and reaches only its policy's hosts through the egress proxy

#### Scenario: Restricted mode without a prepared installation
- **WHEN** `$env:<P>_NETWORK='offline'` is set but setup prepared only unrestricted networking
- **THEN** the launch exits with status 1 and the launcher's setup guidance, before any engine query
- **AND** the guidance names `<name>.ps1 --container-setup` from Windows, not the wrapper path in the distribution

#### Scenario: Qualification
- **WHEN** the user runs `<name>.ps1 --container-qualify` after an offline setup
- **THEN** the fixed qualification runs in the machine and reports its status

#### Scenario: Delegation requested
- **WHEN** `$env:<P>_PODMAN='1'` is set
- **THEN** the entry exits with status 1 stating that delegation is unsupported on Podman machine, and WSL runs nothing

### Requirement: Saved delegation refused
The bootstrap SHALL exit with status 1, before running the managed command, when the release's saved preferences enable Podman delegation, and SHALL ask to rerun setup from Windows. Saved unrestricted, offline and provider networking SHALL be accepted.

#### Scenario: Saved delegation
- **WHEN** a release saved delegation, for example because setup ran from a Linux shell in the machine
- **THEN** every launch through the entry exits with status 1 before any Podman command, asking to rerun `<name>.ps1 --container-setup`

#### Scenario: Saved offline networking
- **WHEN** setup from Windows saved offline networking
- **THEN** the bootstrap runs the managed command

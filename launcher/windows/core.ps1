# Shared Windows shim, run by the thin PowerShell entry of every wrapper on
# Windows PowerShell 5.1 and PowerShell 7. It runs the managed installation in
# the Podman machine's WSL distribution through the release bootstrap
# (launcher/windows/bootstrap.sh), and setup and help from this checkout.
# Sessions and setup enter the PID and mount namespaces of the machine's
# systemd through launcher/windows/enter.sh; help queries no engine.
# User values cross into WSL only in the environment (WSLENV), never on the
# wsl.exe command line. See docs/launcher-contract.md (Windows entry).
# ASCII only: Windows PowerShell 5.1 reads files without a BOM as ANSI.
param(
    [Parameter(Mandatory = $true)]
    [string]$EntryDirectory,
    [object[]]$Arguments = @(),
    [switch]$PipelineInput,
    [string[]]$CommandLine = [Environment]::GetCommandLineArgs()
)
Set-StrictMode -Version 3
$ErrorActionPreference = 'Stop'

$script:Prefix = 'windows entry'
# Largest value that crossed WSLENV on both PowerShell versions; Windows
# PowerShell 5.1 refuses 32767 characters or more.
$script:MaxValue = 32766
$script:SessionCode = 0
# .NET path calls: they do not depend on the current PowerShell location's provider.
$checkout = [IO.Path]::GetDirectoryName([IO.Path]::GetDirectoryName($PSScriptRoot))

function Exit-Entry([string]$Message) {
    [Console]::Error.WriteLine($script:Prefix + ': ' + $Message)
    exit 1
}

# An empty value counts as unset: Windows PowerShell 5.1 cannot hold one.
function Get-Setting([string]$Name) {
    $value = [Environment]::GetEnvironmentVariable($Name)
    if ([string]::IsNullOrEmpty($value)) { return $null }
    return $value
}

function Get-ProfileText($Object, [string]$Field, [string]$Pattern, [switch]$Optional) {
    $property = $Object.PSObject.Properties[$Field]
    if ($null -eq $property -or $null -eq $property.Value) {
        if ($Optional) { return $null }
        Exit-Entry ('the wrapper profile agent/profile.json has no ' + $Field)
    }
    $value = $property.Value
    if (-not ($value -is [string]) -or $value -cnotmatch $Pattern) {
        Exit-Entry ('the wrapper profile agent/profile.json has an invalid ' + $Field)
    }
    return $value
}

function Restore-Variable([string]$Name, $Value) {
    if ($null -eq $Value) {
        if (Test-Path -LiteralPath ('Env:' + $Name)) { Remove-Item -LiteralPath ('Env:' + $Name) }
    } else {
        [Environment]::SetEnvironmentVariable($Name, [string]$Value)
    }
}

# Sets the variables for the child only ($null removes one), runs wsl.exe with
# the console handles inherited and restores the session environment. The exit
# code goes to $script:SessionCode; the function writes no output, so callers
# must not capture it.
function Invoke-WslSession([hashtable]$Environment, [string[]]$WslArguments) {
    $saved = @{}
    foreach ($name in $Environment.Keys) { $saved[$name] = [Environment]::GetEnvironmentVariable($name) }
    try {
        foreach ($name in $Environment.Keys) { Restore-Variable $name $Environment[$name] }
        & wsl.exe @WslArguments
        $script:SessionCode = $LASTEXITCODE
    } finally {
        foreach ($name in $saved.Keys) { Restore-Variable $name $saved[$name] }
    }
}

# Same for a short probe whose output is captured. Windows PowerShell 5.1 turns
# redirected native stderr into a terminating error under Stop.
function Invoke-WslProbe([hashtable]$Environment, [string[]]$WslArguments) {
    $ErrorActionPreference = 'Continue'
    $saved = @{}
    foreach ($name in $Environment.Keys) { $saved[$name] = [Environment]::GetEnvironmentVariable($name) }
    try {
        foreach ($name in $Environment.Keys) { Restore-Variable $name $Environment[$name] }
        $output = @(& wsl.exe @WslArguments 2>&1 | ForEach-Object { [string]$_ })
        return [pscustomobject]@{ Code = $LASTEXITCODE; Output = $output }
    } finally {
        foreach ($name in $saved.Keys) { Restore-Variable $name $saved[$name] }
    }
}

if ($PSVersionTable.PSVersion -lt [version]'5.1') {
    Exit-Entry 'Windows PowerShell 5.1 or PowerShell 7 is required'
}

# Wrapper profile: the only source of wrapper-specific values.
$profilePath = [IO.Path]::Combine($checkout, 'agent', 'profile.json')
try {
    $wrapperProfile = [IO.File]::ReadAllText($profilePath, [Text.Encoding]::UTF8) | ConvertFrom-Json
} catch {
    Exit-Entry ('cannot read the wrapper profile ' + $profilePath + ': ' + $_.Exception.Message)
}
$envName = '^[A-Z][A-Z0-9]*(_[A-Z0-9]+)*\z'
$name = Get-ProfileText $wrapperProfile 'name' '^[a-z][a-z0-9]*(-[a-z0-9]+)*\z'
$script:Prefix = $name
$wrapperFile = Get-ProfileText $wrapperProfile 'wrapper' '^[a-z][a-z0-9-]*\.sh\z'
$P = Get-ProfileText $wrapperProfile 'env_prefix' $envName
$native = $wrapperProfile.PSObject.Properties['native']
if ($null -eq $native) { Exit-Entry 'the wrapper profile agent/profile.json has no native' }
$configEnv = Get-ProfileText $native.Value 'config_dir_env' $envName
$bypassEnv = Get-ProfileText $native.Value 'approval_bypass_env' $envName -Optional
$entryName = $name + '.ps1'
# Provider networking exists only for a profile with authentication methods.
$authProperty = $wrapperProfile.PSObject.Properties['auth']
$modeList = 'unrestricted or offline'
if ($null -ne $authProperty -and $null -ne $authProperty.Value -and
    @($authProperty.Value.PSObject.Properties).Count -gt 0) {
    $modeList = 'unrestricted, offline or provider'
}
# The key variables of the authentication methods. On Linux they are in the
# launcher's environment; the core passes only the selected method's key.
$credentialEnvs = New-Object 'System.Collections.Generic.List[string]'
if ($null -ne $authProperty -and $null -ne $authProperty.Value) {
    foreach ($method in @($authProperty.Value.PSObject.Properties)) {
        $credential = Get-ProfileText $method.Value 'credential_env' $envName -Optional
        if ($null -ne $credential -and -not $credentialEnvs.Contains($credential)) { $credentialEnvs.Add($credential) }
    }
}
$guidance = 'Create a Podman machine with Podman Desktop, using the WSL provider, or set ' +
    $P + '_WSL_DISTRO to the name of its WSL distribution.'

# Per-user installation (launcher/windows/install.ps1). Windows always sets
# LOCALAPPDATA; the tests point it at a temporary folder.
$onWindows = [Environment]::OSVersion.Platform -eq [PlatformID]::Win32NT
$localData = Get-Setting 'LOCALAPPDATA'
if ($null -eq $localData) { $localData = [Environment]::GetFolderPath('LocalApplicationData') }
$installFolder = $null
if ($localData) { $installFolder = [IO.Path]::GetFullPath([IO.Path]::Combine($localData, 'Programs', $name)) }
# install.json marks this folder as an installed copy, complete or not.
$installState = $null
$markerPath = [IO.Path]::Combine($checkout, 'install.json')
if ([IO.File]::Exists($markerPath)) {
    try {
        $installState = [string](([IO.File]::ReadAllText($markerPath) | ConvertFrom-Json).state)
    } catch {
        $installState = 'unreadable'
    }
}

# Arguments. Help takes precedence over everything else, as in the core.
$help = $false
foreach ($item in $Arguments) {
    if ($item -is [string] -and $item -ceq '--container-help') { $help = $true }
}
$strings = New-Object 'System.Collections.Generic.List[string]'
$position = 0
foreach ($item in $Arguments) {
    $position++
    if ($item -is [System.Array] -or $item -is [System.Collections.IList]) {
        if ($help) { continue }
        Exit-Entry ('argument ' + $position + ' is a list, which PowerShell makes from an unquoted comma; ' +
            'quote it, for example ''a,b''')
    }
    $text = [string]$item
    if ($text.IndexOf([char]0) -ge 0) {
        if ($help) { continue }
        Exit-Entry ('argument ' + $position + ' contains a NUL character, which Bash cannot receive')
    }
    $strings.Add($text)
}

# Distribution, user and installation.
$distro = Get-Setting ($P + '_WSL_DISTRO')
if ($null -eq $distro) { $distro = 'podman-machine-default' }
$user = Get-Setting ($P + '_WSL_USER')
if ($null -eq $user) { $user = 'user' }
$selectionError = $null
foreach ($pair in @(@(($P + '_WSL_DISTRO'), $distro), @(($P + '_WSL_USER'), $user))) {
    if ($pair[1] -cnotmatch '^[A-Za-z0-9._-]+\z') {
        $selectionError = $pair[0] + ' must contain only letters, digits, ''.'', ''_'' and ''-'''
    }
}
$stoppedText = 'the Podman machine is stopped: the WSL distribution ''' + $distro + ''' is not running. ' +
    'Start the machine with Podman Desktop or podman machine start, then retry.'
$unstartedText = 'the WSL distribution ''' + $distro + ''' runs without the Podman machine: /run/user/<uid> ' +
    'is missing for ''' + $user + ''', so podman cannot work. Run wsl --terminate ' + $distro + ', then start ' +
    'the machine with Podman Desktop or podman machine start, and retry.'
$installation = Get-Setting ($P + '_WSL_INSTALLATION')
if ($null -eq $installation) {
    $bootstrap = '.local/lib/' + $name + '/current/launcher/windows/bootstrap.sh'
    $installationText = '~/.local/lib/' + $name
} elseif ($installation -cmatch '^/[A-Za-z0-9._-]+(/[A-Za-z0-9._-]+)*\z') {
    $bootstrap = $installation + '/current/launcher/windows/bootstrap.sh'
    $installationText = $installation
} else {
    $bootstrap = $null
    $installationText = $installation
    if ($null -eq $selectionError) {
        $selectionError = $P + '_WSL_INSTALLATION must be an absolute distribution path of letters, digits, ' +
            '''.'', ''_'', ''-'' and ''/'', without a trailing ''/'''
    }
}
$wslPresent = $null -ne (Get-Command -Name 'wsl.exe' -CommandType Application -ErrorAction SilentlyContinue)

function Test-Listed([string[]]$ListArguments) {
    # WSL_UTF8=1 makes current WSL write UTF-8; older versions write UTF-16,
    # whose NUL characters are removed.
    $result = Invoke-WslProbe @{ WSL_UTF8 = '1'; WSLENV = $null } $ListArguments
    $names = @($result.Output | ForEach-Object { ($_ -replace "`0", '').Trim() } | Where-Object { $_ })
    return ($names -contains $distro)
}

# 'running', 'stopped' or 'missing'; neither listing starts the distribution.
function Get-DistributionState {
    if (Test-Listed @('-l', '--running', '-q')) { return 'running' }
    if (Test-Listed @('-l', '-q')) { return 'stopped' }
    return 'missing'
}

# A distribution that wsl.exe started without the Podman machine lacks the
# user's runtime directory, and no podman command works in it (design D6).
function Test-MachineRuntime {
    return Invoke-WslProbe @{ WSLENV = $null } @('-d', $distro, '-u', $user, '--exec', '/bin/sh', '-c',
        'test -d /run/user/$(id -u) -a -w /run/user/$(id -u)')
}

function Test-User {
    $result = Invoke-WslProbe @{ WSLENV = $null } @('-d', $distro, '-u', $user, '--exec', '/bin/true')
    return ($result.Code -eq 0)
}

function Test-Installation {
    $result = Invoke-WslProbe @{ WSLENV = $null } @('-d', $distro, '-u', $user, '--exec', '/bin/sh', '-c',
        ('cd && test -f ' + $bootstrap))
    return ($result.Code -eq 0)
}

function Assert-Machine {
    if (-not $wslPresent) { Exit-Entry ('wsl.exe was not found; install WSL. ' + $guidance) }
    $state = Get-DistributionState
    if ($state -eq 'missing') {
        Exit-Entry ('the WSL distribution ''' + $distro + ''' is not registered. ' + $guidance)
    }
    if ($state -eq 'stopped') { Exit-Entry $stoppedText }
}

function Exit-MissingUser {
    Exit-Entry ('the user ''' + $user + ''' does not exist in the WSL distribution ''' + $distro +
        '''; set ' + $P + '_WSL_USER to the machine''s user (Podman Desktop machines use ''user'')')
}

# Setup and help run Bash from a folder on drvfs: the checkout, or the installed copy.
function Assert-DrivePath([string]$Directory) {
    if ($Directory -cnotmatch '^[A-Za-z]:\\[^"]*[^\\"]\z') {
        Exit-Entry ('the entry directory ' + $Directory + ' is not a folder on a Windows drive; ' +
            'keep the checkout in a folder on a drive such as C:')
    }
}

function Assert-Checkout([string]$Folder) {
    foreach ($relative in @($wrapperFile, 'launcher/core.sh', 'agent/launcher.sh', 'launcher/windows/enter.sh')) {
        $path = [IO.Path]::Combine($Folder, $relative)
        try {
            $bytes = [IO.File]::ReadAllBytes($path)
        } catch {
            Exit-Entry ('the checkout is incomplete: ' + $relative + ' cannot be read')
        }
        if ([Array]::IndexOf($bytes, [byte]13) -ge 0) {
            Exit-Entry ('the checkout has CRLF line endings: ' + $relative + '. Scripts must keep LF line ' +
                'endings, as the repository .gitattributes requires. In a checkout without local changes run ' +
                'git rm -r -q --cached . and then git reset --hard, or clone the repository again.')
        }
    }
}

function Write-WindowsHelp {
    $lines = @(
        ('Windows entry (' + $entryName + ', Podman machine):'),
        ('  Sessions run in the Podman machine''s WSL distribution, through the'),
        ('  installation that ' + $entryName + ' --container-setup creates there.'),
        ('  ' + $entryName + ' --container-install copies this checkout to'),
        ('  %LOCALAPPDATA%\Programs\' + $name + ', adds that folder to your user PATH and runs'),
        ('  setup; then ' + $name + ' works from any project directory.'),
        ('  ' + $name + ' --container-uninstall removes that copy and its PATH entry.'),
        ('  ' + $P + '_WSL_DISTRO        WSL distribution (default: podman-machine-default)'),
        ('  ' + $P + '_WSL_USER          user in the distribution (default: user)'),
        ('  ' + $P + '_WSL_INSTALLATION  absolute installation path in the distribution'),
        ('                                (default: ~/.local/lib/' + $name + ')'),
        ('  ' + $P + '_NETWORK           ' + $modeList + ' (default: the mode setup saved)'),
        '  Restricted modes need a setup that prepared them in the machine.',
        ('  Host Podman delegation was removed: ' + $P + '_PODMAN=1 is refused.'),
        '  PowerShell pipeline input is refused; redirect standard input from cmd.exe.',
        '  Variables with an empty value count as unset. Quote a -- meant for Bash: ''--''.'
    )
    if ($credentialEnvs.Count -gt 0) {
        $lines += ('  Authentication keys forwarded when set: ' + ($credentialEnvs -join ', ') + '.')
    }
    $lines += ''
    foreach ($line in $lines) { [Console]::Out.WriteLine($line) }
}

# Help: the Windows part, then the checkout's wrapper help from the distribution.
if ($help) {
    Write-WindowsHelp
    if ($null -ne $selectionError) {
        [Console]::Out.WriteLine($selectionError)
        [Console]::Out.WriteLine($guidance)
        exit 0
    }
    if (-not $wslPresent) {
        [Console]::Out.WriteLine('The WSL distribution ''' + $distro + ''' is not available. ' + $guidance)
        exit 0
    }
    $state = Get-DistributionState
    if ($state -eq 'missing') {
        [Console]::Out.WriteLine('The WSL distribution ''' + $distro + ''' is not available. ' + $guidance)
        exit 0
    }
    if ($state -eq 'stopped') {
        [Console]::Out.WriteLine($stoppedText.Substring(0, 1).ToUpperInvariant() + $stoppedText.Substring(1))
        exit 0
    }
    Assert-DrivePath $EntryDirectory
    Assert-Checkout $checkout
    Invoke-WslSession @{ WSLENV = $null } @('-d', $distro, '-u', $user, '--cd', $EntryDirectory, '--exec',
        '/bin/bash', $wrapperFile, '--container-help')
    if (($script:SessionCode -eq -1 -or $script:SessionCode -eq 255) -and -not (Test-User)) {
        [Console]::Out.WriteLine('The user ''' + $user + ''' does not exist in the WSL distribution ''' + $distro +
            '''. ' + $guidance)
        exit 0
    }
    exit $script:SessionCode
}

# Uninstall needs no WSL: it works from the installed copy and from a checkout,
# whatever the mode, the WSL settings or the input.
if ($strings.Contains('--container-uninstall')) {
    if ($strings.Count -ne 1) {
        Exit-Entry ('--container-uninstall must be used alone: .\' + $entryName + ' --container-uninstall')
    }
    if ($null -eq $installFolder) { Exit-Entry 'LOCALAPPDATA is not set, so the installation cannot be found' }
    $machineNote = 'the installation inside the Podman machine stays (' + $installationText + ' and its ' +
        'managed command, for ''' + $user + ''' in ''' + $distro + '''); resetting the machine removes it'
    & ([IO.Path]::Combine($PSScriptRoot, 'install.ps1')) -Action Uninstall -Source $checkout -Target $installFolder `
        -Name $name -MachineNote $machineNote
    exit $LASTEXITCODE
}

# Windows PowerShell 5.1 also reports standard input that cmd.exe redirects to
# powershell -File <entry> as pipeline input, although the bytes still reach
# wsl.exe unchanged. No PowerShell pipeline can feed the script that the
# process runs with -File, so its pipeline input is standard input.
function Test-FileEntry([string[]]$ProcessArguments) {
    $entryPath = [IO.Path]::Combine($EntryDirectory, $entryName)
    for ($i = 1; $i -lt $ProcessArguments.Count; $i++) {
        if ($ProcessArguments[$i] -cnotmatch '^[-/][A-Za-z]+\z') { continue }
        $word = $ProcessArguments[$i].Substring(1).ToLowerInvariant()
        # Any abbreviation of a command option ends the check: the input may then
        # come from a PowerShell pipeline.
        foreach ($option in @('command', 'commandwithargs', 'cwa', 'encodedcommand', 'ec')) {
            if ($option.StartsWith($word, [StringComparison]::Ordinal)) { return $false }
        }
        if ('file'.StartsWith($word, [StringComparison]::Ordinal)) {
            if ($i + 1 -ge $ProcessArguments.Count) { return $false }
            try { $path = [IO.Path]::GetFullPath($ProcessArguments[$i + 1]) } catch { return $false }
            return [string]::Equals($path, $entryPath, [StringComparison]::OrdinalIgnoreCase)
        }
    }
    return $false
}
$redirectedInput = $PipelineInput -and [Console]::IsInputRedirected -and (Test-FileEntry $CommandLine)
if ($PipelineInput -and -not $redirectedInput) {
    Exit-Entry ('PowerShell pipeline input is unsupported, because PowerShell alters it; pass data in a ' +
        'file, or redirect standard input from cmd.exe')
}
if ($null -ne $selectionError) { Exit-Entry $selectionError }

$setup = $strings.Contains('--container-setup')
if ($setup -and $strings.Count -ne 1) {
    Exit-Entry ('--container-setup must be used alone: .\' + $entryName + ' --container-setup')
}
if ($strings.Contains('--container-install') -and $strings.Count -ne 1) {
    Exit-Entry ('--container-install must be used alone: .\' + $entryName + ' --container-install')
}
$install = $strings.Contains('--container-install')
$fromInstalledCopy = $null -ne $installFolder -and ([string]::Equals($checkout, $installFolder,
    [StringComparison]::OrdinalIgnoreCase) -or $checkout.StartsWith($installFolder + [IO.Path]::DirectorySeparatorChar,
    [StringComparison]::OrdinalIgnoreCase))
if ($install -and $fromInstalledCopy) {
    Exit-Entry ('this is the installed copy in ' + $checkout + '; run --container-install from a checkout or a ' +
        'downloaded copy')
}
if ($null -ne $installState -and $installState -cne 'complete') {
    Exit-Entry ('the installation in ' + $checkout + ' is incomplete; run --container-install again from a ' +
        'checkout or a downloaded copy')
}

# Network modes and qualification follow setup and the launcher's own checks.
# Host Podman delegation was removed: the exact old opt-in stops the entry with
# the launcher's migration message, before WSL runs.
if ((Get-Setting ($P + '_PODMAN')) -ceq '1') {
    Exit-Entry ($P + '_PODMAN=1: host Podman delegation was removed; add the images your tests need with ' +
        '--container-toolchain add, so that sessions get their own container engine (README: Container tests), ' +
        'then unset ' + $P + '_PODMAN')
}

# A running machine that Podman started (design D6 of the Windows entry).
function Assert-MachineReady {
    Assert-Machine
    $probe = Test-MachineRuntime
    if ($probe.Code -eq -1 -or $probe.Code -eq 255) {
        if (-not (Test-User)) { Exit-MissingUser }
        Exit-Entry ('wsl.exe could not start a command in the WSL distribution ''' + $distro + ''' (exit code ' +
            $probe.Code + '): ' + (($probe.Output | ForEach-Object { ($_ -replace "`0", '').Trim() }) -join ' '))
    }
    if ($probe.Code -ne 0) { Exit-Entry $unstartedText }
}

# Runs setup from a folder as a statement, so that it keeps the terminal, and
# leaves its status in $script:SessionCode. WRAPPER_WINDOWS_SETUP=1 tells setup
# that this entry prints the next step, so it leaves out Linux shell guidance.
# The folder's namespace helper runs it where the machine's service runs.
function Invoke-Setup([string]$Directory) {
    Invoke-WslSession @{ WSLENV = 'WRAPPER_WINDOWS_SETUP/u'; WRAPPER_WINDOWS_SETUP = '1' } @('-d', $distro,
        '-u', $user, '--cd', $Directory, '--exec', '/bin/bash', 'launcher/windows/enter.sh', $name, '/bin/bash',
        $wrapperFile, '--container-setup')
    if (($script:SessionCode -eq -1 -or $script:SessionCode -eq 255) -and -not (Test-User)) { Exit-MissingUser }
}

# The payload: setup's own manifest, read in the distribution, and the Windows
# files. Only standard output holds the list: wsl.exe may print warnings, in
# UTF-16, on standard error. -B keeps Python from caching bytecode in the source.
function Get-InstallManifest {
    $ErrorActionPreference = 'Continue'
    $saved = [Environment]::GetEnvironmentVariable('WSLENV')
    Restore-Variable 'WSLENV' $null
    try {
        $items = @(& wsl.exe -d $distro -u $user --cd $EntryDirectory --exec python3 -I -B setup/common.py --manifest 2>&1)
        $code = $LASTEXITCODE
    } finally {
        Restore-Variable 'WSLENV' $saved
    }
    $text = @($items | Where-Object { $_ -isnot [System.Management.Automation.ErrorRecord] } |
        ForEach-Object { [string]$_ }) -join "`n"
    if ($code -ne 0) {
        $errors = @($items | Where-Object { $_ -is [System.Management.Automation.ErrorRecord] } |
            ForEach-Object { ([string]$_ -replace "`0", '').Trim() })
        Exit-Entry ('cannot read the installation inputs of ' + $checkout + ' in the WSL distribution ''' + $distro +
            ''' (exit code ' + $code + '): ' + ($errors -join ' '))
    }
    $list = New-Object 'System.Collections.Generic.List[string]'
    foreach ($item in ($text -split "`0")) { if ($item) { $list.Add($item) } }
    if ($list.Count -eq 0) { Exit-Entry 'setup reported no installation inputs' }
    $list.Add($entryName)
    # Exact names only: on .NET Framework '*.ps1' also matches 8.3 names and longer extensions.
    foreach ($file in [IO.Directory]::GetFiles([IO.Path]::Combine($checkout, 'launcher', 'windows'), '*.ps1')) {
        $leaf = [IO.Path]::GetFileName($file)
        if ($leaf -cmatch '^[a-z][a-z0-9-]*\.ps1\z') { $list.Add('launcher/windows/' + $leaf) }
    }
    return , $list.ToArray()
}

if ($setup) {
    Assert-DrivePath $EntryDirectory
    Assert-Checkout $checkout
    Assert-MachineReady
    Invoke-Setup $EntryDirectory
    $code = $script:SessionCode
    if ($code -eq 0 -and $null -ne $installState) {
        [Console]::Out.WriteLine($name + ': start sessions with ' + $name + ' from a project directory')
    } elseif ($code -eq 0) {
        [Console]::Out.WriteLine($name + ': start sessions with .\' + $entryName + ' from a project directory')
    }
    exit $code
}

if ($install) {
    if ($null -eq $installFolder) { Exit-Entry 'LOCALAPPDATA is not set, so there is no folder to install into' }
    Assert-DrivePath $EntryDirectory
    # The install folder must be on a drive too: setup runs from it.
    if ($onWindows -and $installFolder -cnotmatch '^[A-Za-z]:\\[^"]*[^\\"]\z') {
        Exit-Entry ('the install folder ' + $installFolder + ' is not on a Windows drive; LOCALAPPDATA must be a ' +
            'folder on a drive such as C:')
    }
    Assert-Checkout $checkout
    Assert-MachineReady
    $files = Get-InstallManifest
    & ([IO.Path]::Combine($PSScriptRoot, 'install.ps1')) -Action Install -Source $checkout -Target $installFolder `
        -Name $name -Files $files
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
    Assert-Checkout $installFolder
    Invoke-Setup $installFolder
    if ($script:SessionCode -ne 0) {
        [Console]::Error.WriteLine($name + ': setup did not complete; the installed copy in ' + $installFolder +
            ' and its PATH entry stay: run ' + $name + ' --container-setup to finish')
        exit $script:SessionCode
    }
    [Console]::Out.WriteLine($name + ': installed in ' + $installFolder + '. Open a new PowerShell window or ' +
        'Terminal tab and run ' + $name + ' from a project directory; this window may not find it yet.')
    exit 0
}

# Ordinary launch through the release bootstrap.
$location = Get-Location
if ($location.Provider.Name -ne 'FileSystem') {
    Exit-Entry ('the current location ' + $location.Path + ' is not a file system path; change to a project ' +
        'directory on a Windows drive')
}

# Names forwarded to the distribution (design D4); empty values count as unset.
$reservedNames = @('WSLENV', 'BASH_ENV', 'ENV', 'SHELLOPTS', 'BASHOPTS', 'CDPATH', 'GLOBIGNORE', 'IFS', 'PS4',
    'PATH', 'HOME', 'USER', 'LOGNAME', 'SHELL', 'PWD', 'OLDPWD', 'TMPDIR')
$reservedPrefixes = @('WRAPPER_WINDOWS_', 'LD_', 'PYTHON', 'XDG_', 'WSL_', 'CONTAINER_', 'CONTAINERS_')
$forwarded = New-Object 'System.Collections.Generic.SortedSet[string]' ([StringComparer]::Ordinal)
foreach ($key in [Environment]::GetEnvironmentVariables().Keys) {
    $variable = [string]$key
    if ($variable.StartsWith($P + '_', [StringComparison]::Ordinal) -and
        -not $variable.StartsWith($P + '_WSL_', [StringComparison]::Ordinal)) {
        # Windows names may contain ':' or '/', which would split WSLENV and
        # import other variables.
        if ($variable -cnotmatch '^[A-Za-z_][A-Za-z0-9_]*\z') {
            [Console]::Error.WriteLine($name + ': ' + $variable + ' is not forwarded: not a valid variable name')
            continue
        }
        [void]$forwarded.Add($variable)
    }
}
[void]$forwarded.Add($configEnv)
if ($null -ne $bypassEnv) { [void]$forwarded.Add($bypassEnv) }
function Test-ReservedName([string]$Variable) {
    $upper = $Variable.ToUpperInvariant()
    if ($reservedNames -contains $upper) { return $true }
    foreach ($start in $reservedPrefixes) { if ($upper.StartsWith($start, [StringComparison]::Ordinal)) { return $true } }
    return $false
}
foreach ($credential in $credentialEnvs) {
    if (-not (Test-ReservedName $credential)) {
        [void]$forwarded.Add($credential)
    } elseif ($null -ne (Get-Setting $credential)) {
        [Console]::Error.WriteLine($name + ': ' + $credential + ' is not forwarded, because the distribution sets it')
    }
}
$listed = Get-Setting ($P + '_ENV_VARS')
if ($null -ne $listed) {
    $noticed = New-Object 'System.Collections.Generic.HashSet[string]' ([StringComparer]::OrdinalIgnoreCase)
    foreach ($variable in ($listed -split '\s+')) {
        # The core reports invalid names itself; they are not forwarded.
        if ($variable -cnotmatch '^[A-Za-z_][A-Za-z0-9_]*\z') { continue }
        if (Test-ReservedName $variable) {
            if ($noticed.Add($variable)) {
                [Console]::Error.WriteLine($name + ': ' + $P + '_ENV_VARS: ' + $variable +
                    ' is not forwarded, because the distribution sets it')
            }
            continue
        }
        [void]$forwarded.Add($variable)
    }
}
$transport = New-Object 'System.Collections.Generic.List[string]'
$payload = $null
if ($strings.Count -gt 0) {
    $encoding = New-Object System.Text.UTF8Encoding($false, $true)
    $stream = New-Object System.IO.MemoryStream
    for ($i = 0; $i -lt $strings.Count; $i++) {
        try {
            $bytes = $encoding.GetBytes($strings[$i])
        } catch {
            Exit-Entry ('argument ' + ($i + 1) + ' is not valid Unicode text')
        }
        $stream.Write($bytes, 0, $bytes.Length)
        $stream.WriteByte(0)
    }
    $payload = [Convert]::ToBase64String($stream.ToArray())
    if ($payload.Length -gt $script:MaxValue) {
        Exit-Entry ('the arguments are too large: encoded they need ' + $payload.Length + ' characters, more ' +
            'than the ' + $script:MaxValue + ' that one Windows environment variable carries into WSL; pass ' +
            'large data in a file')
    }
    $transport.Add('WRAPPER_WINDOWS_ARGS/u')
}
$transport.Add('WRAPPER_WINDOWS_CWD/u')
$transport.Add('WRAPPER_WINDOWS_ENTRY/u')
foreach ($variable in $forwarded) {
    $value = Get-Setting $variable
    if ($null -eq $value) { continue }
    # The agent's configuration-directory variable often holds a Windows path for
    # the native agent; only a distribution path applies in the session.
    if ($variable -ceq $configEnv -and -not $value.StartsWith('/', [StringComparison]::Ordinal)) {
        [Console]::Error.WriteLine($name + ': ' + $configEnv + ' is not forwarded: ' + $value + ' is not a ' +
            'path in the distribution; the configuration directory saved by setup applies')
        continue
    }
    $transport.Add($variable + '/u')
}
$wslenv = $transport -join ':'
if ($wslenv.Length -gt $script:MaxValue) {
    Exit-Entry ('too many variables to forward: WSLENV would need ' + $wslenv.Length + ' characters, more than ' +
        $script:MaxValue)
}

Assert-Machine
Invoke-WslSession @{
    WRAPPER_WINDOWS_ARGS = $payload
    WRAPPER_WINDOWS_CWD = $location.ProviderPath
    WRAPPER_WINDOWS_ENTRY = $EntryDirectory
    WSLENV = $wslenv
} @('-d', $distro, '-u', $user, '--exec', '/bin/sh', '-c', ('cd && exec /bin/bash ' + $bootstrap))
$code = $script:SessionCode
if ($code -eq -1 -or $code -eq 255) {
    if (-not (Test-User)) { Exit-MissingUser }
    if ($code -eq -1) {
        Exit-Entry ('wsl.exe could not start the session in the WSL distribution ''' + $distro +
            ''' (exit code -1); see its message above')
    }
}
if ($code -eq 127 -and -not (Test-Installation)) {
    Exit-Entry ('no installation was found in the WSL distribution ''' + $distro + ''' for user ''' + $user +
        ''' (' + $installationText + '); run .\' + $entryName + ' --container-setup')
}
exit $code

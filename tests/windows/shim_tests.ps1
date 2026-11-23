# Logic tests of the shared Windows shim (launcher/windows/core.ps1) and the
# thin PowerShell entry. tools/powershell.sh runs them on PowerShell 7 in a
# container without network. Each case builds nothing on Windows: a fake
# wsl.exe first on PATH records every call with the variables WSLENV lists,
# and answers like WSL. The synthetic checkout uses the fixture profiles, and
# each case names the windows-launcher scenario it covers. Windows PowerShell
# 5.1 itself is checked on a Windows host with tools/windows-validate.ps1.
Set-StrictMode -Version 3
$ErrorActionPreference = 'Stop'

$source = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
# SANDBOX_TEST_TMPDIR, as in the other shared tests: the fake wsl.exe must be executable.
$tempRoot = if ($env:SANDBOX_TEST_TMPDIR) { $env:SANDBOX_TEST_TMPDIR } else { [IO.Path]::GetTempPath() }
$work = Join-Path $tempRoot ('shim-tests-' + [guid]::NewGuid().ToString('N'))
$bin = Join-Path $work 'bin'
$script:Record = Join-Path $work 'record.txt'
$project = Join-Path $work 'my project'
$WinEntry = 'C:\Work\checkout'
# Fixture values come from the fixture profiles, never as literals.
$agentProfile = [IO.File]::ReadAllText((Join-Path $source 'tests/fixtures/agent/profile.json')) | ConvertFrom-Json
$shellProfile = [IO.File]::ReadAllText((Join-Path $source 'tests/fixtures/shell-agent/profile.json')) | ConvertFrom-Json
$Name = $agentProfile.name
$Bootstrap = '.local/lib/' + $Name + '/current/launcher/windows/bootstrap.sh'
$Launch = @('-d', 'podman-machine-default', '-u', 'user', '--exec', '/bin/sh', '-c', ('cd && exec /bin/bash ' + $Bootstrap))

$fakeWsl = @'
#!/bin/sh
# Fake wsl.exe: records each call, then answers like WSL.
encode() { printf '%s' "$1" | base64 | tr -d '\n'; }
{
    printf 'call\n'
    for arg in "$@"; do printf 'arg %s\n' "$(encode "$arg")"; done
    printf 'wslenv %s\n' "$(encode "${WSLENV-}")"
    printf 'utf8 %s\n' "${WSL_UTF8-unset}"
    if [ -n "${WSLENV:-}" ]; then
        old_ifs=$IFS
        IFS=:
        for item in $WSLENV; do
            name=${item%%/*}
            if eval "[ -n \"\${$name+x}\" ]"; then
                eval "value=\${$name}"
                printf 'env %s %s\n' "$name" "$(encode "$value")"
            else
                printf 'unset %s\n' "$name"
            fi
        done
        IFS=$old_ifs
    fi
    printf 'end\n'
} >> "$FAKE_WSL_RECORD"
distros=${FAKE_WSL_DISTROS-podman-machine-default}
if [ "$1" = -l ]; then
    list=$distros
    [ "$2" != --running ] || list=${FAKE_WSL_RUNNING-$distros}
    for distro in $list; do
        if [ "${WSL_UTF8:-}" = 1 ] && [ -z "${FAKE_WSL_UTF16:-}" ]; then
            printf '%s\n' "$distro"
        else
            printf '%s\r\n' "$distro" | iconv -f UTF-8 -t UTF-16LE
        fi
    done
    exit 0
fi
case " $distros " in *" $2 "*) ;; *) echo 'Wsl/Service/WSL_E_DISTRO_NOT_FOUND' >&2; exit 255 ;; esac
case " ${FAKE_WSL_USERS-user} " in *" $4 "*) ;; *) echo 'Wsl/WSL_E_USER_NOT_FOUND' >&2; exit 255 ;; esac
shift 4
[ "$*" != '--exec /bin/true' ] || exit 0
case "$*" in
    '--exec /bin/sh -c cd && test -f '*) exit "${FAKE_WSL_INSTALLED:-0}" ;;
    '--exec /bin/sh -c test -d /run/user/'*) exit "${FAKE_WSL_RUNTIME:-0}" ;;
    '--cd '*' --exec python3 -I -B setup/common.py --manifest')
        # wsl.exe may warn on stderr, in UTF-16 when WSL_UTF8 is unset.
        [ -z "${FAKE_WSL_WARNING:-}" ] || printf 'wsl: warning\n' | iconv -f UTF-8 -t UTF-16LE >&2
        for item in ${FAKE_WSL_MANIFEST-}; do printf '%s\0' "$item"; done
        exit 0 ;;
esac
exit "${FAKE_WSL_EXIT:-0}"
'@

$fakeUserPath = @'

# Test store instead of the registry (tests/windows/shim_tests.ps1).
function Read-UserPath {
    $value = ''
    if ([IO.File]::Exists($env:FIXTURE_USER_PATH_FILE)) { $value = [IO.File]::ReadAllText($env:FIXTURE_USER_PATH_FILE) }
    return [pscustomobject]@{ Value = $value; Kind = 'ExpandString' }
}
function Write-UserPath([string]$Value, $Kind) {
    [IO.File]::WriteAllText($env:FIXTURE_USER_PATH_FILE, $Value)
    [IO.File]::WriteAllText($env:FIXTURE_USER_PATH_FILE + '.kind', [string]$Kind)
    return $true
}
'@

# A synthetic checkout: the real entry and shim with a fixture profile.
function Build-Checkout([string]$Root, [string]$Fixture) {
    $profileFile = Join-Path $source ('tests/fixtures/' + $Fixture + '/profile.json')
    $fixtureProfile = [IO.File]::ReadAllText($profileFile) | ConvertFrom-Json
    $entries = @(Get-ChildItem -LiteralPath $source -Filter '*.ps1' -File)
    if ($entries.Count -ne 1) { throw 'expected exactly one PowerShell entry in the checkout root' }
    foreach ($part in @('launcher/windows', 'agent')) {
        [void](New-Item -ItemType Directory -Force -Path (Join-Path $Root $part))
    }
    Copy-Item -LiteralPath $entries[0].FullName -Destination (Join-Path $Root ($fixtureProfile.name + '.ps1'))
    Copy-Item -LiteralPath (Join-Path $source 'launcher/windows/core.ps1') -Destination (Join-Path $Root 'launcher/windows/core.ps1')
    Copy-Item -LiteralPath (Join-Path $source 'launcher/windows/install.ps1') -Destination (Join-Path $Root 'launcher/windows/install.ps1')
    # The real string functions, with a file instead of the registry.
    [IO.File]::WriteAllText((Join-Path $Root 'launcher/windows/user-path.ps1'),
        [IO.File]::ReadAllText((Join-Path $source 'launcher/windows/user-path.ps1')) + $fakeUserPath)
    Copy-Item -LiteralPath $profileFile -Destination (Join-Path $Root 'agent/profile.json')
    foreach ($file in @($fixtureProfile.wrapper, 'launcher/core.sh', 'agent/launcher.sh', 'launcher/windows/enter.sh')) {
        [IO.File]::WriteAllText((Join-Path $Root $file), "#!/usr/bin/env bash`n:`n")
    }
    return (Join-Path $Root ($fixtureProfile.name + '.ps1'))
}

function ConvertFrom-Base64([string]$Value) {
    return [Text.Encoding]::UTF8.GetString([Convert]::FromBase64String($Value))
}

function ConvertFrom-Payload([string]$Value) {
    $bytes = [Convert]::FromBase64String($Value)
    $items = New-Object System.Collections.Generic.List[string]
    $start = 0
    for ($i = 0; $i -lt $bytes.Length; $i++) {
        if ($bytes[$i] -eq 0) {
            $items.Add([Text.Encoding]::UTF8.GetString($bytes, $start, $i - $start))
            $start = $i + 1
        }
    }
    return , $items.ToArray()
}

function Get-Call {
    $calls = New-Object System.Collections.Generic.List[object]
    if (-not [IO.File]::Exists($script:Record)) { return , $calls.ToArray() }
    $current = $null
    foreach ($line in [IO.File]::ReadAllLines($script:Record)) {
        $parts = $line.Split(' ', 3)
        switch ($parts[0]) {
            'call' {
                $current = [pscustomobject]@{ Arguments = (New-Object System.Collections.Generic.List[string])
                    Env = @{}; Unset = (New-Object System.Collections.Generic.List[string]); WslEnv = ''; Utf8 = '' }
            }
            'arg' { $current.Arguments.Add((ConvertFrom-Base64 $parts[1])) }
            'wslenv' { $current.WslEnv = ConvertFrom-Base64 $parts[1] }
            'utf8' { $current.Utf8 = $parts[1] }
            'env' { $current.Env[$parts[1]] = ConvertFrom-Base64 $parts[2] }
            'unset' { $current.Unset.Add($parts[1]) }
            'end' { $calls.Add($current) }
        }
    }
    return , $calls.ToArray()
}

# Runs a call of the entry or shim in this process, capturing the console.
function Invoke-Entry([scriptblock]$Call) {
    if ([IO.File]::Exists($script:Record)) { [IO.File]::Delete($script:Record) }
    $out = New-Object System.IO.StringWriter
    $err = New-Object System.IO.StringWriter
    $oldOut = [Console]::Out
    $oldErr = [Console]::Error
    [Console]::SetOut($out)
    [Console]::SetError($err)
    try {
        $null = & $Call
        $code = $LASTEXITCODE
    } finally {
        [Console]::SetOut($oldOut)
        [Console]::SetError($oldErr)
    }
    return [pscustomobject]@{ Code = $code; Out = $out.ToString(); Err = $err.ToString(); Calls = (Get-Call) }
}

function Format-Value($Value) {
    return (ConvertTo-Json -InputObject $Value -Compress -Depth 4)
}

function Assert-Equal($Expected, $Actual, [string]$What) {
    if ((Format-Value $Expected) -cne (Format-Value $Actual)) {
        throw ($What + ': expected ' + (Format-Value $Expected) + ', got ' + (Format-Value $Actual))
    }
}

function Assert-True([bool]$Condition, [string]$What) {
    if (-not $Condition) { throw $What }
}

function Assert-Text([string]$Expected, [string]$Text, [string]$What) {
    if (-not $Text.Contains($Expected)) { throw ($What + ': ' + (Format-Value $Expected) + ' not in ' + (Format-Value $Text)) }
}

# A refused call: status 1, the message, and no wsl.exe call at all.
function Assert-Refused($Result, [string]$Message, [int]$Calls = 0) {
    Assert-Equal 1 $Result.Code 'status'
    Assert-Text $Message $Result.Err 'message'
    Assert-Equal $Calls $Result.Calls.Count 'wsl.exe calls'
}

function Get-LaunchCall($Result) {
    Assert-Equal 2 $Result.Calls.Count 'wsl.exe calls (running list, launch)'
    Assert-Equal @('-l', '--running', '-q') $Result.Calls[0].Arguments.ToArray() 'list call'
    return $Result.Calls[1]
}

function Get-Argument($Result) {
    $call = Get-LaunchCall $Result
    if (-not $call.Env.ContainsKey('WRAPPER_WINDOWS_ARGS')) { return , @() }
    return , (ConvertFrom-Payload $call.Env['WRAPPER_WINDOWS_ARGS'])
}

function Clear-Setting([string]$Name) {
    if (Test-Path -LiteralPath ('Env:' + $Name)) { Remove-Item -LiteralPath ('Env:' + $Name) }
}

function Initialize-Case {
    foreach ($key in @([Environment]::GetEnvironmentVariables().Keys)) {
        if ([string]$key -cmatch '^(FAKE_WSL_|FIXTURE_|WRAPPER_WINDOWS_|WSL)|^(GH_TOKEN|USERPROFILE)$') {
            Clear-Setting ([string]$key)
        }
    }
    $env:FAKE_WSL_RECORD = $script:Record
    [IO.File]::WriteAllText((Join-Path $script:Checkout 'launcher/core.sh'), "#!/usr/bin/env bash`n:`n")
    # A fresh per-user folder and user PATH for every case.
    $local = Join-Path $work 'local'
    if ([IO.Directory]::Exists($local)) { [IO.Directory]::Delete($local, $true) }
    $env:LOCALAPPDATA = $local
    $env:FIXTURE_USER_PATH_FILE = Join-Path $work 'user-path.txt'
    foreach ($file in @($env:FIXTURE_USER_PATH_FILE, ($env:FIXTURE_USER_PATH_FILE + '.kind'))) {
        if ([IO.File]::Exists($file)) { [IO.File]::Delete($file) }
    }
    Set-Location -LiteralPath $project
}

# Installer helpers: the payload of the synthetic checkout and the installed copy.
$Payload = @($agentProfile.wrapper, 'launcher/core.sh', 'agent/launcher.sh', 'launcher/windows/enter.sh', 'agent/profile.json')
function Get-Target { return (Join-Path (Join-Path $env:LOCALAPPDATA 'Programs') $Name) }
function Invoke-Install {
    $env:FAKE_WSL_MANIFEST = $Payload -join ' '
    return (Invoke-Entry { & $Core -EntryDirectory $WinEntry -Arguments @('--container-install') })
}
function Get-InstallState { return ([IO.File]::ReadAllText((Join-Path (Get-Target) 'install.json')) | ConvertFrom-Json) }
# The stored value, followed by '|' and its kind once the installer wrote it.
function Get-UserPathFile {
    $value = ''
    if ([IO.File]::Exists($env:FIXTURE_USER_PATH_FILE)) { $value = [IO.File]::ReadAllText($env:FIXTURE_USER_PATH_FILE) }
    if ([IO.File]::Exists($env:FIXTURE_USER_PATH_FILE + '.kind')) {
        $value += '|' + [IO.File]::ReadAllText($env:FIXTURE_USER_PATH_FILE + '.kind')
    }
    return $value
}

$script:Results = New-Object System.Collections.Generic.List[string]
$script:Failures = 0
function Test-Case([string]$Scenario, [scriptblock]$Body) {
    Initialize-Case
    try {
        & $Body
        $script:Results.Add('PASS ' + $Scenario)
    } catch {
        $script:Failures++
        $script:Results.Add('FAIL ' + $Scenario + ': ' + $_.Exception.Message)
    }
}

[void](New-Item -ItemType Directory -Force -Path $bin, $project)
$fakePath = Join-Path $bin 'wsl.exe'
[IO.File]::WriteAllText($fakePath, $fakeWsl)
& chmod 700 $fakePath
$env:PATH = $bin + [IO.Path]::PathSeparator + $env:PATH
$script:Checkout = Join-Path $work 'checkout'
$Entry = Build-Checkout $script:Checkout 'agent'
$Core = Join-Path $script:Checkout 'launcher/windows/core.ps1'
$shellCheckout = Join-Path $work 'shell-checkout'
$ShellEntry = Build-Checkout $shellCheckout 'shell-agent'
$e = [string][char]0x00E8
$emoji = [char]::ConvertFromUtf32(0x1F600)
$location = Get-Location

try {
    Test-Case 'Ordinary launches / Release bootstrap only; Default machine' {
        $r = Invoke-Entry { & $Entry -c true }
        Assert-Equal 0 $r.Code 'status'
        $call = Get-LaunchCall $r
        Assert-Equal '1' $r.Calls[0].Utf8 'WSL_UTF8 for the list'
        Assert-Equal $Launch $call.Arguments.ToArray() 'launch call'
        Assert-Equal 'unset' $call.Utf8 'WSL_UTF8 for the launch'
        Assert-Equal $project $call.Env['WRAPPER_WINDOWS_CWD'] 'working directory'
        Assert-Equal $script:Checkout $call.Env['WRAPPER_WINDOWS_ENTRY'] 'entry directory'
        Assert-Equal @('-c', 'true') (Get-Argument $r) 'arguments'
        Assert-True (-not $call.WslEnv.Contains('WRAPPER_WINDOWS_SETUP')) 'no setup marker for a launch'
    }
    Test-Case 'Machine distribution and user selection / Default machine (older WSL writes UTF-16)' {
        $env:FAKE_WSL_UTF16 = '1'
        $r = Invoke-Entry { & $Entry }
        Assert-Equal 0 $r.Code 'status'
        Assert-Equal $Launch (Get-LaunchCall $r).Arguments.ToArray() 'launch call'
    }
    Test-Case 'Machine distribution and user selection / Other distribution and user' {
        $env:FIXTURE_AGENT_WSL_DISTRO = 'other-machine'
        $env:FIXTURE_AGENT_WSL_USER = 'dev'
        $env:FAKE_WSL_DISTROS = 'Ubuntu other-machine'
        $env:FAKE_WSL_USERS = 'dev'
        $r = Invoke-Entry { & $Entry }
        Assert-Equal 0 $r.Code 'status'
        Assert-Equal @('-d', 'other-machine', '-u', 'dev') (Get-LaunchCall $r).Arguments.GetRange(0, 4).ToArray() 'selection'
        Assert-True (-not ((Get-LaunchCall $r).WslEnv -match 'WSL_DISTRO')) '<P>_WSL_* is not forwarded'
    }
    Test-Case 'Machine distribution and user selection / Invalid name' {
        $env:FIXTURE_AGENT_WSL_DISTRO = 'bad name'
        Assert-Refused (Invoke-Entry { & $Entry }) 'FIXTURE_AGENT_WSL_DISTRO must contain only letters'
        $env:FIXTURE_AGENT_WSL_DISTRO = 'podman-machine-default'
        $env:FIXTURE_AGENT_WSL_USER = 'us"er'
        Assert-Refused (Invoke-Entry { & $Entry }) 'FIXTURE_AGENT_WSL_USER must contain only letters'
    }
    Test-Case 'Machine distribution and user selection / Missing distribution' {
        $env:FAKE_WSL_DISTROS = 'Ubuntu'
        $r = Invoke-Entry { & $Entry -c true }
        Assert-Refused $r 'the WSL distribution ''podman-machine-default'' is not registered' 2
        Assert-Text 'Podman Desktop' $r.Err 'guidance'
    }
    Test-Case 'Machine distribution and user selection / Missing user' {
        $env:FIXTURE_AGENT_WSL_USER = 'nobody'
        $r = Invoke-Entry { & $Entry -c true }
        Assert-Refused $r 'the user ''nobody'' does not exist in the WSL distribution ''podman-machine-default''' 3
        Assert-Equal @('-d', 'podman-machine-default', '-u', 'nobody', '--exec', '/bin/true') $r.Calls[2].Arguments.ToArray() 'user probe'
    }
    Test-Case 'Exit status, terminal and interruption / Exit status (255 from the session)' {
        $env:FAKE_WSL_EXIT = '255'
        $r = Invoke-Entry { & $Entry -c 'exit 255' }
        Assert-Equal 255 $r.Code 'status'
        Assert-Equal 3 $r.Calls.Count 'user probe after 255'
    }
    Test-Case 'Installation location and missing installation / Custom installation directory' {
        $env:FIXTURE_AGENT_WSL_INSTALLATION = '/home/user/sandbox'
        $r = Invoke-Entry { & $Entry }
        Assert-Equal 'cd && exec /bin/bash /home/user/sandbox/current/launcher/windows/bootstrap.sh' (Get-LaunchCall $r).Arguments[7] 'bootstrap'
        $env:FIXTURE_AGENT_WSL_INSTALLATION = 'home/user/sandbox'
        Assert-Refused (Invoke-Entry { & $Entry }) 'FIXTURE_AGENT_WSL_INSTALLATION must be an absolute distribution path'
    }
    Test-Case 'Installation location and missing installation / Machine reset' {
        $env:FAKE_WSL_EXIT = '127'
        $env:FAKE_WSL_INSTALLED = '1'
        $r = Invoke-Entry { & $Entry }
        Assert-Refused $r ('run .\' + $Name + '.ps1 --container-setup') 3
        Assert-Equal @('-d', 'podman-machine-default', '-u', 'user', '--exec', '/bin/sh', '-c', ('cd && test -f ' + $Bootstrap)) $r.Calls[2].Arguments.ToArray() 'installation probe'
        $env:FAKE_WSL_INSTALLED = '0'
        Assert-Equal 127 (Invoke-Entry { & $Entry }).Code '127 from the session'
    }
    Test-Case 'Arguments reach Bash unchanged / Quotes and empty values' {
        $r = Invoke-Entry { & $Entry -c 'printf "<%s>" "$@"' x '' 'a "b" c\' '\\server\x' ('tab' + "`t" + 'nl' + "`n" + 'end') }
        Assert-Equal @('-c', 'printf "<%s>" "$@"', 'x', '', 'a "b" c\', '\\server\x', ('tab' + "`t" + 'nl' + "`n" + 'end')) (Get-Argument $r) 'arguments'
        Assert-True (-not ($r.Calls[1].Arguments -contains 'x')) 'no argument value on the wsl.exe command line'
    }
    Test-Case 'Arguments reach Bash unchanged / Non-ASCII argument' {
        Assert-Equal @(($e + $emoji)) (Get-Argument (Invoke-Entry { & $Entry ($e + $emoji) })) 'arguments'
    }
    Test-Case 'Arguments reach Bash unchanged / No arguments and one empty argument differ' {
        $r = Invoke-Entry { & $Entry }
        Assert-True (-not ((Get-LaunchCall $r).WslEnv -match 'WRAPPER_WINDOWS_ARGS')) 'no transport variable without arguments'
        Assert-Equal @('') (Get-Argument (Invoke-Entry { & $Entry '' })) 'one empty argument'
    }
    Test-Case 'Arguments reach Bash unchanged / PowerShell binding of --, numbers and -x:y' {
        Assert-Equal @('x') (Get-Argument (Invoke-Entry { & $Entry -- x })) 'bare -- is consumed by PowerShell'
        Assert-Equal @('--', 'x', '5', '-x:', 'y') (Get-Argument (Invoke-Entry { & $Entry '--' x 5 -x:y })) 'quoted --, number, -x:y'
    }
    Test-Case 'Arguments reach Bash unchanged / Oversized arguments' {
        Assert-Equal 1 (Get-Argument (Invoke-Entry { & $Entry ('a' * 24572) })).Count 'largest accepted argument'
        Assert-Refused (Invoke-Entry { & $Entry ('a' * 24573) }) 'more than the 32766'
    }
    Test-Case 'Arguments reach Bash unchanged / Unquoted comma' {
        Assert-Refused (Invoke-Entry { & $Entry -c true a,b }) 'argument 3 is a list'
    }
    Test-Case 'Environment forwarded by name / Launch settings from PowerShell; Listed variable; Name reserved; Unrelated variable' {
        $env:FIXTURE_AGENT_MEMORY_LIMIT = '2g'
        $env:FIXTURE_AGENT_YOLO = '1'
        $env:FIXTURE_CONFIG_DIR = '/home/user/.fixture'
        $env:FIXTURE_AGENT_WSL_USER = 'user'
        $env:FIXTURE_AGENT_ENV_VARS = 'GH_TOKEN PATH  LD_PRELOAD PATH bad-name'
        $env:GH_TOKEN = 'secret'
        $env:USERPROFILE = 'C:\Users\me'
        $env:WSLENV = 'USERPROFILE/p'
        $r = Invoke-Entry { & $Entry }
        $call = Get-LaunchCall $r
        foreach ($pair in @(@('FIXTURE_AGENT_MEMORY_LIMIT', '2g'), @('FIXTURE_AGENT_YOLO', '1'),
                @('FIXTURE_CONFIG_DIR', '/home/user/.fixture'), @('GH_TOKEN', 'secret'),
                @('FIXTURE_AGENT_ENV_VARS', 'GH_TOKEN PATH  LD_PRELOAD PATH bad-name'))) {
            Assert-Equal $pair[1] $call.Env[$pair[0]] $pair[0]
        }
        foreach ($name in @('PATH', 'LD_PRELOAD', 'USERPROFILE', 'FIXTURE_AGENT_WSL_USER', 'bad-name')) {
            Assert-True (-not (($call.WslEnv -split ':') -contains ($name + '/u'))) ($name + ' is not forwarded')
        }
        Assert-True (-not $call.WslEnv.Contains('/p')) 'the user WSLENV is replaced'
        Assert-Equal 1 ([regex]::Matches($r.Err, 'PATH is not forwarded')).Count 'one notice for PATH'
        Assert-Text 'LD_PRELOAD is not forwarded' $r.Err 'notice for LD_PRELOAD'
    }
    Test-Case 'Environment forwarded by name / Name that would split WSLENV' {
        [Environment]::SetEnvironmentVariable('FIXTURE_AGENT_X:BASH_ENV/u', '/tmp/x')
        try {
            $r = Invoke-Entry { & $Entry }
            $call = Get-LaunchCall $r
            Assert-True (-not $call.WslEnv.Contains('BASH_ENV')) 'no BASH_ENV in WSLENV'
            Assert-Text 'FIXTURE_AGENT_X:BASH_ENV/u is not forwarded: not a valid variable name' $r.Err 'notice'
        } finally {
            [Environment]::SetEnvironmentVariable('FIXTURE_AGENT_X:BASH_ENV/u', $null)
        }
    }
    Test-Case 'Environment forwarded by name / Credential variable of an authentication method; Credential variable not set' {
        $env:FIXTURE_API_KEY = 'key value'
        $env:WSLENV = 'USERPROFILE/p'
        $r = Invoke-Entry { & $Entry -c true }
        $call = Get-LaunchCall $r
        Assert-True (($call.WslEnv -split ':') -contains 'FIXTURE_API_KEY/u') 'FIXTURE_API_KEY in WSLENV'
        Assert-Equal 'key value' $call.Env['FIXTURE_API_KEY'] 'FIXTURE_API_KEY value'
        Assert-Equal 'USERPROFILE/p' $env:WSLENV 'WSLENV restored'
        Assert-Equal 'key value' $env:FIXTURE_API_KEY 'PowerShell value kept'
        foreach ($value in @($null, '')) {
            [Environment]::SetEnvironmentVariable('FIXTURE_API_KEY', $value)
            $call = Get-LaunchCall (Invoke-Entry { & $Entry -c true })
            Assert-True (-not $call.WslEnv.Contains('FIXTURE_API_KEY')) ('key ' + (Format-Value $value) + ' is not forwarded')
        }
        $env:FIXTURE_API_KEY = 'key value'
        $call = Get-LaunchCall (Invoke-Entry { & $ShellEntry -c true })
        Assert-True (-not $call.WslEnv.Contains('FIXTURE_API_KEY')) 'a profile without methods forwards no key'
        $shellCore = Join-Path $shellCheckout 'launcher/windows/core.ps1'
        $r = Invoke-Entry { & $shellCore -EntryDirectory $WinEntry -Arguments @('--container-help') }
        Assert-Equal 0 $r.Code ('help status: ' + $r.Err)
        Assert-Text 'Windows entry (fixture-shell.ps1' $r.Out 'shell Windows part'
        Assert-True (-not $r.Out.Contains('Authentication keys')) 'no key line in the help of a profile without methods'
    }
    Test-Case 'Environment forwarded by name / Windows path in the configuration-directory variable' {
        $env:FIXTURE_CONFIG_DIR = 'C:\Users\me\.fixture'
        $r = Invoke-Entry { & $Entry }
        $call = Get-LaunchCall $r
        Assert-True (-not (($call.WslEnv -split ':') -contains 'FIXTURE_CONFIG_DIR/u')) 'Windows path not forwarded'
        Assert-Text 'FIXTURE_CONFIG_DIR is not forwarded: C:\Users\me\.fixture is not a path in the distribution' $r.Err 'notice'
    }
    Test-Case 'Empty Windows variables count as unset / Empty value in PowerShell 7' {
        [Environment]::SetEnvironmentVariable('FIXTURE_AGENT_MEMORY_LIMIT', '')
        $call = Get-LaunchCall (Invoke-Entry { & $Entry })
        Assert-True (-not $call.WslEnv.Contains('FIXTURE_AGENT_MEMORY_LIMIT')) 'empty value is not forwarded'
    }
    Test-Case 'Environment forwarded by name / Session environment restored' {
        $env:WSLENV = 'USERPROFILE/p'
        $env:WRAPPER_WINDOWS_CWD = 'previous'
        foreach ($status in @('0', '7')) {
            $env:FAKE_WSL_EXIT = $status
            $r = Invoke-Entry { & $Entry -c true }
            Assert-Equal ([int]$status) $r.Code 'status'
            Assert-Equal 'USERPROFILE/p' $env:WSLENV 'WSLENV'
            Assert-Equal 'previous' $env:WRAPPER_WINDOWS_CWD 'WRAPPER_WINDOWS_CWD'
            foreach ($name in @('WRAPPER_WINDOWS_ARGS', 'WRAPPER_WINDOWS_ENTRY', 'WSL_UTF8')) {
                Assert-True (-not (Test-Path -LiteralPath ('Env:' + $name))) ($name + ' stays absent')
            }
        }
    }
    Test-Case 'Windows working directory translation / Drive path with spaces (raw location passed on)' {
        Assert-Equal $project (Get-LaunchCall (Invoke-Entry { & $Entry })).Env['WRAPPER_WINDOWS_CWD'] 'raw location'
    }
    Test-Case 'Windows working directory translation / Registry location' {
        Set-Location -LiteralPath 'Env:'
        Assert-Refused (Invoke-Entry { & $Entry }) 'is not a file system path'
    }
    Test-Case 'Network modes from setup, without delegation / Offline session; Provider session' {
        foreach ($mode in @('offline', 'provider')) {
            $env:FIXTURE_AGENT_NETWORK = $mode
            $call = Get-LaunchCall (Invoke-Entry { & $Entry })
            Assert-Equal $mode $call.Env['FIXTURE_AGENT_NETWORK'] ('forwarded ' + $mode)
            Assert-Text 'FIXTURE_AGENT_NETWORK/u' $call.WslEnv ('WSLENV names ' + $mode)
        }
    }
    Test-Case 'Network modes from setup, without delegation / Qualification' {
        Assert-Equal @('--container-qualify') (Get-Argument (Invoke-Entry { & $Entry --container-qualify })) 'arguments'
    }
    Test-Case 'Network modes from setup, without delegation / Delegation requested' {
        $env:FIXTURE_AGENT_PODMAN = '1'
        Assert-Refused (Invoke-Entry { & $Entry }) 'Podman delegation (FIXTURE_AGENT_PODMAN=1) is unsupported on Podman machine'
        $env:FIXTURE_AGENT_NETWORK = 'offline'
        Assert-Refused (Invoke-Entry { & $Entry --container-qualify }) 'Podman delegation (FIXTURE_AGENT_PODMAN=1) is unsupported'
    }
    Test-Case 'Network modes from setup, without delegation / Mode from setup; explicit unrestricted' {
        $env:FIXTURE_AGENT_PODMAN = '0'
        Assert-Equal 0 (Invoke-Entry { & $Entry }).Code 'delegation disabled'
        $env:FIXTURE_AGENT_NETWORK = 'unrestricted'
        Assert-Equal 'unrestricted' (Get-LaunchCall (Invoke-Entry { & $Entry })).Env['FIXTURE_AGENT_NETWORK'] 'forwarded mode'
    }
    Test-Case 'Pipeline input refused, redirected input unchanged / Pipeline input' {
        Assert-Refused (Invoke-Entry { 'text' | & $Entry -c cat }) 'pipeline input is unsupported'
        $entryFile = Join-Path $script:Checkout ($Name + '.ps1')
        foreach ($line in @(@('pwsh', '-File', (Join-Path $work 'other.ps1')), @('powershell.exe', '-Command', '& x', '-File', $entryFile),
                @('powershell.exe', '-co', '& x', '-File', $entryFile), @('powershell.exe', '-E', 'eAA=', '-File', $entryFile))) {
            Assert-Refused (Invoke-Entry { & $Core -EntryDirectory $script:Checkout -Arguments @('-c', 'cat') -PipelineInput -CommandLine $line }) 'pipeline input is unsupported'
        }
    }
    Test-Case 'Pipeline input refused, redirected input unchanged / Redirected input (Windows PowerShell 5.1 -File)' {
        # 5.1 reports stdin redirected to powershell -File <entry> as pipeline input; no pipeline can feed that script.
        $line = @('powershell.exe', '-NoProfile', '-ExecutionPolicy', 'Bypass', '-fil', (Join-Path $script:Checkout ($Name + '.ps1')).ToUpperInvariant(), '-c', 'cat')
        $r = Invoke-Entry { & $Core -EntryDirectory $script:Checkout -Arguments @('-c', 'cat') -PipelineInput -CommandLine $line }
        if ([Console]::IsInputRedirected) {
            Assert-Equal 0 $r.Code 'status'
            Assert-Equal @('-c', 'cat') (Get-Argument $r) 'arguments'
        } else {
            Assert-Refused $r 'pipeline input is unsupported'
        }
    }
    Test-Case 'Exit status, terminal and interruption / Exit status' {
        $env:FAKE_WSL_EXIT = '7'
        Assert-Equal 7 (Invoke-Entry { & $Entry -c 'exit 7' }).Code 'status'
    }
    Test-Case 'Windows entry help / Help with a machine (precedence over every other argument)' {
        $env:FIXTURE_AGENT_NETWORK = 'offline'
        $r = Invoke-Entry { & $Core -EntryDirectory $WinEntry -Arguments @('x', @('a', 'b'), '--container-help') -PipelineInput }
        Assert-Equal 0 $r.Code 'status'
        foreach ($text in @('FIXTURE_AGENT_WSL_DISTRO', 'FIXTURE_AGENT_WSL_USER', 'FIXTURE_AGENT_WSL_INSTALLATION',
                'FIXTURE_AGENT_NETWORK           unrestricted, offline or provider (default: the mode setup saved)',
                'Podman delegation (FIXTURE_AGENT_PODMAN=1) is refused.', 'pipeline input', '--container-install', '--container-uninstall',
                'Authentication keys forwarded when set: FIXTURE_API_KEY.')) {
            Assert-Text $text $r.Out 'Windows part'
        }
        Assert-Equal @('-d', 'podman-machine-default', '-u', 'user', '--cd', $WinEntry, '--exec', '/bin/bash', $agentProfile.wrapper, '--container-help') $r.Calls[1].Arguments.ToArray() 'wrapper help call'
        Assert-Equal '' $r.Calls[1].WslEnv 'no forwarded variables'
    }
    Test-Case 'Windows entry help / Help without a machine' {
        $env:FAKE_WSL_DISTROS = 'Ubuntu'
        $r = Invoke-Entry { & $Core -EntryDirectory $WinEntry -Arguments @('--container-help') }
        Assert-Equal 0 $r.Code 'status'
        Assert-Text 'FIXTURE_AGENT_WSL_DISTRO' $r.Out 'Windows part'
        Assert-Text 'Podman Desktop' $r.Out 'machine guidance'
        Assert-Equal 2 $r.Calls.Count 'only the two list calls'
    }
    Test-Case 'Machine started by Podman / Stopped machine' {
        $env:FAKE_WSL_RUNNING = 'none'
        $r = Invoke-Entry { & $Entry -c true }
        Assert-Refused $r 'the Podman machine is stopped: the WSL distribution ''podman-machine-default'' is not running' 2
        Assert-Text 'podman machine start' $r.Err 'start guidance'
        Assert-Equal @('-l', '-q') $r.Calls[1].Arguments.ToArray() 'second list call'
        $r = Invoke-Entry { & $Core -EntryDirectory $WinEntry -Arguments @('--container-setup') }
        Assert-Refused $r 'the Podman machine is stopped' 2
    }
    Test-Case 'Machine started by Podman / Distribution started by WSL alone (setup)' {
        $env:FAKE_WSL_RUNTIME = '1'
        $r = Invoke-Entry { & $Core -EntryDirectory $WinEntry -Arguments @('--container-setup') }
        Assert-Refused $r 'the WSL distribution ''podman-machine-default'' runs without the Podman machine' 2
        Assert-Text 'Run wsl --terminate podman-machine-default, then start the machine' $r.Err 'restart guidance'
        Assert-Equal @('-d', 'podman-machine-default', '-u', 'user', '--exec', '/bin/sh', '-c', 'test -d /run/user/$(id -u) -a -w /run/user/$(id -u)') $r.Calls[1].Arguments.ToArray() 'runtime probe'
        $env:FIXTURE_AGENT_WSL_USER = 'nobody'
        $r = Invoke-Entry { & $Core -EntryDirectory $WinEntry -Arguments @('--container-setup') }
        Assert-Refused $r 'the user ''nobody'' does not exist' 3
    }
    Test-Case 'Machine started by Podman / Help with a stopped machine' {
        $env:FAKE_WSL_RUNNING = 'none'
        $r = Invoke-Entry { & $Core -EntryDirectory $WinEntry -Arguments @('--container-help') }
        Assert-Equal 0 $r.Code 'status'
        Assert-Text 'FIXTURE_AGENT_WSL_DISTRO' $r.Out 'Windows part'
        Assert-Text 'The Podman machine is stopped' $r.Out 'machine guidance'
        Assert-Equal 2 $r.Calls.Count 'only the two list calls'
    }
    Test-Case 'Setup from the Windows checkout / First setup on Windows' {
        $env:WSLENV = 'USERPROFILE/p'
        $r = Invoke-Entry { & $Core -EntryDirectory $WinEntry -Arguments @('--container-setup') }
        Assert-Equal 0 $r.Code 'status'
        Assert-Equal 3 $r.Calls.Count 'running list, runtime probe, setup'
        Assert-Equal @('-d', 'podman-machine-default', '-u', 'user', '--cd', $WinEntry, '--exec', '/bin/bash', 'launcher/windows/enter.sh', $Name, '/bin/bash', $agentProfile.wrapper, '--container-setup') $r.Calls[2].Arguments.ToArray() 'setup call through the namespace helper'
        Assert-Equal 'WRAPPER_WINDOWS_SETUP/u' $r.Calls[2].WslEnv 'only the Windows setup marker'
        Assert-Equal '1' $r.Calls[2].Env['WRAPPER_WINDOWS_SETUP'] 'marker value'
        Assert-True (-not (Test-Path -LiteralPath 'Env:WRAPPER_WINDOWS_SETUP')) 'marker removed from the session'
        Assert-Text ('start sessions with .\' + $Name + '.ps1 from a project directory') $r.Out 'next step'
        Assert-Equal 'USERPROFILE/p' $env:WSLENV 'WSLENV restored'
    }
    Test-Case 'Setup from the Windows checkout / Setup with other arguments' {
        Assert-Refused (Invoke-Entry { & $Core -EntryDirectory $WinEntry -Arguments @('--container-setup', '--container-shell') }) '--container-setup must be used alone'
        Assert-Refused (Invoke-Entry { & $Core -EntryDirectory '\\server\share\checkout' -Arguments @('--container-setup') }) 'is not a folder on a Windows drive'
    }
    Test-Case 'Sessions and setup in the machine''s systemd namespaces / Checkout without the namespace helper' {
        $helper = Join-Path $script:Checkout 'launcher/windows/enter.sh'
        [IO.File]::Delete($helper)
        try {
            $r = Invoke-Entry { & $Core -EntryDirectory $WinEntry -Arguments @('--container-setup') }
            Assert-Refused $r 'the checkout is incomplete: launcher/windows/enter.sh cannot be read'
        } finally {
            [IO.File]::WriteAllText($helper, "#!/usr/bin/env bash`n:`n")
        }
    }
    Test-Case 'Checkout line endings checked before setup / Checkout converted to CRLF' {
        [IO.File]::WriteAllText((Join-Path $script:Checkout 'launcher/core.sh'), "#!/usr/bin/env bash`r`n:`r`n")
        $r = Invoke-Entry { & $Core -EntryDirectory $WinEntry -Arguments @('--container-setup') }
        Assert-Refused $r 'the checkout has CRLF line endings: launcher/core.sh'
        Assert-Text 'git rm -r -q --cached . and then git reset --hard' $r.Err 'renormalization step'
    }
    Test-Case 'Environment forwarded by name / Profile without an approval-bypass variable' {
        $env:FIXTURE_SHELL_CONFIG_DIR = '/home/user/.config/fixture-shell'
        $r = Invoke-Entry { & $ShellEntry -c true }
        Assert-Equal 0 $r.Code 'status'
        $call = Get-LaunchCall $r
        Assert-Equal '/home/user/.config/fixture-shell' $call.Env['FIXTURE_SHELL_CONFIG_DIR'] 'configuration directory'
        Assert-Equal ('cd && exec /bin/bash .local/lib/' + $shellProfile.name + '/current/launcher/windows/bootstrap.sh') $call.Arguments[7] 'bootstrap'
    }
    Test-Case 'Command on the user PATH / Existing PATH entries (string rules)' {
        . (Join-Path $source 'launcher/windows/user-path.ps1')
        $env:FIXTURE_PATH_ROOT = 'C:\Users\me\AppData\Local'
        $folder = 'C:\Users\me\AppData\Local\Programs\tool'
        foreach ($case in @(
                @('', $folder),
                @('A;B', ('A;B;' + $folder)),
                @('A;', ('A;' + $folder + ';')),
                @('A;;B', ('A;;B;' + $folder)),
                @('A;c:\users\ME\appdata\local\programs\TOOL\;B', 'A;c:\users\ME\appdata\local\programs\TOOL\;B'),
                @('%FIXTURE_PATH_ROOT%\Programs\tool;A', '%FIXTURE_PATH_ROOT%\Programs\tool;A'),
                @('%FIXTURE_PATH_ROOT%\Microsoft\WindowsApps', ('%FIXTURE_PATH_ROOT%\Microsoft\WindowsApps;' + $folder)))) {
            Assert-Equal $case[1] (Get-PathWithEntry $case[0] $folder) ('add to ' + $case[0])
        }
        foreach ($case in @(
                @('', ''),
                @($folder, ''),
                @(('A;' + $folder + ';B'), 'A;B'),
                @(('A;;c:\users\me\appdata\local\programs\tool\;B;' + $folder), 'A;;B'),
                @('%FIXTURE_PATH_ROOT%\Programs\tool;%OTHER%\bin', '%OTHER%\bin'),
                @('A;B', 'A;B'))) {
            Assert-Equal $case[1] (Get-PathWithoutEntry $case[0] $folder) ('remove from ' + $case[0])
        }
        # Uninstall restores the value the install found, byte for byte (round 9).
        foreach ($value in @('', 'A', 'A;', 'A;B;', 'A;;B', ';A', '%FIXTURE_PATH_ROOT%\bin;')) {
            Assert-Equal $value (Get-PathWithoutEntry (Get-PathWithEntry $value $folder) $folder) ('round trip of ' + $value)
        }
    }
    Test-Case 'Self-contained installed copy / Install from a checkout; Command on the user PATH; First install' {
        $r = Invoke-Install
        Assert-Equal 0 $r.Code ('status: ' + $r.Err)
        $target = Get-Target
        $state = Get-InstallState
        Assert-Equal 'complete' $state.state 'install.json state'
        $expected = @($Payload + @(($Name + '.ps1'), 'launcher/windows/core.ps1', 'launcher/windows/install.ps1', 'launcher/windows/user-path.ps1') | Sort-Object -CaseSensitive)
        Assert-Equal $expected @($state.files) 'installed files'
        foreach ($file in $expected) {
            $a = [IO.File]::ReadAllBytes((Join-Path $script:Checkout $file)); $b = [IO.File]::ReadAllBytes((Join-Path $target $file))
            Assert-True ([Convert]::ToBase64String($a) -ceq [Convert]::ToBase64String($b)) ($file + ' has the source bytes')
        }
        Assert-Equal ($target + '|ExpandString') (Get-UserPathFile) 'user PATH'
        Assert-Text ('adding ' + $target + ' to your user PATH') $r.Out 'announcement'
        Assert-Text ('installed in ' + $target) $r.Out 'next step'
        $setup = $r.Calls[$r.Calls.Count - 1]
        Assert-Equal @('-d', 'podman-machine-default', '-u', 'user', '--cd', $target, '--exec', '/bin/bash', 'launcher/windows/enter.sh', $Name, '/bin/bash', $agentProfile.wrapper, '--container-setup') $setup.Arguments.ToArray() 'setup from the installed copy'
        Assert-Equal '1' $setup.Env['WRAPPER_WINDOWS_SETUP'] 'Windows setup marker'
        Assert-True (-not [IO.File]::Exists($target + '.lock')) 'lock released'
    }
    Test-Case 'Self-contained installed copy / Source deleted after install; Setup from the installed copy' {
        $env:FAKE_WSL_WARNING = '1'
        Assert-Equal 0 (Invoke-Install).Code 'install despite a wsl.exe warning on stderr'
        $target = Get-Target
        $away = $script:Checkout + '-away'
        [IO.Directory]::Move($script:Checkout, $away)
        try {
            $r = Invoke-Entry { & (Join-Path $target ($Name + '.ps1')) -c true }
            Assert-Equal 0 $r.Code ('launch from the installed copy: ' + $r.Err)
            Assert-Equal $target (Get-LaunchCall $r).Env['WRAPPER_WINDOWS_ENTRY'] 'entry directory'
            $r = Invoke-Entry { & (Join-Path $target 'launcher/windows/core.ps1') -EntryDirectory 'C:\Users\me\AppData\Local\Programs\fixture' -Arguments @('--container-setup') }
            Assert-Equal 0 $r.Code ('setup from the installed copy: ' + $r.Err)
            Assert-Text ('start sessions with ' + $Name + ' from a project directory') $r.Out 'next step without .\'
        } finally {
            [IO.Directory]::Move($away, $script:Checkout)
        }
    }
    Test-Case 'Self-contained installed copy / Only exact Windows script names' {
        $extra = Join-Path $script:Checkout 'launcher/windows/Backup Copy.ps1'
        [IO.File]::WriteAllText($extra, '# not a shared script')
        try {
            Assert-Equal 0 (Invoke-Install).Code 'install'
        } finally {
            [IO.File]::Delete($extra)
        }
        Assert-True (-not [IO.File]::Exists((Join-Path (Get-Target) 'launcher/windows/Backup Copy.ps1'))) 'not installed'
    }
    Test-Case 'Interrupted or concurrent install / Unexpected error' {
        [void][IO.Directory]::CreateDirectory($env:FIXTURE_USER_PATH_FILE)
        try {
            $r = Invoke-Install
        } finally {
            [IO.Directory]::Delete($env:FIXTURE_USER_PATH_FILE)
        }
        Assert-Equal 1 $r.Code 'status'
        Assert-Text ($Name + ': the install stopped: ') $r.Err 'message with the prefix'
    }
    Test-Case 'Command on the user PATH / Existing PATH entries (install)' {
        [IO.File]::WriteAllText($env:FIXTURE_USER_PATH_FILE, '%FIXTURE_X%\bin;' + (Get-Target).ToUpperInvariant() + '\')
        Assert-Equal 0 (Invoke-Install).Code 'install'
        Assert-Equal ('%FIXTURE_X%\bin;' + (Get-Target).ToUpperInvariant() + '\') (Get-UserPathFile) 'PATH unchanged when already listed'
    }
    Test-Case 'Update from a newer source / Newer checkout' {
        $extra = Join-Path $script:Checkout 'extra'
        [void](New-Item -ItemType Directory -Force -Path $extra)
        [IO.File]::WriteAllText((Join-Path $extra 'old.txt'), "old`n")
        try {
            $env:FAKE_WSL_MANIFEST = ($Payload + 'extra/old.txt') -join ' '
            Assert-Equal 0 (Invoke-Entry { & $Core -EntryDirectory $WinEntry -Arguments @('--container-install') }).Code 'first install'
            Assert-True ([IO.File]::Exists((Join-Path (Get-Target) 'extra/old.txt'))) 'extra file installed'
            [IO.File]::WriteAllText((Join-Path $script:Checkout 'agent/launcher.sh'), "#!/usr/bin/env bash`n: newer`n")
            $r = Invoke-Install
            Assert-Equal 0 $r.Code ('update: ' + $r.Err)
            Assert-Equal "#!/usr/bin/env bash`n: newer`n" ([IO.File]::ReadAllText((Join-Path (Get-Target) 'agent/launcher.sh'))) 'updated file'
            Assert-True (-not [IO.Directory]::Exists((Join-Path (Get-Target) 'extra'))) 'dropped file and folder removed'
            Assert-True (-not (@((Get-InstallState).files) -contains 'extra/old.txt')) 'dropped file unlisted'
        } finally {
            [IO.Directory]::Delete($extra, $true)
            [IO.File]::WriteAllText((Join-Path $script:Checkout 'agent/launcher.sh'), "#!/usr/bin/env bash`n:`n")
        }
    }
    Test-Case 'Update from a newer source / Install from the installed copy' {
        Assert-Equal 0 (Invoke-Install).Code 'install'
        $r = Invoke-Entry { & (Join-Path (Get-Target) ($Name + '.ps1')) --container-install }
        Assert-Refused $r 'this is the installed copy'
    }
    Test-Case 'Interrupted or concurrent install / Copy interrupted' {
        Assert-Equal 0 (Invoke-Install).Code 'install'
        $blocked = Join-Path (Get-Target) 'agent/launcher.sh'
        [IO.File]::Delete($blocked)
        [void](New-Item -ItemType Directory -Path $blocked)
        $r = Invoke-Install
        Assert-Equal 1 $r.Code 'interrupted install'
        Assert-Text 'cannot write agent/launcher.sh' $r.Err 'message'
        Assert-Equal 'incomplete' (Get-InstallState).state 'marker'
        Assert-Refused (Invoke-Entry { & (Join-Path (Get-Target) ($Name + '.ps1')) -c true }) 'is incomplete; run --container-install again'
        [IO.Directory]::Delete($blocked)
        Assert-Equal 0 (Invoke-Install).Code 'repairing install'
        Assert-Equal 'complete' (Get-InstallState).state 'marker after repair'
    }
    Test-Case 'Interrupted or concurrent install / Two installs at once' {
        [void][IO.Directory]::CreateDirectory((Join-Path $env:LOCALAPPDATA 'Programs'))
        # Held in shared mode: the installer's own exclusive open must be what fails.
        $held = New-Object IO.FileStream(((Get-Target) + '.lock'), [IO.FileMode]::OpenOrCreate, [IO.FileAccess]::ReadWrite, [IO.FileShare]::ReadWrite)
        try {
            $r = Invoke-Install
        } finally {
            $held.Dispose()
        }
        Assert-Equal 1 $r.Code 'second install'
        Assert-Text 'another install or uninstall' $r.Err 'message'
        Assert-True (-not [IO.Directory]::Exists((Get-Target))) 'nothing copied'
    }
    Test-Case 'Checks before an install / CRLF source' {
        $data = Join-Path $script:Checkout 'agent/data.txt'
        [IO.File]::WriteAllText($data, "a`r`nb`r`n")
        try {
            $env:FAKE_WSL_MANIFEST = ($Payload + 'agent/data.txt') -join ' '
            $r = Invoke-Entry { & $Core -EntryDirectory $WinEntry -Arguments @('--container-install') }
        } finally {
            [IO.File]::Delete($data)
        }
        Assert-Equal 1 $r.Code 'status'
        Assert-Text 'installation input has CRLF line endings: agent/data.txt' $r.Err 'message'
        Assert-True (-not [IO.Directory]::Exists((Get-Target))) 'nothing copied'
    }
    Test-Case 'Checks before an install / Junction as install folder' {
        $elsewhere = Join-Path $work 'elsewhere'
        [void][IO.Directory]::CreateDirectory($elsewhere)
        [void][IO.Directory]::CreateDirectory((Join-Path $env:LOCALAPPDATA 'Programs'))
        [void](New-Item -ItemType SymbolicLink -Path (Get-Target) -Target $elsewhere)
        try {
            $r = Invoke-Install
            Assert-Equal 1 $r.Code 'status'
            Assert-Text 'is a link (reparse point)' $r.Err 'message'
            Assert-Equal 0 @([IO.Directory]::GetFileSystemEntries($elsewhere)).Count 'nothing written through the link'
        } finally {
            [IO.File]::Delete((Get-Target))
            [IO.Directory]::Delete($elsewhere, $true)
        }
    }
    Test-Case 'Checks before an install / Stopped machine' {
        $env:FAKE_WSL_RUNNING = 'none'
        $r = Invoke-Install
        Assert-Refused $r 'the Podman machine is stopped' 2
        Assert-True (-not [IO.Directory]::Exists((Get-Target))) 'nothing copied'
    }
    Test-Case 'Checkout line endings checked before setup / Install from a CRLF checkout; Checks before an install (distribution started by WSL alone)' {
        [IO.File]::WriteAllText((Join-Path $script:Checkout 'launcher/core.sh'), "#!/usr/bin/env bash`r`n:`r`n")
        $r = Invoke-Install
        Assert-Refused $r 'the checkout has CRLF line endings: launcher/core.sh'
        [IO.File]::WriteAllText((Join-Path $script:Checkout 'launcher/core.sh'), "#!/usr/bin/env bash`n:`n")
        $env:FAKE_WSL_RUNTIME = '1'
        Assert-Refused (Invoke-Install) 'runs without the Podman machine' 2
        Assert-True (-not [IO.Directory]::Exists((Get-Target))) 'nothing copied'
    }
    Test-Case 'Install and uninstall options used alone / Install with other arguments' {
        Assert-Refused (Invoke-Entry { & $Entry --container-install -c true }) '--container-install must be used alone'
        Assert-Refused (Invoke-Entry { & $Entry --container-uninstall x }) '--container-uninstall must be used alone'
        Assert-True (-not [IO.Directory]::Exists((Get-Target))) 'nothing copied'
    }
    Test-Case 'Setup runs from the installed copy / Setup declined after the copy' {
        $env:FAKE_WSL_EXIT = '1'
        $r = Invoke-Install
        Assert-Equal 1 $r.Code 'status'
        Assert-Text ('run ' + $Name + ' --container-setup to finish') $r.Err 'message'
        Assert-Equal 'complete' (Get-InstallState).state 'copy stays'
        Assert-Equal ((Get-Target) + '|ExpandString') (Get-UserPathFile) 'PATH entry stays'
    }
    Test-Case 'Uninstall / Uninstall' {
        [IO.File]::WriteAllText($env:FIXTURE_USER_PATH_FILE, 'C:\keep')
        Assert-Equal 0 (Invoke-Install).Code 'install'
        # Setup runs Python from the installed copy, which caches bytecode there.
        $cache = Join-Path (Get-Target) 'agent/__pycache__'
        [void][IO.Directory]::CreateDirectory($cache)
        [IO.File]::WriteAllText((Join-Path $cache 'module.cpython-314.pyc'), 'bytecode')
        [IO.File]::WriteAllText((Join-Path $cache 'other.cpython-314.pyc.140245'), 'partial bytecode')
        $env:FIXTURE_AGENT_WSL_DISTRO = 'bad name'
        $r = Invoke-Entry { & (Join-Path (Get-Target) ($Name + '.ps1')) --container-uninstall }
        Assert-Equal 0 $r.Code ('uninstall: ' + $r.Err)
        Assert-Equal 'C:\keep|ExpandString' (Get-UserPathFile) 'PATH entry removed, others kept'
        Assert-True (-not [IO.Directory]::Exists((Get-Target))) 'folder removed'
        Assert-Text 'the installation inside the Podman machine stays' $r.Out 'machine note'
        Assert-Equal 0 $r.Calls.Count 'no wsl.exe call'
    }
    Test-Case 'Install and uninstall options used alone / Uninstall from a checkout; missing installation' {
        Assert-Equal 0 (Invoke-Install).Code 'install'
        $r = Invoke-Entry { & $Entry --container-uninstall }
        Assert-Equal 0 $r.Code ('uninstall: ' + $r.Err)
        Assert-True (-not [IO.Directory]::Exists((Get-Target))) 'folder removed'
        $r = Invoke-Entry { & $Entry --container-uninstall }
        Assert-Equal 0 $r.Code 'nothing installed'
        Assert-Text 'nothing is installed in' $r.Out 'message'
    }
    Test-Case 'Uninstall / Files the installer did not create' {
        Assert-Equal 0 (Invoke-Install).Code 'install'
        $own = Join-Path (Get-Target) 'agent/notes.txt'
        [IO.File]::WriteAllText($own, 'kept')
        $r = Invoke-Entry { & $Entry --container-uninstall }
        Assert-Equal 1 $r.Code 'status'
        Assert-Text 'still holds files that the installer did not create' $r.Err 'message'
        Assert-Text ('not removed: ' + (Join-Path (Get-Target) 'agent')) $r.Err 'folder with the foreign file named'
        Assert-True ([IO.File]::Exists($own)) 'the foreign file is kept'
        Assert-True ([IO.File]::Exists((Join-Path (Get-Target) 'install.json'))) 'install.json kept for the next uninstall'
        [IO.File]::Delete($own)
        $r = Invoke-Entry { & $Entry --container-uninstall }
        Assert-Equal 0 $r.Code ('second uninstall: ' + $r.Err)
        Assert-True (-not [IO.Directory]::Exists((Get-Target))) 'folder removed'
    }
    Test-Case 'Uninstall / Names in install.json stay inside the folder' {
        Assert-Equal 0 (Invoke-Install).Code 'install'
        $outside = Join-Path (Join-Path $env:LOCALAPPDATA 'Programs') 'outside.txt'
        [IO.File]::WriteAllText($outside, 'keep')
        $marker = Join-Path (Get-Target) 'install.json'
        $state = Get-InstallState
        $state.files = @($state.files) + @('../outside.txt', 'install.json')
        [IO.File]::WriteAllText($marker, ($state | ConvertTo-Json -Depth 3))
        $r = Invoke-Entry { & $Entry --container-uninstall }
        Assert-Equal 0 $r.Code ('uninstall: ' + $r.Err)
        Assert-True ([IO.File]::Exists($outside)) 'the file outside the folder is kept'
        Assert-True (-not [IO.Directory]::Exists((Get-Target))) 'folder removed'
    }
    Test-Case 'Uninstall / Empty folder left by an interrupted uninstall' {
        [void][IO.Directory]::CreateDirectory((Get-Target))
        $r = Invoke-Entry { & $Entry --container-uninstall }
        Assert-Equal 0 $r.Code ('uninstall: ' + $r.Err)
        Assert-True (-not [IO.Directory]::Exists((Get-Target))) 'empty folder removed'
    }
    Test-Case 'Uninstall / Folder in use' {
        Assert-Equal 0 (Invoke-Install).Code 'install'
        $blocked = Join-Path (Get-Target) 'agent/launcher.sh'
        [IO.File]::Delete($blocked)
        [void](New-Item -ItemType Directory -Path $blocked)
        $r = Invoke-Entry { & $Entry --container-uninstall }
        Assert-Equal 1 $r.Code 'status'
        Assert-Text 'wsl --shutdown' $r.Err 'release hint'
        Assert-Text ('not removed: ' + $blocked) $r.Err 'remaining item'
        Assert-Equal '|ExpandString' (Get-UserPathFile) 'PATH entry removed'
        [IO.Directory]::Delete((Get-Target), $true)
    }
} finally {
    Set-Location -LiteralPath $location
    Remove-Item -LiteralPath $work -Recurse -Force
}

foreach ($line in $script:Results) { [Console]::Out.WriteLine($line) }
[Console]::Out.WriteLine(('{0} cases, {1} failed' -f $script:Results.Count, $script:Failures))
if ($script:Failures -gt 0) { exit 1 }

# Shared Windows installer, run by the shim (launcher/windows/core.ps1) for
# --container-install and --container-uninstall. It copies the payload into
# the per-user folder and adds that folder to the user's PATH, or removes
# both. The shim runs the WSL checks and computes the payload list and the
# folder. See docs/launcher-contract.md (Windows installer).
# ASCII only: Windows PowerShell 5.1 reads files without a BOM as ANSI.
param(
    [Parameter(Mandatory = $true)]
    [ValidateSet('Install', 'Uninstall')]
    [string]$Action,
    [Parameter(Mandatory = $true)]
    [string]$Source,
    [Parameter(Mandatory = $true)]
    [string]$Target,
    [Parameter(Mandatory = $true)]
    [string]$Name,
    [string[]]$Files = @(),
    [string]$MachineNote = ''
)
Set-StrictMode -Version 3
$ErrorActionPreference = 'Stop'
. ([IO.Path]::Combine($PSScriptRoot, 'user-path.ps1'))

$onWindows = [Environment]::OSVersion.Platform -eq [PlatformID]::Win32NT
$comparison = if ($onWindows) { [StringComparison]::OrdinalIgnoreCase } else { [StringComparison]::Ordinal }
# NTFS ignores the letter case of names; Linux, where the tests run, does not.
$nameComparer = if ($onWindows) { [StringComparer]::OrdinalIgnoreCase } else { [StringComparer]::Ordinal }
$separator = [IO.Path]::DirectorySeparatorChar
$Source = [IO.Path]::GetFullPath($Source).TrimEnd('\', '/')
$Target = [IO.Path]::GetFullPath($Target).TrimEnd('\', '/')
$markerPath = [IO.Path]::Combine($Target, 'install.json')
$namePattern = '^[A-Za-z0-9_.-]+(/[A-Za-z0-9_.-]+)*\z'
$prefix = $Name + ': '

function Exit-Install([string]$Message) {
    [Console]::Error.WriteLine($prefix + $Message)
    exit 1
}

function Write-Note([string]$Message) {
    [Console]::Out.WriteLine($prefix + $Message)
}

function Test-ReparsePoint([string]$Path) {
    try {
        $attributes = [IO.File]::GetAttributes($Path)
    } catch {
        # Missing; a path that cannot be read is refused when it is written.
        return $false
    }
    return (($attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0)
}

function Test-Inside([string]$Path, [string]$Folder) {
    return ([string]::Equals($Path, $Folder, $comparison) -or
        $Path.StartsWith($Folder + $separator, $comparison))
}

function Get-NativePath([string]$Relative) {
    return [IO.Path]::Combine($Target, $Relative.Replace('/', $separator))
}

function Get-Sha256([byte[]]$Bytes) {
    $sha = [Security.Cryptography.SHA256]::Create()
    try {
        return [BitConverter]::ToString($sha.ComputeHash($Bytes))
    } finally {
        $sha.Dispose()
    }
}

# Another install or uninstall holds this file open while it runs.
function Open-InstallLock {
    $parent = [IO.Path]::GetDirectoryName($Target)
    if (Test-ReparsePoint $parent) {
        Exit-Install ($parent + ' is a link (reparse point); the installer does not write through links')
    }
    [void][IO.Directory]::CreateDirectory($parent)
    try {
        return New-Object IO.FileStream(($Target + '.lock'), [IO.FileMode]::OpenOrCreate, [IO.FileAccess]::ReadWrite,
            [IO.FileShare]::None, 1, [IO.FileOptions]::DeleteOnClose)
    } catch {
        Exit-Install ('another install or uninstall of ' + $Name + ' is running (' + $Target + '.lock is in use); ' +
            'retry when it has finished')
    }
}

function Read-InstallState {
    if (-not [IO.File]::Exists($markerPath)) { return $null }
    try {
        $data = [IO.File]::ReadAllText($markerPath) | ConvertFrom-Json
        $list = @($data.files | ForEach-Object { [string]$_ })
        return [pscustomobject]@{ State = [string]$data.state; Files = $list }
    } catch {
        return [pscustomobject]@{ State = 'unreadable'; Files = @() }
    }
}

# Writes through <path>.new, checks the bytes that arrived, then replaces the
# target; Windows PowerShell 5.1 has no overwrite flag on File.Move.
function Write-FileChecked([string]$Path, [byte[]]$Bytes, [string]$Label) {
    $temporary = $Path + '.new'
    try {
        [IO.File]::WriteAllBytes($temporary, $Bytes)
        if ([IO.File]::Exists($Path)) {
            # [NullString]: PowerShell would pass $null to a .NET string parameter as ''.
            [void][IO.File]::Replace($temporary, $Path, [NullString]::Value)
        } else {
            [IO.File]::Move($temporary, $Path)
        }
        $written = Get-Sha256 ([IO.File]::ReadAllBytes($Path))
    } catch {
        Exit-Install ('cannot write ' + $Label + ' in ' + $Target + ': ' + $_.Exception.Message + ' Run the install ' +
            'again; an antivirus may have blocked the file.')
    }
    if ($written -cne (Get-Sha256 $Bytes)) {
        Exit-Install ('the installed ' + $Label + ' differs from the source; an antivirus may have changed it. ' +
            'Run the install again.')
    }
}

function Write-InstallState([string]$State, [string[]]$List) {
    $data = [ordered]@{ state = $State; files = @($List); source = $Source; time = [DateTime]::UtcNow.ToString('o') }
    $text = ($data | ConvertTo-Json -Depth 3) + "`n"
    Write-FileChecked $markerPath ((New-Object Text.UTF8Encoding($false)).GetBytes($text)) 'install.json'
}

# Deletes one installed file and a leftover <file>.new. Returns an error text, or $null.
function Clear-InstalledFile([string]$Relative) {
    $path = Get-NativePath $Relative
    foreach ($candidate in @($path, ($path + '.new'))) {
        try {
            if ([IO.Directory]::Exists($candidate) -or (Test-ReparsePoint $candidate)) {
                return ($candidate + ' is not a regular file')
            }
            if ([IO.File]::Exists($candidate)) { [IO.File]::Delete($candidate) }
        } catch {
            return ($candidate + ': ' + $_.Exception.Message)
        }
    }
    return $null
}

# Setup runs Python from the installed copy, and Python caches bytecode next to
# the modules. Removes each __pycache__ folder of the listed files' folders when
# it holds only .pyc files. Returns the error texts.
function Clear-BytecodeCache([string[]]$List) {
    $problems = New-Object 'System.Collections.Generic.List[string]'
    $folders = New-Object 'System.Collections.Generic.HashSet[string]'
    foreach ($relative in $List) {
        $parts = $relative -split '/'
        if ($parts.Count -gt 1) { [void]$folders.Add(($parts[0..($parts.Count - 2)] -join '/')) }
    }
    foreach ($folder in $folders) {
        $cache = Get-NativePath ($folder + '/__pycache__')
        if (-not [IO.Directory]::Exists($cache) -or (Test-ReparsePoint $cache)) { continue }
        $entries = @([IO.Directory]::GetFileSystemEntries($cache))
        # Python writes <module>.pyc.<number> first, then renames it.
        $foreign = @($entries | Where-Object { -not ([IO.File]::Exists($_) -and $_ -cmatch '\.pyc(\.[0-9]+)?\z') })
        if ($foreign.Count -gt 0) { continue }
        try {
            foreach ($entry in $entries) { [IO.File]::Delete($entry) }
            [IO.Directory]::Delete($cache)
        } catch {
            $problems.Add($cache + ': ' + $_.Exception.Message)
        }
    }
    return , $problems.ToArray()
}

# Removes the folders of the listed files, deepest first, when they are empty.
# Returns the error texts of empty folders that could not be removed.
function Clear-EmptyFolder([string[]]$List) {
    $problems = New-Object 'System.Collections.Generic.List[string]'
    $folders = New-Object 'System.Collections.Generic.HashSet[string]'
    foreach ($relative in $List) {
        $parts = $relative -split '/'
        for ($i = 1; $i -lt $parts.Count; $i++) { [void]$folders.Add(($parts[0..($i - 1)] -join '/')) }
    }
    foreach ($folder in @($folders | Sort-Object { ($_ -split '/').Count } -Descending)) {
        $path = Get-NativePath $folder
        if (-not [IO.Directory]::Exists($path) -or (Test-ReparsePoint $path)) { continue }
        if (@([IO.Directory]::GetFileSystemEntries($path)).Count -eq 0) {
            try { [IO.Directory]::Delete($path) } catch { $problems.Add($path + ': ' + $_.Exception.Message) }
        }
    }
    return , $problems.ToArray()
}

# A relative name inside the folder: no '.' or '..' segment, not the marker,
# not a temporary .new file. Names read back from install.json pass it too.
function Test-ValidName([string]$Relative) {
    $parts = $Relative -split '/'
    return -not ($Relative -cnotmatch $namePattern -or $parts -contains '..' -or $parts -contains '.' -or
        [string]::Equals($Relative, 'install.json', $comparison) -or $Relative.EndsWith('.new', $comparison))
}

function Assert-ValidName([string]$Relative) {
    if (-not (Test-ValidName $Relative)) { Exit-Install ('invalid installation input name: ' + $Relative) }
}

function Invoke-Install([string[]]$List) {
    if (Test-Inside $Source $Target) {
        Exit-Install ('the install runs from ' + $Source + ', the installed copy; run --container-install from a ' +
            'checkout or a downloaded copy')
    }
    if (Test-ReparsePoint $Target) {
        Exit-Install ($Target + ' is a link (reparse point); the installer does not write through links')
    }
    $lock = Open-InstallLock
    try {
        $previous = Read-InstallState
        if ([IO.Directory]::Exists($Target)) {
            if ($onWindows) {
                # An elevated session of the same user creates folders owned by Administrators.
                $owner = (Get-Acl -LiteralPath $Target).GetOwner([Security.Principal.SecurityIdentifier])
                $administrators = New-Object Security.Principal.SecurityIdentifier('S-1-5-32-544')
                if ($owner -ne [Security.Principal.WindowsIdentity]::GetCurrent().User -and $owner -ne $administrators) {
                    Exit-Install ($Target + ' belongs to another account (' + $owner + '); remove it or ask its owner')
                }
            }
            if ($null -eq $previous -and @([IO.Directory]::GetFileSystemEntries($Target)).Count -gt 0) {
                Exit-Install ($Target + ' exists without install.json, so the installer did not create it; move ' +
                    'it away first')
            }
        }
        # Every input is read and checked before anything is written.
        $payload = New-Object 'System.Collections.Generic.List[object]'
        $names = New-Object 'System.Collections.Generic.SortedSet[string]' ($nameComparer)
        foreach ($relative in $List) {
            Assert-ValidName $relative
            if (-not $names.Add($relative)) { continue }
            $from = [IO.Path]::Combine($Source, $relative.Replace('/', $separator))
            if ((Test-ReparsePoint $from) -or -not [IO.File]::Exists($from)) {
                Exit-Install ('installation input missing or not a regular file: ' + $relative)
            }
            $bytes = [IO.File]::ReadAllBytes($from)
            if ([Array]::IndexOf($bytes, [byte]13) -ge 0) {
                Exit-Install ('installation input has CRLF line endings: ' + $relative + '. Release files must use ' +
                    'LF, as the repository .gitattributes requires. In a checkout without local changes run ' +
                    'git rm -r -q --cached . and then git reset --hard, or clone the repository again.')
            }
            $payload.Add([pscustomobject]@{ Relative = $relative; Bytes = $bytes })
        }
        $userPath = Read-UserPath
        $withEntry = Get-PathWithEntry $userPath.Value $Target
        if ($withEntry.Length -gt 32766) {
            Exit-Install ('adding ' + $Target + ' would make your user PATH longer than 32766 characters; shorten ' +
                'it first')
        }

        $previousFiles = @()
        if ($null -ne $previous) { $previousFiles = @($previous.Files | Where-Object { Test-ValidName $_ }) }
        $all = New-Object 'System.Collections.Generic.SortedSet[string]' ($nameComparer)
        foreach ($relative in @($previousFiles) + @($names)) { [void]$all.Add($relative) }
        [void][IO.Directory]::CreateDirectory($Target)
        Write-InstallState 'incomplete' @($all)
        foreach ($item in $payload) {
            $parts = $item.Relative -split '/'
            for ($i = 1; $i -lt $parts.Count; $i++) {
                $folder = Get-NativePath ($parts[0..($i - 1)] -join '/')
                if (Test-ReparsePoint $folder) {
                    Exit-Install ($folder + ' is a link (reparse point); the installer does not write through links')
                }
            }
            $destination = Get-NativePath $item.Relative
            [void][IO.Directory]::CreateDirectory([IO.Path]::GetDirectoryName($destination))
            Write-FileChecked $destination $item.Bytes $item.Relative
        }
        $dropped = @($previousFiles | Where-Object { -not $names.Contains($_) })
        foreach ($relative in $dropped) {
            $problem = Clear-InstalledFile $relative
            if ($null -ne $problem) { Exit-Install ('cannot remove a file of the previous install: ' + $problem) }
        }
        # An empty folder that stays, for example in use, does no harm here.
        [void](Clear-EmptyFolder $dropped)
        Write-InstallState 'complete' @($names)
        Write-Note ('copied ' + $names.Count + ' files to ' + $Target)

        # Read again: the user PATH may have changed while the files were copied.
        $userPath = Read-UserPath
        $withEntry = Get-PathWithEntry $userPath.Value $Target
        if ($withEntry.Length -gt 32766) {
            Exit-Install ('adding ' + $Target + ' would make your user PATH longer than 32766 characters; shorten ' +
                'it, then run the install again')
        }
        if ($withEntry -cne $userPath.Value) {
            Write-Note ('adding ' + $Target + ' to your user PATH (HKCU\Environment), so that new PowerShell ' +
                'windows find ' + $Name)
            if (-not (Write-UserPath $withEntry $userPath.Kind)) {
                Write-Note 'running programs were not told about the new PATH; sign out and back in before using it'
            }
        }
        if ($onWindows) { $env:Path = Get-PathWithEntry $env:Path $Target }
    } finally {
        $lock.Dispose()
    }
}

function Invoke-Uninstall([string]$Note) {
    $lock = Open-InstallLock
    try {
        # The PATH entry goes first, so that a damaged copy is not reachable either.
        $userPath = Read-UserPath
        $withoutEntry = Get-PathWithoutEntry $userPath.Value $Target
        if ($withoutEntry -cne $userPath.Value) {
            $broadcast = Write-UserPath $withoutEntry $userPath.Kind
            Write-Note ('removed ' + $Target + ' from your user PATH')
            if (-not $broadcast) {
                Write-Note 'running programs were not told about the change; it applies after you sign out and back in'
            }
        }
        if ($onWindows) { $env:Path = Get-PathWithoutEntry $env:Path $Target }
        if ($Note) { Write-Note $Note }
        if (-not [IO.Directory]::Exists($Target)) {
            Write-Note ('nothing is installed in ' + $Target)
            return
        }
        if (Test-ReparsePoint $Target) {
            Exit-Install ($Target + ' is a link (reparse point); it was not removed')
        }
        $state = Read-InstallState
        if ($null -eq $state) {
            # An empty folder is what an earlier, interrupted uninstall leaves.
            if (@([IO.Directory]::GetFileSystemEntries($Target)).Count -eq 0) {
                [IO.Directory]::Delete($Target)
                Write-Note ('removed ' + $Target)
                return
            }
            Exit-Install ($Target + ' has no install.json, so the installer did not create it; nothing was removed')
        }
        $listed = @($state.Files | Where-Object { Test-ValidName $_ })
        $problems = New-Object 'System.Collections.Generic.List[string]'
        foreach ($relative in $listed) {
            $problem = Clear-InstalledFile $relative
            if ($null -ne $problem) { $problems.Add($problem) }
        }
        foreach ($problem in (Clear-BytecodeCache $listed)) { $problems.Add($problem) }
        foreach ($problem in (Clear-EmptyFolder $listed)) { $problems.Add($problem) }
        # install.json stays until everything else is gone, so that a second
        # uninstall still knows what to remove.
        $markers = @($markerPath, ($markerPath + '.new'))
        $foreign = @([IO.Directory]::GetFileSystemEntries($Target) | Where-Object { $markers -notcontains $_ })
        if ($problems.Count -eq 0 -and $foreign.Count -gt 0) {
            foreach ($entry in $foreign) { [Console]::Error.WriteLine($prefix + 'not removed: ' + $entry) }
            Exit-Install ($Target + ' still holds files that the installer did not create; move them away, then run ' +
                '--container-uninstall again from a checkout')
        }
        if ($problems.Count -eq 0) {
            try {
                foreach ($path in $markers) { if ([IO.File]::Exists($path)) { [IO.File]::Delete($path) } }
                [IO.Directory]::Delete($Target)
            } catch {
                $problems.Add($Target + ': ' + $_.Exception.Message)
            }
        }
        if ($problems.Count -gt 0) {
            foreach ($problem in $problems) { [Console]::Error.WriteLine($prefix + 'not removed: ' + $problem) }
            Exit-Install ('the uninstall is incomplete; when a WSL process still uses the folder, run wsl --shutdown, ' +
                'then run the uninstall again from a checkout, or delete ' + $Target)
        }
        Write-Note ('removed ' + $Target)
    } finally {
        $lock.Dispose()
    }
}

# An unexpected error becomes a message with the wrapper's prefix and status 1.
try {
    if ($Action -ceq 'Install') { Invoke-Install $Files } else { Invoke-Uninstall $MachineNote }
} catch {
    Exit-Install ('the ' + $Action.ToLowerInvariant() + ' stopped: ' + $_.Exception.Message + ' Run it again; ' +
        'an install that stopped while copying stays marked incomplete until one completes.')
}
exit 0

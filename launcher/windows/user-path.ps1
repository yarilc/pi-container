# User PATH helper of the Windows installer (launcher/windows/install.ps1).
# It defines functions only: dot-sourcing it changes nothing. The string
# functions keep every other entry byte for byte, and Read-UserPath and
# Write-UserPath keep the registry value kind, so %VAR% references in the
# user's PATH still expand. See docs/launcher-contract.md (Windows installer).

# Entries match case-insensitively after %VAR% expansion and a trailing '\' trim.
function Test-PathEntryMatch([string]$Entry, [string]$Folder) {
    $left = [Environment]::ExpandEnvironmentVariables($Entry.Trim()).TrimEnd('\')
    $right = [Environment]::ExpandEnvironmentVariables($Folder.Trim()).TrimEnd('\')
    return ($left.Length -gt 0 -and [string]::Equals($left, $right, [StringComparison]::OrdinalIgnoreCase))
}

# The value with $Folder appended, or unchanged when an entry already matches.
# A trailing ';' stays trailing, so that removing the entry restores the value.
function Get-PathWithEntry([string]$Value, [string]$Folder) {
    if ([string]::IsNullOrEmpty($Value)) { return $Folder }
    foreach ($entry in ($Value -split ';')) {
        if (Test-PathEntryMatch $entry $Folder) { return $Value }
    }
    if ($Value.EndsWith(';')) { return $Value + $Folder + ';' }
    return $Value + ';' + $Folder
}

# The value without the entries that match $Folder; the others stay as they are.
function Get-PathWithoutEntry([string]$Value, [string]$Folder) {
    if ([string]::IsNullOrEmpty($Value)) { return '' }
    $kept = @($Value -split ';' | Where-Object { -not (Test-PathEntryMatch $_ $Folder) })
    return ($kept -join ';')
}

# HKCU\Environment\Path without expansion, with its value kind. A missing value
# reads as empty, of kind ExpandString, which Windows itself uses for PATH.
function Read-UserPath {
    $kind = [Microsoft.Win32.RegistryValueKind]::ExpandString
    $key = [Microsoft.Win32.Registry]::CurrentUser.OpenSubKey('Environment', $false)
    if ($null -eq $key) { return [pscustomobject]@{ Value = ''; Kind = $kind } }
    try {
        $value = $key.GetValue('Path', $null, [Microsoft.Win32.RegistryValueOptions]::DoNotExpandEnvironmentNames)
        if ($null -eq $value) { return [pscustomobject]@{ Value = ''; Kind = $kind } }
        return [pscustomobject]@{ Value = [string]$value; Kind = $key.GetValueKind('Path') }
    } finally {
        $key.Close()
    }
}

# Writes the value with its kind (an empty value removes it), then tells
# running programs, such as Explorer, that the environment changed. Returns
# $false when the broadcast was not possible, for example in Constrained
# Language Mode, where Add-Type is blocked: then only a new sign-in sees it.
function Write-UserPath([string]$Value, [Microsoft.Win32.RegistryValueKind]$Kind) {
    $key = [Microsoft.Win32.Registry]::CurrentUser.CreateSubKey('Environment')
    try {
        if ([string]::IsNullOrEmpty($Value)) {
            $key.DeleteValue('Path', $false)
        } else {
            $key.SetValue('Path', $Value, $Kind)
        }
    } finally {
        $key.Close()
    }
    return (Send-EnvironmentChange)
}

# WM_SETTINGCHANGE with "Environment" to every top-level window, as Windows
# sends after an environment change in its own settings.
function Send-EnvironmentChange {
    try {
        if (-not ('WrapperWindows.EnvironmentBroadcast' -as [type])) {
            Add-Type -Namespace 'WrapperWindows' -Name 'EnvironmentBroadcast' -MemberDefinition @'
[DllImport("user32.dll", SetLastError = true, CharSet = CharSet.Unicode)]
public static extern IntPtr SendMessageTimeout(IntPtr hWnd, uint msg, UIntPtr wParam, string lParam,
    uint flags, uint timeout, out UIntPtr result);
'@
        }
        $result = [UIntPtr]::Zero
        # HWND_BROADCAST, WM_SETTINGCHANGE, SMTO_ABORTIFHUNG, 5 s.
        $sent = [WrapperWindows.EnvironmentBroadcast]::SendMessageTimeout([IntPtr]0xffff, 0x1A, [UIntPtr]::Zero,
            'Environment', 2, 5000, [ref]$result)
        return ($sent -ne [IntPtr]::Zero)
    } catch {
        return $false
    }
}

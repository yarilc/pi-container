# Thin Windows entry: identical in every wrapper. The shared shim
# (launcher/windows/core.ps1) does everything with this wrapper's profile;
# see docs/launcher-contract.md (Windows entry).
Set-StrictMode -Version 3
$ErrorActionPreference = 'Stop'
& ([IO.Path]::Combine($PSScriptRoot, 'launcher', 'windows', 'core.ps1')) -EntryDirectory $PSScriptRoot -Arguments $args -PipelineInput:$MyInvocation.ExpectingInput
exit $LASTEXITCODE

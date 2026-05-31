param(
    [switch]$SkipDriver,
    [switch]$EnableTestSigning,
    [switch]$UninstallDriver
)

$ErrorActionPreference = "Stop"

function Test-Admin {
    $identity = [Security.Principal.WindowsIdentity]::GetCurrent()
    $principal = New-Object Security.Principal.WindowsPrincipal($identity)
    return $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
}

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$agentExe = Join-Path $scriptDir "Rice_Harvester_Agent.exe"
$driverInstaller = Join-Path $scriptDir "VhfDriver\install.ps1"

if (-not (Test-Path $agentExe)) {
    throw "Rice_Harvester_Agent.exe not found next to this installer."
}

if (-not $SkipDriver) {
    if (-not (Test-Admin)) {
        throw "Run this script as Administrator to install the VHF driver."
    }

    if (-not (Test-Path $driverInstaller)) {
        throw "VHF driver installer not found: $driverInstaller"
    }

    if ($EnableTestSigning) {
        & powershell -NoProfile -ExecutionPolicy Bypass -File $driverInstaller -TestSign
        Write-Host "[Agent] Reboot Windows, then run this installer again without -EnableTestSigning."
        exit 0
    }

    if ($UninstallDriver) {
        & powershell -NoProfile -ExecutionPolicy Bypass -File $driverInstaller -Uninstall
        exit 0
    }

    & powershell -NoProfile -ExecutionPolicy Bypass -File $driverInstaller
}

Write-Host "[Agent] Install complete."
Write-Host "[Agent] Run: $agentExe [port] [secret]"

param(
    [switch]$Uninstall,
    [switch]$TestSign,
    [switch]$NoDeviceInstall
)

$ErrorActionPreference = "Stop"

function Test-Admin {
    $identity = [Security.Principal.WindowsIdentity]::GetCurrent()
    $principal = New-Object Security.Principal.WindowsPrincipal($identity)
    return $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
}

if (-not (Test-Admin)) {
    throw "Administrator privileges are required to install or remove the VHF driver."
}

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$infPath = Join-Path $scriptDir "VhfDriver.inf"
$driverPath = Join-Path $scriptDir "VhfDriver.sys"

if (-not (Test-Path $driverPath)) {
    $sourceBuildDriver = Join-Path $scriptDir "..\Build\VhfDriver\VhfDriver.sys"
    if (Test-Path $sourceBuildDriver) {
        $driverPath = [System.IO.Path]::GetFullPath($sourceBuildDriver)
    }
}

if ($Uninstall) {
    Write-Host "[VHF] Removing driver package and service..."
    pnputil /delete-driver VhfDriver.inf /uninstall /force
    sc.exe delete VhfDriver | Out-Null
    Write-Host "[VHF] Removed."
    exit 0
}

if ($TestSign) {
    Write-Host "[VHF] Enabling Windows test-signing mode. Reboot is required."
    bcdedit /set testsigning on
    exit 0
}

if (-not (Test-Path $infPath)) {
    throw "VhfDriver.inf not found: $infPath"
}

if (-not (Test-Path $driverPath)) {
    throw "VhfDriver.sys not found. Build the driver first, then rerun the Agent installer."
}

Write-Host "[VHF] Installing driver from $infPath"
pnputil /add-driver $infPath /install

if (-not $NoDeviceInstall) {
    $devcon = Get-Command devcon.exe -ErrorAction SilentlyContinue
    if ($devcon) {
        Write-Host "[VHF] Creating root device Root\VhfDriver..."
        devcon install $infPath Root\VhfDriver
    } else {
        Write-Warning "devcon.exe was not found. If the device is not created automatically, install Root\VhfDriver manually from Device Manager."
    }
}

Write-Host "[VHF] Install complete. Device Manager should show QA HID Companion (VHF)."

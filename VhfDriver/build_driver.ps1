param(
    [string]$SourceRoot = (Split-Path -Parent $PSScriptRoot),
    [string]$Configuration = "Release",
    [string]$Platform = "x64",
    [ValidateSet("Submission", "Test", "None")]
    [string]$SigningMode = "Submission",
    [string]$EvCertificateThumbprint = "",
    [string]$TimestampUrl = "http://timestamp.digicert.com"
)

$ErrorActionPreference = "Stop"

$project = Join-Path $PSScriptRoot "VhfDriver.vcxproj"
$infSource = Join-Path $PSScriptRoot "VhfDriver.inf"
$outDir = Join-Path $SourceRoot "Build\VhfDriver"
$objDir = Join-Path $SourceRoot "Build\_vhf_obj"
$submissionDir = Join-Path $SourceRoot "Build\DriverSubmission"
$windowsKits = Join-Path ${env:ProgramFiles(x86)} "Windows Kits\10"
$vswhere = Join-Path ${env:ProgramFiles(x86)} "Microsoft Visual Studio\Installer\vswhere.exe"
$certSubject = "CN=Rice Harvester VHF Test Certificate"
$certOut = Join-Path $outDir "VhfDriver.cer"

function Assert-PathExists([string]$Path, [string]$Label) {
    if (-not (Test-Path $Path)) {
        throw "$Label not found: $Path"
    }
}

function Get-LatestWdkKmVersion {
    $libRoot = Join-Path $windowsKits "Lib"
    Get-ChildItem -Path $libRoot -Directory |
        Where-Object { Test-Path (Join-Path $_.FullName "km\x64\vhfkm.lib") } |
        Sort-Object Name -Descending |
        Select-Object -First 1 -ExpandProperty Name
}

function Get-LatestWdkSharedVersion {
    $includeRoot = Join-Path $windowsKits "Include"
    Get-ChildItem -Path $includeRoot -Directory |
        Where-Object { Test-Path (Join-Path $_.FullName "shared\vhf.h") } |
        Sort-Object Name -Descending |
        Select-Object -First 1 -ExpandProperty Name
}

function Get-LatestTool([string]$ToolName, [string]$Arch) {
    $binRoot = Join-Path $windowsKits "bin"
    Get-ChildItem -Path $binRoot -Directory |
        ForEach-Object { Join-Path $_.FullName "$Arch\$ToolName" } |
        Where-Object { Test-Path $_ } |
        Sort-Object -Descending |
        Select-Object -First 1
}

function Get-LatestKitTool([string]$ToolName, [string]$Arch) {
    $toolsRoot = Join-Path $windowsKits "Tools"
    Get-ChildItem -Path $toolsRoot -Directory -ErrorAction SilentlyContinue |
        ForEach-Object { Join-Path $_.FullName "$Arch\$ToolName" } |
        Where-Object { Test-Path $_ } |
        Sort-Object -Descending |
        Select-Object -First 1
}

function Get-OrCreate-TestCertificate {
    $cert = Get-ChildItem -Path Cert:\CurrentUser\My |
        Where-Object { $_.Subject -eq $certSubject -and $_.HasPrivateKey } |
        Sort-Object NotAfter -Descending |
        Select-Object -First 1

    if (-not $cert) {
        Write-Host "[VHF] Creating test signing certificate..."
        $cert = New-SelfSignedCertificate `
            -Type CodeSigningCert `
            -Subject $certSubject `
            -CertStoreLocation Cert:\CurrentUser\My `
            -KeyExportPolicy Exportable `
            -KeyUsage DigitalSignature `
            -NotAfter (Get-Date).AddYears(10)
    }

    Export-Certificate -Cert $cert -FilePath $certOut -Force | Out-Null
    return $cert
}

function New-SubmissionCab([string]$CabName, [string[]]$Files) {
    New-Item -ItemType Directory -Force -Path $submissionDir | Out-Null
    $ddf = Join-Path $objDir "VhfDriverSubmission.ddf"
    $cabPath = Join-Path $submissionDir $CabName

    $ddfLines = @(
        ".OPTION EXPLICIT",
        ".Set CabinetNameTemplate=$CabName",
        ".Set DiskDirectoryTemplate=$submissionDir",
        ".Set CompressionType=MSZIP",
        ".Set Cabinet=on",
        ".Set Compress=on",
        ".Set DestinationDir=VhfDriver"
    )
    foreach ($file in $Files) {
        if (Test-Path $file) {
            $ddfLines += "`"$file`""
        }
    }

    Set-Content -Path $ddf -Value $ddfLines -Encoding ASCII
    if (Test-Path $cabPath) {
        Remove-Item -LiteralPath $cabPath -Force
    }

    & makecab.exe /F $ddf | ForEach-Object { Write-Host $_ }
    if ($LASTEXITCODE -ne 0) {
        throw "Driver submission CAB generation failed."
    }

    return ,$cabPath
}

Assert-PathExists $project "VHF driver project"
Assert-PathExists $infSource "VHF driver INF"
Assert-PathExists $windowsKits "Windows Kit"
Assert-PathExists $vswhere "vswhere"

$vsInstall = & $vswhere -latest -products * -requires Microsoft.Component.MSBuild -property installationPath
if (-not $vsInstall) {
    $vsInstall = & $vswhere -latest -products * -property installationPath
}
if (-not $vsInstall) {
    throw "Visual Studio installation was not found."
}

$msbuild = Join-Path $vsInstall "MSBuild\Current\Bin\amd64\MSBuild.exe"
$vsDevCmd = Join-Path $vsInstall "Common7\Tools\VsDevCmd.bat"
Assert-PathExists $msbuild "MSBuild"
Assert-PathExists $vsDevCmd "VsDevCmd"

$wdkKmVersion = Get-LatestWdkKmVersion
$wdkSharedVersion = Get-LatestWdkSharedVersion
if (-not $wdkKmVersion) {
    throw "WDK kernel-mode libraries with vhfkm.lib were not found."
}
if (-not $wdkSharedVersion) {
    throw "WDK shared headers with vhf.h were not found."
}

New-Item -ItemType Directory -Force -Path $outDir, $objDir, $submissionDir | Out-Null

Write-Host "[VHF] Compiling driver objects..."
& $msbuild $project `
    /p:Configuration=$Configuration `
    /p:Platform=$Platform `
    /p:PlatformToolset=v143 `
    /p:WindowsTargetPlatformVersion=$wdkSharedVersion `
    /p:WdkKmVersion=$wdkKmVersion `
    /p:WdkSharedVersion=$wdkSharedVersion `
    /v:minimal
if ($LASTEXITCODE -ne 0) {
    throw "VHF driver compile failed."
}

$sysOut = Join-Path $outDir "VhfDriver.sys"
$pdbOut = Join-Path $outDir "VhfDriver.pdb"
$catPath = Join-Path $outDir "VhfDriver.cat"

Remove-Item -LiteralPath $sysOut -Force -ErrorAction SilentlyContinue
Remove-Item -LiteralPath $pdbOut -Force -ErrorAction SilentlyContinue
Remove-Item -LiteralPath $catPath -Force -ErrorAction SilentlyContinue
Remove-Item -LiteralPath $certOut -Force -ErrorAction SilentlyContinue

$driverObj = Join-Path $objDir "driver.obj"
$deviceObj = Join-Path $objDir "device.obj"
Assert-PathExists $driverObj "driver.obj"
Assert-PathExists $deviceObj "device.obj"

$kmLib = Join-Path $windowsKits "Lib\$wdkKmVersion\km\x64"
$kmdfLib = Join-Path $windowsKits "Lib\wdf\kmdf\x64\1.15"

$linkRsp = Join-Path $objDir "VhfDriver.link.rsp"
$linkArgs = @(
    "/OUT:`"$sysOut`"",
    "/PDB:`"$pdbOut`"",
    "/DEBUG",
    "/MACHINE:X64",
    "/DRIVER",
    "/SUBSYSTEM:NATIVE",
    "/ENTRY:FxDriverEntry",
    "/NODEFAULTLIB",
    "/MANIFEST:NO",
    "`"$driverObj`"",
    "`"$deviceObj`"",
    "`"$(Join-Path $kmLib 'ntoskrnl.lib')`"",
    "`"$(Join-Path $kmLib 'hal.lib')`"",
    "`"$(Join-Path $kmLib 'wmilib.lib')`"",
    "`"$(Join-Path $kmLib 'wdmsec.lib')`"",
    "`"$(Join-Path $kmLib 'BufferOverflowFastFailK.lib')`"",
    "`"$(Join-Path $kmLib 'vhfkm.lib')`"",
    "`"$(Join-Path $kmdfLib 'WdfLdr.lib')`"",
    "`"$(Join-Path $kmdfLib 'WdfDriverEntry.lib')`""
)
Set-Content -Path $linkRsp -Value $linkArgs -Encoding ASCII

Write-Host "[VHF] Linking VhfDriver.sys..."
$cmd = "call `"$vsDevCmd`" -arch=x64 -host_arch=x64 >nul && link.exe @`"$linkRsp`""
& cmd.exe /d /c $cmd
if ($LASTEXITCODE -ne 0) {
    throw "VHF driver link failed."
}

Assert-PathExists $sysOut "VhfDriver.sys"
Copy-Item -Force $infSource (Join-Path $outDir "VhfDriver.inf")

$inf2Cat = Get-LatestTool "Inf2Cat.exe" "x86"
if ($inf2Cat) {
    Write-Host "[VHF] Generating VhfDriver.cat..."
    & $inf2Cat /driver:$outDir /os:10_X64
    if ($LASTEXITCODE -ne 0) {
        throw "VHF driver catalog generation failed."
    }
} else {
    Write-Warning "Inf2Cat.exe was not found. VhfDriver.cat was not generated."
}

$generatedCat = Get-ChildItem -Path $outDir -Filter "*.cat" |
    Sort-Object LastWriteTime -Descending |
    Select-Object -First 1
if ($generatedCat -and $generatedCat.FullName -cne $catPath) {
    Move-Item -Force -LiteralPath $generatedCat.FullName -Destination $catPath
}

$signtool = Get-LatestTool "signtool.exe" "x64"
if ($SigningMode -eq "Test" -and $signtool -and (Test-Path $catPath)) {
    $cert = Get-OrCreate-TestCertificate
    Write-Host "[VHF] Signing driver package with test certificate..."
    & $signtool sign /fd SHA256 /sha1 $cert.Thumbprint $catPath
    if ($LASTEXITCODE -ne 0) {
        throw "VHF driver catalog signing failed."
    }
    & $signtool sign /fd SHA256 /sha1 $cert.Thumbprint $sysOut
    if ($LASTEXITCODE -ne 0) {
        throw "VHF driver binary signing failed."
    }
} elseif ($SigningMode -eq "Test" -and -not $signtool) {
    throw "signtool.exe was not found. Test signing cannot continue."
} elseif ($SigningMode -eq "Submission") {
    Write-Host "[VHF] Leaving driver package unsigned for Microsoft attestation signing."
} elseif (-not $signtool) {
    Write-Warning "signtool.exe was not found."
}

$devcon = Get-LatestKitTool "devcon.exe" "x64"
if ($devcon) {
    Copy-Item -Force $devcon (Join-Path $outDir "devcon.exe")
}

$submissionFiles = @(
    (Join-Path $outDir "VhfDriver.inf"),
    $sysOut,
    $catPath,
    $pdbOut
)

if ($SigningMode -eq "Submission") {
    $cabPath = New-SubmissionCab -CabName "RiceHarvesterVhfDriver_Submission.cab" -Files $submissionFiles
    Write-Host "[VHF] Submission CAB ready: $cabPath"

    if ($EvCertificateThumbprint -and $signtool) {
        Write-Host "[VHF] Signing submission CAB with EV certificate..."
        & $signtool sign /fd SHA256 /tr $TimestampUrl /td SHA256 /sha1 $EvCertificateThumbprint $cabPath
        if ($LASTEXITCODE -ne 0) {
            throw "Driver submission CAB signing failed."
        }
    } elseif (-not $EvCertificateThumbprint) {
        Write-Warning "Submission CAB is not EV-signed. Sign it before uploading to Partner Center."
    }
}

Write-Host "[VHF] Driver ready: $sysOut"

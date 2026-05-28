# Rice_Harvester 전체 빌드 스크립트
# 실행: .\build_all.ps1

$root    = "C:\QA Security Project"
$dotnet  = "$env:ProgramFiles\dotnet\dotnet.exe"
$iscc    = "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe"
$icon    = "$root\assets\icon.ico"
$python  = "python"

# ── 0. 아이콘 변환 ─────────────────────────────────────────────────────
if (-not (Test-Path $icon)) {
    Write-Host "[1/4] 아이콘 변환 중..."
    & $python "$root\assets\make_icon.py"
} else {
    Write-Host "[1/4] 아이콘: 이미 존재함"
}

# ── 1. Agent (C#) ──────────────────────────────────────────────────────
Write-Host "[2/4] Agent 빌드 중..."
& $dotnet publish "$root\Agent\Agent.csproj" `
    --configuration Release `
    --runtime win-x64 `
    --self-contained true `
    -p:PublishSingleFile=true `
    -p:IncludeNativeLibrariesForSelfExtract=true `
    --output "$root\Build\Agent" `
    -v minimal
if ($LASTEXITCODE -ne 0) { Write-Error "Agent 빌드 실패"; exit 1 }

# ── 2. Controller (Python → exe) ────────────────────────────────────
Write-Host "[3/4] Controller 빌드 중..."
& $python -m pip install -r "$root\Controller\requirements.txt" --quiet
& $python -m PyInstaller "$root\Controller\main.py" `
    --onefile `
    --windowed `
    --name "Rice_Harvester" `
    --icon "$icon" `
    --distpath "$root\Build\Controller" `
    --workpath "$root\Build\_pyi_work" `
    --specpath "$root\Build" `
    --add-data "$root\assets\icon.ico;assets" `
    --noconfirm
if ($LASTEXITCODE -ne 0) { Write-Error "Controller 빌드 실패"; exit 1 }

# ── 3. Inno Setup 인스톨러 ──────────────────────────────────────────────
Write-Host "[4/4] 인스톨러 빌드 중..."
if (Test-Path $iscc) {
    & $iscc "$root\Build\installer.iss"
} else {
    Write-Warning "Inno Setup을 찾을 수 없습니다. installer.iss를 수동으로 컴파일하세요."
}

Write-Host ""
Write-Host "=== 빌드 완료 ==="
Write-Host "  Agent:      $root\Build\Agent\Rice_Harvester_Agent.exe"
Write-Host "  Controller: $root\Build\Controller\Rice_Harvester.exe"
Write-Host "  Installer:  $root\Build\Output\Rice_Harvester_Setup_v1.0.0.exe"

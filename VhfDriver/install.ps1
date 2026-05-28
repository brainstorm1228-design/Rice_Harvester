# VhfDriver 설치 스크립트 (관리자 권한 필요)
# 빌드 후 Build\VhfDriver\ 디렉토리에서 실행

param(
    [switch]$Uninstall,
    [switch]$TestSign   # 테스트 서명 모드 (개발 환경)
)

$driverPath = Join-Path $PSScriptRoot "..\Build\VhfDriver\VhfDriver.sys"
$infPath    = Join-Path $PSScriptRoot "VhfDriver.inf"

if ($Uninstall) {
    Write-Host "[*] 드라이버 제거 중..."
    pnputil /delete-driver VhfDriver.inf /uninstall /force
    sc.exe delete VhfDriver
    Write-Host "[+] 제거 완료"
    exit 0
}

if ($TestSign) {
    Write-Host "[*] 테스트 서명 모드 활성화 (재부팅 필요)"
    bcdedit /set testsigning on
    Write-Host "[!] 시스템을 재부팅한 후 다시 실행하세요."
    exit 0
}

if (-not (Test-Path $driverPath)) {
    Write-Error "VhfDriver.sys not found. 먼저 Visual Studio + WDK로 빌드하세요."
    exit 1
}

Write-Host "[*] 드라이버 설치 중..."
pnputil /add-driver $infPath /install

# 루트 열거 장치 생성 (소프트웨어 장치)
$devcon = Get-Command devcon.exe -ErrorAction SilentlyContinue
if ($devcon) {
    devcon install $infPath Root\VhfDriver
} else {
    Write-Host "[!] devcon.exe를 찾을 수 없습니다. 수동으로 장치를 추가하세요:"
    Write-Host "    장치 관리자 → 작업 → 레거시 하드웨어 추가 → 목록에서 선택"
}

Write-Host "[+] 설치 완료. QA HID Companion이 Device Manager에 나타나야 합니다."

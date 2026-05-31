# Rice Harvester

원격 다중 PC 화면 모니터링과 입력 자동화를 위한 Windows QA/보안 연구 도구입니다.
Controller 한 대에서 여러 Agent PC를 연결하고, 화면 확인, 개별 제어, 행동 미러링, 워크플로우 실행을 수행합니다.

> 승인된 테스트 PC, 사내 QA 환경, 보안 연구 랩에서만 사용하세요.

## 현재 구현 상태

- Controller UI 전면 한글화
- 연결 / 모니터링 / 워크플로우 중심의 좌측 행동 패널
- 다크/라이트 모드 전환
- 상단 아이콘형 설정, 테마, 상태 UI
- Agent 연결 상태 드롭다운과 연결 품질 표시
  - 초록: 정상
  - 주황: 연결 불안정 또는 지연 과다
  - 빨강: 끊긴 PC 존재 또는 연결 없음
- 모니터링 화면 그리드
  - 연결된 PC 화면을 한 화면에서 확인
  - 더블클릭으로 개별 확대 창 열기
  - Shift+클릭 다중 선택, 빈 공간 클릭 선택 해제
  - 전체 선택 체크박스
  - 편집 모드에서 PC 이름 표시/수정, 화면 위치 이동
- 확대 창 제어
  - 선택 PC 화면 확대
  - `Alt+F12` 또는 행동 미러링 체크로 마우스/키보드 입력 전달
- 워크플로우
  - 저장 위치: `내 문서\Rice Harvester\flows`
  - 초 단위 시간 입력 UI
  - 키 직접 입력과 조합키 지원
  - 마우스 이동, 자연 이동, 랜덤 클릭, 스크롤
  - PC별 랜덤 지연 실행
  - 모니터링/확대 창 하단 프리셋 바에서 선택 PC 대상으로 실행
- 이미지 감지 워크플로우
  - Agent 화면에서 이미지 찾기
  - 이미지 대기 후 다음 단계 진행
  - 이미지 감지 시 클릭, 해당 Agent 중지, 전체 중지, 알림 동작
- Debug 모드
  - 좌측 상단 Rice Harvester의 `R` 클릭으로 활성화
  - Debug 상태에서 현재 PC 화면을 모니터링 카드로 추가
  - 연결 UI에서 Debug PC를 여러 개 추가 가능
- 입력 백엔드
  - VHF 드라이버 기반 HID 컴패니언
  - SendInput 폴백
  - Arduino Pro Micro / Leonardo 계열 Serial HID 브릿지 지원

## 폴더 구조

```text
Agent/
  HID/                  입력 에뮬레이터
  Network/              명령 서버, 암호화
  Screen/               화면 캡처, 스트리밍, 이미지 감지
  install_agent.ps1     Agent 설치/드라이버 설치 보조 스크립트

Controller/
  ui/main_window.py     메인 UI
  ui/remote_view.py     확대 화면/미러링 창
  network/              Agent 연결, 화면 수신
  models/command.py     명령 모델
  config.py             설정/워크플로우 경로 관리

VhfDriver/              KMDF/VHF 컴패니언 드라이버
Hardware/ProMicro/      Arduino HID 브릿지 펌웨어
build_all.ps1           전체 빌드 및 설치파일 생성
```

## 빌드 출력

현재 알파 빌드 대상 폴더:

```text
C:\QA Security Project_Test_Alpha
```

주요 산출물:

```text
C:\QA Security Project_Test_Alpha\Controller\Rice_Harvester.exe
C:\QA Security Project_Test_Alpha\Agent\Rice_Harvester_Agent.exe
C:\QA Security Project_Test_Alpha\Installer\Rice_Harvester_Setup.exe
C:\QA Security Project_Test_Alpha\Installer\Rice_Harvester_Controller_Setup.exe
C:\QA Security Project_Test_Alpha\Installer\Rice_Harvester_Agent_Setup.exe
```

설치파일은 목적에 따라 풀 패키지 또는 분리 패키지로 만들 수 있습니다.
Inno Setup이 없는 환경에서는 .NET WinForms 기반 설치 마법사를 생성하며, 일반 설치 프로그램처럼 설치 경로 선택과 바로가기 옵션을 제공합니다.

- `Rice_Harvester_Setup.exe`: Controller, Agent, VHF 드라이버 패키지, Hardware/ProMicro 자료를 모두 포함하는 풀 패키지

- `Rice_Harvester_Controller_Setup.exe`: Controller 실행 파일과 README만 포함
- `Rice_Harvester_Agent_Setup.exe`: Agent, VHF 드라이버 패키지, Hardware/ProMicro 자료 포함

Inno Setup이 설치되어 있으면 Inno 기반 설치파일을 만들고, 없으면 .NET 자가압축 설치파일을 생성합니다.
Defender 오탐 가능성을 줄이기 위해 Controller 설치파일에는 Agent/드라이버 파일을 넣지 않습니다.

기본 설치 위치:

```text
%LOCALAPPDATA%\Programs\Rice Harvester
```

Agent 설치파일도 드라이버를 자동 설치하지 않습니다. VHF 드라이버는 관리자 권한과 서명 정책이 필요하므로 설치 후 Agent 폴더의 설치 스크립트로 별도 처리합니다.

## 전체 빌드

```powershell
cd "C:\QA Security Project"
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\build_all.ps1 `
  -OutputRoot "C:\QA Security Project_Test_Alpha" `
  -SkipPipInstall `
  -InstallerMode Full
```

`-InstallerMode` 값:

- `Full`: 실전 배포용 풀 패키지 설치파일 생성
- `Split`: Controller/Agent 분리 설치파일 생성. 기본값이며 실전 배포 시 권장
- `Both`: 풀 패키지와 분리 설치파일을 모두 생성

설치파일 생성을 건너뛰려면:

```powershell
.\build_all.ps1 -OutputRoot "C:\QA Security Project_Test_Alpha" -SkipPipInstall -SkipInstaller
```

드라이버 테스트 서명 빌드가 필요하면:

```powershell
.\build_all.ps1 -OutputRoot "C:\QA Security Project_Test_Alpha" -DriverSigningMode Test
```

## 실행

Controller:

```powershell
C:\QA Security Project_Test_Alpha\Controller\Rice_Harvester.exe
```

Agent:

```powershell
C:\QA Security Project_Test_Alpha\Agent\Rice_Harvester_Agent.exe 9000 change-this-secret
```

Pro Micro HID 브릿지 사용:

```powershell
Rice_Harvester_Agent.exe 9000 change-this-secret --hid=promicro --hid-port=COM3
```

환경변수 방식:

```powershell
$env:RICE_HARVESTER_HID_MODE = "promicro"
$env:RICE_HARVESTER_PRO_MICRO_PORT = "COM3"
Rice_Harvester_Agent.exe
```

## VHF 드라이버

VHF 드라이버는 `VhfDriver.sys`, `VhfDriver.inf`, `VhfDriver.cat`로 구성됩니다.
Windows 보안 정책상 실제 배포용 커널 드라이버는 Microsoft Attestation Signing 또는 EV 코드 서명 절차가 필요합니다.

테스트 서명 환경:

```powershell
# 관리자 PowerShell
bcdedit /set testsigning on
# 재부팅 후
cd "C:\QA Security Project_Test_Alpha\Agent"
.\install_agent.ps1 -InstallDriver -EnableTestSigning
```

일반 설치 시도:

```powershell
# 관리자 PowerShell
cd "C:\QA Security Project_Test_Alpha\Agent"
.\install_agent.ps1 -InstallDriver
```

## Arduino Pro Micro

펌웨어 위치:

```text
C:\QA Security Project_Test_Alpha\Hardware\ProMicro\RiceHarvesterHidBridge\RiceHarvesterHidBridge.ino
```

권장 보드:

- Arduino Pro Micro 5V/16MHz
- Arduino Leonardo

Arduino IDE에서 펌웨어를 업로드한 뒤 Agent 실행 시 COM 포트를 지정합니다.

## 보안 참고

Controller만 실행하는 경우 보안 프로그램에 탐지될 가능성은 낮은 편입니다.
다만 PyInstaller exe, 네트워크 제어, 원격 화면/입력 자동화 기능 때문에 오탐 가능성은 있습니다.

민감도가 높은 순서:

1. VHF 드라이버 설치
2. Agent 실행
3. Controller 실행

배포 전에는 Windows Defender 검사와 별도 테스트 PC 검증을 권장합니다.

## 통신

기본 포트:

| 포트 | 역할 |
| --- | --- |
| 9000 | 명령 채널 |
| 9001 | 화면 스트리밍 |

암호화:

```text
shared_secret -> SHA256 -> AES-256-CBC key
frame = [4B big-endian length][16B IV + ciphertext]
```

## 라이선스

보안 연구 및 승인된 QA 자동화 목적 전용입니다.
무단 시스템 접근, 우회, 악성 자동화에 사용하지 마세요.

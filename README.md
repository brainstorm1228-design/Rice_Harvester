# 🌾 Rice_Harvester

원격 다중 PC HID 에뮬레이션 보안 연구 도구.  
Controller PC 한 대에서 여러 Agent PC를 연결하여 마우스/키보드 입력을 전송하고, 원격 화면을 실시간으로 확인할 수 있습니다.

> **용도**: 보안 연구, QA 자동화, 펜 테스트 랩 환경  
> **주의**: 승인된 시스템에서만 사용하십시오.

---

## 아키텍처

```
Controller (Python)
    │
    ├── CommandChannel (TCP, AES-256-CBC) ──▶ Agent (C# .NET 8)
    │       JSON HID 명령                        ├── VhfEmulator      ← Device Manager에 HW로 인식
    │                                            │   └── \\.\QAHidCompanion (VHF 드라이버)
    └── ScreenChannel  (TCP, AES-256-CBC) ◀──   └── FallbackEmulator ← SendInput (드라이버 없을 때)
            [4B W][4B H][JPEG] 암호화
```

### 포트 구성

| 포트 | 역할 |
|------|------|
| 9000 (기본) | 명령 수신 (TCP) |
| 9001 (기본+1) | 화면 스트리밍 (TCP) |

### 암호화 프로토콜

```
shared_secret ─SHA256─▶ 32B key
payload ─AES-256-CBC─▶ [16B IV][ciphertext]
frame  = [4B big-endian length][encrypted payload]
```

---

## 구성 요소

### Agent (C# .NET 8, Windows)

```
Agent/
├── HID/
│   ├── IHidEmulator.cs        인터페이스 정의
│   ├── VhfEmulator.cs         VHF 컴패니언 드라이버 통신 (하드웨어 인식)
│   ├── FallbackEmulator.cs    SendInput 폴백 (개발/테스트용)
│   └── HidReportBuilder.cs   HID 바이트 리포트 생성
├── Network/
│   ├── CommandServer.cs       TCP 명령 수신 및 HID 디스패치
│   └── Crypto.cs              AES-256-CBC 암호화
├── Screen/
│   ├── ScreenCapture.cs       GDI BitBlt → JPEG 캡처
│   └── ScreenServer.cs        화면 스트리밍 서버
├── Models/
│   └── HidCommand.cs          명령 직렬화 모델
└── Program.cs                 진입점, VHF→Fallback 자동 선택
```

### Controller (Python 3.11+)

```
Controller/
├── network/
│   ├── agent_manager.py       다중 에이전트 연결 관리, 자동 재연결
│   └── screen_client.py       화면 스트리밍 수신
├── ui/
│   ├── main_window.py         메인 UI (customtkinter, 다크 테마)
│   └── remote_view.py         원격 화면 뷰어 + 클릭→HID 변환
├── models/
│   └── command.py             HID 명령 직렬화
├── config.py                  설정 저장/불러오기
├── main.py                    진입점
└── requirements.txt
```

### VhfDriver (KMDF, Windows WDK)

```
VhfDriver/
├── driver.c / driver.h        DriverEntry, WDF 드라이버 초기화
├── device.c                   DeviceAdd, VHF HID 장치 생성, EvtIoWrite
├── hid_descriptors.h          키보드/마우스 HID 리포트 디스크립터
├── VhfDriver.inf              드라이버 설치 파일
└── install.ps1                드라이버 설치 스크립트 (테스트 서명 지원)
```

---

## 빌드

### 사전 요구사항

| 항목 | 버전 |
|------|------|
| .NET SDK | 8.0+ |
| Python | 3.11+ |
| PyInstaller | 6.0+ (`pip install pyinstaller`) |
| Inno Setup | 6.x (선택 사항, 설치파일 생성 시) |
| WDK | 10.0.26100+ (VHF 드라이버 빌드 시) |

### Agent 빌드

```powershell
cd "C:\QA Security Project"
dotnet publish Agent -c Release -r win-x64 --self-contained -o Build\Agent
```

출력: `Build\Agent\Rice_Harvester_Agent.exe`

### Controller 빌드

```powershell
cd Controller
pip install -r requirements.txt
pyinstaller --onefile --windowed --name Rice_Harvester_Controller main.py
```

출력: `dist\Rice_Harvester_Controller.exe`

### 전체 빌드 (자동화)

```powershell
.\build_all.ps1
```

순서: 아이콘 변환 → Agent dotnet publish → Controller PyInstaller → Inno Setup 설치파일

### 아이콘 설정 (선택)

`assets/icon.png` 배치 후:

```powershell
cd assets
python make_icon.py
```

---

## 실행

### Agent 실행

```powershell
Rice_Harvester_Agent.exe [포트] [시크릿]
# 예:
Rice_Harvester_Agent.exe 9000 my-secret-key
# 또는 환경변수:
$env:AGENT_SECRET = "my-secret-key"
Rice_Harvester_Agent.exe
```

### Controller 실행

```powershell
python Controller/main.py
# 또는 빌드된 exe:
Rice_Harvester_Controller.exe
```

Controller UI에서:
1. **Settings** 탭에서 시크릿 키 설정
2. **Connect** 버튼 → `host:port` 입력으로 Agent 추가
3. **Keyboard** / **Mouse** 탭에서 HID 명령 전송
4. 에이전트 카드의 🖥 버튼으로 원격 화면 뷰어 열기 (화면 클릭 → HID 전달)

---

## VHF 컴패니언 드라이버 설치

> VHF 드라이버 없이도 Agent는 동작하지만, SendInput 방식은 보안 소프트웨어에 탐지될 수 있습니다.  
> 하드웨어로 인식시키려면 아래 드라이버를 설치하세요.

### 테스트 환경 (테스트 서명)

```powershell
# 관리자 PowerShell
bcdedit /set testsigning on
# 재시작 후:
cd VhfDriver
.\install.ps1 -TestSign
```

### 프로덕션 (EV 코드 서명 인증서 필요)

```powershell
cd VhfDriver
.\install.ps1
```

드라이버 설치 후 Device Manager에 **QA HID Companion (Keyboard)**, **QA HID Companion (Mouse)** 두 장치가 등록됩니다.

---

## HID 패킷 형식

### 키보드 리포트 (8바이트, Boot Protocol)

| 바이트 | 내용 |
|--------|------|
| 0 | Modifier (Ctrl=0x01, Shift=0x02, Alt=0x04, Win=0x08) |
| 1 | Reserved (0x00) |
| 2–7 | Keycode 1–6 (동시 입력) |

### 마우스 리포트 (4바이트)

| 바이트 | 내용 |
|--------|------|
| 0 | Buttons (Left=0x01, Right=0x02, Middle=0x04) |
| 1 | Delta X (signed, -127~127) |
| 2 | Delta Y (signed, -127~127) |
| 3 | Wheel (signed, -127~127) |

### 컴패니언 드라이버 패킷

```
[1B type][report bytes]
  0x00 = 키보드 (8B)
  0x01 = 마우스  (4B)
```

---

## 탐지 저항

| 방식 | 탐지 저항 | 설명 |
|------|-----------|------|
| VHF 드라이버 (하드웨어 인식) | 높음 | Device Manager에 Logitech VID/PID로 등록 |
| SendInput 폴백 | 낮음 | 보안 소프트웨어가 API 후킹으로 탐지 가능 |

VHF 방식은 Windows 커널의 `vhf.sys`를 통해 진짜 HID 장치로 등록되므로, 사용자 공간 HID 탐지를 우회합니다.

---

## 보안 고려사항

- 기본 시크릿 키(`change-this-secret`)는 반드시 변경하세요.
- Agent는 바인딩 주소를 `0.0.0.0`으로 설정합니다. 방화벽으로 접근을 제한하세요.
- 모든 트래픽은 AES-256-CBC로 암호화되지만, 인증서 기반 상호 인증(mTLS)은 미구현 상태입니다.
- 허가된 시스템에서만 사용하십시오.

---

## 라이선스

보안 연구 목적 전용. 무단 시스템 접근에 사용 금지.

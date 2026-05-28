#include "driver.h"

// ──────────────────────────────────────────────────────────────
//  VHF 콜백 — 실제 HID 장치처럼 동작하기 위한 최소 구현
// ──────────────────────────────────────────────────────────────

static VOID VhfEvtReadyForNextReadReport(PVOID VhfClientContext, VHFOPERATIONHANDLE VhfOperationHandle, PVOID VhfOperationContext)
{
    UNREFERENCED_PARAMETER(VhfClientContext);
    UNREFERENCED_PARAMETER(VhfOperationContext);
    VhfOperationComplete(VhfOperationHandle, STATUS_SUCCESS);
}

// ──────────────────────────────────────────────────────────────
//  DeviceAdd: 장치 생성 + VHF 초기화 + I/O 큐 생성
// ──────────────────────────────────────────────────────────────

NTSTATUS DeviceAdd(
    _In_    WDFDRIVER       Driver,
    _Inout_ PWDFDEVICE_INIT DeviceInit)
{
    UNREFERENCED_PARAMETER(Driver);
    NTSTATUS status;

    WdfDeviceInitSetDeviceType(DeviceInit, FILE_DEVICE_UNKNOWN);

    // 장치 컨텍스트 설정
    WDF_OBJECT_ATTRIBUTES devAttrs;
    WDF_OBJECT_ATTRIBUTES_INIT_CONTEXT_TYPE(&devAttrs, DEVICE_CONTEXT);
    devAttrs.EvtCleanupCallback = EvtDeviceCleanup;

    WDFDEVICE device;
    status = WdfDeviceCreate(&DeviceInit, &devAttrs, &device);
    if (!NT_SUCCESS(status)) return status;

    // 유저 모드에서 \\.\QAHidCompanion 으로 열 수 있도록 심볼릭 링크 생성
    DECLARE_CONST_UNICODE_STRING(symLink, L"\\DosDevices\\QAHidCompanion");
    WdfDeviceCreateSymbolicLink(device, &symLink);

    // ── 키보드 VHF 초기화 ──────────────────────────────────────
    PDEVICE_CONTEXT ctx = DeviceGetContext(device);

    VHF_CONFIG vhfKbd;
    VHF_CONFIG_INIT(&vhfKbd,
                    WdfDeviceWdmGetDeviceObject(device),
                    sizeof(s_KeyboardDescriptor),
                    (PUCHAR)s_KeyboardDescriptor);
    vhfKbd.VendorID      = 0x046D;   // Logitech
    vhfKbd.ProductID     = 0xC31C;   // K120 Keyboard
    vhfKbd.VersionNumber = 0x0300;
    vhfKbd.EvtVhfReadyForNextReadReport = VhfEvtReadyForNextReadReport;

    status = VhfCreate(&vhfKbd, &ctx->hVhfKeyboard);
    if (!NT_SUCCESS(status)) return status;

    // ── 마우스 VHF 초기화 ──────────────────────────────────────
    VHF_CONFIG vhfMouse;
    VHF_CONFIG_INIT(&vhfMouse,
                    WdfDeviceWdmGetDeviceObject(device),
                    sizeof(s_MouseDescriptor),
                    (PUCHAR)s_MouseDescriptor);
    vhfMouse.VendorID      = 0x046D;  // Logitech
    vhfMouse.ProductID     = 0xC52F;  // M310 Mouse
    vhfMouse.VersionNumber = 0x0300;
    vhfMouse.EvtVhfReadyForNextReadReport = VhfEvtReadyForNextReadReport;

    status = VhfCreate(&vhfMouse, &ctx->hVhfMouse);
    if (!NT_SUCCESS(status)) return status;

    // VHF 장치 활성화 (Device Manager 등록)
    status = VhfStart(ctx->hVhfKeyboard);
    if (!NT_SUCCESS(status)) return status;
    status = VhfStart(ctx->hVhfMouse);
    if (!NT_SUCCESS(status)) return status;

    // ── I/O 큐 생성 (유저 모드 WriteFile 처리) ────────────────
    WDF_IO_QUEUE_CONFIG qCfg;
    WDF_IO_QUEUE_CONFIG_INIT_DEFAULT_QUEUE(&qCfg, WdfIoQueueDispatchParallel);
    qCfg.EvtIoWrite = EvtIoWrite;

    status = WdfIoQueueCreate(device, &qCfg, WDF_NO_OBJECT_ATTRIBUTES, WDF_NO_HANDLE);
    return status;
}

// ──────────────────────────────────────────────────────────────
//  EvtIoWrite: 유저 모드에서 WriteFile로 전달된 HID 리포트 처리
//
//  패킷 형식: [1B type][report bytes]
//    type 0x00 = 키보드 (8B: modifiers, reserved, k1..k6)
//    type 0x01 = 마우스 (4B: buttons, deltaX, deltaY, wheel)
// ──────────────────────────────────────────────────────────────

VOID EvtIoWrite(
    _In_ WDFQUEUE   Queue,
    _In_ WDFREQUEST Request,
    _In_ size_t     Length)
{
    UNREFERENCED_PARAMETER(Length);

    NTSTATUS status;
    PVOID    buffer;
    size_t   bufLen;

    status = WdfRequestRetrieveInputBuffer(Request, 2, &buffer, &bufLen);
    if (!NT_SUCCESS(status)) {
        WdfRequestComplete(Request, status);
        return;
    }

    PUCHAR data       = (PUCHAR)buffer;
    UCHAR  deviceType = data[0];

    PDEVICE_CONTEXT ctx = DeviceGetContext(WdfIoQueueGetDevice(Queue));

    HID_XFER_PACKET packet;
    RtlZeroMemory(&packet, sizeof(packet));
    packet.reportBuffer    = data + 1;
    packet.reportBufferLen = (ULONG)(bufLen - 1);
    packet.reportId        = 0;

    if (deviceType == 0x00)
        status = VhfReadReportSubmit(ctx->hVhfKeyboard, &packet);
    else
        status = VhfReadReportSubmit(ctx->hVhfMouse, &packet);

    WdfRequestComplete(Request, status);
}

// ──────────────────────────────────────────────────────────────
//  EvtDeviceCleanup: 드라이버 언로드 시 VHF 해제
// ──────────────────────────────────────────────────────────────

VOID EvtDeviceCleanup(_In_ WDFOBJECT Device)
{
    PDEVICE_CONTEXT ctx = DeviceGetContext((WDFDEVICE)Device);
    if (ctx->hVhfKeyboard) VhfDelete(ctx->hVhfKeyboard, TRUE);
    if (ctx->hVhfMouse)    VhfDelete(ctx->hVhfMouse,    TRUE);
}

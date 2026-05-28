// VHF 컴패니언 드라이버와 통신하는 하드웨어급 HID 에뮬레이터.
// 드라이버가 Windows VHF를 통해 Device Manager에 실제 HID 장치로 등록하므로
// 보안 소프트웨어가 하드웨어로 인식함.
//
// 패킷 형식: [1B type][report bytes]
//   0x00 = 키보드 (8B: modifiers, reserved, k1..k6)
//   0x01 = 마우스  (4B: buttons, deltaX, deltaY, wheel)

namespace Agent.HID;

using System.Runtime.InteropServices;
using Microsoft.Win32.SafeHandles;

public sealed class VhfEmulator : IHidEmulator
{
    private const string DevicePath = @"\\.\QAHidCompanion";

    [DllImport("kernel32.dll", CharSet = CharSet.Unicode, SetLastError = true)]
    private static extern SafeFileHandle CreateFile(
        string lpFileName, uint dwAccess, uint dwShare,
        IntPtr lpSecurity, uint dwCreation, uint dwFlags, IntPtr hTemplate);

    [DllImport("kernel32.dll", SetLastError = true)]
    private static extern bool WriteFile(
        SafeFileHandle hFile, byte[] lpBuffer, uint nBytes,
        out uint lpWritten, IntPtr lpOverlapped);

    private const uint GENERIC_WRITE = 0x40000000;
    private const uint OPEN_EXISTING = 3;

    private SafeFileHandle? _handle;

    public string Name => "VHF 가상 HID (하드웨어 인식)";
    public bool IsHardwareLike => true;

    public bool Initialize()
    {
        _handle = CreateFile(DevicePath, GENERIC_WRITE, 0, IntPtr.Zero, OPEN_EXISTING, 0, IntPtr.Zero);
        if (_handle.IsInvalid)
        {
            _handle.Dispose();
            _handle = null;
            return false;
        }
        return true;
    }

    private void Send(byte type, byte[] report)
    {
        if (_handle is null || _handle.IsInvalid) return;
        var packet = new byte[1 + report.Length];
        packet[0] = type;
        report.CopyTo(packet, 1);
        WriteFile(_handle, packet, (uint)packet.Length, out _, IntPtr.Zero);
    }

    public void KeyPress(byte keyCode, byte modifiers)
        => Send(0x00, HidReportBuilder.KeyboardReport(modifiers, keyCode));

    public void KeyRelease(byte keyCode, byte modifiers)
        => Send(0x00, HidReportBuilder.KeyboardReport(0));

    public void MouseMove(int x, int y, bool absolute)
    {
        // 상대 이동만 지원 (드라이버 마우스 디스크립터가 relative)
        // absolute 좌표는 호출자가 이전 위치 대비 delta를 계산해서 전달
        sbyte dx = (sbyte)Math.Clamp(x, -127, 127);
        sbyte dy = (sbyte)Math.Clamp(y, -127, 127);
        Send(0x01, HidReportBuilder.MouseReport(0, dx, dy));
    }

    public void MouseButtonDown(byte button)
        => Send(0x01, HidReportBuilder.MouseReport(button, 0, 0));

    public void MouseButtonUp(byte button)
        => Send(0x01, HidReportBuilder.MouseReport(0, 0, 0));

    public void MouseScroll(int delta)
    {
        sbyte wheel = (sbyte)Math.Clamp(delta / 15, -127, 127);
        Send(0x01, HidReportBuilder.MouseReport(0, 0, 0, wheel));
    }

    public void Dispose() => _handle?.Dispose();
}

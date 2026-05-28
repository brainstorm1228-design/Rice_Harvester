// SendInput 기반 폴백 에뮬레이터.
// VHF 컴패니언 드라이버가 없을 때 자동으로 사용됨.
// 보안 소프트웨어에 의해 탐지될 수 있으므로 개발/테스트 전용.

namespace Agent.HID;

using System.Runtime.InteropServices;

public sealed class FallbackEmulator : IHidEmulator
{
    public string Name => "SendInput 폴백 (탐지 가능 — 개발용)";
    public bool IsHardwareLike => false;

    public bool Initialize() => true;

    #region P/Invoke

    [DllImport("user32.dll", SetLastError = true)]
    private static extern uint SendInput(uint nInputs, INPUT[] pInputs, int cbSize);

    [DllImport("user32.dll")]
    private static extern int GetSystemMetrics(int nIndex);

    private const int SM_CXSCREEN = 0;
    private const int SM_CYSCREEN = 1;

    [StructLayout(LayoutKind.Sequential)]
    private struct INPUT
    {
        public uint Type;
        public InputUnion Data;
    }

    [StructLayout(LayoutKind.Explicit)]
    private struct InputUnion
    {
        [FieldOffset(0)] public MOUSEINPUT Mouse;
        [FieldOffset(0)] public KEYBDINPUT Keyboard;
    }

    [StructLayout(LayoutKind.Sequential)]
    private struct MOUSEINPUT
    {
        public int dx, dy;
        public uint mouseData, dwFlags, time;
        public IntPtr dwExtraInfo;
    }

    [StructLayout(LayoutKind.Sequential)]
    private struct KEYBDINPUT
    {
        public ushort wVk, wScan;
        public uint dwFlags, time;
        public IntPtr dwExtraInfo;
    }

    private const uint INPUT_MOUSE    = 0;
    private const uint INPUT_KEYBOARD = 1;

    private const uint KEYEVENTF_KEYUP    = 0x0002;

    private const uint MOUSEEVENTF_MOVE        = 0x0001;
    private const uint MOUSEEVENTF_ABSOLUTE    = 0x8000;
    private const uint MOUSEEVENTF_LEFTDOWN    = 0x0002;
    private const uint MOUSEEVENTF_LEFTUP      = 0x0004;
    private const uint MOUSEEVENTF_RIGHTDOWN   = 0x0008;
    private const uint MOUSEEVENTF_RIGHTUP     = 0x0010;
    private const uint MOUSEEVENTF_MIDDLEDOWN  = 0x0020;
    private const uint MOUSEEVENTF_MIDDLEUP    = 0x0040;
    private const uint MOUSEEVENTF_WHEEL       = 0x0800;

    #endregion

    public void KeyPress(byte keyCode, byte modifiers)   => SendKey(keyCode, modifiers, down: true);
    public void KeyRelease(byte keyCode, byte modifiers) => SendKey(keyCode, modifiers, down: false);

    private static void SendKey(byte keyCode, byte modifiers, bool down)
    {
        var inputs = new List<INPUT>();

        if ((modifiers & 0x01) != 0) inputs.Add(MakeKey(0x11, down)); // VK_CONTROL
        if ((modifiers & 0x02) != 0) inputs.Add(MakeKey(0x10, down)); // VK_SHIFT
        if ((modifiers & 0x04) != 0) inputs.Add(MakeKey(0x12, down)); // VK_MENU
        if ((modifiers & 0x08) != 0) inputs.Add(MakeKey(0x5B, down)); // VK_LWIN
        inputs.Add(MakeKey(keyCode, down));

        SendInput((uint)inputs.Count, inputs.ToArray(), Marshal.SizeOf<INPUT>());
    }

    private static INPUT MakeKey(byte vk, bool down) => new()
    {
        Type = INPUT_KEYBOARD,
        Data = new InputUnion
        {
            Keyboard = new KEYBDINPUT { wVk = vk, dwFlags = down ? 0u : KEYEVENTF_KEYUP }
        }
    };

    public void MouseMove(int x, int y, bool absolute)
    {
        int nx = absolute ? x * 65535 / GetSystemMetrics(SM_CXSCREEN) : x;
        int ny = absolute ? y * 65535 / GetSystemMetrics(SM_CYSCREEN) : y;

        SendInput(1, [new INPUT
        {
            Type = INPUT_MOUSE,
            Data = new InputUnion
            {
                Mouse = new MOUSEINPUT
                {
                    dx = nx, dy = ny,
                    dwFlags = MOUSEEVENTF_MOVE | (absolute ? MOUSEEVENTF_ABSOLUTE : 0u)
                }
            }
        }], Marshal.SizeOf<INPUT>());
    }

    public void MouseButtonDown(byte button) => SendMouseButton(button, down: true);
    public void MouseButtonUp(byte button)   => SendMouseButton(button, down: false);

    private static void SendMouseButton(byte button, bool down)
    {
        uint flags = button switch
        {
            0x01 => down ? MOUSEEVENTF_LEFTDOWN   : MOUSEEVENTF_LEFTUP,
            0x02 => down ? MOUSEEVENTF_RIGHTDOWN  : MOUSEEVENTF_RIGHTUP,
            0x04 => down ? MOUSEEVENTF_MIDDLEDOWN : MOUSEEVENTF_MIDDLEUP,
            _    => down ? MOUSEEVENTF_LEFTDOWN   : MOUSEEVENTF_LEFTUP
        };
        SendInput(1, [new INPUT
        {
            Type = INPUT_MOUSE,
            Data = new InputUnion { Mouse = new MOUSEINPUT { dwFlags = flags } }
        }], Marshal.SizeOf<INPUT>());
    }

    public void MouseScroll(int delta) =>
        SendInput(1, [new INPUT
        {
            Type = INPUT_MOUSE,
            Data = new InputUnion
            {
                Mouse = new MOUSEINPUT { dwFlags = MOUSEEVENTF_WHEEL, mouseData = (uint)delta }
            }
        }], Marshal.SizeOf<INPUT>());

    public void Dispose() { }
}

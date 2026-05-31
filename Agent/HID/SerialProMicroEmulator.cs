namespace Agent.HID;

using System.Runtime.InteropServices;
using System.Text;
using Microsoft.Win32.SafeHandles;

public sealed class SerialProMicroEmulator : IHidEmulator
{
    private const int BaudRate = 115200;
    private readonly string? _configuredPort;
    private readonly object _sync = new();
    private SafeFileHandle? _handle;

    public SerialProMicroEmulator(string? configuredPort = null)
    {
        _configuredPort = string.IsNullOrWhiteSpace(configuredPort) ? null : configuredPort.Trim();
    }

    public string Name => $"Arduino Pro Micro HID ({PortName ?? "not connected"})";
    public bool IsHardwareLike => true;
    public string? PortName { get; private set; }

    public bool Initialize()
    {
        if (_configuredPort is { } port)
            return TryOpen(port);

        foreach (var portName in Enumerable.Range(1, 64).Select(i => $"COM{i}"))
        {
            if (TryOpen(portName))
                return true;
        }

        return false;
    }

    public void KeyPress(byte keyCode, byte modifiers)
        => WriteLine($"KD {modifiers} {keyCode}");

    public void KeyRelease(byte keyCode, byte modifiers)
        => WriteLine("KU");

    public void MouseMove(int x, int y, bool absolute)
    {
        if (absolute && GetCursorPos(out var point))
        {
            x -= point.X;
            y -= point.Y;
        }

        SendRelativeMove(x, y);
    }

    public void MouseButtonDown(byte button)
        => WriteLine($"MD {button}");

    public void MouseButtonUp(byte button)
        => WriteLine($"MU {button}");

    public void MouseScroll(int delta)
    {
        int wheel = delta / 120;
        if (wheel == 0 && delta != 0)
            wheel = Math.Sign(delta);
        WriteLine($"MW {Math.Clamp(wheel, -10, 10)}");
    }

    private void SendRelativeMove(int dx, int dy)
    {
        while (dx != 0 || dy != 0)
        {
            int chunkX = Math.Clamp(dx, -127, 127);
            int chunkY = Math.Clamp(dy, -127, 127);
            WriteLine($"MM {chunkX} {chunkY}");
            dx -= chunkX;
            dy -= chunkY;
        }
    }

    private bool TryOpen(string portName)
    {
        var handle = CreateFile(
            @"\\.\" + portName,
            GENERIC_READ | GENERIC_WRITE,
            0,
            IntPtr.Zero,
            OPEN_EXISTING,
            0,
            IntPtr.Zero);

        if (handle.IsInvalid)
        {
            handle.Dispose();
            return false;
        }

        if (!ConfigurePort(handle))
        {
            handle.Dispose();
            return false;
        }

        _handle = handle;
        PortName = portName;
        PurgeComm(handle, PURGE_RXCLEAR | PURGE_TXCLEAR);

        var deadline = DateTime.UtcNow.AddMilliseconds(1800);
        while (DateTime.UtcNow < deadline)
        {
            WriteLine("PING");
            var response = ReadLine(TimeSpan.FromMilliseconds(250));
            if (response.Contains("RHID:PONG", StringComparison.OrdinalIgnoreCase))
            {
                WriteLine("REL");
                return true;
            }
        }

        Dispose();
        return false;
    }

    private static bool ConfigurePort(SafeFileHandle handle)
    {
        var dcb = new DCB { DCBlength = (uint)Marshal.SizeOf<DCB>() };
        if (!BuildCommDCB($"baud={BaudRate} parity=N data=8 stop=1", ref dcb))
            return false;
        if (!SetCommState(handle, ref dcb))
            return false;

        var timeouts = new COMMTIMEOUTS
        {
            ReadIntervalTimeout = 20,
            ReadTotalTimeoutMultiplier = 0,
            ReadTotalTimeoutConstant = 80,
            WriteTotalTimeoutMultiplier = 0,
            WriteTotalTimeoutConstant = 1000
        };
        if (!SetCommTimeouts(handle, ref timeouts))
            return false;

        EscapeCommFunction(handle, SETDTR);
        EscapeCommFunction(handle, SETRTS);
        return true;
    }

    private void WriteLine(string line)
    {
        lock (_sync)
        {
            if (_handle is null || _handle.IsInvalid)
                return;

            var bytes = Encoding.ASCII.GetBytes(line + "\n");
            WriteFile(_handle, bytes, (uint)bytes.Length, out _, IntPtr.Zero);
        }
    }

    private string ReadLine(TimeSpan timeout)
    {
        if (_handle is null || _handle.IsInvalid)
            return "";

        var end = DateTime.UtcNow + timeout;
        var buffer = new byte[1];
        var sb = new StringBuilder();

        while (DateTime.UtcNow < end)
        {
            if (!ReadFile(_handle, buffer, 1, out var read, IntPtr.Zero))
                break;
            if (read == 0)
                continue;

            char ch = (char)buffer[0];
            if (ch == '\n')
                break;
            if (ch != '\r')
                sb.Append(ch);
        }

        return sb.ToString();
    }

    public void Dispose()
    {
        _handle?.Dispose();
        _handle = null;
        PortName = null;
    }

    [DllImport("kernel32.dll", CharSet = CharSet.Unicode, SetLastError = true)]
    private static extern SafeFileHandle CreateFile(
        string lpFileName, uint dwDesiredAccess, uint dwShareMode,
        IntPtr lpSecurityAttributes, uint dwCreationDisposition,
        uint dwFlagsAndAttributes, IntPtr hTemplateFile);

    [DllImport("kernel32.dll", SetLastError = true)]
    private static extern bool BuildCommDCB(string lpDef, ref DCB lpDCB);

    [DllImport("kernel32.dll", SetLastError = true)]
    private static extern bool SetCommState(SafeFileHandle hFile, ref DCB lpDCB);

    [DllImport("kernel32.dll", SetLastError = true)]
    private static extern bool SetCommTimeouts(SafeFileHandle hFile, ref COMMTIMEOUTS lpCommTimeouts);

    [DllImport("kernel32.dll", SetLastError = true)]
    private static extern bool PurgeComm(SafeFileHandle hFile, uint dwFlags);

    [DllImport("kernel32.dll", SetLastError = true)]
    private static extern bool EscapeCommFunction(SafeFileHandle hFile, uint dwFunc);

    [DllImport("kernel32.dll", SetLastError = true)]
    private static extern bool WriteFile(
        SafeFileHandle hFile, byte[] lpBuffer, uint nBytesToWrite,
        out uint lpNumberOfBytesWritten, IntPtr lpOverlapped);

    [DllImport("kernel32.dll", SetLastError = true)]
    private static extern bool ReadFile(
        SafeFileHandle hFile, byte[] lpBuffer, uint nNumberOfBytesToRead,
        out uint lpNumberOfBytesRead, IntPtr lpOverlapped);

    [DllImport("user32.dll")]
    private static extern bool GetCursorPos(out POINT lpPoint);

    private const uint GENERIC_READ = 0x80000000;
    private const uint GENERIC_WRITE = 0x40000000;
    private const uint OPEN_EXISTING = 3;
    private const uint PURGE_RXCLEAR = 0x0008;
    private const uint PURGE_TXCLEAR = 0x0004;
    private const uint SETRTS = 3;
    private const uint SETDTR = 5;

    [StructLayout(LayoutKind.Sequential)]
    private struct COMMTIMEOUTS
    {
        public uint ReadIntervalTimeout;
        public uint ReadTotalTimeoutMultiplier;
        public uint ReadTotalTimeoutConstant;
        public uint WriteTotalTimeoutMultiplier;
        public uint WriteTotalTimeoutConstant;
    }

    [StructLayout(LayoutKind.Sequential)]
    private struct DCB
    {
        public uint DCBlength;
        public uint BaudRate;
        public uint Flags;
        public ushort wReserved;
        public ushort XonLim;
        public ushort XoffLim;
        public byte ByteSize;
        public byte Parity;
        public byte StopBits;
        public sbyte XonChar;
        public sbyte XoffChar;
        public sbyte ErrorChar;
        public sbyte EofChar;
        public sbyte EvtChar;
        public ushort wReserved1;
    }

    [StructLayout(LayoutKind.Sequential)]
    private struct POINT
    {
        public int X;
        public int Y;
    }
}

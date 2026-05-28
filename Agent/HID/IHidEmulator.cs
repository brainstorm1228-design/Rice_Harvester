namespace Agent.HID;

public interface IHidEmulator : IDisposable
{
    string Name { get; }

    // true = 하드웨어처럼 인식됨 (Device Manager 등록), false = 소프트웨어 API
    bool IsHardwareLike { get; }

    bool Initialize();

    void KeyPress(byte keyCode, byte modifiers);
    void KeyRelease(byte keyCode, byte modifiers);

    void MouseMove(int x, int y, bool absolute);
    void MouseButtonDown(byte button);
    void MouseButtonUp(byte button);
    void MouseScroll(int delta);
}

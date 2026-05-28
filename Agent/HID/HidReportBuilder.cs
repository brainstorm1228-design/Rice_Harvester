namespace Agent.HID;

public static class HidReportBuilder
{
    // Standard 8-byte boot-protocol keyboard report
    // [0] modifiers, [1] reserved, [2..7] keycodes (up to 6)
    public static byte[] KeyboardReport(byte modifiers, params byte[] keyCodes)
    {
        var r = new byte[8];
        r[0] = modifiers;
        for (int i = 0; i < Math.Min(keyCodes.Length, 6); i++)
            r[2 + i] = keyCodes[i];
        return r;
    }

    // Standard 4-byte boot-protocol mouse report
    // [0] buttons, [1] deltaX, [2] deltaY, [3] wheel
    public static byte[] MouseReport(byte buttons, sbyte deltaX, sbyte deltaY, sbyte wheel = 0)
        => [(byte)buttons, (byte)deltaX, (byte)deltaY, (byte)wheel];

    public static byte ModifierByte(IEnumerable<string>? mods)
    {
        if (mods == null) return 0;
        byte m = 0;
        foreach (var mod in mods)
            m |= mod.ToLowerInvariant() switch
            {
                "ctrl"  or "lctrl"  => 0x01,
                "shift" or "lshift" => 0x02,
                "alt"   or "lalt"   => 0x04,
                "win"   or "lgui"   => 0x08,
                "rctrl"             => 0x10,
                "rshift"            => 0x20,
                "ralt"              => 0x40,
                "rgui"              => 0x80,
                _                   => 0x00
            };
        return m;
    }

    public static byte MouseButtonByte(string button) => button.ToLowerInvariant() switch
    {
        "left"   => 0x01,
        "right"  => 0x02,
        "middle" => 0x04,
        _        => 0x01
    };
}

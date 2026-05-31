using Agent.HID;
using Agent.Network;
using Agent.Screen;

Console.OutputEncoding = System.Text.Encoding.UTF8;

int port = 9000;
string secret = Environment.GetEnvironmentVariable("AGENT_SECRET") ?? "change-this-secret";
string hidMode = Environment.GetEnvironmentVariable("RICE_HARVESTER_HID_MODE") ?? "auto";
string? proMicroPort = Environment.GetEnvironmentVariable("RICE_HARVESTER_PRO_MICRO_PORT");

foreach (var arg in args)
{
    if (arg.StartsWith("--hid=", StringComparison.OrdinalIgnoreCase))
    {
        hidMode = arg["--hid=".Length..].Trim();
    }
    else if (arg.StartsWith("--hid-port=", StringComparison.OrdinalIgnoreCase))
    {
        proMicroPort = arg["--hid-port=".Length..].Trim();
    }
    else if (int.TryParse(arg, out var parsedPort))
    {
        port = parsedPort;
    }
    else
    {
        secret = arg;
    }
}

Console.WriteLine("=== Rice_Harvester Agent ===");
Console.WriteLine($"[Agent] command port: {port} | screen port: {port + 1}");
Console.WriteLine($"[Agent] HID mode: {hidMode}");

IHidEmulator hid = CreateHid(hidMode, proMicroPort);

Console.WriteLine($"[Agent] HID backend: {hid.Name}");
Console.WriteLine($"[Agent] hardware-like input: {(hid.IsHardwareLike ? "yes" : "no")}");

Console.CancelKeyPress += (_, e) => { e.Cancel = true; Environment.Exit(0); };

using var hidScope = hid;
using var commandServer = new CommandServer(port, secret, hid);
using var screenServer = new ScreenServer(port + 1, secret);

await Task.WhenAll(
    commandServer.RunAsync(),
    screenServer.RunAsync()
);

static IHidEmulator CreateHid(string mode, string? proMicroPort)
{
    mode = mode.Trim().ToLowerInvariant();

    if (mode is "promicro" or "pro-micro" or "arduino")
    {
        var proMicro = new SerialProMicroEmulator(proMicroPort);
        if (proMicro.Initialize())
            return proMicro;

        Console.WriteLine("[Agent] Pro Micro was not found. Falling back to SendInput.");
        proMicro.Dispose();
        return InitializeFallback();
    }

    if (mode is "sendinput" or "fallback")
        return InitializeFallback();

    if (!string.IsNullOrWhiteSpace(proMicroPort))
    {
        var proMicro = new SerialProMicroEmulator(proMicroPort);
        if (proMicro.Initialize())
            return proMicro;

        proMicro.Dispose();
        Console.WriteLine($"[Agent] Pro Micro was not found on {proMicroPort}.");
    }

    var vhf = new VhfEmulator();
    if (vhf.Initialize())
        return vhf;

    vhf.Dispose();
    Console.WriteLine("[Agent] VHF driver was not found. Falling back to SendInput.");
    return InitializeFallback();
}

static IHidEmulator InitializeFallback()
{
    var fallback = new FallbackEmulator();
    fallback.Initialize();
    return fallback;
}

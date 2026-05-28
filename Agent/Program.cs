using Agent.HID;
using Agent.Network;
using Agent.Screen;

Console.OutputEncoding = System.Text.Encoding.UTF8;

int port      = args.Length > 0 ? int.Parse(args[0]) : 9000;
string secret = args.Length > 1 ? args[1]
              : Environment.GetEnvironmentVariable("AGENT_SECRET") ?? "change-this-secret";

Console.WriteLine("=== Rice_Harvester Agent ===");
Console.WriteLine($"[에이전트] 포트: {port}  |  화면 스트리밍 포트: {port + 1}");

// VHF 드라이버 시도 → 없으면 SendInput 폴백
IHidEmulator hid = new VhfEmulator();
if (!hid.Initialize())
{
    Console.WriteLine("[에이전트] VHF 드라이버 미설치 → SendInput 폴백으로 전환");
    Console.WriteLine("[경고] SendInput 방식은 보안 소프트웨어에 탐지될 수 있습니다.");
    Console.WriteLine("[안내] 하드웨어 인식이 필요하면 VhfDriver.sys 를 설치하세요.");
    hid.Dispose();
    hid = new FallbackEmulator();
    hid.Initialize();
}
else
{
    Console.WriteLine("[에이전트] VHF 드라이버 연결 성공 → 하드웨어로 인식됩니다.");
}

Console.WriteLine($"[에이전트] HID 방식: {hid.Name}");
Console.WriteLine($"[에이전트] 하드웨어 인식 여부: {(hid.IsHardwareLike ? "예 (하드웨어)" : "아니오 (소프트웨어)")}");

Console.CancelKeyPress += (_, e) => { e.Cancel = true; Environment.Exit(0); };

using var hidScope      = hid;
using var commandServer = new CommandServer(port, secret, hid);
using var screenServer  = new ScreenServer(port + 1, secret);

await Task.WhenAll(
    commandServer.RunAsync(),
    screenServer.RunAsync()
);

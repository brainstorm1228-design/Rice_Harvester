namespace Agent.Network;

using System.Net;
using System.Net.Sockets;
using System.Text;
using System.Text.Json;
using Agent.HID;
using Agent.Models;
using Agent.Screen;

public sealed class CommandServer : IDisposable
{
    private readonly TcpListener _listener;
    private readonly byte[] _key;
    private readonly IHidEmulator _hid;
    private readonly CancellationTokenSource _cts = new();

    public CommandServer(int port, string secret, IHidEmulator hid)
    {
        _listener = new TcpListener(IPAddress.Any, port);
        _key = Crypto.DeriveKey(secret);
        _hid = hid;
    }

    public async Task RunAsync()
    {
        _listener.Start();
        Console.WriteLine($"[명령 서버] 수신 대기 중 — 포트 {((IPEndPoint)_listener.LocalEndpoint).Port}");

        while (!_cts.IsCancellationRequested)
        {
            try
            {
                var client = await _listener.AcceptTcpClientAsync(_cts.Token);
                _ = Task.Run(() => HandleClientAsync(client));
            }
            catch (OperationCanceledException) { break; }
        }
    }

    private async Task HandleClientAsync(TcpClient client)
    {
        using var _ = client;
        var remote = client.Client.RemoteEndPoint;
        Console.WriteLine($"[명령 서버] Controller 연결됨: {remote}");

        try
        {
            var stream = client.GetStream();
            var lenBuf = new byte[4];

            while (!_cts.IsCancellationRequested)
            {
                await stream.ReadExactlyAsync(lenBuf, _cts.Token);
                int len = (lenBuf[0] << 24) | (lenBuf[1] << 16) | (lenBuf[2] << 8) | lenBuf[3];

                if (len is < 1 or > 65536)
                {
                    Console.WriteLine($"[명령 서버] 잘못된 패킷 길이 {len} — 연결 종료");
                    break;
                }

                var encrypted = new byte[len];
                await stream.ReadExactlyAsync(encrypted, _cts.Token);

                var json = Encoding.UTF8.GetString(Crypto.Decrypt(encrypted, _key));
                var cmd  = JsonSerializer.Deserialize<HidCommand>(json);
                if (cmd != null)
                {
                    var response = Dispatch(cmd);
                    if (!string.IsNullOrWhiteSpace(cmd.RequestId))
                        await WriteResponseAsync(stream, cmd.RequestId!, response, _cts.Token);
                }
            }
        }
        catch (Exception ex) when (ex is not OperationCanceledException)
        {
            Console.WriteLine($"[명령 서버] {remote} 연결 끊김: {ex.Message}");
        }
    }

    private object Dispatch(HidCommand cmd)
    {
        if (cmd.Type == "ping")
        {
            return new { ok = true, type = "pong", ts = DateTimeOffset.UtcNow.ToUnixTimeMilliseconds() };
        }
        if (cmd.Type == "query" && cmd.Action == "status")
        {
            return ScreenCapture.Status();
        }
        if (cmd.Type == "image" && cmd.Action == "find")
        {
            return ImageDetector.Find(cmd.Data);
        }
        if (cmd.Type == "keyboard" && cmd.Keyboard is { } kb)
        {
            byte mods = HidReportBuilder.ModifierByte(kb.Modifiers);
            if (cmd.Action == "press")   _hid.KeyPress(kb.KeyCode, mods);
            if (cmd.Action == "release") _hid.KeyRelease(kb.KeyCode, mods);
        }
        else if (cmd.Type == "mouse" && cmd.Mouse is { } m)
        {
            switch (cmd.Action)
            {
                case "move":   _hid.MouseMove(m.X, m.Y, m.Absolute); break;
                case "down":   _hid.MouseButtonDown(HidReportBuilder.MouseButtonByte(m.Button)); break;
                case "up":     _hid.MouseButtonUp(HidReportBuilder.MouseButtonByte(m.Button)); break;
                case "scroll": _hid.MouseScroll(m.ScrollDelta); break;
            }
        }
        return new { ok = true };
    }

    private async Task WriteResponseAsync(NetworkStream stream, string requestId, object payload, CancellationToken token)
    {
        var response = JsonSerializer.SerializeToUtf8Bytes(new
        {
            requestId,
            data = payload
        });
        var encrypted = Crypto.Encrypt(response, _key);
        byte[] lenBytes = new byte[4];
        int len = encrypted.Length;
        lenBytes[0] = (byte)(len >> 24);
        lenBytes[1] = (byte)(len >> 16);
        lenBytes[2] = (byte)(len >> 8);
        lenBytes[3] = (byte)len;
        await stream.WriteAsync(lenBytes, token);
        await stream.WriteAsync(encrypted, token);
    }

    public void Dispose()
    {
        _cts.Cancel();
        _listener.Stop();
    }
}

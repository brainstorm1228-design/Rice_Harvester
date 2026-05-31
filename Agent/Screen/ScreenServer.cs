namespace Agent.Screen;

using System.Net;
using System.Net.Sockets;
using Agent.Network;

// 화면을 JPEG으로 캡처해 연결된 Controller로 스트리밍합니다.
// 프레임 형식: [4B 빅엔디안 길이][AES-256 암호화된 JPEG 바이트]
// 기본 포트: CommandServer 포트 + 1 (예: 9001)

public sealed class ScreenServer : IDisposable
{
    private readonly TcpListener _listener;
    private readonly byte[] _key;
    private readonly CancellationTokenSource _cts = new();

    public int TargetFps { get; set; } = 10;

    public ScreenServer(int port, string secret)
    {
        _listener = new TcpListener(IPAddress.Any, port);
        _key = Crypto.DeriveKey(secret);
    }

    public async Task RunAsync()
    {
        _listener.Start();
        Console.WriteLine($"[화면 서버] 수신 대기 중 — 포트 {((IPEndPoint)_listener.LocalEndpoint).Port}");

        while (!_cts.IsCancellationRequested)
        {
            try
            {
                var client = await _listener.AcceptTcpClientAsync(_cts.Token);
                _ = Task.Run(() => StreamToClientAsync(client));
            }
            catch (OperationCanceledException) { break; }
        }
    }

    private async Task StreamToClientAsync(TcpClient client)
    {
        using var _ = client;
        client.SendBufferSize = 1024 * 512;
        Console.WriteLine($"[화면 서버] 뷰어 연결됨: {client.Client.RemoteEndPoint}");

        var stream   = client.GetStream();
        var interval = TimeSpan.FromSeconds(1.0 / TargetFps);

        try
        {
            while (!_cts.IsCancellationRequested && client.Connected)
            {
                var t0 = DateTime.UtcNow;

                // 해상도 정보를 첫 바이트에 포함하는 메타 헤더 [4B W][4B H][JPEG]
                int w = ScreenCapture.VirtualWidth;
                int h = ScreenCapture.VirtualHeight;
                byte[] jpeg = ScreenCapture.CaptureJpeg();

                // 메타 + JPEG 합치기
                var payload = new byte[8 + jpeg.Length];
                BitConverter.GetBytes(w).CopyTo(payload, 0);
                BitConverter.GetBytes(h).CopyTo(payload, 4);
                jpeg.CopyTo(payload, 8);

                // 암호화
                byte[] encrypted = Crypto.Encrypt(payload, _key);

                // 길이 프리픽스 (빅엔디안 4B)
                byte[] lenBytes = new byte[4];
                int len = encrypted.Length;
                lenBytes[0] = (byte)(len >> 24);
                lenBytes[1] = (byte)(len >> 16);
                lenBytes[2] = (byte)(len >>  8);
                lenBytes[3] = (byte)(len);

                await stream.WriteAsync(lenBytes, _cts.Token);
                await stream.WriteAsync(encrypted, _cts.Token);

                // FPS 유지
                var elapsed = DateTime.UtcNow - t0;
                var wait    = interval - elapsed;
                if (wait > TimeSpan.Zero)
                    await Task.Delay(wait, _cts.Token);
            }
        }
        catch (Exception ex) when (ex is not OperationCanceledException)
        {
            Console.WriteLine($"[화면 서버] 뷰어 연결 끊김: {ex.Message}");
        }
    }

    public void Dispose()
    {
        _cts.Cancel();
        _listener.Stop();
    }
}

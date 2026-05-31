namespace Agent.Screen;

using System.Drawing;
using System.Drawing.Imaging;
using System.Runtime.InteropServices;

public static class ScreenCapture
{
    [DllImport("user32.dll")]
    private static extern int GetSystemMetrics(int n);

    [DllImport("user32.dll")]
    private static extern bool GetCursorPos(out POINT lpPoint);

    private const int SM_CXSCREEN = 0;
    private const int SM_CYSCREEN = 1;
    private const int SM_XVIRTUALSCREEN = 76;
    private const int SM_YVIRTUALSCREEN = 77;
    private const int SM_CXVIRTUALSCREEN = 78;
    private const int SM_CYVIRTUALSCREEN = 79;

    public static int ScreenWidth  => GetSystemMetrics(SM_CXSCREEN);
    public static int ScreenHeight => GetSystemMetrics(SM_CYSCREEN);
    public static int VirtualX => GetSystemMetrics(SM_XVIRTUALSCREEN);
    public static int VirtualY => GetSystemMetrics(SM_YVIRTUALSCREEN);
    public static int VirtualWidth => GetSystemMetrics(SM_CXVIRTUALSCREEN);
    public static int VirtualHeight => GetSystemMetrics(SM_CYVIRTUALSCREEN);

    // GDI BitBlt 캡처 → JPEG 바이트 반환
    // DXGI보다 약간 느리지만 의존성 없이 동작
    public static byte[] CaptureJpeg(int quality = 55)
    {
        using var bmp = CaptureBitmap();
        var jpegParams = new EncoderParameters(1);
        jpegParams.Param[0] = new EncoderParameter(Encoder.Quality, (long)quality);

        var codec = GetJpegCodec();
        using var ms = new MemoryStream();
        bmp.Save(ms, codec, jpegParams);
        return ms.ToArray();
    }

    public static Bitmap CaptureBitmap()
    {
        int w = Math.Max(1, VirtualWidth);
        int h = Math.Max(1, VirtualHeight);
        var bmp = new Bitmap(w, h, PixelFormat.Format32bppArgb);
        using var g = Graphics.FromImage(bmp);
        g.CopyFromScreen(VirtualX, VirtualY, 0, 0, new Size(w, h), CopyPixelOperation.SourceCopy);
        return bmp;
    }

    public static object Status()
    {
        GetCursorPos(out var pt);
        return new
        {
            ok = true,
            cursor = new { x = pt.X, y = pt.Y },
            screen = new { width = ScreenWidth, height = ScreenHeight },
            virtualScreen = new { x = VirtualX, y = VirtualY, width = VirtualWidth, height = VirtualHeight },
            ts = DateTimeOffset.UtcNow.ToUnixTimeMilliseconds()
        };
    }

    private static ImageCodecInfo GetJpegCodec()
        => ImageCodecInfo.GetImageEncoders()
                         .First(c => c.MimeType == "image/jpeg");

    [StructLayout(LayoutKind.Sequential)]
    private struct POINT
    {
        public int X;
        public int Y;
    }
}

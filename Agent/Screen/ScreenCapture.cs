namespace Agent.Screen;

using System.Drawing;
using System.Drawing.Imaging;
using System.Runtime.InteropServices;

public static class ScreenCapture
{
    [DllImport("user32.dll")]
    private static extern int GetSystemMetrics(int n);

    public static int ScreenWidth  => GetSystemMetrics(0);
    public static int ScreenHeight => GetSystemMetrics(1);

    // GDI BitBlt 캡처 → JPEG 바이트 반환
    // DXGI보다 약간 느리지만 의존성 없이 동작
    public static byte[] CaptureJpeg(int quality = 55)
    {
        int w = ScreenWidth, h = ScreenHeight;

        using var bmp = new Bitmap(w, h, PixelFormat.Format32bppArgb);
        using var g   = Graphics.FromImage(bmp);
        g.CopyFromScreen(0, 0, 0, 0, new Size(w, h), CopyPixelOperation.SourceCopy);

        var jpegParams = new EncoderParameters(1);
        jpegParams.Param[0] = new EncoderParameter(Encoder.Quality, (long)quality);

        var codec = GetJpegCodec();
        using var ms = new MemoryStream();
        bmp.Save(ms, codec, jpegParams);
        return ms.ToArray();
    }

    private static ImageCodecInfo GetJpegCodec()
        => ImageCodecInfo.GetImageEncoders()
                         .First(c => c.MimeType == "image/jpeg");
}

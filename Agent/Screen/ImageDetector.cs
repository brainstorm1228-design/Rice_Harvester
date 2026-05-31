namespace Agent.Screen;

using System.Drawing;
using System.Text.Json;

public static class ImageDetector
{
    public static object Find(JsonElement? data)
    {
        if (data is null)
            return Fail("missing image find data");

        var d = data.Value;
        string imageData = GetString(d, "imageData") ?? "";
        if (string.IsNullOrWhiteSpace(imageData))
            return Fail("imageData is empty");

        double threshold = GetDouble(d, "threshold", 0.92);
        string mode = (GetString(d, "matchMode") ?? "similar").ToLowerInvariant();
        int timeoutMs = Math.Clamp(GetInt(d, "timeoutMs", 1500), 100, 15000);

        using var template = LoadImage(imageData);
        using var screen = ScreenCapture.CaptureBitmap();

        var roi = GetRoi(d, screen.Width, screen.Height);
        var deadline = DateTime.UtcNow.AddMilliseconds(timeoutMs);
        var result = mode == "exact"
            ? FindExact(screen, template, roi, deadline)
            : FindSimilar(screen, template, roi, threshold, deadline);

        if (!result.Ok)
            return new { ok = false, msg = result.Message, score = result.Score };

        return new
        {
            ok = true,
            x = ScreenCapture.VirtualX + result.X + template.Width / 2,
            y = ScreenCapture.VirtualY + result.Y + template.Height / 2,
            left = ScreenCapture.VirtualX + result.X,
            top = ScreenCapture.VirtualY + result.Y,
            width = template.Width,
            height = template.Height,
            score = Math.Round(result.Score, 4),
            msg = result.Message
        };
    }

    private static Bitmap LoadImage(string imageData)
    {
        int comma = imageData.IndexOf(',');
        if (imageData.StartsWith("data:", StringComparison.OrdinalIgnoreCase) && comma >= 0)
            imageData = imageData[(comma + 1)..];

        var bytes = Convert.FromBase64String(imageData);
        using var ms = new MemoryStream(bytes);
        using var img = Image.FromStream(ms);
        return new Bitmap(img);
    }

    private static Rectangle GetRoi(JsonElement d, int screenW, int screenH)
    {
        if (d.TryGetProperty("roi", out var roi) && roi.ValueKind == JsonValueKind.Object)
        {
            int x = Math.Clamp(GetInt(roi, "x", 0), 0, screenW - 1);
            int y = Math.Clamp(GetInt(roi, "y", 0), 0, screenH - 1);
            int w = Math.Clamp(GetInt(roi, "w", screenW), 1, screenW - x);
            int h = Math.Clamp(GetInt(roi, "h", screenH), 1, screenH - y);
            return new Rectangle(x, y, w, h);
        }
        return new Rectangle(0, 0, screenW, screenH);
    }

    private static MatchResult FindExact(Bitmap screen, Bitmap template, Rectangle roi, DateTime deadline)
    {
        int maxX = roi.Right - template.Width;
        int maxY = roi.Bottom - template.Height;
        if (maxX < roi.Left || maxY < roi.Top)
            return MatchResult.Miss("template larger than search area");

        for (int y = roi.Top; y <= maxY; y++)
        {
            for (int x = roi.Left; x <= maxX; x++)
            {
                if (DateTime.UtcNow > deadline)
                    return MatchResult.Miss("image scan timeout");
                if (IsExactAt(screen, template, x, y))
                    return MatchResult.Hit(x, y, 1.0, "exact match");
            }
        }

        return MatchResult.Miss("not found");
    }

    private static bool IsExactAt(Bitmap screen, Bitmap template, int x, int y)
    {
        for (int ty = 0; ty < template.Height; ty += 2)
        {
            for (int tx = 0; tx < template.Width; tx += 2)
            {
                if (Distance(screen.GetPixel(x + tx, y + ty), template.GetPixel(tx, ty)) > 8)
                    return false;
            }
        }
        return true;
    }

    private static MatchResult FindSimilar(Bitmap screen, Bitmap template, Rectangle roi, double threshold, DateTime deadline)
    {
        int maxX = roi.Right - template.Width;
        int maxY = roi.Bottom - template.Height;
        if (maxX < roi.Left || maxY < roi.Top)
            return MatchResult.Miss("template larger than search area");

        int step = template.Width * template.Height > 2400 ? 3 : 2;
        double bestScore = 0;
        int bestX = 0, bestY = 0;

        for (int y = roi.Top; y <= maxY; y += 2)
        {
            for (int x = roi.Left; x <= maxX; x += 2)
            {
                if (DateTime.UtcNow > deadline)
                    return MatchResult.Miss($"image scan timeout; best={bestScore:0.000}");

                double score = ScoreAt(screen, template, x, y, step);
                if (score > bestScore)
                {
                    bestScore = score;
                    bestX = x;
                    bestY = y;
                    if (bestScore >= threshold)
                        return MatchResult.Hit(bestX, bestY, bestScore, "similar match");
                }
            }
        }

        return MatchResult.Miss($"not found; best={bestScore:0.000}", bestScore);
    }

    private static double ScoreAt(Bitmap screen, Bitmap template, int x, int y, int step)
    {
        double diff = 0;
        int count = 0;
        for (int ty = 0; ty < template.Height; ty += step)
        {
            for (int tx = 0; tx < template.Width; tx += step)
            {
                diff += Distance(screen.GetPixel(x + tx, y + ty), template.GetPixel(tx, ty));
                count++;
            }
        }
        double avg = diff / Math.Max(1, count);
        return Math.Clamp(1.0 - avg / 255.0, 0.0, 1.0);
    }

    private static double Distance(Color a, Color b)
    {
        int dr = a.R - b.R;
        int dg = a.G - b.G;
        int db = a.B - b.B;
        return Math.Sqrt((dr * dr + dg * dg + db * db) / 3.0);
    }

    private static object Fail(string msg) => new { ok = false, msg };

    private static string? GetString(JsonElement d, string name)
        => d.TryGetProperty(name, out var v) && v.ValueKind == JsonValueKind.String ? v.GetString() : null;

    private static int GetInt(JsonElement d, string name, int fallback)
        => d.TryGetProperty(name, out var v) && v.TryGetInt32(out var i) ? i : fallback;

    private static double GetDouble(JsonElement d, string name, double fallback)
        => d.TryGetProperty(name, out var v) && v.TryGetDouble(out var i) ? i : fallback;

    private readonly record struct MatchResult(bool Ok, int X, int Y, double Score, string Message)
    {
        public static MatchResult Hit(int x, int y, double score, string msg) => new(true, x, y, score, msg);
        public static MatchResult Miss(string msg, double score = 0) => new(false, 0, 0, score, msg);
    }
}

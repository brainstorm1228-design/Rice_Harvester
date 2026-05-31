using System.Text.Json.Serialization;
using System.Text.Json;

namespace Agent.Models;

public record HidCommand
{
    [JsonPropertyName("type")]
    public string Type { get; init; } = "";   // "keyboard" | "mouse"

    [JsonPropertyName("action")]
    public string Action { get; init; } = ""; // "press" | "release" | "move" | "down" | "up" | "scroll"

    [JsonPropertyName("keyboard")]
    public KeyboardData? Keyboard { get; init; }

    [JsonPropertyName("mouse")]
    public MouseData? Mouse { get; init; }

    [JsonPropertyName("ts")]
    public long Timestamp { get; init; }

    [JsonPropertyName("requestId")]
    public string? RequestId { get; init; }

    [JsonPropertyName("data")]
    public JsonElement? Data { get; init; }
}

public record KeyboardData
{
    [JsonPropertyName("keyCode")]
    public byte KeyCode { get; init; }

    [JsonPropertyName("modifiers")]
    public string[] Modifiers { get; init; } = [];

    [JsonPropertyName("text")]
    public string? Text { get; init; }
}

public record MouseData
{
    [JsonPropertyName("x")]
    public int X { get; init; }

    [JsonPropertyName("y")]
    public int Y { get; init; }

    [JsonPropertyName("absolute")]
    public bool Absolute { get; init; } = true;

    [JsonPropertyName("button")]
    public string Button { get; init; } = "left";

    [JsonPropertyName("scrollDelta")]
    public int ScrollDelta { get; init; }
}

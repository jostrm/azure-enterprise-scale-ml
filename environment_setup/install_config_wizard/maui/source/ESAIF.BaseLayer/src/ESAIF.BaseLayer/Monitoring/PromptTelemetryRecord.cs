using System.Text.Json.Serialization;

namespace ESAIF.BaseLayer.Monitoring;

public sealed record PromptTelemetryRecord
{
    [JsonPropertyName("operation_id")]
    public string OperationId { get; init; } = string.Empty;

    [JsonPropertyName("conversation_id")]
    public string? ConversationId { get; init; }

    [JsonPropertyName("response_id")]
    public string? ResponseId { get; init; }

    public string Timestamp { get; init; } = string.Empty;

    [JsonPropertyName("project_number")]
    public string? ProjectNumber { get; init; }

    public string? Environment { get; init; }

    public string? Region { get; init; }

    public string Model { get; init; } = string.Empty;

    public string Category { get; init; } = string.Empty;

    public string Prompt { get; init; } = string.Empty;

    public string Response { get; init; } = string.Empty;

    [JsonPropertyName("input_tokens")]
    [JsonNumberHandling(JsonNumberHandling.AllowReadingFromString)]
    public long InputTokens { get; init; }

    [JsonPropertyName("cached_input_tokens")]
    [JsonNumberHandling(JsonNumberHandling.AllowReadingFromString)]
    public long CachedInputTokens { get; init; }

    [JsonPropertyName("output_tokens")]
    [JsonNumberHandling(JsonNumberHandling.AllowReadingFromString)]
    public long OutputTokens { get; init; }

    [JsonPropertyName("total_tokens")]
    [JsonNumberHandling(JsonNumberHandling.AllowReadingFromString)]
    public long TotalTokens { get; init; }

    [JsonPropertyName("latency_ms")]
    [JsonNumberHandling(JsonNumberHandling.AllowReadingFromString)]
    public double? LatencyMilliseconds { get; init; }

    public bool Success { get; init; } = true;

    [JsonPropertyName("error_type")]
    public string? ErrorType { get; init; }

    public string Source { get; init; } = string.Empty;
}

public sealed record TokenUsageSummary
{
    public int RequestCount { get; init; }

    public int SuccessCount { get; init; }

    public int ErrorCount { get; init; }

    public long InputTokens { get; init; }

    public long CachedInputTokens { get; init; }

    public long OutputTokens { get; init; }

    public long TotalTokens { get; init; }

    public double SuccessRate { get; init; }

    public double AverageLatencyMilliseconds { get; init; }
}

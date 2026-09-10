using System.Text.Json.Serialization;

namespace ESAIF.DomainLayer.Operations;

public sealed record RegionPipelineFinding
{
    public string Id { get; init; } = string.Empty;
    public string Kind { get; init; } = string.Empty;
    public string Service { get; init; } = string.Empty;
    public IReadOnlyList<string> Skus { get; init; } = [];
    public string Message { get; init; } = string.Empty;
    public string Source { get; init; } = string.Empty;
    [JsonPropertyName("run_id")]
    public string? RunId { get; init; }
    [JsonPropertyName("run_url")]
    public string? RunUrl { get; init; }
    [JsonPropertyName("observed_at")]
    public string? ObservedAt { get; init; }
    [JsonPropertyName("recorded_at")]
    public string RecordedAt { get; init; } = string.Empty;
    public string Environment { get; init; } = string.Empty;
    public string Status { get; init; } = string.Empty;
}

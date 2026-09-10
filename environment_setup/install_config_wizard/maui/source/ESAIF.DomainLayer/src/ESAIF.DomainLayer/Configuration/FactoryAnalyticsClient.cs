using System.Text.Json.Serialization;

namespace ESAIF.DomainLayer.Configuration;

public interface IFactoryAnalyticsClient
{
    Task<FactoryAnalytics> GetCurrentFactoryAnalyticsAsync(
        string aiFactoryFolder, CancellationToken cancellationToken = default);
}

public sealed record FactoryAnalytics
{
    public string Title { get; init; } = "Current AI Factory";
    public string Source { get; init; } = "Unknown";
    [JsonPropertyName("generated_at")]
    public string GeneratedAt { get; init; } = string.Empty;
    public string? Warning { get; init; }
    public IReadOnlyList<FactoryAnalyticsSection> Sections { get; init; } = [];
}

public sealed record FactoryAnalyticsSection
{
    public string Title { get; init; } = string.Empty;
    public string Description { get; init; } = string.Empty;
    public IReadOnlyList<string> Columns { get; init; } = [];
    public IReadOnlyList<IReadOnlyList<string>> Rows { get; init; } = [];
    public string Source { get; init; } = "Unknown";
}

public sealed partial class AiFactoryApiClient : IFactoryAnalyticsClient
{
    public Task<FactoryAnalytics> GetCurrentFactoryAnalyticsAsync(
        string aiFactoryFolder, CancellationToken cancellationToken = default)
    {
        ValidateFolder(aiFactoryFolder);
        return SendAsync<FactoryAnalytics>(HttpMethod.Post, "/api/v1/analytics/current-factory",
            new { aifactory_folder = aiFactoryFolder }, true, cancellationToken);
    }
}

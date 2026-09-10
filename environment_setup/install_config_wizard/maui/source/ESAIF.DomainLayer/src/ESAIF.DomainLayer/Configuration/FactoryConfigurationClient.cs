using System.Text.Json.Nodes;
using System.Text.Json.Serialization;

namespace ESAIF.DomainLayer.Configuration;

public interface IFactoryConfigurationClient
{
    Task<FactoryConfigurationPreparation> PrepareFactoryConfigurationAsync(
        string kind, string targetRegion, string? sourceFolder = null,
        CancellationToken cancellationToken = default);

    Task<FactoryConfigurationSaveResult> SaveFactoryConfigurationAsync(
        string kind, string targetRegion, string? sourceFolder, string destinationFolder,
        JsonObject state, CancellationToken cancellationToken = default);
}

public sealed record FactoryConfigurationPreparation
{
    public JsonObject State { get; init; } = [];
    [JsonPropertyName("field_keys")]
    public IReadOnlyList<string> FieldKeys { get; init; } = [];
    public string Message { get; init; } = string.Empty;
}

public sealed record FactoryConfigurationSaveResult
{
    public JsonObject State { get; init; } = [];
    public string Path { get; init; } = string.Empty;
    public string Message { get; init; } = string.Empty;
}

public sealed partial class AiFactoryApiClient
{
    public Task<FactoryConfigurationPreparation> PrepareFactoryConfigurationAsync(
        string kind, string targetRegion, string? sourceFolder = null,
        CancellationToken cancellationToken = default)
    {
        ValidateConfigurationRequest(kind, targetRegion, sourceFolder);
        return SendAsync<FactoryConfigurationPreparation>(
            HttpMethod.Post, "/api/v1/factories/configuration/prepare",
            new { kind, target_region = targetRegion, source_folder = sourceFolder },
            true, cancellationToken);
    }

    public Task<FactoryConfigurationSaveResult> SaveFactoryConfigurationAsync(
        string kind, string targetRegion, string? sourceFolder, string destinationFolder,
        JsonObject state, CancellationToken cancellationToken = default)
    {
        ValidateConfigurationRequest(kind, targetRegion, sourceFolder);
        ValidateFolder(destinationFolder);
        ArgumentNullException.ThrowIfNull(state);
        return SendAsync<FactoryConfigurationSaveResult>(
            HttpMethod.Post, "/api/v1/factories/configuration/save",
            new { kind, target_region = targetRegion, source_folder = sourceFolder,
                destination_folder = destinationFolder, state },
            true, cancellationToken);
    }

    private static void ValidateConfigurationRequest(string kind, string region, string? sourceFolder)
    {
        if (kind is not ("factory" or "scale-set" or "clone"))
        {
            throw new ArgumentOutOfRangeException(nameof(kind), "Unknown configuration workflow.");
        }
        ArgumentException.ThrowIfNullOrWhiteSpace(region);
        if (kind != "factory")
        {
            ArgumentException.ThrowIfNullOrWhiteSpace(sourceFolder);
        }
    }
}

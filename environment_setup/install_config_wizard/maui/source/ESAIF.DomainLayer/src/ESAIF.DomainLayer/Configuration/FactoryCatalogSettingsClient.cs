using System.Text.Json.Nodes;
using System.Text.Json.Serialization;

namespace ESAIF.DomainLayer.Configuration;

public interface IFactoryCatalogSettingsClient
{
    Task<FactoryCatalogSettings> GetFactoryCatalogSettingsAsync(string folder, string factoryId,
        string? scaleSetId = null, string? projectId = null, CancellationToken cancellationToken = default);
}

public sealed record FactoryCatalogSettings
{
    [JsonPropertyName("contract_version")]
    public int ContractVersion { get; init; }
    public string Revision { get; init; } = string.Empty;
    [JsonPropertyName("factory_id")]
    public string FactoryId { get; init; } = string.Empty;
    [JsonPropertyName("scale_set_id")]
    public string? ScaleSetId { get; init; }
    [JsonPropertyName("project_id")]
    public string? ProjectId { get; init; }
    public JsonObject State { get; init; } = [];
    [JsonPropertyName("field_keys")]
    public IReadOnlyList<string> FieldKeys { get; init; } = [];
    public string Message { get; init; } = string.Empty;
}

public sealed partial class AiFactoryApiClient : IFactoryCatalogSettingsClient
{
    public async Task<FactoryCatalogSettings> GetFactoryCatalogSettingsAsync(string folder, string factoryId,
        string? scaleSetId = null, string? projectId = null, CancellationToken cancellationToken = default)
    {
        ArgumentException.ThrowIfNullOrWhiteSpace(folder);
        ArgumentException.ThrowIfNullOrWhiteSpace(factoryId);
        var path = $"{FactoryCatalogPath}/settings?folder={Uri.EscapeDataString(folder)}&factory_id={Uri.EscapeDataString(factoryId)}";
        if (scaleSetId is not null) path += "&scale_set_id=" + Uri.EscapeDataString(scaleSetId);
        if (projectId is not null) path += "&project_id=" + Uri.EscapeDataString(projectId);
        var result = await SendAsync<FactoryCatalogSettings>(HttpMethod.Get, path, null, true, cancellationToken).ConfigureAwait(false);
        RequireCatalogContract(result.ContractVersion);
        if (result.FactoryId != factoryId || result.ScaleSetId != scaleSetId || result.ProjectId != projectId ||
            string.IsNullOrWhiteSpace(result.Revision) || result.FieldKeys.Any(key => !result.State.ContainsKey(key)) ||
            result.FieldKeys.Distinct(StringComparer.Ordinal).Count() != result.FieldKeys.Count)
            throw new InvalidDataException("The API returned incomplete settings or a different catalog scope.");
        return result;
    }
}

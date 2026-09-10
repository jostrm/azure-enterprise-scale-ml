using System.Text.Json.Serialization;

namespace ESAIF.DomainLayer.Configuration;

public interface IScaleSetConfigurationClient
{
    Task<ScaleSetConfigurationDeleteResult> DeleteScaleSetConfigurationAsync(
        string aiFactoryFolder, string scaleSetId, string path, CancellationToken cancellationToken = default);
}

public sealed record ScaleSetConfigurationDeleteResult
{
    [JsonPropertyName("deleted_path")]
    public string DeletedPath { get; init; } = string.Empty;
    public string Message { get; init; } = string.Empty;
}

public sealed partial class AiFactoryApiClient : IScaleSetConfigurationClient
{
    public Task<ScaleSetConfigurationDeleteResult> DeleteScaleSetConfigurationAsync(
        string aiFactoryFolder, string scaleSetId, string path, CancellationToken cancellationToken = default)
    {
        ValidateFolder(aiFactoryFolder);
        ArgumentException.ThrowIfNullOrWhiteSpace(scaleSetId);
        ArgumentException.ThrowIfNullOrWhiteSpace(path);
        return SendAsync<ScaleSetConfigurationDeleteResult>(HttpMethod.Post, "/api/v1/scale-sets/delete",
            new { aifactory_folder = aiFactoryFolder, scale_set_id = scaleSetId, path },
            true, cancellationToken);
    }
}

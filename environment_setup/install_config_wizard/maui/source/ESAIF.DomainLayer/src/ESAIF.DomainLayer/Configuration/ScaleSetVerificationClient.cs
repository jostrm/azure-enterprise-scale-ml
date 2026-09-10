using System.Text.Json.Serialization;

namespace ESAIF.DomainLayer.Configuration;

public interface IScaleSetVerificationClient
{
    Task<ScaleSetResourceGroupVerification> VerifyScaleSetResourceGroupsAsync(
        string aiFactoryFolder, string scaleSetId, string path, CancellationToken cancellationToken = default);
}

public sealed record ResourceGroupHttpCheck
{
    [JsonPropertyName("resource_id")]
    public string ResourceId { get; init; } = string.Empty;
    [JsonPropertyName("http_status")]
    public int? HttpStatus { get; init; }
    public bool Verified { get; init; }
    public string Message { get; init; } = string.Empty;
}

public sealed record ScaleSetResourceGroupVerification
{
    [JsonPropertyName("scale_set_id")]
    public string ScaleSetId { get; init; } = string.Empty;
    [JsonPropertyName("checked_at")]
    public string CheckedAt { get; init; } = string.Empty;
    public string Message { get; init; } = string.Empty;
    public IReadOnlyList<ResourceGroupHttpCheck> Checks { get; init; } = [];
}

public sealed partial class AiFactoryApiClient : IScaleSetVerificationClient
{
    public Task<ScaleSetResourceGroupVerification> VerifyScaleSetResourceGroupsAsync(
        string aiFactoryFolder, string scaleSetId, string path, CancellationToken cancellationToken = default)
    {
        ValidateFolder(aiFactoryFolder);
        ArgumentException.ThrowIfNullOrWhiteSpace(scaleSetId);
        ArgumentException.ThrowIfNullOrWhiteSpace(path);
        return SendAsync<ScaleSetResourceGroupVerification>(HttpMethod.Post, "/api/v1/scale-sets/verify-resource-groups",
            new { aifactory_folder = aiFactoryFolder, scale_set_id = scaleSetId, path }, true, cancellationToken);
    }
}

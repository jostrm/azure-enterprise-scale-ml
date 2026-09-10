using System.Text.Json.Serialization;

namespace ESAIF.DomainLayer.Configuration;

public interface IProjectVerificationClient
{
    Task<ProjectResourceGroupVerification> VerifyProjectResourceGroupsAsync(
        string aiFactoryFolder, string projectNumber, string path, CancellationToken cancellationToken = default);
}

public sealed record ProjectResourceGroupVerification
{
    [JsonPropertyName("project_number")]
    public string ProjectNumber { get; init; } = string.Empty;
    [JsonPropertyName("checked_at")]
    public string CheckedAt { get; init; } = string.Empty;
    public string Message { get; init; } = string.Empty;
    public IReadOnlyList<ResourceGroupHttpCheck> Checks { get; init; } = [];
}

public sealed partial class AiFactoryApiClient : IProjectVerificationClient
{
    public Task<ProjectResourceGroupVerification> VerifyProjectResourceGroupsAsync(
        string aiFactoryFolder, string projectNumber, string path, CancellationToken cancellationToken = default)
    {
        ValidateFolder(aiFactoryFolder);
        ArgumentException.ThrowIfNullOrWhiteSpace(projectNumber);
        ArgumentException.ThrowIfNullOrWhiteSpace(path);
        return SendAsync<ProjectResourceGroupVerification>(HttpMethod.Post, "/api/v1/projects/verify-resource-groups",
            new { aifactory_folder = aiFactoryFolder, project_number = projectNumber, path }, true, cancellationToken);
    }
}

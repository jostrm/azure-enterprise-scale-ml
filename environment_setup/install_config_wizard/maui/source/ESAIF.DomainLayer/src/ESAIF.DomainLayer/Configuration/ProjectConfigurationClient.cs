using System.Text.Json.Serialization;

namespace ESAIF.DomainLayer.Configuration;

public interface IProjectConfigurationClient
{
    Task<ProjectConfigurationDeleteResult> DeleteProjectConfigurationAsync(
        string aiFactoryFolder, string projectNumber, string path, CancellationToken cancellationToken = default);
}

public sealed record ProjectConfigurationDeleteResult
{
    [JsonPropertyName("deleted_path")]
    public string DeletedPath { get; init; } = string.Empty;
    public string Message { get; init; } = string.Empty;
}

public sealed partial class AiFactoryApiClient : IProjectConfigurationClient
{
    public Task<ProjectConfigurationDeleteResult> DeleteProjectConfigurationAsync(
        string aiFactoryFolder, string projectNumber, string path, CancellationToken cancellationToken = default)
    {
        ValidateFolder(aiFactoryFolder);
        ArgumentException.ThrowIfNullOrWhiteSpace(projectNumber);
        ArgumentException.ThrowIfNullOrWhiteSpace(path);
        return SendAsync<ProjectConfigurationDeleteResult>(HttpMethod.Post, "/api/v1/projects/delete",
            new { aifactory_folder = aiFactoryFolder, project_number = projectNumber, path },
            true, cancellationToken);
    }
}

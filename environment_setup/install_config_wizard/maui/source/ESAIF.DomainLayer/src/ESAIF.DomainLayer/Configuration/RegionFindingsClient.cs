namespace ESAIF.DomainLayer.Configuration;

public interface IRegionFindingsClient
{
    Task<RegionFindingsImportResult> ImportRegionFindingsAsync(
        string aiFactoryFolder, string content, CancellationToken cancellationToken = default);
}

public sealed record RegionFindingsImportResult
{
    public int Recorded { get; init; }
    public string Message { get; init; } = string.Empty;
}

public sealed partial class AiFactoryApiClient : IRegionFindingsClient
{
    public Task<RegionFindingsImportResult> ImportRegionFindingsAsync(
        string aiFactoryFolder, string content, CancellationToken cancellationToken = default)
    {
        ValidateFolder(aiFactoryFolder);
        ArgumentException.ThrowIfNullOrWhiteSpace(content);
        return SendAsync<RegionFindingsImportResult>(HttpMethod.Post,
            "/api/v1/operations/region-findings/import",
            new { aifactory_folder = aiFactoryFolder, content }, true, cancellationToken);
    }
}

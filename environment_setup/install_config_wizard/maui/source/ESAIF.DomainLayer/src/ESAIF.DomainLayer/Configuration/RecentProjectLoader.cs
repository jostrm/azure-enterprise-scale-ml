using System.Net;
using ESAIF.BaseLayer.Networking;

namespace ESAIF.DomainLayer.Configuration;

public sealed class RecentProjectLoader : IRecentProjectLoader
{
    private readonly IAiFactoryApiClient _apiClient;

    public RecentProjectLoader(IAiFactoryApiClient apiClient)
    {
        _apiClient = apiClient;
    }

    public async Task<RecentProjectLoadResult> LoadAsync(
        RecentProject project,
        CancellationToken cancellationToken = default)
    {
        ArgumentNullException.ThrowIfNull(project);

        try
        {
            var snapshot = await _apiClient.LoadProjectAsync(
                project.Folder,
                project.Project,
                cancellationToken);
            return new RecentProjectLoadResult(
                snapshot.State,
                snapshot.Path,
                FieldsLoaded: 0,
                LoadedSnapshot: true);
        }
        catch (ApiRequestException exception)
            when (exception.StatusCode == HttpStatusCode.NotFound)
        {
            var startup = await _apiClient.LoadStartupAsync(
                project.Folder,
                project.Project,
                cancellationToken);
            return new RecentProjectLoadResult(
                startup.State,
                startup.SourcePath,
                startup.FieldsLoaded,
                LoadedSnapshot: false);
        }
    }
}

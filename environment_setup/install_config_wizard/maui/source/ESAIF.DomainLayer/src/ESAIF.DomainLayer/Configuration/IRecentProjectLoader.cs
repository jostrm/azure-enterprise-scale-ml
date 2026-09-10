using System.Text.Json.Nodes;

namespace ESAIF.DomainLayer.Configuration;

public interface IRecentProjectLoader
{
    Task<RecentProjectLoadResult> LoadAsync(
        RecentProject project,
        CancellationToken cancellationToken = default);
}

public sealed record RecentProjectLoadResult(
    JsonObject State,
    string? SourcePath,
    int FieldsLoaded,
    bool LoadedSnapshot);

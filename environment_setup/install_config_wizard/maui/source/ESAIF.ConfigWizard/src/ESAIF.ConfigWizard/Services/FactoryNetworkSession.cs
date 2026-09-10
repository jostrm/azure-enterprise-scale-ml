using System.Text.Json;
using ESAIF.ConfigWizard.ViewModels;
using ESAIF.DomainLayer.Configuration;
using ESAIF.DomainLayer.Operations;

namespace ESAIF.ConfigWizard.Services;

public sealed record FactoryNetworkSnapshot(
    string Folder, OperationsOverview? Overview, IReadOnlyList<SavedConfigurationItemViewModel> Projects,
    IReadOnlyList<SavedConfigurationItemViewModel> ScaleSets, string Error);

public sealed class FactoryNetworkSession(
    IAiFactoryApiClient api, IProjectVerificationClient projectVerifier, IScaleSetVerificationClient scaleVerifier)
{
    private readonly Dictionary<string, FactoryNetworkSnapshot> _snapshots = new(StringComparer.OrdinalIgnoreCase);
    private readonly HashSet<string> _knownFolders = new(StringComparer.OrdinalIgnoreCase);
    private readonly SemaphoreSlim _loadLock = new(1, 1);
    private Task? _refreshTask;
    public event EventHandler? Changed;
    public IReadOnlyList<FactoryNetworkSnapshot> Snapshots => _snapshots.Values.ToArray();
    public bool IsRefreshing => _refreshTask is { IsCompleted: false };
    public string DiscoveryError { get; private set; } = string.Empty;
    public IReadOnlyList<AzureRegionInfo> Regions => AggregateRegions(Snapshots);
    public IReadOnlyList<string> KnownFolders => _knownFolders.Order(StringComparer.OrdinalIgnoreCase).ToArray();
    public IReadOnlyList<string> LastRefreshFolders { get; private set; } = [];
    public string Warning => string.Join("\n\n", new[] { DiscoveryError }.Concat(
        Snapshots.Where(snapshot => snapshot.Error.Length > 0).Select(snapshot => $"{snapshot.Folder}\n{snapshot.Error}"))
        .Where(message => message.Length > 0));

    public static string NormalizeFolder(string folder) => folder.Trim().Replace('/', '\\').TrimEnd('\\');
    public static bool SameFolder(string first, string second) =>
        NormalizeFolder(first).Equals(NormalizeFolder(second), StringComparison.OrdinalIgnoreCase);

    public FactoryNetworkSnapshot? Find(string folder) => _snapshots.GetValueOrDefault(NormalizeFolder(folder));

    public void RememberFolder(string folder)
    {
        if (!string.IsNullOrWhiteSpace(folder))
        {
            _knownFolders.Add(NormalizeFolder(folder));
        }
    }

    public async Task<T> DeleteConfigurationAsync<T>(SavedConfigurationItemViewModel item, Func<Task<T>> delete)
    {
        await _loadLock.WaitAsync();
        try
        {
            var snapshot = Find(item.Folder);
            if (snapshot is null || !snapshot.Projects.Concat(snapshot.ScaleSets).Contains(item))
            {
                throw new InvalidOperationException("The saved configuration list changed. Select the configuration again.");
            }
            var result = await delete();
            _snapshots[NormalizeFolder(item.Folder)] = snapshot with
            {
                Projects = snapshot.Projects.Where(existing => !ReferenceEquals(existing, item)).ToArray(),
                ScaleSets = snapshot.ScaleSets.Where(existing => !ReferenceEquals(existing, item)).ToArray()
            };
            Changed?.Invoke(this, EventArgs.Empty);
            return result;
        }
        finally { _loadLock.Release(); }
    }

    public Task RefreshAsync(string currentFolder, Action<string>? progress = null)
    {
        if (_refreshTask is { IsCompleted: false })
        {
            return _refreshTask;
        }
        _refreshTask = RefreshCoreAsync(currentFolder, progress);
        return _refreshTask;
    }

    public async Task<IReadOnlyList<string>> DiscoverFoldersAsync(string currentFolder, CancellationToken cancellationToken = default)
    {
        DiscoveryError = string.Empty;
        RememberFolder(currentFolder);
        try
        {
            foreach (var recent in (await api.GetRecentProjectsAsync(cancellationToken)).RecentProjects)
            {
                if (recent.Orchestrator.ToLowerInvariant() is "ado" or "gha" && !string.IsNullOrWhiteSpace(recent.Folder))
                {
                    _knownFolders.Add(NormalizeFolder(recent.Folder));
                }
            }
        }
        catch (OperationCanceledException) when (cancellationToken.IsCancellationRequested) { throw; }
        catch (Exception error) when (IsExpectedFailure(error))
        {
            DiscoveryError = $"Could not list all recent ADO/GHA factories: {error.Message}";
        }
        return KnownFolders;
    }

    public async Task EnsureLoadedAsync(string currentFolder)
    {
        await _loadLock.WaitAsync();
        try
        {
            foreach (var folder in await DiscoverFoldersAsync(currentFolder))
            {
                if (!_snapshots.ContainsKey(folder))
                {
                    await LoadFolderAsync(folder, false);
                }
            }
        }
        finally { _loadLock.Release(); }
    }

    private async Task RefreshCoreAsync(string currentFolder, Action<string>? progress)
    {
        await Task.Yield();
        await _loadLock.WaitAsync();
        try
        {
            var folders = await DiscoverFoldersAsync(currentFolder);
            LastRefreshFolders = folders;
            if (folders.Count == 0)
            {
                throw new InvalidOperationException(DiscoveryError.Length > 0 ? DiscoveryError :
                    "No known factories. Load an ADO or GitHub project first.");
            }
            var index = 0;
            foreach (var folder in folders)
            {
                progress?.Invoke($"Refreshing factory {++index}/{folders.Count}: {folder}");
                await LoadFolderAsync(folder, true, () => progress?.Invoke(
                    $"Verifying project and common RG access {index}/{folders.Count}: {folder}"));
            }
        }
        finally { _loadLock.Release(); }
    }

    private async Task LoadFolderAsync(string folder, bool forceRefresh, Action? verifying = null)
    {
        var previous = Find(folder);
        var errors = new List<string>();
        OperationsOverview? overview = null;
        IReadOnlyList<SavedConfigurationItemViewModel> projects = previous?.Projects ?? [];
        IReadOnlyList<SavedConfigurationItemViewModel> scales = previous?.ScaleSets ?? [];
        try
        {
            // Non-refresh list navigation uses local data, never a new Azure collection.
            overview = await api.GetOperationsOverviewAsync(folder, forceRefresh, forceRefresh);
            if (!SameFolder(folder, overview.Factory.Folder))
            {
                throw new InvalidOperationException("The API returned inventory for a different factory folder.");
            }
        }
        catch (Exception error) when (IsExpectedFailure(error))
        {
            overview = null;
            errors.Add($"Inventory: {error.Message}");
        }
        try
        {
            projects = (await api.GetProjectsAsync(folder)).Projects
                .DistinctBy(project => project.ProjectNumber + "|" + NormalizeFolder(project.Path), StringComparer.OrdinalIgnoreCase)
                .Select(project => new SavedConfigurationItemViewModel(project, folder)).ToArray();
        }
        catch (Exception error) when (IsExpectedFailure(error)) { errors.Add($"Projects: {error.Message}"); }
        try
        {
            scales = (await api.GetScaleSetsAsync(folder)).ScaleSets
                .DistinctBy(scale => scale.ScaleSetId + "|" + NormalizeFolder(scale.Path), StringComparer.OrdinalIgnoreCase)
                .Select(scale => new SavedConfigurationItemViewModel(scale, folder)).ToArray();
        }
        catch (Exception error) when (IsExpectedFailure(error)) { errors.Add($"Scale sets: {error.Message}"); }
        var items = projects.Concat(scales).ToList();
        foreach (var item in items)
        {
            item.UpdateDeployment(overview);
        }
        if (forceRefresh && overview is not null)
        {
            verifying?.Invoke();
            await new SavedConfigurationVerifier(projectVerifier, scaleVerifier).VerifyAsync(items, () => folder);
        }
        _snapshots[folder] = new(folder, overview ?? previous?.Overview, projects, scales, string.Join("\n", errors));
        Changed?.Invoke(this, EventArgs.Empty);
    }

    private static bool IsExpectedFailure(Exception error) => error is
        HttpRequestException or IOException or JsonException or InvalidOperationException or ArgumentException or OperationCanceledException;

    public static IReadOnlyList<AzureRegionInfo> AggregateRegions(IEnumerable<FactoryNetworkSnapshot> snapshots)
    {
        var all = snapshots.ToArray();
        var available = all.Where(snapshot => snapshot.Overview is not null).ToArray();
        var unlocatedFailure = all.Any(snapshot => snapshot.Overview is null && snapshot.Error.Length > 0);
        var result = new List<AzureRegionInfo>();
        foreach (var group in available.SelectMany(snapshot => snapshot.Overview!.Regions
                     .Select(region => (Snapshot: snapshot, Region: region))).GroupBy(item => item.Region.Name, StringComparer.OrdinalIgnoreCase))
        {
            var scoped = group.Where(item =>
                item.Snapshot.Overview!.ResourceInventory.Source is "azure" or "cached" &&
                (item.Snapshot.Overview.Factory.MonitoringRegions.Contains(group.Key, StringComparer.OrdinalIgnoreCase) ||
                 item.Region.ResourceCount > 0))
                .GroupBy(item => item.Snapshot.Overview!.Factory.Orchestrator + "|" + string.Join("|",
                    item.Snapshot.Overview!.Factory.SubscriptionIds.Order(StringComparer.OrdinalIgnoreCase)) + "|" +
                    item.Snapshot.Overview.Factory.PrefixResourceGroup + "|" + item.Snapshot.Overview.Factory.SuffixResourceGroup,
                    StringComparer.OrdinalIgnoreCase)
                .Select(factory => factory.OrderByDescending(item => item.Snapshot.Overview!.GeneratedAt).First())
                .ToArray();
            var template = group.First().Region;
            var complete = !unlocatedFailure && scoped.Length > 0 && scoped.All(item => item.Region.CountStatus == "complete" &&
                item.Snapshot.Overview!.ResourceInventory is { Source: "azure", IsComplete: true } && item.Snapshot.Error.Length == 0);
            var factories = scoped.Sum(item => item.Region.HasFactory ? Math.Max(1, item.Region.FactoryCount) : 0);
            result.Add(template with
            {
                HasFactory = factories > 0 || group.Any(item => item.Region.HasFactory),
                FactoryCount = factories > 0 ? factories : group.Any(item => item.Region.HasFactory) ? 1 : 0,
                ProjectCount = scoped.Sum(item => item.Region.ProjectCount),
                ResourceCount = scoped.Sum(item => item.Region.ResourceCount),
                CountStatus = complete ? "complete" : scoped.Length > 0 ? "partial" : "out_of_scope",
                CountDetails = scoped.Length == 0
                    ? "No refreshed factory covers this region. Configured markers are not deployment evidence."
                    : string.Join("\n\n", scoped.Select(item =>
                        $"{item.Snapshot.Overview!.Factory.Name} ({item.Snapshot.Overview.Factory.Orchestrator})\n" +
                        $"{item.Snapshot.Folder}\n{item.Region.CountDetails}" +
                        (item.Snapshot.Error.Length > 0 ? $"\n{item.Snapshot.Error}" : ""))) +
                       (unlocatedFailure ? "\nOther known factories could not be located/refreshed; regional totals may be incomplete." : ""),
                PipelineFindings = group.SelectMany(item => item.Region.PipelineFindings).Distinct().ToArray()
            });
        }
        return result.OrderBy(region => region.DisplayName, StringComparer.OrdinalIgnoreCase).ToArray();
    }
}

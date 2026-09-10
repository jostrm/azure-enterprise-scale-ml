using System.Globalization;
using ESAIF.DomainLayer.Configuration;
using ESAIF.DomainLayer.Operations;

namespace ESAIF.ConfigWizard.Services;

public sealed record ProjectDeploymentStatus(bool IsDeployed, string Label, string Description)
{
    public string Color => IsDeployed ? "#409EFF" : "#8C929C";
}

public static class ProjectDeploymentPresentation
{
    public static ProjectDeploymentStatus FromOverview(ProjectSummary project, string folder, OperationsOverview? overview)
    {
        if (overview is null || !SameFolder(folder, overview.Factory.Folder))
        {
            return new(false, "Not checked", "Use Refresh Azure to check deployment status for this factory.");
        }
        var inventory = overview.ResourceInventory;
        if (inventory.Source is not ("azure" or "cached"))
        {
            return new(false, "Not checked", "Azure inventory is unavailable. Local configuration does not prove deployment.");
        }
        if (!MatchesActiveInventory(project.DeploymentScope, folder, overview))
        {
            return new(false, "Not checked", "This saved configuration is outside the active factory inventory scope.");
        }
        var matching = overview.Projects.Where(item => SameProject(item.ProjectNumber, project.ProjectNumber));
        var environments = matching.SelectMany(item => item.Environments)
            .Where(env => !string.IsNullOrWhiteSpace(env.ResourceGroup) ||
                          env.ResourceGroups.Any(name => !string.IsNullOrWhiteSpace(name)) ||
                          env.ResourceGroupReferences.Count > 0)
            .Select(env => env.Environment).Distinct(StringComparer.OrdinalIgnoreCase).ToArray();
        var timestamp = DateTimeOffset.TryParse(inventory.CollectedAt, CultureInfo.InvariantCulture,
            DateTimeStyles.AssumeUniversal, out var time)
            ? $" Snapshot: {time.ToLocalTime():yyyy-MM-dd HH:mm}." : string.Empty;
        var cached = inventory.Source == "cached" ? "cached " : string.Empty;
        if (environments.Length > 0)
        {
            return new(true, "Deployed",
                $"Project resource group found in {cached}Azure inventory ({string.Join(", ", environments)}). " +
                "This indicates deployed resources, not application health." + timestamp);
        }
        return inventory.IsComplete
            ? new(false, "Not deployed", $"No project resource group found in the current factory's {cached}Azure inventory." + timestamp)
            : new(false, "Not checked", "Inventory is incomplete; absence cannot establish that the project is not deployed.");
    }

    public static IReadOnlyList<ProjectResourceGroupLink> ResourceGroupLinks(
        ProjectSummary project, string folder, OperationsOverview? overview)
    {
        if (overview is null || !FromOverview(project, folder, overview).IsDeployed)
        {
            return [];
        }
        return overview.Projects
            .Where(item => SameProject(item.ProjectNumber, project.ProjectNumber))
            .SelectMany(item => item.Environments)
            .SelectMany(ProjectResourceGroupLink.FromEnvironment)
            .DistinctBy(link => link.Url.AbsoluteUri, StringComparer.OrdinalIgnoreCase)
            .ToArray();
    }

    public static IReadOnlyList<string> DeployedEnvironments(ProjectSummary project, string folder, OperationsOverview? overview)
    {
        if (!MatchesActiveInventory(project.DeploymentScope, folder, overview))
        {
            return [];
        }
        return overview!.Projects.Where(item => SameProject(item.ProjectNumber, project.ProjectNumber))
            .SelectMany(item => item.Environments)
            .Where(environment => !string.IsNullOrWhiteSpace(environment.ResourceGroup) ||
                environment.ResourceGroups.Count > 0 || environment.ResourceGroupReferences.Count > 0)
            .Select(environment => NormalizeEnvironment(environment.Environment))
            .Where(environment => environment.Length > 0).Distinct()
            .OrderBy(EnvironmentOrder).ToArray();
    }

    public static string NormalizeEnvironment(string environment) => environment.Trim().ToLowerInvariant() switch
    {
        "dev" or "development" => "Dev",
        "stage" or "test" or "staging" => "Stage",
        "prod" or "production" => "Prod",
        _ => string.Empty
    };

    public static int EnvironmentOrder(string environment) => environment switch { "Dev" => 0, "Stage" => 1, "Prod" => 2, _ => 3 };

    public static bool MatchesActiveInventory(ProjectDeploymentScope? scope, string folder, OperationsOverview? overview) =>
        scope is not null && overview is not null &&
        SameFolder(folder, overview.Factory.Folder) &&
        overview.ResourceInventory.Source is "azure" or "cached" &&
        SameIdentity(scope.PrefixResourceGroup, overview.Factory.PrefixResourceGroup) &&
        SameIdentity(scope.SuffixResourceGroup, overview.Factory.SuffixResourceGroup) &&
        overview.Factory.MonitoringRegions.Contains(scope.Region, StringComparer.OrdinalIgnoreCase) &&
        scope.SubscriptionIds.Count > 0 &&
        !scope.SubscriptionIds.Except(overview.ResourceInventory.Subscriptions, StringComparer.OrdinalIgnoreCase).Any();

    private static bool SameProject(string first, string second) =>
        string.Equals(first.Trim().TrimStart('0'), second.Trim().TrimStart('0'), StringComparison.OrdinalIgnoreCase);

    private static bool SameIdentity(string first, string second) =>
        !string.IsNullOrWhiteSpace(first) && !string.IsNullOrWhiteSpace(second) &&
        first.Trim().Trim('-', '_').Equals(second.Trim().Trim('-', '_'), StringComparison.OrdinalIgnoreCase);

    private static bool SameFolder(string first, string second) =>
        FactoryNetworkSession.SameFolder(first, second);
}

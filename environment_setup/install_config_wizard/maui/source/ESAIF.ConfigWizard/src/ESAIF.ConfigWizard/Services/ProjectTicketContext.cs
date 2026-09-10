using System.Text.Json.Nodes;
using ESAIF.ConfigWizard.ViewModels;
using ESAIF.DomainLayer.Configuration;
using ESAIF.DomainLayer.Operations;

namespace ESAIF.ConfigWizard.Services;

public sealed record ProjectTicketContext(
    string ProjectNumber, IReadOnlyList<ProjectResourceGroupLink> ResourceGroups)
{
    public static ProjectTicketContext FromProject(SavedConfigurationItemViewModel item,
        OperationsOverview? current, OperationsOverview? snapshot)
    {
        if (item.Project is not { } project)
            throw new InvalidOperationException("Select a saved project before opening a ticket draft.");
        var links = ProjectDeploymentPresentation.ResourceGroupLinks(project, item.Folder, current);
        if (links.Count == 0)
            links = ProjectDeploymentPresentation.ResourceGroupLinks(project, item.Folder, snapshot);
        if (links.Count == 0)
            links = item.ResourceGroupLinks;
        return new(project.ProjectNumber, Order(links));
    }

    public static ProjectTicketContext FromState(JsonObject state, OperationsOverview? current,
        OperationsOverview? snapshot)
    {
        var identity = WizardIdentity.FromState(state, Read(state, "_save_folder"));
        if (!identity.HasProject)
            throw new InvalidOperationException("Select or load a project before opening a ticket draft.");
        var project = new ProjectSummary
        {
            ProjectNumber = identity.ProjectNumber,
            DeploymentScope = new ProjectDeploymentScope
            {
                PrefixResourceGroup = Read(state, "admin_aifactoryPrefixRG"),
                SuffixResourceGroup = Read(state, "admin_aifactorySuffixRG"),
                Region = Read(state, "admin_location"),
                SubscriptionIds = new[] { "dev_sub_id", "test_sub_id", "prod_sub_id" }
                    .Select(key => Read(state, key)).Where(value => Guid.TryParse(value, out _))
                    .Distinct(StringComparer.OrdinalIgnoreCase).ToArray()
            }
        };
        var links = ProjectDeploymentPresentation.ResourceGroupLinks(project, identity.Folder, current);
        if (links.Count == 0)
            links = ProjectDeploymentPresentation.ResourceGroupLinks(project, identity.Folder, snapshot);
        return new(identity.ProjectNumber, Order(links));
    }

    private static IReadOnlyList<ProjectResourceGroupLink> Order(IEnumerable<ProjectResourceGroupLink> links) =>
        links.DistinctBy(link => link.ResourceId, StringComparer.OrdinalIgnoreCase)
            .OrderBy(link => ProjectDeploymentPresentation.EnvironmentOrder(link.Environment))
            .ThenBy(link => link.Name, StringComparer.OrdinalIgnoreCase)
            .ThenBy(link => link.SubscriptionId, StringComparer.OrdinalIgnoreCase).ToArray();

    private static string Read(JsonObject state, string key)
    {
        var value = state[key]?.ToString().Trim() ?? string.Empty;
        return value.Contains("<todo>", StringComparison.OrdinalIgnoreCase) ? string.Empty : value;
    }
}

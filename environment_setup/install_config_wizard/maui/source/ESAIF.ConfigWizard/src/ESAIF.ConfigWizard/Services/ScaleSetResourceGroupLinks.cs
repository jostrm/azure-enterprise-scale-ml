using ESAIF.DomainLayer.Configuration;
using ESAIF.DomainLayer.Operations;

namespace ESAIF.ConfigWizard.Services;

public static class ScaleSetResourceGroupLinks
{
    public static IReadOnlyList<ProjectResourceGroupLink> FromOverview(
        ScaleSetSummary scaleSet, string folder, OperationsOverview? overview)
    {
        if (scaleSet.DeploymentScope is not { } scope || overview is null ||
            !ProjectDeploymentPresentation.MatchesActiveInventory(scope, folder, overview) ||
            !scaleSet.ScaleSetId.Equals(scope.SuffixResourceGroup.Trim().TrimStart('-'), StringComparison.OrdinalIgnoreCase))
        {
            return [];
        }
        var references = new List<ProjectResourceGroupReference>();
        foreach (var common in overview.CommonResourceGroups)
        {
            // Older snapshots omit subscriptionId on common groups; recover it
            // only from a unique observed group in the same inventory.
            var group = common;
            if (string.IsNullOrWhiteSpace(group.SubscriptionId))
            {
                var candidates = overview.ResourceInventory.ResourceGroups
                    .Where(item => item.Name.Equals(common.Name, StringComparison.OrdinalIgnoreCase) &&
                                   scope.SubscriptionIds.Contains(item.SubscriptionId, StringComparer.OrdinalIgnoreCase))
                    .Take(2).ToArray();
                if (candidates.Length != 1)
                {
                    continue;
                }
                group = candidates[0];
            }
            if (!scope.SubscriptionIds.Contains(group.SubscriptionId, StringComparer.OrdinalIgnoreCase))
            {
                continue;
            }
            references.Add(new ProjectResourceGroupReference
            {
                Id = group.Id, Name = group.Name, SubscriptionId = group.SubscriptionId,
                TenantId = common.TenantId
            });
        }
        return ProjectResourceGroupLink.FromEnvironment(new ProjectEnvironment { ResourceGroupReferences = references });
    }
}

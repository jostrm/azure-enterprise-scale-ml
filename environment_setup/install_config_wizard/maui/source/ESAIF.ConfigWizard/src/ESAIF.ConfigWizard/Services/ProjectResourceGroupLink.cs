using ESAIF.DomainLayer.Operations;

namespace ESAIF.ConfigWizard.Services;

public sealed record ProjectResourceGroupLink(string Name, Uri Url, string SubscriptionId)
{
    public string Environment { get; init; } = string.Empty;
    public string ResourceId => $"/subscriptions/{SubscriptionId}/resourceGroups/{Name}";

    public static IReadOnlyList<ProjectResourceGroupLink> FromEnvironment(ProjectEnvironment environment)
    {
        // Use the observed group references, never generate a guessed RG for an undeployed environment.
        var legacyName = environment.ResourceGroup ??
            (environment.ResourceGroups.Count == 1 ? environment.ResourceGroups[0] : null);
        IReadOnlyList<ProjectResourceGroupReference> groups = environment.ResourceGroupReferences.Count > 0
            ? environment.ResourceGroupReferences
            : string.IsNullOrWhiteSpace(legacyName) ? [] :
            [new() { Name = legacyName, SubscriptionId = environment.SubscriptionId ?? string.Empty }];
        return groups.Select(Create).OfType<ProjectResourceGroupLink>()
            .Select(link => link with { Environment = ProjectDeploymentPresentation.NormalizeEnvironment(environment.Environment) })
            .DistinctBy(link => link.Url.AbsoluteUri, StringComparer.OrdinalIgnoreCase).ToArray();
    }

    private static ProjectResourceGroupLink? Create(ProjectResourceGroupReference group)
    {
        if (!Guid.TryParseExact(group.SubscriptionId, "D", out var subscription) ||
            string.IsNullOrWhiteSpace(group.Name) || group.Name.IndexOfAny(['/', '\\', '?', '#']) >= 0 ||
            group.Name.Any(char.IsControl) || group.Name.EndsWith('.'))
        {
            return null;
        }
        var id = $"/subscriptions/{subscription:D}/resourceGroups/{group.Name}";
        if (!string.IsNullOrWhiteSpace(group.Id) && !group.Id.TrimEnd('/').Equals(id, StringComparison.OrdinalIgnoreCase))
        {
            return null;
        }
        var tenant = Guid.TryParseExact(group.TenantId, "D", out var tenantId) ? $"@{tenantId:D}/" : string.Empty;
        var address = $"https://portal.azure.com/#{tenant}resource/subscriptions/{subscription:D}/resourceGroups/{Uri.EscapeDataString(group.Name)}/overview";
        return new ProjectResourceGroupLink(group.Name, new Uri(address), subscription.ToString("D"));
    }
}

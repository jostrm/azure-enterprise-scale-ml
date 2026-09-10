using ESAIF.ConfigWizard.ViewModels;

namespace ESAIF.ConfigWizard.Services;

public sealed record WizardFieldMatch(string SectionTitle, ConfigFieldViewModel Field);

public static class WizardFieldSearch
{
    public static IEnumerable<ConfigFieldViewModel> EditableCards(IEnumerable<ConfigFieldViewModel> fields)
    {
        var snapshot = fields.ToArray();
        var hasNetworkEditor = snapshot.Any(field => field.IsNetworkMode);
        var hasRunnerEditor = snapshot.Any(field => field.IsRunnerConfiguration);
        var hasHubEditor = snapshot.Any(field => field.IsHubTopology);
        return snapshot.Where(field => (!hasNetworkEditor || !field.IsNetworkFlag) &&
            (!hasRunnerEditor || !field.IsRunnerDetail) &&
            (!hasHubEditor || field.Key != HubTopologyViewModel.OwnHubKey));
    }

    public static IReadOnlyList<WizardFieldMatch> Find(IEnumerable<WizardStepViewModel> steps, string query)
    {
        var term = query.Trim();
        if (term.Length == 0)
        {
            return [];
        }
        var results = new List<WizardFieldMatch>();
        foreach (var step in steps)
        {
            var matchedFlags = step.Fields.Where(field => field.IsNetworkFlag && Matches(field, term)).Any();
            var matchedRunner = step.Fields.Any(field => field.IsRunnerDetail && Matches(field, term));
            foreach (var field in EditableCards(step.Fields))
            {
                if (Matches(field, term) || field.IsNetworkMode && matchedFlags ||
                    field.IsRunnerConfiguration && matchedRunner)
                {
                    results.Add(new WizardFieldMatch(step.Title, field));
                }
            }
        }
        return results;
    }

    private static bool Matches(ConfigFieldViewModel field, string query) =>
        field.Label.Contains(query, StringComparison.OrdinalIgnoreCase) ||
        field.Key.Contains(query, StringComparison.OrdinalIgnoreCase) ||
        field.IsScalingMode && "Own subscriptions per project Common subscriptions scale capacity".Contains(query, StringComparison.OrdinalIgnoreCase) ||
        field.IsHubTopology && ("Central DNS Zone By Policy In Hub".Contains(query, StringComparison.OrdinalIgnoreCase) ||
            HubTopologyViewModel.OwnHubKey.Contains(query, StringComparison.OrdinalIgnoreCase) ||
            "Enable AI Factory Hub".Contains(query, StringComparison.OrdinalIgnoreCase));
}

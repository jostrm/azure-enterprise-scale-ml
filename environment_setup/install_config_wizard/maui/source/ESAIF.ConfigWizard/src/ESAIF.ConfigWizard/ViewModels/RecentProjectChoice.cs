using ESAIF.DomainLayer.Configuration;
using ESAIF.ConfigWizard.Services;

namespace ESAIF.ConfigWizard.ViewModels;

public sealed record RecentProjectChoice(string Title, RecentProject Project)
{
    public string SelectionLabel { get; init; } = string.Empty;
    public static RecentProjectChoice Create(int position, RecentProject project)
    {
        var prefix = project.PrefixResourceGroup.Trim().TrimEnd('-');
        var suffix = project.SuffixResourceGroup.Trim().TrimStart('-');
        var identity = prefix.Length > 0 && suffix.Length > 0
            ? $" ({prefix}-{suffix})"
            : suffix.Length > 0
                ? $" ({suffix})"
                : string.Empty;
        var label = $"{position}. Project {project.Project}{identity}";
        return new RecentProjectChoice($"{label} - {project.Folder}", project)
        {
            SelectionLabel = TechnicalValuePresentation.Summary(label)
        };
    }
}

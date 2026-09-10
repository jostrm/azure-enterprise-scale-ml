using ESAIF.BaseLayer.Application;
using ESAIF.ConfigWizard.Services;
using ESAIF.DomainLayer.Configuration;
using ESAIF.DomainLayer.Operations;

namespace ESAIF.ConfigWizard.ViewModels;

public sealed class SavedConfigurationItemViewModel : ObservableObject
{
    private readonly string _folder;
    private bool _isSelected;
    private bool _isHighlighted;
    private ProjectDeploymentStatus _deployment = new(false, "Not checked", "Use Refresh Azure to check deployment.");

    public SavedConfigurationItemViewModel(ProjectSummary project, string folder)
    {
        Project = project;
        _folder = folder;
    }

    public SavedConfigurationItemViewModel(ScaleSetSummary scaleSet, string folder)
    {
        ScaleSet = scaleSet;
        _folder = folder;
    }

    public ProjectSummary? Project { get; }
    public ScaleSetSummary? ScaleSet { get; }
    public string Label => Project?.Label ?? ScaleSet?.ScaleSetId ?? string.Empty;
    public string Path => Project?.Path ?? ScaleSet?.Path ?? string.Empty;
    public bool IsSelected { get => _isSelected; private set => SetProperty(ref _isSelected, value); }
    public bool IsHighlighted { get => _isHighlighted; private set => SetProperty(ref _isHighlighted, value); }
    public void SetHighlight(bool highlighted) => IsHighlighted = highlighted;
    public string Folder => _folder;
    public string Owner => string.IsNullOrWhiteSpace(Project?.Owner) ? "Not specified" : Project.Owner;
    public string FactoryScaleSet
    {
        get
        {
            var scope = Project?.DeploymentScope;
            var label = scope is null ? "" : string.Join("-",
                new[] { scope.PrefixResourceGroup.Trim('-', '_'), scope.SuffixResourceGroup.Trim('-', '_') }
                    .Where(value => !string.IsNullOrWhiteSpace(value)));
            return label.Length == 0 ? "Unknown factory" : label;
        }
    }
    public IReadOnlyList<string> DeployedEnvironments { get; private set; } = [];
    public IReadOnlyList<string> PlannedEnvironments => (Project?.PlannedEnvironments ?? [])
        .Select(ProjectDeploymentPresentation.NormalizeEnvironment).Where(value => value.Length > 0)
        .Distinct().OrderBy(ProjectDeploymentPresentation.EnvironmentOrder).ToArray();
    public string EnvironmentStatus => DeployedEnvironments.Count > 0
        ? string.Join(" · ", DeployedEnvironments)
        : PlannedEnvironments.Count > 0 ? $"Planned: {string.Join(" · ", PlannedEnvironments)}" : "Not checked";
    public bool MatchesEnvironment(string environment) => environment == "All" ||
        (DeployedEnvironments.Count > 0 ? DeployedEnvironments : PlannedEnvironments).Contains(environment);
    public bool IsDeployed => _deployment.IsDeployed;
    public string DeploymentLabel => _deployment.Label;
    public string DeploymentColor => _deployment.Color;
    public string DeploymentDescription => _deployment.Description;
    public IReadOnlyList<ProjectResourceGroupLink> ResourceGroupLinks { get; private set; } = [];
    public bool HasResourceGroupLink => ResourceGroupLinks.Count > 0;
    public string ResourceGroupLinkHint => HasResourceGroupLink
        ? $"Open the observed {(ScaleSet is null ? "project" : "scale-set common")} resource group in Azure Portal."
        : $"No {(ScaleSet is null ? "project" : "matching scale-set common")} resource group is available in the active factory inventory. Use Refresh Azure to check.";
    public bool IsResourceGroupVerified { get; private set; }
    public string VerificationLabel { get; private set; } = "Not checked";
    public string VerificationDetails { get; private set; } = "Resource group access has not been verified.";
    public string VerificationColor => IsResourceGroupVerified ? "#409EFF" : "#555C66";
    public bool IsVerificationComplete => IsResourceGroupVerified || VerificationLabel == "Not deployed";

    public void SetVerificationPending()
    {
        SetVerification(false, "Checking RG...", "Checking the actual resource group through Azure Resource Manager.");
    }

    public void SetVerificationUnavailable(string message) =>
        SetVerification(false, DeploymentLabel == "Not deployed" ? "Not deployed" : "Not verified", message);

    public void ApplyVerification(ScaleSetResourceGroupVerification result) =>
        ApplyVerification(ScaleSet is not null && result.ScaleSetId == ScaleSet.ScaleSetId,
            result.CheckedAt, result.Message, result.Checks);

    public void ApplyVerification(ProjectResourceGroupVerification result) =>
        ApplyVerification(Project is not null && result.ProjectNumber == Project.ProjectNumber,
            result.CheckedAt, result.Message, result.Checks);

    private void ApplyVerification(bool identityMatches, string checkedAt, string message, IReadOnlyList<ResourceGroupHttpCheck> checks)
    {
        var expectedIds = ResourceGroupLinks.Select(link => link.ResourceId.TrimEnd('/'))
            .ToHashSet(StringComparer.OrdinalIgnoreCase);
        var actualIds = checks.Select(check => check.ResourceId.TrimEnd('/'))
            .ToHashSet(StringComparer.OrdinalIgnoreCase);
        var verified = identityMatches &&
            expectedIds.Count > 0 && expectedIds.SetEquals(actualIds) &&
            checks.All(check => check.HttpStatus == 200 && check.Verified);
        var description = message + $"\nChecked: {checkedAt}" +
            string.Concat(checks.Select(check =>
                $"\n{check.ResourceId}: {(check.HttpStatus is { } status ? $"HTTP {status}" : "No HTTP response")} - {check.Message}"));
        SetVerification(verified, verified ? "Accessible" : "Not verified", description);
    }

    private void SetVerification(bool verified, string label, string description)
    {
        IsResourceGroupVerified = verified;
        VerificationLabel = label;
        VerificationDetails = description;
        OnPropertyChanged(nameof(IsResourceGroupVerified));
        OnPropertyChanged(nameof(VerificationLabel));
        OnPropertyChanged(nameof(VerificationDetails));
        OnPropertyChanged(nameof(VerificationColor));
        OnPropertyChanged(nameof(IsVerificationComplete));
    }

    public void UpdateDeployment(OperationsOverview? overview)
    {
        if (Project is not null)
        {
            _deployment = ProjectDeploymentPresentation.FromOverview(Project, _folder, overview);
            ResourceGroupLinks = ProjectDeploymentPresentation.ResourceGroupLinks(Project, _folder, overview);
            DeployedEnvironments = ProjectDeploymentPresentation.DeployedEnvironments(Project, _folder, overview);
            OnPropertyChanged(nameof(DeployedEnvironments));
            OnPropertyChanged(nameof(EnvironmentStatus));
            SetVerification(false, DeploymentLabel == "Not deployed" ? "Not deployed" : "Not checked", ResourceGroupLinkHint);
        }
        else if (ScaleSet is not null)
        {
            ResourceGroupLinks = ScaleSetResourceGroupLinks.FromOverview(ScaleSet, _folder, overview);
            var checkedAbsence = ResourceGroupLinks.Count == 0 && overview?.ResourceInventory.IsComplete == true &&
                ProjectDeploymentPresentation.MatchesActiveInventory(ScaleSet.DeploymentScope, _folder, overview) &&
                ScaleSet.ScaleSetId.Equals(ScaleSet.DeploymentScope!.SuffixResourceGroup.Trim().TrimStart('-'),
                    StringComparison.OrdinalIgnoreCase);
            _deployment = new(false, checkedAbsence ? "Not deployed" : "Not checked", ResourceGroupLinkHint);
            SetVerification(false, DeploymentLabel, ResourceGroupLinkHint);
        }
        OnPropertyChanged(nameof(IsDeployed));
        OnPropertyChanged(nameof(DeploymentLabel));
        OnPropertyChanged(nameof(DeploymentColor));
        OnPropertyChanged(nameof(DeploymentDescription));
        OnPropertyChanged(nameof(ResourceGroupLinks));
        OnPropertyChanged(nameof(HasResourceGroupLink));
        OnPropertyChanged(nameof(ResourceGroupLinkHint));
    }

    public void UpdateSelection(WizardIdentity identity) =>
        IsSelected = Project is not null
            ? identity.IsProjectSelected(_folder, Project.ProjectNumber)
            : ScaleSet is not null && identity.IsScaleSetSelected(_folder, ScaleSet.ScaleSetId);
}

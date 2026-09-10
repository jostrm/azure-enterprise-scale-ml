using ESAIF.BaseLayer.Application;
using ESAIF.DomainLayer.Operations;
using ESAIF.ConfigWizard.Services;
using ESAIF.DomainLayer.Configuration;

namespace ESAIF.ConfigWizard.ViewModels;

public sealed class ProjectEnvironmentCardViewModel : ObservableObject
{
    private bool _deleteAllForProject;
    private bool _deleteAllServices;
    private bool _showPlanningOptions;
    private bool _isSelected;
    private bool _patch;
    private string _factoryVersion;
    private bool _hasVersionEdit;

    public ProjectEnvironmentCardViewModel(
        FactoryProject project,
        ProjectEnvironment environment,
        ProjectDeploymentDraft? draft = null,
        FactoryVersionSelection? factoryVersion = null)
    {
        ArgumentNullException.ThrowIfNull(project);
        ArgumentNullException.ThrowIfNull(environment);
        Project = project;
        EnvironmentInfo = environment;
        Draft = draft;
        _patch = draft?.Patch ?? false;
        SavedVersionSelection = !string.IsNullOrWhiteSpace(draft?.RequestedVersion) ? draft : factoryVersion;
        _factoryVersion = SavedVersionSelection?.RequestedVersion ?? string.Empty;
    }

    public FactoryProject Project { get; }

    public ProjectEnvironment EnvironmentInfo { get; }
    public ProjectDeploymentDraft? Draft { get; }
    public bool IsDeployed => HasObservedResourceGroup(EnvironmentInfo);
    public bool IsDraft => Draft is not null && !IsDeployed;
    public bool IsPlaceholder => !IsDeployed && !IsDraft;
    public bool HasCard => IsDeployed || IsDraft;
    public bool IsSelected { get => _isSelected; private set => SetProperty(ref _isSelected, value); }
    public void SetSelected(bool selected) => IsSelected = selected && HasCard;
    public bool IsFailure => Draft?.Status is "failed" or "interrupted" ||
        string.Equals(EnvironmentInfo.Status?.Trim(), "failed", StringComparison.OrdinalIgnoreCase);
    public bool IsActive => !IsFailure && Draft?.IsRunning != true && IsDeployed &&
        string.Equals(EnvironmentInfo.Status?.Trim(), "active", StringComparison.OrdinalIgnoreCase);
    public bool IsDeploying => !IsFailure && !IsActive && Draft?.Status is "queued" or "running" or "submitted";
    public bool IsStatusLit => IsActive || IsDeploying || IsFailure;
    public bool IsStatusPulsing => IsActive || IsDeploying;
    public string StatusColor => IsFailure ? "#F05252" : IsDeploying ? "#35C878" : IsActive ? "#409EFF" : "#555C66";
    public string ActivityDescription => IsFailure ? "Deployment failed or was interrupted. Review the terminal before taking further action."
        : IsDeploying ? "Deployment is in progress or awaiting Azure inventory confirmation; it is not yet marked active."
        : IsActive
        ? "Active in the current Azure inventory. This is not a live application health check."
        : $"Inventory status: {Status}.";
    public string PlaceholderDescription =>
        $"Project {ProjectNumber}, {EnvironmentLabel}: no resource group observed in this inventory. Not an available deployment.";
    public bool ShowPlanningOptions { get => _showPlanningOptions; set => SetProperty(ref _showPlanningOptions, value); }

    public string ProjectNumber => Project.ProjectNumber;
    public string Owner => string.IsNullOrWhiteSpace(Project.Owner) ? "Not specified" : Project.Owner;
    public string DeploymentEnvironments
    {
        get
        {
            var deployed = Project.Environments.Where(HasObservedResourceGroup)
                .Select(environment => ProjectDeploymentPresentation.NormalizeEnvironment(environment.Environment))
                .Where(environment => environment.Length > 0).Distinct()
                .OrderBy(ProjectDeploymentPresentation.EnvironmentOrder).ToArray();
            return deployed.Length > 0 ? string.Join(" · ", deployed) : "Not deployed / not checked";
        }
    }

    public string ProjectLabel => string.IsNullOrWhiteSpace(Project.DisplayName)
        ? $"Project {ProjectNumber}"
        : Project.DisplayName;

    public string Environment => EnvironmentInfo.Environment;

    public string EnvironmentLabel =>
        string.IsNullOrWhiteSpace(Environment)
            ? string.Empty
            : char.ToUpperInvariant(Environment[0]) + Environment[1..].ToLowerInvariant();

    public string Status => IsFailure ? Draft?.Status == "interrupted" ? "Needs review" : "Failed"
        : IsActive ? "active" : Draft is not null ? Draft.Status switch
    {
        "draft" => IsDeployed ? "Update planned" : "Not deployed",
        "queued" => "Queued",
        "running" => "Deploying",
        "submitted" => "Awaiting Azure",
        "failed" => "Failed",
        "interrupted" => "Needs review",
        _ => "Unknown deployment state"
    } : string.IsNullOrWhiteSpace(EnvironmentInfo.Status)
        ? "Unknown"
        : EnvironmentInfo.Status;

    public string Region => EnvironmentInfo.Region
        ?? EnvironmentInfo.Regions.FirstOrDefault()
        ?? "Not reported";

    public string ResourceGroup => EnvironmentInfo.ResourceGroup
        ?? EnvironmentInfo.ResourceGroups.FirstOrDefault()
        ?? "Not reported";

    public int ResourceCount => EnvironmentInfo.ResourceCount;
    public IReadOnlyList<ProjectResourceGroupLink> ResourceGroupLinks => ProjectResourceGroupLink.FromEnvironment(EnvironmentInfo);
    public bool HasResourceGroupLink => ResourceGroupLinks.Count > 0;
    public string ResourceGroupLinkHint => HasResourceGroupLink
        ? "Open the observed project resource group in Azure Portal."
        : "No deployed resource group is available in the current Azure inventory for this environment.";

    public bool DeleteAllForProject
    {
        get => _deleteAllForProject;
        set => SetProperty(ref _deleteAllForProject, value);
    }

    public bool DeleteAllServices
    {
        get => _deleteAllServices;
        set => SetProperty(ref _deleteAllServices, value);
    }

    public string? DeploymentTarget =>
        GetDeploymentTarget(Environment);

    public bool CanDeploy => IsDeployed && DeploymentTarget is not null && !IsFailure && Draft?.IsRunning != true;

    public string DeployButtonText => DeploymentTarget is null
        ? "No forward deployment"
        : $"Plan to {Capitalize(DeploymentTarget)}";

    public bool IsUpdate => Draft?.Operation == "update";
    public bool CanSubmitDraft => Draft?.Status == "draft" && (IsUpdate ? IsDeployed : IsDraft);
    public bool ShowDeployButton => CanSubmitDraft && !IsUpdate;
    public bool CanUpdate => IsDeployed && !IsFailure &&
        (Draft is null || Draft.Status == "submitted" || IsUpdate && CanSubmitDraft);
    public bool CanReviewOutcome => Draft is { Status: "failed" or "interrupted", ReconciledAt: null } && HasTerminal;
    public bool IsOutcomeReviewed => !string.IsNullOrWhiteSpace(Draft?.ReconciledAt);
    public bool CanEditPatch => HasCard && !IsFailure && Draft?.IsRunning != true;
    public bool Patch
    {
        get => _patch;
        set
        {
            if (SetProperty(ref _patch, value)) OnPropertyChanged(nameof(PatchDescription));
        }
    }
    public string PatchDescription => Patch
        ? "Patch enabled: refresh shared templates before deploying this project."
        : "Project only: pass --project-only; skip the shared-template patch.";
    public string FactoryVersion
    {
        get => _factoryVersion;
        set
        {
            if (_factoryVersion == (value ?? string.Empty)) return;
            _hasVersionEdit = true;
            SetProperty(ref _factoryVersion, value ?? string.Empty);
        }
    }
    public bool HasVersionEdit => _hasVersionEdit;
    public FactoryVersionSelection? SavedVersionSelection { get; }
    public string SavedTemplateBranch => string.IsNullOrWhiteSpace(SavedVersionSelection?.Branch)
        ? "Resolved from saved configuration during review" : SavedVersionSelection.Branch;
    public string SavedTemplateRef => SavedVersionSelection?.ResolvedRef ?? string.Empty;
    public void RestoreVersionEdit(string value)
    {
        _hasVersionEdit = true;
        SetProperty(ref _factoryVersion, value, nameof(FactoryVersion));
    }
    public string VersionGuidance => "Blank inherits the saved factory version. 124 → release/v1.24; 125 → release/v1.25; major.minor or main. With Patch off, installed code is preserved; a different version requires a prior factory upgrade or Patch.";
    public bool HasDeploymentDetails => Draft is not null;
    public bool HasTerminal => !string.IsNullOrWhiteSpace(Draft?.JobId);
    public string DraftDescription => IsUpdate
        ? $"Update the existing {EnvironmentLabel} project; no environment promotion."
        : IsDraft
        ? $"Saved {Capitalize(Draft!.SourceEnvironment)} to {EnvironmentLabel} plan. No deployed {EnvironmentLabel} resource group has been observed."
        : string.Empty;
    public string DraftMessage => Draft?.Message ?? string.Empty;
    public string DraftRoute => Draft?.Route switch
    {
        "ado" => "Azure DevOps",
        "gha" or "github" => "GitHub Actions",
        _ => "Route resolved by Python API"
    };

    public static string? GetDeploymentTarget(string? environment) =>
        environment?.Trim().ToLowerInvariant() switch
        {
            "dev" => "stage",
            "stage" => "prod",
            _ => null
        };

    public static IReadOnlyList<ProjectEnvironmentCardViewModel> Flatten(
        IEnumerable<FactoryProject>? projects,
        string environment)
    {
        var normalizedEnvironment = environment.Trim().ToLowerInvariant();
        return (projects ?? [])
            .SelectMany(project => project.Environments
                .Where(item => string.Equals(
                    item.Environment,
                    normalizedEnvironment,
                    StringComparison.OrdinalIgnoreCase) && HasObservedResourceGroup(item))
                .Select(item => new ProjectEnvironmentCardViewModel(project, item)))
            .OrderBy(card => ProjectSortKey(card.ProjectNumber))
            .ThenBy(card => card.ProjectNumber, StringComparer.OrdinalIgnoreCase)
            .ToArray();
    }

    public static bool HasObservedResourceGroup(ProjectEnvironment environment) =>
        !string.IsNullOrWhiteSpace(environment.ResourceGroup) ||
        environment.ResourceGroups.Any(name => !string.IsNullOrWhiteSpace(name)) ||
        environment.ResourceGroupReferences.Any(group => !string.IsNullOrWhiteSpace(group.Name) ||
            !string.IsNullOrWhiteSpace(group.Id));

    public static IReadOnlyList<ProjectEnvironmentRowViewModel> BuildRows(OperationsOverview? overview,
        IReadOnlyList<ProjectDeploymentDraft>? drafts = null, FactoryVersionSelection? factoryVersion = null)
    {
        var savedDrafts = (drafts ?? []).Where(draft => !string.IsNullOrWhiteSpace(draft.Id) &&
            !string.IsNullOrWhiteSpace(draft.ProjectNumber) &&
            (draft.Operation == "update"
                ? draft.SourceEnvironment == draft.TargetEnvironment && draft.TargetEnvironment is "dev" or "stage" or "prod"
                : draft.Operation == "deploy" &&
                  (draft.SourceEnvironment, draft.TargetEnvironment) is ("dev", "stage") or ("stage", "prod"))).ToArray();
        var observedProjects = overview?.ResourceInventory.Source is "azure" or "cached" ? overview.Projects : [];
        var projects = observedProjects
            .Where(project => project.Environments.Any(environment => HasObservedResourceGroup(environment) &&
               ProjectDeploymentPresentation.NormalizeEnvironment(environment.Environment).Length > 0)).ToList();
        foreach (var number in savedDrafts.Select(draft => draft.ProjectNumber).Distinct())
        {
            if (projects.All(project => project.ProjectNumber != number))
                projects.Add(new FactoryProject { ProjectNumber = number, DisplayName = $"Project {number}" });
        }
        return projects
            .OrderBy(project => ProjectSortKey(project.ProjectNumber))
            .ThenBy(project => project.ProjectNumber, StringComparer.OrdinalIgnoreCase)
            .Select(project => new ProjectEnvironmentRowViewModel(
               Cell(project, "dev", savedDrafts, factoryVersion), Cell(project, "stage", savedDrafts, factoryVersion),
               Cell(project, "prod", savedDrafts, factoryVersion)))
            .ToArray();
    }

    private static ProjectEnvironmentCardViewModel Cell(FactoryProject project, string environment,
        IReadOnlyList<ProjectDeploymentDraft> drafts, FactoryVersionSelection? factoryVersion)
    {
        var observed = project.Environments.FirstOrDefault(item =>
            ProjectDeploymentPresentation.NormalizeEnvironment(item.Environment).Equals(
               ProjectDeploymentPresentation.NormalizeEnvironment(environment), StringComparison.Ordinal) &&
            HasObservedResourceGroup(item));
        return new(project, observed is null
            ? new ProjectEnvironment { Environment = environment, Status = "not_observed" }
            : observed with { Environment = environment },
                drafts.LastOrDefault(draft => draft.ProjectNumber == project.ProjectNumber && draft.TargetEnvironment == environment),
                factoryVersion);
    }

    private static long ProjectSortKey(string projectNumber)
    {
        var digits = new string(projectNumber.Where(char.IsDigit).ToArray());
        return long.TryParse(digits, out var value) ? value : long.MaxValue;
    }

    private static string Capitalize(string value) =>
        char.ToUpperInvariant(value[0]) + value[1..];
}

public sealed record ProjectEnvironmentRowViewModel(
    ProjectEnvironmentCardViewModel Dev,
    ProjectEnvironmentCardViewModel Stage,
    ProjectEnvironmentCardViewModel Prod);

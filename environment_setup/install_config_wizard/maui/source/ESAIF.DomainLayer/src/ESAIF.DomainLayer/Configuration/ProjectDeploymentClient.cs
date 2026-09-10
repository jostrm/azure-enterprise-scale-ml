using System.Text.Json.Serialization;

namespace ESAIF.DomainLayer.Configuration;

public interface IProjectDeploymentClient
{
    Task<ProjectDeploymentList> GetProjectDeploymentsAsync(string folder, CancellationToken cancellationToken = default);
    Task<ProjectDeploymentDraft> PlanProjectDeploymentAsync(string folder, string projectNumber,
        string sourceEnvironment, string targetEnvironment, bool patch = false, string operation = "deploy",
        CancellationToken cancellationToken = default, string? factoryVersion = null);
    Task<ProjectDeploymentPlan> PrepareProjectDeploymentAsync(string folder, string draftId, bool patch = false,
        CancellationToken cancellationToken = default, string? factoryVersion = null);
    Task<ProjectDeploymentDraft> StartProjectDeploymentAsync(string folder, string confirmationId, CancellationToken cancellationToken = default);
    Task<ProjectDeploymentPlan> PrepareProjectReconciliationAsync(string folder, string jobId, CancellationToken cancellationToken = default);
    Task<ProjectDeploymentDraft> ReconcileProjectDeploymentAsync(string folder, string confirmationId, CancellationToken cancellationToken = default);
}

public sealed record ProjectDeploymentList : FactoryVersionSelection
{
    private FactoryVersionSelection? _versionSelection;
    public IReadOnlyList<ProjectDeploymentDraft> Drafts { get; init; } = [];
    [JsonPropertyName("version_selection")]
    public FactoryVersionSelection? VersionSelection
    {
        get
        {
            if (_versionSelection is { } nested && !string.IsNullOrWhiteSpace(RequestedVersion) &&
                (nested.RequestedVersion != RequestedVersion || nested.Branch != Branch || nested.ResolvedRef != ResolvedRef))
                throw new InvalidDataException("The API returned conflicting inherited version metadata.");
            return _versionSelection ?? (string.IsNullOrWhiteSpace(RequestedVersion) ? null : new FactoryVersionSelection
            {
                RequestedVersion = RequestedVersion, Branch = Branch, ResolvedRef = ResolvedRef
            });
        }
        init => _versionSelection = value;
    }
    [JsonPropertyName("version_blockers")]
    public IReadOnlyList<string> VersionBlockers { get; init; } = [];
}

public sealed record ProjectDeploymentDraft : FactoryVersionSelection
{
    [JsonPropertyName("deployment_contract")]
    public ProjectDeploymentAcknowledgement? DeploymentContract { get; init; }
    public string Id { get; init; } = string.Empty;
    [JsonPropertyName("project_number")]
    public string ProjectNumber { get; init; } = string.Empty;
    [JsonPropertyName("source_environment")]
    public string SourceEnvironment { get; init; } = string.Empty;
    [JsonPropertyName("target_environment")]
    public string TargetEnvironment { get; init; } = string.Empty;
    public string Operation { get; init; } = "deploy";
    public bool Patch { get; init; }
    public string Status { get; init; } = string.Empty;
    public string Message { get; init; } = string.Empty;
    public string Route { get; init; } = string.Empty;
    [JsonPropertyName("script_path")]
    public string ScriptPath { get; init; } = string.Empty;
    [JsonPropertyName("job_id")]
    public string? JobId { get; init; }
    [JsonPropertyName("created_at")]
    public string CreatedAt { get; init; } = string.Empty;
    [JsonPropertyName("updated_at")]
    public string UpdatedAt { get; init; } = string.Empty;
    [JsonPropertyName("reconciled_at")]
    public string? ReconciledAt { get; init; }
    [JsonIgnore]
    public bool IsRunning => Status is "queued" or "running";
}

public sealed record ProjectDeploymentAcknowledgement : FactoryVersionSelection
{
    public int? Version { get; init; }
    [JsonPropertyName("draft_id")]
    public string? DraftId { get; init; }
    public string? Operation { get; init; }
    public bool? Patch { get; init; }
}

public sealed record ProjectDeploymentPlan : FactoryVersionSelection
{
    [JsonPropertyName("deployment_contract")]
    public ProjectDeploymentAcknowledgement? DeploymentContract { get; init; }
    [JsonPropertyName("confirmation_id")]
    public string ConfirmationId { get; init; } = string.Empty;
    [JsonPropertyName("can_execute")]
    public bool CanExecute { get; init; }
    public string Summary { get; init; } = string.Empty;
    public string Command { get; init; } = string.Empty;
    [JsonPropertyName("working_directory")]
    public string WorkingDirectory { get; init; } = string.Empty;
    public IReadOnlyList<string> Effects { get; init; } = [];
    public IReadOnlyList<string> Warnings { get; init; } = [];
    public IReadOnlyList<string> Blockers { get; init; } = [];
    [JsonPropertyName("expires_at")]
    public string ExpiresAt { get; init; } = string.Empty;
}

public sealed partial class AiFactoryApiClient : IProjectDeploymentClient
{
    private const string ProjectDeploymentsPath = "/api/v1/operations/project-deployments";

    public Task<ProjectDeploymentList> GetProjectDeploymentsAsync(string folder, CancellationToken cancellationToken = default)
    {
        ArgumentException.ThrowIfNullOrWhiteSpace(folder);
        return SendAsync<ProjectDeploymentList>(HttpMethod.Get,
            $"{ProjectDeploymentsPath}?folder={Uri.EscapeDataString(folder)}", null, true, cancellationToken);
    }

    public async Task<ProjectDeploymentDraft> PlanProjectDeploymentAsync(string folder, string projectNumber,
        string sourceEnvironment, string targetEnvironment, bool patch = false, string operation = "deploy",
        CancellationToken cancellationToken = default, string? factoryVersion = null)
    {
        ArgumentException.ThrowIfNullOrWhiteSpace(folder);
        ArgumentException.ThrowIfNullOrWhiteSpace(projectNumber);
        var valid = operation switch
        {
            "deploy" => (sourceEnvironment, targetEnvironment) is ("dev", "stage") or ("stage", "prod") or ("dev", "prod"),
            "update" => sourceEnvironment == targetEnvironment && targetEnvironment is "dev" or "stage" or "prod",
            _ => false
        };
        if (!valid)
            throw new ArgumentException("Deploy requires a later environment; Update requires the same Dev, Stage or Prod environment.");
        var request = new Dictionary<string, object>
        {
            ["folder"] = folder, ["project_number"] = projectNumber, ["source_environment"] = sourceEnvironment,
            ["target_environment"] = targetEnvironment, ["patch"] = patch, ["operation"] = operation
        };
        if (factoryVersion is not null) request["aifactory_version"] = factoryVersion;
        var draft = await SendAsync<ProjectDeploymentDraft>(HttpMethod.Post, $"{ProjectDeploymentsPath}/plan", request,
            true, cancellationToken).ConfigureAwait(false);
        ValidateDeploymentAcknowledgement(draft.DeploymentContract, draft.Id, patch, operation);
        ValidateDeploymentVersion(draft, draft.DeploymentContract, factoryVersion, requireResolvedRef: false);
        if (draft.ProjectNumber != projectNumber.PadLeft(3, '0') ||
            draft.SourceEnvironment != sourceEnvironment || draft.TargetEnvironment != targetEnvironment ||
            draft.Operation != operation || draft.Patch != patch)
            throw new InvalidOperationException("The API returned a different project, environment, operation or patch choice. No deployment was started.");
        return draft;
    }

    public async Task<ProjectDeploymentPlan> PrepareProjectDeploymentAsync(string folder, string draftId, bool patch = false,
        CancellationToken cancellationToken = default, string? factoryVersion = null)
    {
        ArgumentException.ThrowIfNullOrWhiteSpace(folder);
        ArgumentException.ThrowIfNullOrWhiteSpace(draftId);
        var request = new Dictionary<string, object> { ["folder"] = folder, ["draft_id"] = draftId, ["patch"] = patch };
        if (factoryVersion is not null) request["aifactory_version"] = factoryVersion;
        var plan = await SendAsync<ProjectDeploymentPlan>(HttpMethod.Post, $"{ProjectDeploymentsPath}/prepare",
            request, true, cancellationToken).ConfigureAwait(false);
        ValidateDeploymentAcknowledgement(plan.DeploymentContract, draftId, patch);
        ValidateDeploymentVersion(plan, plan.DeploymentContract, factoryVersion, plan.CanExecute);
        return plan;
    }

    private static void ValidateDeploymentVersion(FactoryVersionSelection selection,
        ProjectDeploymentAcknowledgement? contract, string? factoryVersion, bool requireResolvedRef)
    {
        if (factoryVersion is null) return;
        if (contract is null || !selection.SameResolvedSelection(contract))
            throw FactoryVersionSelection.VersionAcknowledgementError();
        selection.ValidateExplicitSelection(factoryVersion, requireResolvedRef);
        contract.ValidateExplicitSelection(factoryVersion, requireResolvedRef);
    }

    private static void ValidateDeploymentAcknowledgement(ProjectDeploymentAcknowledgement? contract,
        string draftId, bool patch, string? operation = null)
    {
        if (contract is null || contract.Version != 2 || string.IsNullOrWhiteSpace(draftId) || contract.DraftId != draftId ||
            contract.Patch != patch || contract.Operation is not ("deploy" or "update") ||
            (operation is not null && contract.Operation != operation))
            throw new InvalidOperationException(
                "The API did not explicitly acknowledge the supported deployment contract and selected operation/patch choice. Update the API sidecar and prepare again; no deployment was started.");
    }

    public Task<ProjectDeploymentDraft> StartProjectDeploymentAsync(string folder, string confirmationId, CancellationToken cancellationToken = default)
    {
        ArgumentException.ThrowIfNullOrWhiteSpace(folder);
        ArgumentException.ThrowIfNullOrWhiteSpace(confirmationId);
        return SendAsync<ProjectDeploymentDraft>(HttpMethod.Post, $"{ProjectDeploymentsPath}/start",
            new { folder, confirmation_id = confirmationId }, true, cancellationToken);
    }

    public Task<ProjectDeploymentPlan> PrepareProjectReconciliationAsync(string folder, string jobId, CancellationToken cancellationToken = default)
    {
        ArgumentException.ThrowIfNullOrWhiteSpace(folder);
        ArgumentException.ThrowIfNullOrWhiteSpace(jobId);
        return SendAsync<ProjectDeploymentPlan>(HttpMethod.Post, $"{ProjectDeploymentsPath}/reconcile/prepare",
            new { folder, job_id = jobId }, true, cancellationToken);
    }

    public Task<ProjectDeploymentDraft> ReconcileProjectDeploymentAsync(string folder, string confirmationId, CancellationToken cancellationToken = default)
    {
        ArgumentException.ThrowIfNullOrWhiteSpace(folder);
        ArgumentException.ThrowIfNullOrWhiteSpace(confirmationId);
        return SendAsync<ProjectDeploymentDraft>(HttpMethod.Post, $"{ProjectDeploymentsPath}/reconcile",
            new { folder, confirmation_id = confirmationId }, true, cancellationToken);
    }
}

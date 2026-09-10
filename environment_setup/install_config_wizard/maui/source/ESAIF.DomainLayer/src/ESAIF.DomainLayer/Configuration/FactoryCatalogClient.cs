using System.Text.Json.Serialization;
using System.Text.Json.Nodes;

namespace ESAIF.DomainLayer.Configuration;

public interface IFactoryCatalogClient
{
    Task<FactoryCatalog> GetFactoryCatalogAsync(string folder, CancellationToken cancellationToken = default);
    Task<FactoryCatalogPreview> PrepareFactoryCatalogAsync(FactoryCatalogRequest request, CancellationToken cancellationToken = default);
    Task<FactoryCatalogConfirmation> ConfirmFactoryCatalogAsync(string folder, string confirmationId, CancellationToken cancellationToken = default);
    Task<FactoryCatalogJobs> GetFactoryCatalogJobsAsync(string folder, CancellationToken cancellationToken = default);
    Task<FactoryCatalogJob> GetFactoryCatalogJobAsync(string folder, string jobId, CancellationToken cancellationToken = default);
}

public sealed record FactoryCatalog
{
    [JsonPropertyName("contract_version")]
    public int ContractVersion { get; init; }
    public string Mode { get; init; } = string.Empty;
    public string Revision { get; init; } = string.Empty;
    public IReadOnlyList<CatalogFactory> Factories { get; init; } = [];
    public IReadOnlyList<string> Warnings { get; init; } = [];
    [JsonPropertyName("requires_selection")]
    public bool RequiresSelection { get; init; }
}

public sealed record CatalogFactory
{
    public string Id { get; init; } = string.Empty;
    public string Key { get; init; } = string.Empty;
    public string Prefix { get; init; } = string.Empty;
    public string Region { get; init; } = string.Empty;
    [JsonPropertyName("default_orchestrator")]
    public string DefaultOrchestrator { get; init; } = string.Empty;
    public string Status { get; init; } = string.Empty;
    [JsonPropertyName("version_ref")]
    public string VersionRef { get; init; } = string.Empty;
    [JsonPropertyName("aifactory_version")]
    public string? FactoryVersion { get; init; }
    [JsonPropertyName("scale_sets")]
    public IReadOnlyList<CatalogScaleSet> ScaleSets { get; init; } = [];
    public IReadOnlyList<CatalogProject> Projects { get; init; } = [];
    public IReadOnlyList<CatalogBindingState> Bindings { get; init; } = [];
}

public sealed record CatalogBindingState
{
    public string Orchestrator { get; init; } = string.Empty;
    public CatalogRuntimeBinding? Configuration { get; init; }
    public string? Error { get; init; }
    public bool Verified { get; init; }
}

public sealed record CatalogRuntimeBinding
{
    [JsonPropertyName("contract_version")]
    public int ContractVersion { get; init; } = 1;
    public string Orchestrator { get; init; } = string.Empty;
    [JsonPropertyName("writer_id")]
    public string WriterId { get; init; } = string.Empty;
    public string Repository { get; init; } = string.Empty;
    public string Ref { get; init; } = "refs/heads/main";
    [JsonPropertyName("shared_remote")]
    public bool SharedRemote { get; init; }
    [JsonPropertyName("auth_namespace"), JsonIgnore(Condition = JsonIgnoreCondition.WhenWritingNull)]
    public string? AuthNamespace { get; init; }
    [JsonPropertyName("deployment_object_id"), JsonIgnore(Condition = JsonIgnoreCondition.WhenWritingNull)]
    public string? DeploymentObjectId { get; init; }
    [JsonIgnore(Condition = JsonIgnoreCondition.WhenWritingNull)]
    public CatalogRunnerSelection? Runner { get; init; }
    public CatalogLockEnrollment Locks { get; init; } = new();
    public IReadOnlyList<CatalogBindingTarget> Targets { get; init; } = [];
}

public sealed record CatalogRunnerSelection
{
    public string Kind { get; init; } = string.Empty;
    public string Os { get; init; } = "linux";
    [JsonIgnore(Condition = JsonIgnoreCondition.WhenWritingNull)]
    public string? Image { get; init; }
    [JsonIgnore(Condition = JsonIgnoreCondition.WhenWritingNull)]
    public IReadOnlyList<string>? Labels { get; init; }
    [JsonIgnore(Condition = JsonIgnoreCondition.WhenWritingNull)]
    public string? Pool { get; init; }
    [JsonPropertyName("agent_name"), JsonIgnore(Condition = JsonIgnoreCondition.WhenWritingNull)]
    public string? AgentName { get; init; }
}

public sealed record CatalogLockEnrollment
{
    [JsonPropertyName("account_url")]
    public string AccountUrl { get; init; } = string.Empty;
    public string Container { get; init; } = string.Empty;
    [JsonPropertyName("coordination_blob")]
    public string CoordinationBlob { get; init; } = string.Empty;
    [JsonPropertyName("coordination_hash")]
    public string CoordinationHash { get; init; } = string.Empty;
    public int Revision { get; init; } = 1;
}

public sealed record CatalogBindingTarget
{
    [JsonPropertyName("scale_set_id")]
    public string ScaleSetId { get; init; } = string.Empty;
    [JsonPropertyName("resource_group_ids")]
    public IReadOnlyList<string> ResourceGroupIds { get; init; } = [];
    [JsonPropertyName("common_dependency_ids")]
    public IReadOnlyList<string> CommonDependencyIds { get; init; } = [];
    [JsonIgnore(Condition = JsonIgnoreCondition.WhenWritingNull)]
    public CatalogTargetExecution? Execution { get; init; }
}

public sealed record CatalogTargetExecution
{
    [JsonPropertyName("writer_id")]
    public string WriterId { get; init; } = string.Empty;
    [JsonPropertyName("auth_namespace")]
    public string AuthNamespace { get; init; } = string.Empty;
    [JsonPropertyName("deployment_object_id")]
    public string DeploymentObjectId { get; init; } = string.Empty;
    public CatalogRunnerSelection Runner { get; init; } = new();
}

public sealed record CatalogScaleSet
{
    public string Id { get; init; } = string.Empty;
    public string Environment { get; init; } = string.Empty;
    public string Suffix { get; init; } = string.Empty;
    [JsonPropertyName("subscription_id")]
    public string SubscriptionId { get; init; } = string.Empty;
    [JsonPropertyName("tenant_id")]
    public string TenantId { get; init; } = string.Empty;
    public string Orchestrator { get; init; } = string.Empty;
    public CatalogNetwork Network { get; init; } = new();
    public string Status { get; init; } = string.Empty;
    [JsonPropertyName("owned_resource_ids")]
    public IReadOnlyList<string> OwnedResourceIds { get; init; } = [];
}

public sealed record CatalogProject
{
    public string Id { get; init; } = string.Empty;
    public string Key { get; init; } = string.Empty;
    public string Number { get; init; } = string.Empty;
    [JsonPropertyName("display_name")]
    public string DisplayName { get; init; } = string.Empty;
    public string Status { get; init; } = string.Empty;
    public IReadOnlyList<CatalogPlacement> Placements { get; init; } = [];
}

public sealed record CatalogPlacement
{
    public string Environment { get; init; } = string.Empty;
    [JsonPropertyName("scale_set_id")]
    public string ScaleSetId { get; init; } = string.Empty;
}

public sealed record CatalogProjectInput
{
    public string Number { get; init; } = string.Empty;
    [JsonPropertyName("display_name")]
    public string DisplayName { get; init; } = string.Empty;
    public IReadOnlyList<CatalogPlacement> Placements { get; init; } = [];
}

public sealed record CatalogNetwork
{
    [JsonPropertyName("vnet_cidr")]
    public string VnetCidr { get; init; } = string.Empty;
    [JsonPropertyName("max_projects")]
    public int MaxProjects { get; init; } = 1;
    [JsonPropertyName("common_subnets"), JsonIgnore(Condition = JsonIgnoreCondition.WhenWritingNull)]
    public CatalogCommonSubnets? CommonSubnets { get; init; }
}

public sealed record CatalogCommonSubnets
{
    public string Common { get; init; } = string.Empty;
    public string Scoring { get; init; } = string.Empty;
    public string Powerbi { get; init; } = string.Empty;
    public string Bastion { get; init; } = string.Empty;
}

public sealed record CatalogScaleSetInput
{
    public string Environment { get; init; } = "dev";
    public string Suffix { get; init; } = string.Empty;
    [JsonPropertyName("subscription_id")]
    public string SubscriptionId { get; init; } = string.Empty;
    [JsonPropertyName("tenant_id")]
    public string TenantId { get; init; } = string.Empty;
    public string Orchestrator { get; init; } = string.Empty;
    public CatalogNetwork Network { get; init; } = new();
}

public sealed record FactoryCatalogRequest
{
    public string Folder { get; init; } = string.Empty;
    [JsonPropertyName("contract_version")]
    public int ContractVersion { get; init; } = 1;
    public string Action { get; init; } = string.Empty;
    [JsonPropertyName("expected_revision"), JsonIgnore(Condition = JsonIgnoreCondition.WhenWritingNull)]
    public string? SourceRevision { get; init; }
    [JsonPropertyName("factory_id"), JsonIgnore(Condition = JsonIgnoreCondition.WhenWritingNull)]
    public string? FactoryId { get; init; }
    [JsonPropertyName("scale_set_id"), JsonIgnore(Condition = JsonIgnoreCondition.WhenWritingNull)]
    public string? ScaleSetId { get; init; }
    [JsonPropertyName("project_id"), JsonIgnore(Condition = JsonIgnoreCondition.WhenWritingNull)]
    public string? ProjectId { get; init; }
    [JsonPropertyName("target_prefix"), JsonIgnore(Condition = JsonIgnoreCondition.WhenWritingNull)]
    public string? TargetPrefix { get; init; }
    [JsonPropertyName("target_region"), JsonIgnore(Condition = JsonIgnoreCondition.WhenWritingNull)]
    public string? TargetRegion { get; init; }
    [JsonPropertyName("include_projects")]
    public string IncludeProjects { get; init; } = "none";
    [JsonPropertyName("scale_sets"), JsonIgnore(Condition = JsonIgnoreCondition.WhenWritingNull)]
    public IReadOnlyList<CatalogScaleSetInput>? ScaleSets { get; init; }
    [JsonPropertyName("version_ref"), JsonIgnore(Condition = JsonIgnoreCondition.WhenWritingNull)]
    public string? VersionRef { get; init; }
    [JsonPropertyName("aifactory_version"), JsonIgnore(Condition = JsonIgnoreCondition.WhenWritingNull)]
    public string? FactoryVersion { get; init; }
    [JsonIgnore(Condition = JsonIgnoreCondition.WhenWritingNull)]
    public CatalogRuntimeBinding? Binding { get; init; }
    [JsonIgnore(Condition = JsonIgnoreCondition.WhenWritingNull)]
    public CatalogProjectInput? Project { get; init; }
    [JsonIgnore(Condition = JsonIgnoreCondition.WhenWritingNull)]
    public IReadOnlyList<CatalogPlacement>? Placements { get; init; }
    [JsonIgnore(Condition = JsonIgnoreCondition.WhenWritingNull)]
    public JsonObject? Settings { get; init; }
}

public sealed record FactoryCatalogPreview
{
    [JsonPropertyName("contract_version")]
    public int ContractVersion { get; init; }
    [JsonPropertyName("confirmation_id")]
    public string ConfirmationId { get; init; } = string.Empty;
    [JsonPropertyName("can_execute")]
    public bool CanExecute { get; init; }
    public string Summary { get; init; } = string.Empty;
    public IReadOnlyList<string> Effects { get; init; } = [];
    public IReadOnlyList<string> Warnings { get; init; } = [];
    public IReadOnlyList<string> Blockers { get; init; } = [];
    [JsonPropertyName("expires_at")]
    public string ExpiresAt { get; init; } = string.Empty;
    [JsonPropertyName("source_revision")]
    public string SourceRevision { get; init; } = string.Empty;
    [JsonPropertyName("operation_mode")]
    public string OperationMode { get; init; } = string.Empty;
    public CatalogFactory? Target { get; init; }
    public IReadOnlyList<CatalogInventoryResource> Inventory { get; init; } = [];
    [JsonPropertyName("source_version")]
    public CatalogSourceVersion? SourceVersion { get; init; }
    public CatalogRuntimeBinding? Binding { get; init; }
}

public sealed record CatalogSourceVersion
{
    [JsonPropertyName("aifactory_version")]
    public string? FactoryVersion { get; init; }
    [JsonPropertyName("requested_version")]
    public string RequestedVersion { get; init; } = string.Empty;
    public string Branch { get; init; } = string.Empty;
    [JsonPropertyName("resolved_ref")]
    public string ResolvedRef { get; init; } = string.Empty;
}

public sealed record CatalogInventoryResource
{
    [JsonPropertyName("resource_id")]
    public string ResourceId { get; init; } = string.Empty;
    public IReadOnlyList<string> Dependencies { get; init; } = [];
}

public sealed record FactoryCatalogConfirmation
{
    [JsonPropertyName("contract_version")]
    public int ContractVersion { get; init; }
    public FactoryCatalog? Catalog { get; init; }
    public FactoryCatalogJob? Job { get; init; }
}

public sealed record FactoryCatalogJobs
{
    [JsonPropertyName("contract_version")]
    public int ContractVersion { get; init; }
    public IReadOnlyList<FactoryCatalogJob> Jobs { get; init; } = [];
}

public sealed record FactoryCatalogJob
{
    public string Id { get; init; } = string.Empty;
    public string Action { get; init; } = string.Empty;
    public string Status { get; init; } = string.Empty;
    public string Message { get; init; } = string.Empty;
    [JsonPropertyName("factory_id")]
    public string FactoryId { get; init; } = string.Empty;
    [JsonPropertyName("scale_set_id")]
    public string? ScaleSetId { get; init; }
    [JsonPropertyName("created_at")]
    public string CreatedAt { get; init; } = string.Empty;
    [JsonPropertyName("updated_at")]
    public string UpdatedAt { get; init; } = string.Empty;
    [JsonPropertyName("exit_code")]
    public int? ExitCode { get; init; }
    [JsonPropertyName("terminal_available")]
    public bool TerminalAvailable { get; init; }
    [JsonPropertyName("source_version")]
    public CatalogSourceVersion? SourceVersion { get; init; }
    [JsonIgnore]
    public bool IsRunning => Status is "queued" or "running";
}

public sealed partial class AiFactoryApiClient : IFactoryCatalogClient
{
    private const string FactoryCatalogPath = "/api/v1/factory-catalog";

    public async Task<FactoryCatalog> GetFactoryCatalogAsync(string folder, CancellationToken cancellationToken = default)
    {
        ArgumentException.ThrowIfNullOrWhiteSpace(folder);
        var result = await SendAsync<FactoryCatalog>(HttpMethod.Get,
            $"{FactoryCatalogPath}?folder={Uri.EscapeDataString(folder)}", null, true, cancellationToken).ConfigureAwait(false);
        ValidateCatalog(result);
        return result;
    }

    public async Task<FactoryCatalogPreview> PrepareFactoryCatalogAsync(FactoryCatalogRequest request,
        CancellationToken cancellationToken = default)
    {
        ArgumentNullException.ThrowIfNull(request);
        ArgumentException.ThrowIfNullOrWhiteSpace(request.Folder);
        RequireCatalogContract(request.ContractVersion);
        if (request.Action is not ("migrate" or "create-factory" or "clone" or "create-scale-set" or "configure-binding" or "configure-settings" or
            "add-project" or "add-project-placements" or
            "deploy" or "delete-factory" or "delete-scale-set"))
            throw new ArgumentException("Select a supported catalog action.", nameof(request));
        if (request.Action is not ("migrate" or "create-factory")) ArgumentException.ThrowIfNullOrWhiteSpace(request.FactoryId);
        if (request.FactoryVersion is not null && request.Action is not ("create-factory" or "clone"))
            throw new ArgumentException("A saved factory version can only be selected when creating or cloning a factory.");
        if (request.Action == "create-factory")
        {
            if (request.FactoryId is not null) throw new ArgumentException("A new factory cannot reuse an existing factory identity.");
            ArgumentException.ThrowIfNullOrWhiteSpace(request.TargetPrefix);
            ArgumentException.ThrowIfNullOrWhiteSpace(request.TargetRegion);
            if (request.ScaleSets is not { Count: > 0 }) throw new ArgumentException("Select at least one explicit new scale-set placement.");
        }
        if ((request.Action == "configure-binding") != (request.Binding is not null))
            throw new ArgumentException("Only a binding configuration action can carry a typed binding.");
        if ((request.Action == "add-project") != (request.Project is not null))
            throw new ArgumentException("Only project creation can carry a new project definition.");
        if ((request.Action == "configure-settings") != (request.Settings is not null))
            throw new ArgumentException("Only scoped settings configuration accepts configuration values.");
        if (request.Settings is { } settings && (settings.Count == 0 || settings.Any(item => item.Value is JsonObject or JsonArray)))
            throw new ArgumentException("Select nonempty scalar settings from the returned catalog settings schema.");
        if (request.Project is { } project)
        {
            if (project.Number.Length != 3 || !project.Number.All(char.IsAsciiDigit) || project.Number == "000")
                throw new ArgumentException("Choose a project number from 001 through 999.");
            ArgumentException.ThrowIfNullOrWhiteSpace(project.DisplayName);
            ValidateCatalogPlacements(project.Placements);
        }
        if (request.Action == "add-project-placements")
        {
            ArgumentException.ThrowIfNullOrWhiteSpace(request.ProjectId);
            ValidateCatalogPlacements(request.Placements ?? []);
        }
        else if (request.Placements is { Count: > 0 })
            throw new ArgumentException("Only the add-placement action accepts top-level project placements.");
        if (request.Binding is { } binding)
        {
            RequireCatalogContract(binding.ContractVersion);
            if (binding.Orchestrator is not ("ado" or "gha") || binding.Targets.Count == 0)
                throw new ArgumentException("Select an orchestrator and explicit scale-set targets for the binding.");
            ArgumentException.ThrowIfNullOrWhiteSpace(binding.WriterId);
            ArgumentException.ThrowIfNullOrWhiteSpace(binding.Repository);
            ArgumentException.ThrowIfNullOrWhiteSpace(binding.Locks.AccountUrl);
            ArgumentException.ThrowIfNullOrWhiteSpace(binding.Locks.CoordinationHash);
            if (binding.Runner is { } runner)
            {
                ArgumentException.ThrowIfNullOrWhiteSpace(binding.AuthNamespace);
                ArgumentException.ThrowIfNullOrWhiteSpace(binding.DeploymentObjectId);
                ValidateCatalogRunner(runner, binding.Orchestrator);
            }
            foreach (var target in binding.Targets)
            {
                if (target.Execution is not { } execution) continue;
                if (!binding.SharedRemote) throw new ArgumentException("Per-target execution overrides require a shared remote.");
                ArgumentException.ThrowIfNullOrWhiteSpace(execution.WriterId);
                ArgumentException.ThrowIfNullOrWhiteSpace(execution.AuthNamespace);
                ArgumentException.ThrowIfNullOrWhiteSpace(execution.DeploymentObjectId);
                ValidateCatalogRunner(execution.Runner, binding.Orchestrator);
            }
        }
        if (request.Action == "delete-scale-set") ArgumentException.ThrowIfNullOrWhiteSpace(request.ScaleSetId);
        if (request.IncludeProjects is not ("none" or "all"))
            throw new ArgumentException("Clone must include either no projects or all projects.", nameof(request));
        if (request.ScaleSets is { } scaleSets)
            foreach (var scale in scaleSets)
            {
                if (scale.Environment is not ("dev" or "stage" or "prod") ||
                    scale.Orchestrator is not ("ado" or "gha") ||
                    scale.Network.MaxProjects is < 1 or > 8)
                    throw new ArgumentException("Choose an explicit scale-set environment, orchestrator and capacity from 1 to 8.", nameof(request));
                ArgumentException.ThrowIfNullOrWhiteSpace(scale.Suffix);
                ArgumentException.ThrowIfNullOrWhiteSpace(scale.SubscriptionId);
                ArgumentException.ThrowIfNullOrWhiteSpace(scale.TenantId);
                ArgumentException.ThrowIfNullOrWhiteSpace(scale.Network.VnetCidr);
            }
        var result = await SendAsync<FactoryCatalogPreview>(HttpMethod.Post, $"{FactoryCatalogPath}/prepare",
            request, true, cancellationToken).ConfigureAwait(false);
        RequireCatalogContract(result.ContractVersion);
        if (result.OperationMode is not ("configuration" or "runtime") ||
            string.IsNullOrWhiteSpace(result.SourceRevision))
            throw new InvalidDataException("The API returned an incomplete catalog review. Nothing was confirmed.");
        if (result.CanExecute && result.OperationMode == "runtime" &&
            (result.SourceVersion is not { } version || string.IsNullOrWhiteSpace(version.RequestedVersion) ||
             string.IsNullOrWhiteSpace(version.Branch) || version.ResolvedRef.Length != 40 ||
             !version.ResolvedRef.All(Uri.IsHexDigit)))
            throw new InvalidDataException("The catalog runtime preview has no exact reviewed source version. Nothing was confirmed.");
        if (result.CanExecute && result.OperationMode == "runtime" && request.VersionRef is not null &&
            result.SourceVersion?.FactoryVersion != request.VersionRef)
            throw new InvalidDataException("The catalog runtime did not acknowledge the selected AI Factory version. Nothing was confirmed.");
        return result;
    }

    public async Task<FactoryCatalogConfirmation> ConfirmFactoryCatalogAsync(string folder, string confirmationId,
        CancellationToken cancellationToken = default)
    {
        ArgumentException.ThrowIfNullOrWhiteSpace(folder);
        ArgumentException.ThrowIfNullOrWhiteSpace(confirmationId);
        var result = await SendAsync<FactoryCatalogConfirmation>(HttpMethod.Post, $"{FactoryCatalogPath}/confirm",
            new { folder, contract_version = 1, confirmation_id = confirmationId }, true, cancellationToken).ConfigureAwait(false);
        RequireCatalogContract(result.ContractVersion);
        if ((result.Catalog is null) == (result.Job is null))
            throw new InvalidDataException("The confirmation response is incomplete. Reload catalog and jobs before taking further action; do not submit again.");
        if (result.Catalog is not null) ValidateCatalog(result.Catalog);
        if (result.Job is not null) ValidateCatalogJob(result.Job);
        return result;
    }

    public async Task<FactoryCatalogJobs> GetFactoryCatalogJobsAsync(string folder,
        CancellationToken cancellationToken = default)
    {
        ArgumentException.ThrowIfNullOrWhiteSpace(folder);
        var result = await SendAsync<FactoryCatalogJobs>(HttpMethod.Get,
            $"{FactoryCatalogPath}/jobs?folder={Uri.EscapeDataString(folder)}", null, true, cancellationToken).ConfigureAwait(false);
        RequireCatalogContract(result.ContractVersion);
        foreach (var job in result.Jobs) ValidateCatalogJob(job);
        return result;
    }

    public async Task<FactoryCatalogJob> GetFactoryCatalogJobAsync(string folder, string jobId,
        CancellationToken cancellationToken = default)
    {
        ArgumentException.ThrowIfNullOrWhiteSpace(folder);
        ArgumentException.ThrowIfNullOrWhiteSpace(jobId);
        var result = await SendAsync<FactoryCatalogJob>(HttpMethod.Get,
            $"{FactoryCatalogPath}/jobs/{Uri.EscapeDataString(jobId)}?folder={Uri.EscapeDataString(folder)}",
            null, true, cancellationToken).ConfigureAwait(false);
        ValidateCatalogJob(result);
        if (result.Id != jobId) throw new InvalidDataException("The API returned a different catalog job.");
        return result;
    }

    private static void RequireCatalogContract(int version)
    {
        if (version != 1) throw new InvalidDataException("The API does not support this factory catalog contract. Update the API; no fallback action was attempted.");
    }

    private static void ValidateCatalogPlacements(IReadOnlyList<CatalogPlacement> placements)
    {
        if (placements.Count is < 1 or > 3 || placements.Any(placement =>
                placement.Environment is not ("dev" or "stage" or "prod") || string.IsNullOrWhiteSpace(placement.ScaleSetId)) ||
            placements.Select(placement => placement.Environment).Distinct(StringComparer.Ordinal).Count() != placements.Count)
            throw new ArgumentException("Select at most one explicit scale-set placement for each environment.");
    }

    private static void ValidateCatalogRunner(CatalogRunnerSelection runner, string orchestrator)
    {
        var valid = runner.Os == "linux" && (runner.Kind switch
        {
            "hosted" => runner.Image is "ubuntu-latest" or "ubuntu-24.04" or "ubuntu-22.04" &&
                runner.Labels is null && runner.Pool is null && runner.AgentName is null,
            "self-hosted" when orchestrator == "gha" => runner.Image is null && runner.Pool is null &&
                runner.AgentName is null && runner.Labels is { Count: >= 2 and <= 16 } labels &&
                labels.Contains("self-hosted", StringComparer.OrdinalIgnoreCase) && labels.Contains("linux", StringComparer.OrdinalIgnoreCase),
            "self-hosted" when orchestrator == "ado" => runner.Image is null && runner.Labels is null &&
                !string.IsNullOrWhiteSpace(runner.Pool),
            _ => false
        });
        if (!valid) throw new ArgumentException("Select a supported Linux hosted runner or the exact provider's self-hosted runner.");
    }

    private static void ValidateCatalog(FactoryCatalog catalog)
    {
        RequireCatalogContract(catalog.ContractVersion);
        if (catalog.Mode is not ("legacy" or "catalog") || string.IsNullOrWhiteSpace(catalog.Revision))
            throw new InvalidDataException("Catalog scope or revision is missing.");
        if (catalog.Factories.Any(factory => string.IsNullOrWhiteSpace(factory.Id)) ||
            catalog.Factories.Select(factory => factory.Id).Distinct(StringComparer.Ordinal).Count() != catalog.Factories.Count)
            throw new InvalidDataException("Factory catalog identities are missing or ambiguous.");
    }

    private static void ValidateCatalogJob(FactoryCatalogJob job)
    {
        if (string.IsNullOrWhiteSpace(job.Id) || string.IsNullOrWhiteSpace(job.FactoryId) || string.IsNullOrWhiteSpace(job.Status))
            throw new InvalidDataException("The API returned an incomplete catalog job. Reload before taking further action.");
    }
}

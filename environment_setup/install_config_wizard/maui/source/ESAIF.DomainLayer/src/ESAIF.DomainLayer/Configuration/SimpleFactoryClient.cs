using System.Text.Json.Serialization;

namespace ESAIF.DomainLayer.Configuration;

public interface ISimpleFactoryClient
{
    Task<SimpleFactoryOptions> GetSimpleFactoryOptionsAsync(CancellationToken cancellationToken = default);
    Task<SimpleFactoryPlan> PrepareSimpleFactoryAsync(SimpleFactoryDraft draft, CancellationToken cancellationToken = default);
    Task<SimpleFactoryJob> StartSimpleFactoryAsync(string confirmationId, CancellationToken cancellationToken = default);
    Task<SimpleFactoryJob> GetSimpleFactoryJobAsync(string jobId, CancellationToken cancellationToken = default);
}

// Deliberately closed: identity, credentials, script selection and presets belong to the server.
public sealed record SimpleFactoryDraft
{
    [JsonPropertyName("subscription_id")]
    public string SubscriptionId { get; init; } = string.Empty;
    [JsonPropertyName("tenant_id")]
    public string TenantId { get; init; } = string.Empty;
    [JsonPropertyName("location")]
    public string Location { get; init; } = "swedencentral";
    [JsonPropertyName("factory_prefix")]
    public string FactoryPrefix { get; init; } = "aif-";
    [JsonPropertyName("aifactory_version")]
    [JsonIgnore(Condition = JsonIgnoreCondition.WhenWritingNull)]
    public string? FactoryVersion { get; init; }
    [JsonPropertyName("github_repository")]
    public string GithubRepository { get; init; } = string.Empty;
    [JsonPropertyName("github_visibility")]
    public string GithubVisibility { get; init; } = "private";
    [JsonPropertyName("project_resources")]
    public IReadOnlyList<string> ProjectResources { get; init; } = [];
    [JsonPropertyName("app_gateway_hostname")]
    public string AppGatewayHostname { get; init; } = string.Empty;
    [JsonPropertyName("app_gateway_backend_fqdn")]
    public string AppGatewayBackendFqdn { get; init; } = string.Empty;
    [JsonPropertyName("app_gateway_certificate_secret_id")]
    public string AppGatewayCertificateSecretId { get; init; } = string.Empty;
    [JsonPropertyName("team_member_email")]
    public string TeamMemberEmail { get; init; } = string.Empty;
    [JsonPropertyName("team_group_name")]
    public string TeamGroupName { get; init; } = string.Empty;
    [JsonPropertyName("cost_center")]
    public string CostCenter { get; init; } = "123456";
    [JsonPropertyName("repo_root")]
    public string RepoRoot { get; init; } = string.Empty;
}

public sealed record SimpleFactoryAzureAccount
{
    [JsonPropertyName("subscription_id")]
    public string SubscriptionId { get; init; } = string.Empty;
    [JsonPropertyName("subscription_name")]
    public string SubscriptionName { get; init; } = string.Empty;
    [JsonPropertyName("tenant_id")]
    public string TenantId { get; init; } = string.Empty;
    [JsonPropertyName("account_name")]
    public string AccountName { get; init; } = string.Empty;
    [JsonIgnore]
    public string DisplayName => $"{SubscriptionName} · {SubscriptionId}";
}

public sealed record SimpleFactoryOptions
{
    public SimpleFactoryDraft Defaults { get; init; } = new();
    [JsonPropertyName("azure_accounts")]
    public IReadOnlyList<SimpleFactoryAzureAccount> AzureAccounts { get; init; } = [];
    [JsonPropertyName("github_account")]
    public string GithubAccount { get; init; } = string.Empty;
    public IReadOnlyList<string> Regions { get; init; } = [];
    public IReadOnlyList<string> Requirements { get; init; } = [];
    public IReadOnlyList<string> Warnings { get; init; } = [];
    [JsonPropertyName("script_path")]
    public string ScriptPath { get; init; } = string.Empty;
    [JsonPropertyName("resource_catalog")]
    public SimpleFactoryResourceCatalog? ResourceCatalog { get; init; }
}

public sealed record SimpleFactoryResource
{
    public string Id { get; init; } = string.Empty;
    public string Label { get; init; } = string.Empty;
    public string Description { get; init; } = string.Empty;
    public bool Required { get; init; }
    [JsonPropertyName("default_selected")]
    public bool DefaultSelected { get; init; }
    public IReadOnlyList<string> Dependencies { get; init; } = [];
}

public sealed record SimpleFactoryResourceCatalog
{
    public IReadOnlyList<SimpleFactoryResource> Hub { get; init; } = [];
    public IReadOnlyList<SimpleFactoryResource> Common { get; init; } = [];
    public IReadOnlyList<SimpleFactoryResource> Project { get; init; } = [];
}

public sealed record SimpleFactoryPlan : FactoryVersionSelection
{
    [JsonPropertyName("confirmation_id")]
    public string ConfirmationId { get; init; } = string.Empty;
    [JsonPropertyName("can_execute")]
    public bool CanExecute { get; init; }
    public string Summary { get; init; } = string.Empty;
    [JsonPropertyName("script_path")]
    public string ScriptPath { get; init; } = string.Empty;
    public string Command { get; init; } = string.Empty;
    public IReadOnlyDictionary<string, string> Environment { get; init; } = new Dictionary<string, string>();
    public IReadOnlyList<string> Effects { get; init; } = [];
    public IReadOnlyList<string> Requirements { get; init; } = [];
    public IReadOnlyList<string> Warnings { get; init; } = [];
    public IReadOnlyList<string> Blockers { get; init; } = [];
    [JsonPropertyName("resource_catalog")]
    public SimpleFactoryResourceCatalog? ResourceCatalog { get; init; }
    // Keep malformed/unknown expiry readable; the UI must fail closed, not deserialize into a valid plan.
    [JsonPropertyName("expires_at")]
    public string ExpiresAt { get; init; } = string.Empty;
}

public record FactoryVersionSelection
{
    [JsonPropertyName("aifactory_version")]
    [JsonIgnore(Condition = JsonIgnoreCondition.WhenWritingNull)]
    public string? FactoryVersion { get; init; }
    [JsonPropertyName("requested_version")]
    public string? RequestedVersion { get; init; }
    public string Branch { get; init; } = string.Empty;
    [JsonPropertyName("resolved_ref")]
    public string ResolvedRef { get; init; } = string.Empty;

    internal void ValidateExplicitSelection(string requestedVersion, bool requireResolvedRef = true)
    {
        if (FactoryVersion != requestedVersion || string.IsNullOrWhiteSpace(RequestedVersion) ||
            string.IsNullOrWhiteSpace(Branch) ||
            (requireResolvedRef && string.IsNullOrWhiteSpace(ResolvedRef)) ||
            (!string.IsNullOrEmpty(ResolvedRef) && (ResolvedRef.Length != 40 || !ResolvedRef.All(Uri.IsHexDigit))))
            throw VersionAcknowledgementError();
    }

    internal bool SameResolvedSelection(FactoryVersionSelection other) =>
        RequestedVersion == other.RequestedVersion && Branch == other.Branch && ResolvedRef == other.ResolvedRef;

    internal static InvalidOperationException VersionAcknowledgementError() => new(
        "The API did not explicitly acknowledge the selected factory version and exact template reference. Update the API sidecar and review again; nothing was started.");
}

public sealed record SimpleFactoryJob
{
    public string Id { get; init; } = string.Empty;
    public string Status { get; init; } = string.Empty;
    public string Stage { get; init; } = string.Empty;
    public string Message { get; init; } = string.Empty;
    [JsonPropertyName("created_at")]
    public string CreatedAt { get; init; } = string.Empty;
    [JsonPropertyName("updated_at")]
    public string UpdatedAt { get; init; } = string.Empty;
    [JsonPropertyName("exit_code")]
    public int? ExitCode { get; init; }
    [JsonPropertyName("repository_url")]
    public string RepositoryUrl { get; init; } = string.Empty;
    [JsonPropertyName("repo_root")]
    public string RepoRoot { get; init; } = string.Empty;
    public IReadOnlyList<string> Events { get; init; } = [];
    [JsonIgnore]
    public bool IsTerminal => Status is "succeeded" or "failed" or "interrupted";
}

public sealed partial class AiFactoryApiClient : ISimpleFactoryClient
{
    public Task<SimpleFactoryOptions> GetSimpleFactoryOptionsAsync(CancellationToken cancellationToken = default) =>
        SendAsync<SimpleFactoryOptions>(HttpMethod.Get, "/api/v1/simple-mode/options", null, true, cancellationToken);

    public async Task<SimpleFactoryPlan> PrepareSimpleFactoryAsync(SimpleFactoryDraft draft, CancellationToken cancellationToken = default)
    {
        ArgumentNullException.ThrowIfNull(draft);
        var plan = await SendAsync<SimpleFactoryPlan>(HttpMethod.Post, "/api/v1/simple-mode/prepare", draft, true, cancellationToken)
            .ConfigureAwait(false);
        if (draft.FactoryVersion is not null)
            plan.ValidateExplicitSelection(draft.FactoryVersion, plan.CanExecute);
        return plan;
    }

    public Task<SimpleFactoryJob> StartSimpleFactoryAsync(string confirmationId, CancellationToken cancellationToken = default)
    {
        ArgumentException.ThrowIfNullOrWhiteSpace(confirmationId);
        return SendAsync<SimpleFactoryJob>(HttpMethod.Post, "/api/v1/simple-mode/start",
            new { confirmation_id = confirmationId }, true, cancellationToken);
    }

    public Task<SimpleFactoryJob> GetSimpleFactoryJobAsync(string jobId, CancellationToken cancellationToken = default)
    {
        ArgumentException.ThrowIfNullOrWhiteSpace(jobId);
        if (jobId is "." or "..") throw new ArgumentException("Invalid job ID.", nameof(jobId));
        return SendAsync<SimpleFactoryJob>(HttpMethod.Get,
            $"/api/v1/simple-mode/jobs/{Uri.EscapeDataString(jobId)}", null, true, cancellationToken);
    }
}

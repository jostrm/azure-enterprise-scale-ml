using System.Text.Json.Serialization;

namespace ESAIF.DomainLayer.Configuration;

public interface ITicketClient
{
    Task<TicketListResult> ListTicketsAsync(string? aiFactoryFolder = null, CancellationToken cancellationToken = default);
    Task<FactoryTicket> CreateTicketAsync(CreateTicketRequest request, CancellationToken cancellationToken = default);
    Task<FactoryTicket> UpdateTicketAsync(string id, string status, CancellationToken cancellationToken = default);
    Task<FactoryTicket> UpdateTicketAsync(string id, string status, string? severity, CancellationToken cancellationToken = default);
    Task<TicketResourceIdentity> ParseTicketResourceGroupAsync(string resourceGroup, CancellationToken cancellationToken = default);
    Task<TicketConnectionsResult> ListTicketConnectionsAsync(CancellationToken cancellationToken = default);
    Task<TicketConnection> SaveTicketConnectionAsync(TicketConnection request, CancellationToken cancellationToken = default);
    Task<TicketSyncPreview> PreviewTicketSyncAsync(string ticketId, string connectionId, CancellationToken cancellationToken = default);
    Task<FactoryTicket> ConfirmTicketSyncAsync(string confirmationId, CancellationToken cancellationToken = default);
}

public static class TicketChoices
{
    public static IReadOnlyList<string> Types { get; } = ["Request Azure service", "Bug report"];
    public static IReadOnlyList<string> Severities { get; } = ["minor", "major", "blocker"];
    public static IReadOnlyList<string> Statuses { get; } = ["New", "Active", "Solved"];
    public static IReadOnlyList<string> Providers { get; } = ["Jira", "ServiceNow"];
}

public sealed record FactoryTicket
{
    private string? _severity;
    public string Id { get; init; } = string.Empty;
    public string Title { get; init; } = string.Empty;
    public string Description { get; init; } = string.Empty;
    public string Type { get; init; } = string.Empty;
    public string Status { get; init; } = "New";
    public string Severity { get => _severity ?? (Type == "Blocker" ? "blocker" : "minor"); init => _severity = value; }
    [JsonPropertyName("resource_group")]
    public string ResourceGroup { get; init; } = string.Empty;
    public string Environment { get; init; } = string.Empty;
    public string Region { get; init; } = string.Empty;
    [JsonPropertyName("ai_factory_prefix")]
    public string AiFactoryPrefix { get; init; } = string.Empty;
    [JsonPropertyName("ai_factory_suffix")]
    public string AiFactorySuffix { get; init; } = string.Empty;
    [JsonPropertyName("cost_center")]
    public string CostCenter { get; init; } = string.Empty;
    [JsonPropertyName("department_name")]
    public string DepartmentName { get; init; } = string.Empty;
    public string Owner { get; init; } = "Unknown";
    [JsonPropertyName("project_number")]
    public string? ProjectNumber { get; init; }
    [JsonPropertyName("aifactory_folder")]
    public string AiFactoryFolder { get; init; } = string.Empty;
    [JsonPropertyName("requested_service")]
    public string? RequestedService { get; init; }
    [JsonPropertyName("created_at")]
    public string CreatedAt { get; init; } = string.Empty;
    [JsonPropertyName("updated_at")]
    public string UpdatedAt { get; init; } = string.Empty;
    [JsonPropertyName("external_url")]
    public string? ExternalUrl { get; init; }
    [JsonPropertyName("sync_state")]
    public string? SyncState { get; init; }
}

public sealed record TicketListResult
{
    public string Owner { get; init; } = "Unknown";
    public IReadOnlyList<FactoryTicket> Tickets { get; init; } = [];
    public TicketCounts Counts { get; init; } = new();
    public string? Warning { get; init; }
}

public sealed record TicketCounts
{
    [JsonPropertyName("new")]
    public int New { get; init; }
    public int Active { get; init; }
    public int Solved { get; init; }
}

public sealed record CreateTicketRequest
{
    [JsonPropertyName("aifactory_folder")]
    public string? AiFactoryFolder { get; init; }
    [JsonPropertyName("project_number")]
    public string? ProjectNumber { get; init; }
    public string Type { get; init; } = "Request Azure service";
    public string Title { get; init; } = string.Empty;
    public string Description { get; init; } = string.Empty;
    [JsonPropertyName("requested_service")]
    public string? RequestedService { get; init; }
    [JsonIgnore(Condition = JsonIgnoreCondition.WhenWritingNull)]
    public string? Severity { get; init; }
    [JsonPropertyName("resource_group")]
    public string? ResourceGroup { get; init; }
    [JsonPropertyName("cost_center")]
    public string? CostCenter { get; init; }
    [JsonPropertyName("department_name")]
    public string? DepartmentName { get; init; }
}

public sealed record TicketResourceIdentity
{
    [JsonPropertyName("resource_group")]
    public string ResourceGroup { get; init; } = string.Empty;
    public string Environment { get; init; } = string.Empty;
    [JsonPropertyName("project_number")]
    public string ProjectNumber { get; init; } = string.Empty;
    public string Region { get; init; } = string.Empty;
    [JsonPropertyName("ai_factory_prefix")]
    public string AiFactoryPrefix { get; init; } = string.Empty;
    [JsonPropertyName("ai_factory_suffix")]
    public string AiFactorySuffix { get; init; } = string.Empty;
}

public sealed record TicketConnection
{
    [JsonIgnore(Condition = JsonIgnoreCondition.WhenWritingNull)]
    public string? Id { get; init; }
    public string Name { get; init; } = string.Empty;
    public string Provider { get; init; } = "Jira";
    [JsonPropertyName("base_url")]
    public string BaseUrl { get; init; } = string.Empty;
    [JsonPropertyName("project_key")]
    public string? ProjectKey { get; init; }
    public string? Username { get; init; }
    [JsonPropertyName("credential_env")]
    public string CredentialEnv { get; init; } = string.Empty;
}

public sealed record TicketConnectionsResult
{
    public IReadOnlyList<TicketConnection> Connections { get; init; } = [];
}

public sealed record TicketSyncPreview
{
    [JsonPropertyName("confirmation_id")]
    public string ConfirmationId { get; init; } = string.Empty;
    public string Recipient { get; init; } = string.Empty;
    public string Content { get; init; } = string.Empty;
}

public sealed partial class AiFactoryApiClient : ITicketClient
{
    public Task<TicketListResult> ListTicketsAsync(string? aiFactoryFolder = null, CancellationToken cancellationToken = default) =>
        SendAsync<TicketListResult>(HttpMethod.Post, "/api/v1/tickets/list",
            new { aifactory_folder = aiFactoryFolder }, true, cancellationToken);

    public Task<FactoryTicket> CreateTicketAsync(CreateTicketRequest request, CancellationToken cancellationToken = default)
    {
        ArgumentNullException.ThrowIfNull(request);
        if (string.IsNullOrWhiteSpace(request.ResourceGroup))
            ValidateFolder(request.AiFactoryFolder ?? string.Empty);
        ArgumentException.ThrowIfNullOrWhiteSpace(request.Title);
        ArgumentException.ThrowIfNullOrWhiteSpace(request.Description);
        if (!TicketChoices.Types.Contains(request.Type) && request.Type != "Blocker")
            throw new ArgumentException("Choose Request Azure service or Bug report.", nameof(request));
        ValidateTicketSeverity(request.Severity);
        return SendAsync<FactoryTicket>(HttpMethod.Post, "/api/v1/tickets/create", request, true, cancellationToken);
    }

    public Task<FactoryTicket> UpdateTicketAsync(string id, string status, CancellationToken cancellationToken = default) =>
        UpdateTicketAsync(id, status, null, cancellationToken);

    public Task<FactoryTicket> UpdateTicketAsync(string id, string status, string? severity, CancellationToken cancellationToken = default)
    {
        ArgumentException.ThrowIfNullOrWhiteSpace(id);
        if (!TicketChoices.Statuses.Contains(status))
            throw new ArgumentException("Choose New, Active, or Solved.", nameof(status));
        ValidateTicketSeverity(severity);
        var body = new System.Text.Json.Nodes.JsonObject { ["id"] = id, ["status"] = status };
        if (severity is not null) body["severity"] = severity;
        return SendAsync<FactoryTicket>(HttpMethod.Post, "/api/v1/tickets/update", body, true, cancellationToken);
    }

    public Task<TicketResourceIdentity> ParseTicketResourceGroupAsync(string resourceGroup, CancellationToken cancellationToken = default)
    {
        ArgumentException.ThrowIfNullOrWhiteSpace(resourceGroup);
        return SendAsync<TicketResourceIdentity>(HttpMethod.Post, "/api/v1/tickets/resource-group/parse",
            new { resource_group = resourceGroup.Trim() }, true, cancellationToken);
    }

    private static void ValidateTicketSeverity(string? severity)
    {
        if (severity is not null && !TicketChoices.Severities.Contains(severity))
            throw new ArgumentException("Choose minor, major, or blocker.", nameof(severity));
    }
    public Task<TicketConnectionsResult> ListTicketConnectionsAsync(CancellationToken cancellationToken = default) =>
        SendAsync<TicketConnectionsResult>(HttpMethod.Post, "/api/v1/tickets/connections/list", new { }, true, cancellationToken);

    public Task<TicketConnection> SaveTicketConnectionAsync(TicketConnection request, CancellationToken cancellationToken = default)
    {
        ArgumentNullException.ThrowIfNull(request);
        ArgumentException.ThrowIfNullOrWhiteSpace(request.Name);
        ArgumentException.ThrowIfNullOrWhiteSpace(request.CredentialEnv);
        if (!TicketChoices.Providers.Contains(request.Provider))
            throw new ArgumentException("Choose Jira or ServiceNow.", nameof(request));
        if (!Uri.TryCreate(request.BaseUrl, UriKind.Absolute, out var uri) ||
            uri.Scheme != Uri.UriSchemeHttps || !string.IsNullOrEmpty(uri.UserInfo) ||
            !string.IsNullOrEmpty(uri.Query) || !string.IsNullOrEmpty(uri.Fragment))
            throw new ArgumentException("Use an HTTPS connector URL without credentials, a query, or a fragment.", nameof(request));
        return SendAsync<TicketConnection>(HttpMethod.Post, "/api/v1/tickets/connections/save", request, true, cancellationToken);
    }

    public Task<TicketSyncPreview> PreviewTicketSyncAsync(string ticketId, string connectionId, CancellationToken cancellationToken = default)
    {
        ArgumentException.ThrowIfNullOrWhiteSpace(ticketId);
        ArgumentException.ThrowIfNullOrWhiteSpace(connectionId);
        return SendAsync<TicketSyncPreview>(HttpMethod.Post, "/api/v1/tickets/sync/preview",
            new { ticket_id = ticketId, connection_id = connectionId }, true, cancellationToken);
    }

    public Task<FactoryTicket> ConfirmTicketSyncAsync(string confirmationId, CancellationToken cancellationToken = default)
    {
        ArgumentException.ThrowIfNullOrWhiteSpace(confirmationId);
        return SendAsync<FactoryTicket>(HttpMethod.Post, "/api/v1/tickets/sync",
            new { confirmation_id = confirmationId }, true, cancellationToken);
    }
}

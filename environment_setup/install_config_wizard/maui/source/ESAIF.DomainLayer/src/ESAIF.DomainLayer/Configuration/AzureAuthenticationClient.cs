using System.Text.Json.Serialization;

namespace ESAIF.DomainLayer.Configuration;

public interface IAzureAuthenticationClient
{
    Task<AzureAuthenticationStatus> GetAzureAuthenticationStatusAsync(
        string? aiFactoryFolder, CancellationToken cancellationToken = default);
    Task<AzureAuthenticationStatus> LoginToAzureAsync(
        string? aiFactoryFolder, string? tenantId, CancellationToken cancellationToken = default);
    Task<AzureAuthenticationStatus> LogoutFromAzureAsync(
        string? aiFactoryFolder, CancellationToken cancellationToken = default);
    Task<AzureAuthenticationStatus> GetAzureAuthenticationOperationAsync(
        string operationId, CancellationToken cancellationToken = default);
}

public sealed record AzureAuthenticationTenant
{
    [JsonPropertyName("tenant_id")]
    public string TenantId { get; init; } = string.Empty;
    [JsonPropertyName("needs_login")]
    public bool NeedsLogin { get; init; }
    [JsonPropertyName("account_name")]
    public string AccountName { get; init; } = string.Empty;
    public string Message { get; init; } = string.Empty;
}

public sealed record AzureAuthenticationStatus
{
    public string State { get; init; } = "unavailable";
    [JsonPropertyName("is_logged_in")]
    public bool IsLoggedIn { get; init; }
    [JsonPropertyName("account_name")]
    public string AccountName { get; init; } = string.Empty;
    [JsonPropertyName("tenant_id")]
    public string TenantId { get; init; } = string.Empty;
    public string Message { get; init; } = string.Empty;
    public IReadOnlyList<AzureAuthenticationTenant> Tenants { get; init; } = [];
    [JsonPropertyName("operation_id")]
    public string? OperationId { get; init; }
}

public sealed partial class AiFactoryApiClient : IAzureAuthenticationClient
{
    public Task<AzureAuthenticationStatus> GetAzureAuthenticationStatusAsync(
        string? aiFactoryFolder, CancellationToken cancellationToken = default) =>
        SendAsync<AzureAuthenticationStatus>(HttpMethod.Post, "/api/v1/azure/auth/status",
            new { aifactory_folder = AuthenticationFolder(aiFactoryFolder) }, true, cancellationToken);

    public Task<AzureAuthenticationStatus> LoginToAzureAsync(
        string? aiFactoryFolder, string? tenantId, CancellationToken cancellationToken = default)
    {
        if (!string.IsNullOrWhiteSpace(tenantId) && !Guid.TryParse(tenantId, out _))
        {
            throw new ArgumentException("The tenant ID must be a GUID.", nameof(tenantId));
        }
        return SendAsync<AzureAuthenticationStatus>(HttpMethod.Post, "/api/v1/azure/auth/login",
            new { aifactory_folder = AuthenticationFolder(aiFactoryFolder), tenant_id = tenantId }, true, cancellationToken);
    }

    public Task<AzureAuthenticationStatus> LogoutFromAzureAsync(
        string? aiFactoryFolder, CancellationToken cancellationToken = default) =>
        SendAsync<AzureAuthenticationStatus>(HttpMethod.Post, "/api/v1/azure/auth/logout",
            new { aifactory_folder = AuthenticationFolder(aiFactoryFolder) }, true, cancellationToken);

    private static string? AuthenticationFolder(string? folder) =>
        string.IsNullOrWhiteSpace(folder) ? null : folder.Trim();

    public Task<AzureAuthenticationStatus> GetAzureAuthenticationOperationAsync(
        string operationId, CancellationToken cancellationToken = default)
    {
        ArgumentException.ThrowIfNullOrWhiteSpace(operationId);
        return SendAsync<AzureAuthenticationStatus>(HttpMethod.Get,
            $"/api/v1/azure/auth/operations/{Uri.EscapeDataString(operationId)}", null, true, cancellationToken);
    }
}

using System.Text.Json.Serialization;

namespace ESAIF.DomainLayer.Operations;

public sealed record ProjectResourceGroupReference
{
    public string Id { get; init; } = string.Empty;
    public string Name { get; init; } = string.Empty;
    [JsonPropertyName("subscription_id")]
    public string SubscriptionId { get; init; } = string.Empty;
    [JsonPropertyName("tenant_id")]
    public string TenantId { get; init; } = string.Empty;
}

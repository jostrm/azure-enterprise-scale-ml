using System.Text.Json.Serialization;

namespace ESAIF.DomainLayer.Configuration;

public sealed record ProjectDeploymentScope
{
    [JsonPropertyName("prefix_rg")]
    public string PrefixResourceGroup { get; init; } = string.Empty;
    [JsonPropertyName("suffix_rg")]
    public string SuffixResourceGroup { get; init; } = string.Empty;
    public string Region { get; init; } = string.Empty;
    [JsonPropertyName("subscription_ids")]
    public IReadOnlyList<string> SubscriptionIds { get; init; } = [];
}

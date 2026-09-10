using System.Text.Json.Nodes;
using System.Text.Json.Serialization;
using System.Net;
using System.Net.Sockets;

namespace ESAIF.DomainLayer.Configuration;

public interface INetworkPlacementClient
{
    Task<NetworkPlacementPreview> PreviewNetworkPlacementAsync(JsonObject state, CancellationToken cancellationToken = default);
}

public sealed record NetworkPlacementPreview
{
    public string Guidance { get; init; } = string.Empty;
    [JsonPropertyName("is_peerable")]
    public bool IsPeerable { get; init; }
    [JsonPropertyName("can_optimize")]
    public bool CanOptimize { get; init; }
    [JsonPropertyName("optimization_changes")]
    public JsonObject OptimizationChanges { get; init; } = [];
    [JsonPropertyName("optimization_description")]
    public string OptimizationDescription { get; init; } = string.Empty;
}

public static class EnvironmentVNetAddressing
{
    public static string ValidationError(JsonObject state)
    {
        var template = state["common_vnet_cidr"]?.ToString();
        if (string.IsNullOrWhiteSpace(template))
            return "Enter the VNet CIDR template before planning peering.";
        var networks = new List<(string Name, IPNetwork Network)>();
        foreach (var (name, key) in new[]
        {
            ("Dev", "dev_cidr_range"), ("Stage/Test", "test_cidr_range"), ("Prod", "prod_cidr_range")
        })
        {
            var value = state[key]?.ToString();
            if (!int.TryParse(value, out var octet) || octet is < 0 or > 255)
                return $"{name}: enter a valid third octet (0-255).";
            var cidr = template.Replace("XX", octet.ToString(System.Globalization.CultureInfo.InvariantCulture), StringComparison.Ordinal);
            if (!IPNetwork.TryParse(cidr, out var network) || network.BaseAddress.AddressFamily != AddressFamily.InterNetwork ||
                !IPAddress.TryParse(cidr.Split('/')[0], out var address) || !network.BaseAddress.Equals(address))
                return $"{name}: {cidr} is not an aligned IPv4 VNet. XX starts must align to the CIDR size.";
            foreach (var prior in networks)
                if (prior.Network.Contains(network.BaseAddress) || network.Contains(prior.Network.BaseAddress))
                    return $"Cannot peer: {prior.Name} {prior.Network} overlaps {name} {network}. Use non-overlapping XX starts.";
            networks.Add((name, network));
        }
        return string.Empty;
    }

    public static void RequireNonOverlapping(JsonObject state)
    {
        var error = ValidationError(state);
        if (error.Length > 0) throw new InvalidOperationException(error);
    }
}

public static class NetworkPlacementInput
{
    public static IReadOnlyList<string> Keys { get; } = Array.AsReadOnly(new[]
    {
        "scaling-mode", "common_vnet_cidr", "dev_cidr_range", "test_cidr_range", "prod_cidr_range",
        "common_subnet_cidr", "common_subnet_scoring_cidr", "common_pbi_subnet_cidr", "common_bastion_subnet_cidr"
    });
    public static JsonObject Capture(JsonObject state) => new(Keys.Where(state.ContainsKey)
        .Select(key => new KeyValuePair<string, JsonNode?>(key, state[key]?.DeepClone())));
}

public sealed partial class AiFactoryApiClient : INetworkPlacementClient
{
    public Task<NetworkPlacementPreview> PreviewNetworkPlacementAsync(JsonObject state, CancellationToken cancellationToken = default)
    {
        ArgumentNullException.ThrowIfNull(state);
        return SendAsync<NetworkPlacementPreview>(HttpMethod.Post, "/api/v1/network/placement/preview",
            new { state = NetworkPlacementInput.Capture(state) }, true, cancellationToken);
    }
}

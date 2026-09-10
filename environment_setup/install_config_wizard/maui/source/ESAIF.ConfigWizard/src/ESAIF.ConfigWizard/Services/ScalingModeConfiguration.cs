using System.Text.Json.Nodes;
using ESAIF.DomainLayer.Configuration;

namespace ESAIF.ConfigWizard.Services;

public static class ScalingModeConfiguration
{
    public const string Key = "scaling-mode";
    public const string Own = "own-subscriptions";
    public const string Shared = "shared-subscriptions";

    public static string SelectedMode(JsonObject state) => state[Key]?.ToString() ?? Shared;

    public static JsonObject? Profile(FactorySchema? schema, string mode) =>
        schema?.Options["scaling_modes"]?[mode] as JsonObject;

    public static JsonObject Defaults(FactorySchema? schema, string mode) =>
        Profile(schema, mode)?["network_defaults"] is JsonObject { Count: > 0 } defaults &&
        defaults["common_vnet_cidr"] is not null
            ? defaults
            : throw new InvalidOperationException("The API does not provide network defaults for this scaling mode. Reconnect to the updated API.");

    public static bool MatchesProfile(JsonObject state, FactorySchema? schema, string mode) =>
        Profile(schema, mode)?["network_defaults"] is JsonObject { Count: > 0 } defaults &&
        MatchesDefaults(state, defaults);

    public static bool MatchesKnownProfile(JsonObject state, FactorySchema? schema) =>
        schema?.Options["scaling_network_profiles"] is JsonArray profiles
            ? profiles.OfType<JsonObject>().Any(defaults => MatchesDefaults(state, defaults))
            : MatchesProfile(state, schema, Own) || MatchesProfile(state, schema, Shared);

    private static bool MatchesDefaults(JsonObject state, JsonObject defaults) =>
        defaults.Count > 0 && defaults["common_vnet_cidr"] is not null &&
        defaults.All(item => string.Equals(state[item.Key]?.ToString(), item.Value?.ToString(), StringComparison.Ordinal));

    public static void SetMode(JsonObject state, FactorySchema? schema, string mode)
    {
        if (mode is not (Own or Shared))
            throw new ArgumentException("Choose own-subscriptions or shared-subscriptions.");
        var changed = SelectedMode(state) != mode;
        var apply = changed && MatchesKnownProfile(state, schema);
        if (apply) ApplyDefaults(state, schema, mode);
        state[Key] = mode;
    }

    public static void ApplyDefaults(JsonObject state, FactorySchema? schema, string? mode = null)
    {
        var defaults = Defaults(schema, mode ?? SelectedMode(state));
        EnvironmentVNetAddressing.RequireNonOverlapping(defaults);
        foreach (var item in defaults)
            state[item.Key] = item.Value?.DeepClone();
    }

    public static void ApplyOptimization(JsonObject state, JsonObject expected, JsonObject changes)
    {
        if (!JsonNode.DeepEquals(NetworkPlacementInput.Capture(state), expected))
            throw new InvalidOperationException("Network configuration changed. Review a new optimization preview.");
        EnvironmentVNetAddressing.RequireNonOverlapping(expected);
        if (changes.Count == 0 || changes.Any(item =>
            item.Key is not ("dev_cidr_range" or "test_cidr_range" or "prod_cidr_range") ||
            item.Value is not JsonValue value || !value.TryGetValue<string>(out var text) ||
            !int.TryParse(text, out var octet) || octet is < 0 or > 255))
            throw new InvalidDataException("The API returned unsupported network optimization changes.");
        var proposed = NetworkPlacementInput.Capture(state);
        foreach (var item in changes) proposed[item.Key] = item.Value?.DeepClone();
        EnvironmentVNetAddressing.RequireNonOverlapping(proposed);
        foreach (var item in changes) state[item.Key] = item.Value?.DeepClone();
    }
}

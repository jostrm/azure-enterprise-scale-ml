using System.Text.Json.Nodes;
using ESAIF.DomainLayer.Configuration;
using ESAIF.ConfigWizard.ViewModels;

namespace ESAIF.ConfigWizard.Services;

public static class ConfigurationStateEditing
{
    public static void SetValue(JsonObject state, FactorySchema? schema, string key, JsonNode? value)
    {
        if (key == ScalingModeConfiguration.Key)
        {
            ScalingModeConfiguration.SetMode(state, schema, value?.ToString() ?? string.Empty);
            return;
        }
        if (key == HubTopologyViewModel.StateKey)
        {
            var topology = value?.ToString();
            if (topology is not ("standalone" or "own-hub" or "external-hub"))
            {
                throw new ArgumentException("Choose a supported AI Factory hub topology.");
            }
            if (topology == "standalone" && IsPrivate(state, schema))
            {
                throw new InvalidOperationException("Private networking requires an own hub or an external hub.");
            }
            SetFlag(state, HubTopologyViewModel.DnsKey, topology == "external-hub");
            SetFlag(state, HubTopologyViewModel.OwnHubKey, topology == "own-hub");
        }
        if (key == "admin_location" &&
            !string.Equals(state[key]?.ToString(), value?.ToString(), StringComparison.OrdinalIgnoreCase) &&
            schema?.Options["azure_region_suffixes"] is JsonObject suffixes)
        {
            var region = value?.ToString().Trim().ToLowerInvariant() ?? string.Empty;
            // Do not retain a previous region's abbreviation when no default exists.
            state["admin_locationSuffix"] = suffixes[region]?.DeepClone() ?? JsonValue.Create("");
        }
        state[key] = value;
        if (key is HubTopologyViewModel.DnsKey or HubTopologyViewModel.OwnHubKey)
            state[HubTopologyViewModel.StateKey] = HubTopologyViewModel.ChoiceFromState(state);
        if (key == "network_mode" && value is JsonValue jsonValue &&
            jsonValue.TryGetValue<string>(out var mode) &&
            schema?.Options["network_modes"]?[mode] is JsonObject flags)
        {
            foreach (var flag in flags)
            {
                state[flag.Key] = flag.Value?.DeepClone();
            }
        }

    }

    public static void ValidateTopology(JsonObject state, FactorySchema? schema)
    {
        var topology = HubTopologyViewModel.ChoiceFromState(state);
        if (topology.Length == 0)
            throw new InvalidOperationException("The hub flags must be true or false. Choose a hub topology in Start & destination.");
        if (topology == "standalone" && IsPrivate(state, schema))
        {
            throw new InvalidOperationException("Private networking requires an own hub or an external hub. Choose a hub topology in Start & destination.");
        }

    }

    private static void SetFlag(JsonObject state, string key, bool value) =>
        state[key] = state[key] is JsonValue existing && existing.TryGetValue<bool>(out _)
            ? JsonValue.Create(value) : JsonValue.Create(value.ToString().ToLowerInvariant());

    private static bool IsPrivate(JsonObject state, FactorySchema? schema) =>
        schema?.Options["network_modes"]?["private"] is JsonObject flags &&
        NetworkModeViewModel.FlagKeys.All(key =>
            bool.TryParse(state[key]?.ToString(), out var actual) &&
            bool.TryParse(flags[key]?.ToString(), out var expected) && actual == expected);
}

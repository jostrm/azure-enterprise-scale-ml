using System.Text;
using System.Text.Json.Nodes;
using System.Text.RegularExpressions;
using ESAIF.DomainLayer.Configuration;
using ESAIF.ConfigWizard.ViewModels;

namespace ESAIF.ConfigWizard.Services;

public static partial class WizardFieldCatalog
{
    public static IReadOnlyList<string> NetworkAddressFields { get; } = Array.AsReadOnly(new[]
    {
        "common_vnet_cidr", "dev_cidr_range", "test_cidr_range", "prod_cidr_range",
        "common_subnet_name", "common_subnet_cidr", "common_subnet_scoring_cidr",
        "common_pbi_subnet_name", "common_pbi_subnet_cidr",
        "common_bastion_subnet_name", "addBastionHost", "common_bastion_subnet_cidr",
        "vnetNameBase", "vnetResourceGroupBase"
    });
    private static readonly HashSet<string> FoundationFields =
    [
        ScalingModeConfiguration.Key,
        "orchestrator",
        "useSelfHostedBuildAgent",
        "network_mode",
        "centralDnsZoneByPolicyInHub",
        HubTopologyViewModel.OwnHubKey,
        "_save_folder",
        "aifactory-dash-01",
        "_also_update_git",
        "allowPublicAccessWhenBehindVnet",
        "enablePublicGenAIAccess",
        "enablePublicAccessWithPerimeter"
    ];

    private static readonly Dictionary<string, string> KnownLabels =
        new(StringComparer.OrdinalIgnoreCase)
        {
            ["_save_folder"] = "AI Factory folder",
            [ScalingModeConfiguration.Key] = "Scaling mode",
            ["aifactory-dash-01"] = "AI Factory dashboard URL",
            ["_also_update_git"] = "Also update the pipeline variable file",
            ["orchestrator"] = "CI/CD orchestrator",
            ["network_mode"] = "Network mode",
            ["centralDnsZoneByPolicyInHub"] = "AI Factory hub topology",
            [HubTopologyViewModel.OwnHubKey] = "Enable AI Factory Hub",
            ["project_number_000"] = "Project number",
            ["admin_aifactoryPrefixRG"] = "AI Factory resource group prefix",
            ["admin_aifactorySuffixRG"] = "AI Factory resource group suffix",
            ["admin_aiSearchTier"] = "AI Search tier",
            ["admin_semanticSearchTier"] = "Semantic Search tier",
            ["enableAFoundryCaphost"] = "Enable AI Foundry Capability host",
            ["useSelfHostedBuildAgent"] = "CI/CD runner / build agent",
            ["selfHostedRunnerLabel"] = "GitHub runner label",
            ["adminVMBuildAgentName"] = "VM / Azure DevOps agent name",
            ["adminVMBuildAgentPool"] = "Azure DevOps agent pool",
            ["disable_whitelisting_for_build_agents"] = "Disable build-agent IP whitelisting"
        };

    private static readonly HashSet<string> Acronyms =
    [
        "acr", "ado", "ai", "aks", "api", "byo", "cidr", "cmk", "db", "dns",
        "gha", "github", "id", "ip", "kv", "ml", "oid", "rbac", "rg", "sku",
        "sp", "sql", "ui", "url", "uuid", "vnet"
    ];

    public static IReadOnlyList<WizardStepViewModel> Build(
        FactorySchema schema,
        JsonObject state,
        Action<string, JsonNode?> setValue,
        Action? applyScalingDefaults = null,
        INetworkPlacementClient? networkPlacementClient = null,
        Action<JsonObject, JsonObject>? applyNetworkOptimization = null)
    {
        var scaleSetKeys = schema.Sections.ScaleSetVariables.ToHashSet(StringComparer.Ordinal);
        var scaling = schema.Options["scaling_modes"] is JsonObject
            ? new ScalingModeViewModel(schema, state,
                mode => setValue(ScalingModeConfiguration.Key, JsonValue.Create(mode)), applyScalingDefaults,
                networkPlacementClient, applyNetworkOptimization)
            : null;
        var network = schema.Options["network_modes"] is JsonObject modes
            ? new NetworkModeViewModel(modes, state, mode => setValue("network_mode", JsonValue.Create(mode)))
            : null;
        var buckets = Enumerable.Range(0, 8)
            .Select(_ => new List<ConfigFieldViewModel>())
            .ToArray();
        var keys = schema.Defaults
            .Select(item => item.Key)
            .Concat(state.Select(item => item.Key))
            .Distinct(StringComparer.Ordinal)
            .Where(IsUserFacing)
            .Order(StringComparer.OrdinalIgnoreCase);

        var runner = state.ContainsKey(RunnerConfigurationViewModel.SelectionKey) ||
                     schema.Defaults.ContainsKey(RunnerConfigurationViewModel.SelectionKey)
            ? new RunnerConfigurationViewModel(state, enabled =>
                setValue(RunnerConfigurationViewModel.SelectionKey,
                    state[RunnerConfigurationViewModel.SelectionKey] is JsonValue current && current.TryGetValue<bool>(out _)
                        ? JsonValue.Create(enabled) : JsonValue.Create(enabled.ToString().ToLowerInvariant())))
            : null;

        foreach (var key in keys)
        {
            var value = state[key];
            var defaultValue = schema.Defaults[key];
            var field = new ConfigFieldViewModel(
                key,
                Humanize(key),
                key.Equals("admin_location", StringComparison.OrdinalIgnoreCase)
                    ? $"API field: {key}. Changing region applies its default location suffix. If no default exists, enter a suffix manually. Availability depends on your subscription and services."
                    : $"API field: {key}",
                value,
                defaultValue,
                GetOptions(schema, key),
                setValue,
                key == "network_mode" ? network : null,
                key == HubTopologyViewModel.DnsKey
                    ? new HubTopologyViewModel(state, network,
                        topology => setValue(HubTopologyViewModel.StateKey, JsonValue.Create(topology)))
                    : null,
                key == RunnerConfigurationViewModel.SelectionKey ? runner : null,
                key == ScalingModeConfiguration.Key ? scaling : null);
            buckets[GetBucket(key, scaleSetKeys)].Add(field);
        }
        runner?.AttachFields(buckets.SelectMany(fields => fields).ToDictionary(field => field.Key, StringComparer.Ordinal));

        return
        [
            new(1, "Start & destination",
                "Connect the configuration to its orchestrator, network posture, and AI Factory folder.",
                buckets[0].OrderBy(field => field.Key == ScalingModeConfiguration.Key ? -1 :
                    field.Key == "network_mode" ? 0 :
                    field.Key == HubTopologyViewModel.DnsKey ? 1 :
                    field.Key == "orchestrator" ? 2 :
                    field.Key == RunnerConfigurationViewModel.SelectionKey ? 3 : 4)
                    .ThenBy(field => field.Label, StringComparer.OrdinalIgnoreCase)),
            new(2, "Scale set & region",
                "Configure shared subscriptions, regions, and scale-set identity.",
                buckets[1]),
            new(3, "Platform networking",
                "Configure VNet addressing and environment ranges, then subnets, DNS, and service connections.",
                NetworkAddressFields.Select(key => buckets[2].FirstOrDefault(field => field.Key == key))
                    .OfType<ConfigFieldViewModel>()
                    .Concat(buckets[2].Where(field => !NetworkAddressFields.Contains(field.Key))))
                { NetworkFormatHelp = scaling },
            new(4, "Security & governance",
                "Set identity, RBAC, encryption, diagnostics, tags, and cost controls.",
                buckets[3]),
            new(5, "Project",
                "Configure the project identity, pipeline behavior, and project-specific values.",
                PinFirst(buckets[4], "project_number_000")),
            new(6, "Services",
                "Choose deployed services, model settings, and compute options.",
                buckets[5]),
            new(7, "SKUs",
                "Set service tiers separately for Dev and for Stage & Prod.",
                buckets[6],
                isSkuStep: true),
            new(8, "Advanced",
                "Edit remaining API-supported settings without hiding configuration capability.",
                buckets[7]),
            new(9, "Review & save",
                "Validate with the Python API, then save project, scale-set, or exported configuration.",
                [], true)
        ];
    }

    private static int GetBucket(string key, HashSet<string> scaleSetKeys)
    {
        if (key == "enableAFoundryCaphost")
        {
            return 7;
        }
        if (NetworkAddressFields.Contains(key))
        {
            return 2;
        }
        if (FoundationFields.Contains(key) || RunnerConfigurationViewModel.DetailKeys.Contains(key, StringComparer.Ordinal) ||
            key.StartsWith("github_", StringComparison.OrdinalIgnoreCase))
        {
            return 0;
        }

        if (scaleSetKeys.Contains(key))
        {
            return 1;
        }

        var normalized = key.ToLowerInvariant();
        if (ContainsAny(normalized,
                "version", "network", "vnet", "subnet", "cidr", "dns",
                "whitelist", "firewall", "location", "service_connection"))
        {
            return 2;
        }

        if (ContainsAny(normalized,
                "security", "defender", "rbac", "cmk", "keyvault", "auth",
                "tenant", "technical_admin", "cost", "tag_", "diagnostic", "acr_"))
        {
            return 3;
        }

        if (normalized.Contains("project", StringComparison.Ordinal))
        {
            return 4;
        }

        if (IsSkuField(key))
        {
            return 6;
        }

        if (ContainsAny(normalized,
                "enable", "disable", "deploy", "model", "sku", "add",
                "openai", "foundry", "machinelearning", "databricks",
                "cosmos", "postgres", "redis", "sql", "webapp", "function",
                "eventhub", "logicapp", "container"))
        {
            return 5;
        }

        return 7;
    }

    private static IReadOnlyList<string> GetOptions(FactorySchema schema, string key)
    {
        if (key.Equals("admin_location", StringComparison.OrdinalIgnoreCase))
        {
            return GetStringArray(schema.Options, "azure_regions")
                .Distinct(StringComparer.OrdinalIgnoreCase)
                .Order(StringComparer.OrdinalIgnoreCase).ToArray();
        }

        if (key.Equals("orchestrator", StringComparison.OrdinalIgnoreCase))
        {
            return schema.Orchestrators;
        }

        if (key.Equals("network_mode", StringComparison.OrdinalIgnoreCase) &&
            schema.Options["network_modes"] is JsonObject networkModes)
        {
            return networkModes.Select(item => item.Key).ToArray();
        }

        if (key.Equals("admin_aiSearchTier", StringComparison.OrdinalIgnoreCase) ||
            key.Equals("skuAISearchDev", StringComparison.OrdinalIgnoreCase) ||
            key.Equals("skuAISearchStageProd", StringComparison.OrdinalIgnoreCase))
        {
            return GetStringArray(schema.Options, "ai_search_skus");
        }

        if (key.Contains("semanticSearchTier", StringComparison.OrdinalIgnoreCase))
        {
            return GetStringArray(schema.Options, "semantic_skus");
        }

        if (key.Equals("diagnosticSettingLevel", StringComparison.OrdinalIgnoreCase))
        {
            return GetStringArray(schema.Options, "diagnostic_levels");
        }

        if (key.Equals("acr_SKU", StringComparison.OrdinalIgnoreCase))
        {
            return GetStringArray(schema.Options, "acr_skus");
        }

        return [];
    }

    private static IReadOnlyList<string> GetStringArray(JsonObject options, string key)
    {
        return options[key] is JsonArray values
            ? values
                .Select(value => value?.GetValue<string>())
                .Where(value => !string.IsNullOrWhiteSpace(value))
                .Select(value => value!)
                .ToArray()
            : [];
    }

    public static bool IsUserFacing(string key)
    {
        return key != "addAIFoundryHub" &&
               (!key.StartsWith("_", StringComparison.Ordinal) || key == "_also_update_git");
    }

    private static bool ContainsAny(string value, params string[] terms)
    {
        return terms.Any(term => value.Contains(term, StringComparison.Ordinal));
    }

    private static IEnumerable<ConfigFieldViewModel> PinFirst(
        IEnumerable<ConfigFieldViewModel> fields,
        string firstKey)
    {
        return fields
            .OrderBy(field =>
                field.Key.Equals(firstKey, StringComparison.Ordinal) ? 0 : 1)
            .ThenBy(field => field.Label, StringComparer.OrdinalIgnoreCase);
    }

    private static string Humanize(string key)
    {
        if (KnownLabels.TryGetValue(key, out var known))
        {
            return known;
        }

        var displayKey = key.TrimStart('_');
        if (displayKey.StartsWith("sku", StringComparison.OrdinalIgnoreCase))
        {
            displayKey = displayKey[3..];
            displayKey = displayKey.EndsWith("StageProd", StringComparison.Ordinal)
                ? displayKey[..^9]
                : displayKey.EndsWith("Dev", StringComparison.Ordinal)
                    ? displayKey[..^3]
                    : displayKey;
        }

        var spaced = WordBoundaryRegex().Replace(displayKey, " $1");
        var words = spaced
            .Replace('_', ' ')
            .Split(' ', StringSplitOptions.RemoveEmptyEntries);
        var result = new StringBuilder();
        foreach (var word in words)
        {
            if (result.Length > 0)
            {
                result.Append(' ');
            }

            result.Append(Acronyms.Contains(word)
                ? word.ToUpperInvariant()
                : char.ToUpperInvariant(word[0]) + word[1..]);
        }

        return result.ToString();
    }

    private static bool IsSkuField(string key)
    {
        return key.StartsWith("sku", StringComparison.OrdinalIgnoreCase) ||
               key.Equals("admin_aiSearchTier", StringComparison.OrdinalIgnoreCase) ||
               key.Equals("admin_semanticSearchTier", StringComparison.OrdinalIgnoreCase);
    }

    [GeneratedRegex("([A-Z][a-z]+|[A-Z]+(?![a-z]))")]
    private static partial Regex WordBoundaryRegex();
}

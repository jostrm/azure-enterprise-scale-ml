using System.Text.Json;
using System.Text.Json.Nodes;
using System.Text.Json.Serialization;
using ESAIF.BaseLayer.Monitoring;

namespace ESAIF.DomainLayer.Operations;

public sealed record OperationsOverview
{
    private FactorySummary _factory = new();
    private IReadOnlyList<AzureRegionInfo> _regions = [];
    private IReadOnlyList<FactoryProject> _projects = [];
    private IReadOnlyList<AzureResourceGroup> _commonResourceGroups = [];
    private ResourceInventorySummary _resourceInventory = new();
    private MonitoringChartCollection _monitoring = new();
    private IReadOnlyList<OperationConfigResult> _operationConfigs = [];
    private IReadOnlyList<DraftFactoryAction> _factoryActionRequests = [];
    private PromptSummary _promptSummary = new();

    [JsonPropertyName("generated_at")]
    public string GeneratedAt { get; init; } = string.Empty;

    public string Source { get; init; } = string.Empty;

    public string? Warning { get; init; }

    public FactorySummary Factory
    {
        get => _factory;
        init => _factory = value ?? new();
    }

    public IReadOnlyList<AzureRegionInfo> Regions
    {
        get => _regions;
        init => _regions = value ?? [];
    }

    public IReadOnlyList<FactoryProject> Projects
    {
        get => _projects;
        init => _projects = value ?? [];
    }

    [JsonPropertyName("common_resource_groups")]
    public IReadOnlyList<AzureResourceGroup> CommonResourceGroups
    {
        get => _commonResourceGroups;
        init => _commonResourceGroups = value ?? [];
    }

    [JsonPropertyName("resource_inventory")]
    public ResourceInventorySummary ResourceInventory
    {
        get => _resourceInventory;
        init => _resourceInventory = value ?? new();
    }

    public MonitoringChartCollection Monitoring
    {
        get => _monitoring;
        init => _monitoring = value ?? new();
    }

    [JsonPropertyName("operation_configs")]
    public IReadOnlyList<OperationConfigResult> OperationConfigs
    {
        get => _operationConfigs;
        init => _operationConfigs = value ?? [];
    }

    [JsonPropertyName("factory_action_requests")]
    public IReadOnlyList<DraftFactoryAction> FactoryActionRequests
    {
        get => _factoryActionRequests;
        init => _factoryActionRequests = value ?? [];
    }

    [JsonPropertyName("prompt_summary")]
    public PromptSummary PromptSummary
    {
        get => _promptSummary;
        init => _promptSummary = value ?? new();
    }
}

public sealed record FactorySummary
{
    [JsonPropertyName("monitoring_regions")]
    public IReadOnlyList<string> MonitoringRegions { get; init; } = [];

    [JsonPropertyName("dashboard_url")]
    public string DashboardUrl { get; init; } = string.Empty;

    [JsonPropertyName("primary_region")]
    public string PrimaryRegion { get; init; } = string.Empty;

    private IReadOnlyList<string> _activeRegions = [];
    private IReadOnlyDictionary<string, string> _subscriptions =
        new Dictionary<string, string>(StringComparer.Ordinal);
    private IReadOnlyList<string> _subscriptionIds = [];
    private IReadOnlyList<string> _projectNumbers = [];

    public string Folder { get; init; } = string.Empty;

    public string Name { get; init; } = string.Empty;

    public string Orchestrator { get; init; } = string.Empty;

    [JsonPropertyName("active_regions")]
    public IReadOnlyList<string> ActiveRegions
    {
        get => _activeRegions;
        init => _activeRegions = value ?? [];
    }

    public IReadOnlyDictionary<string, string> Subscriptions
    {
        get => _subscriptions;
        init => _subscriptions = value
            ?? new Dictionary<string, string>(StringComparer.Ordinal);
    }

    [JsonPropertyName("subscription_ids")]
    public IReadOnlyList<string> SubscriptionIds
    {
        get => _subscriptionIds;
        init => _subscriptionIds = value ?? [];
    }

    [JsonPropertyName("project_numbers")]
    public IReadOnlyList<string> ProjectNumbers
    {
        get => _projectNumbers;
        init => _projectNumbers = value ?? [];
    }

    [JsonPropertyName("prefix_rg")]
    public string PrefixResourceGroup { get; init; } = string.Empty;

    [JsonPropertyName("suffix_rg")]
    public string SuffixResourceGroup { get; init; } = string.Empty;

    [JsonPropertyName("variables_found")]
    [JsonConverter(typeof(FlexibleBooleanConverter))]
    public bool VariablesFound { get; init; }

    [JsonPropertyName("project_count")]
    [JsonNumberHandling(JsonNumberHandling.AllowReadingFromString)]
    public int ProjectCount { get; init; }

    [JsonPropertyName("resource_group_count")]
    [JsonNumberHandling(JsonNumberHandling.AllowReadingFromString)]
    public int ResourceGroupCount { get; init; }

    [JsonPropertyName("resource_count")]
    [JsonNumberHandling(JsonNumberHandling.AllowReadingFromString)]
    public int ResourceCount { get; init; }
}

public sealed record AzureRegionInfo
{
    private IReadOnlyList<RegionPipelineFinding> _pipelineFindings = [];

    [JsonPropertyName("pipeline_findings")]
    public IReadOnlyList<RegionPipelineFinding> PipelineFindings
    {
        get => _pipelineFindings;
        init => _pipelineFindings = value ?? [];
    }

    public string Name { get; init; } = string.Empty;

    [JsonPropertyName("display_name")]
    public string DisplayName { get; init; } = string.Empty;

    public string Geography { get; init; } = string.Empty;

    [JsonPropertyName("physical_location")]
    public string PhysicalLocation { get; init; } = string.Empty;

    [JsonNumberHandling(JsonNumberHandling.AllowReadingFromString)]
    public double Latitude { get; init; }

    [JsonNumberHandling(JsonNumberHandling.AllowReadingFromString)]
    public double Longitude { get; init; }

    [JsonPropertyName("normalized_latitude")]
    [JsonNumberHandling(JsonNumberHandling.AllowReadingFromString)]
    public double NormalizedLatitude { get; init; }

    [JsonPropertyName("normalized_longitude")]
    [JsonNumberHandling(JsonNumberHandling.AllowReadingFromString)]
    public double NormalizedLongitude { get; init; }

    [JsonPropertyName("has_factory")]
    [JsonConverter(typeof(FlexibleBooleanConverter))]
    public bool HasFactory { get; init; }

    [JsonPropertyName("factory_count")]
    [JsonNumberHandling(JsonNumberHandling.AllowReadingFromString)]
    public int FactoryCount { get; init; }

    [JsonPropertyName("project_count")]
    [JsonNumberHandling(JsonNumberHandling.AllowReadingFromString)]
    public int ProjectCount { get; init; }

    [JsonPropertyName("resource_count")]
    [JsonNumberHandling(JsonNumberHandling.AllowReadingFromString)]
    public int ResourceCount { get; init; }

    [JsonPropertyName("count_status")]
    public string CountStatus { get; init; } = string.Empty;

    [JsonPropertyName("count_details")]
    public string CountDetails { get; init; } = string.Empty;

    public string ProjectCountLabel => CountLabel(ProjectCount);
    public string ResourceCountLabel => CountLabel(ResourceCount);

    private string CountLabel(int count) => CountStatus switch
    {
        "out_of_scope" or "not_collected" => "Not checked",
        "partial" => count > 0 ? $"{count}+" : "Unknown",
        _ => count.ToString()
    };

    public string Status { get; init; } = string.Empty;
}

public sealed record FactoryProject
{
    public string Owner { get; init; } = string.Empty;

    private IReadOnlyList<ProjectEnvironment> _environments = [];

    [JsonPropertyName("project_number")]
    public string ProjectNumber { get; init; } = string.Empty;

    [JsonPropertyName("display_name")]
    public string DisplayName { get; init; } = string.Empty;

    public IReadOnlyList<ProjectEnvironment> Environments
    {
        get => _environments;
        init => _environments = value ?? [];
    }

    [JsonPropertyName("resource_count")]
    [JsonNumberHandling(JsonNumberHandling.AllowReadingFromString)]
    public int ResourceCount { get; init; }
}

public sealed record ProjectEnvironment
{
    private IReadOnlyList<string> _resourceGroups = [];
    private IReadOnlyList<string> _regions = [];
    private IReadOnlyList<ProjectResourceGroupReference> _resourceGroupReferences = [];

    [JsonPropertyName("resource_group_refs")]
    public IReadOnlyList<ProjectResourceGroupReference> ResourceGroupReferences
    {
        get => _resourceGroupReferences;
        init => _resourceGroupReferences = value ?? [];
    }

    public string Environment { get; init; } = string.Empty;

    public string Status { get; init; } = string.Empty;

    [JsonPropertyName("resource_group")]
    public string? ResourceGroup { get; init; }

    [JsonPropertyName("resource_groups")]
    public IReadOnlyList<string> ResourceGroups
    {
        get => _resourceGroups;
        init => _resourceGroups = value ?? [];
    }

    public string? Region { get; init; }

    public IReadOnlyList<string> Regions
    {
        get => _regions;
        init => _regions = value ?? [];
    }

    [JsonPropertyName("subscription_id")]
    public string? SubscriptionId { get; init; }

    [JsonPropertyName("resource_count")]
    [JsonNumberHandling(JsonNumberHandling.AllowReadingFromString)]
    public int ResourceCount { get; init; }
}

public sealed record ResourceInventorySummary
{
    [JsonPropertyName("is_complete")]
    public bool IsComplete { get; init; }

    private IReadOnlyList<string> _subscriptions = [];
    private IReadOnlyList<AzureResourceGroup> _resourceGroups = [];
    private IReadOnlyList<AzureResource> _resources = [];

    public string Source { get; init; } = string.Empty;

    [JsonPropertyName("collected_at")]
    public string? CollectedAt { get; init; }

    public IReadOnlyList<string> Subscriptions
    {
        get => _subscriptions;
        init => _subscriptions = value ?? [];
    }

    [JsonPropertyName("subscription_count")]
    [JsonNumberHandling(JsonNumberHandling.AllowReadingFromString)]
    public int SubscriptionCount { get; init; }

    [JsonPropertyName("resource_group_count")]
    [JsonNumberHandling(JsonNumberHandling.AllowReadingFromString)]
    public int ResourceGroupCount { get; init; }

    [JsonPropertyName("resource_count")]
    [JsonNumberHandling(JsonNumberHandling.AllowReadingFromString)]
    public int ResourceCount { get; init; }

    [JsonPropertyName("resource_groups")]
    public IReadOnlyList<AzureResourceGroup> ResourceGroups
    {
        get => _resourceGroups;
        init => _resourceGroups = value ?? [];
    }

    public IReadOnlyList<AzureResource> Resources
    {
        get => _resources;
        init => _resources = value ?? [];
    }
}

public sealed record AzureResourceGroup
{
    private JsonObject _tags = [];

    public string Id { get; init; } = string.Empty;
    [JsonPropertyName("tenant_id")]
    public string TenantId { get; init; } = string.Empty;

    public string Name { get; init; } = string.Empty;

    public string Location { get; init; } = string.Empty;

    [JsonPropertyName("subscriptionId")]
    public string SubscriptionId { get; init; } = string.Empty;

    public JsonObject Tags
    {
        get => _tags;
        init => _tags = value ?? [];
    }
}

public sealed record AzureResource
{
    private JsonObject _tags = [];

    public string Id { get; init; } = string.Empty;

    public string Name { get; init; } = string.Empty;

    public string Type { get; init; } = string.Empty;

    public string Location { get; init; } = string.Empty;

    [JsonPropertyName("resourceGroup")]
    public string ResourceGroup { get; init; } = string.Empty;

    [JsonPropertyName("subscriptionId")]
    public string SubscriptionId { get; init; } = string.Empty;

    [JsonPropertyName("provisioningState")]
    public string? ProvisioningState { get; init; }

    public JsonObject Tags
    {
        get => _tags;
        init => _tags = value ?? [];
    }
}

public sealed record MonitoringChartCollection
{
    private ChartDataSet _resourcesByServiceType = new();
    private ChartDataSet _resourcesByEnvironment = new();
    private ChartDataSet _resourcesByRegion = new();
    private ChartDataSet _topResourceGroups = new();
    private ChartDataSet _provisioningState = new();
    private ChartDataSet _snapshotHistory = new();
    private ChartDataSet _requestsOverTime = new();
    private ChartDataSet _tokensOverTime = new();
    private ChartDataSet _requestsByModel = new();
    private ChartDataSet _tokensByModel = new();
    private ChartDataSet _successErrorRate = new();
    private ChartDataSet _latencyTrend = new();

    [JsonPropertyName("resources_by_service_type")]
    public ChartDataSet ResourcesByServiceType
    {
        get => _resourcesByServiceType;
        init => _resourcesByServiceType = value ?? new();
    }

    [JsonPropertyName("resources_by_environment")]
    public ChartDataSet ResourcesByEnvironment
    {
        get => _resourcesByEnvironment;
        init => _resourcesByEnvironment = value ?? new();
    }

    [JsonPropertyName("resources_by_region")]
    public ChartDataSet ResourcesByRegion
    {
        get => _resourcesByRegion;
        init => _resourcesByRegion = value ?? new();
    }

    [JsonPropertyName("top_resource_groups")]
    public ChartDataSet TopResourceGroups
    {
        get => _topResourceGroups;
        init => _topResourceGroups = value ?? new();
    }

    [JsonPropertyName("provisioning_state")]
    public ChartDataSet ProvisioningState
    {
        get => _provisioningState;
        init => _provisioningState = value ?? new();
    }

    [JsonPropertyName("snapshot_history")]
    public ChartDataSet SnapshotHistory
    {
        get => _snapshotHistory;
        init => _snapshotHistory = value ?? new();
    }

    [JsonPropertyName("requests_over_time")]
    public ChartDataSet RequestsOverTime
    {
        get => _requestsOverTime;
        init => _requestsOverTime = value ?? new();
    }

    [JsonPropertyName("tokens_over_time")]
    public ChartDataSet TokensOverTime
    {
        get => _tokensOverTime;
        init => _tokensOverTime = value ?? new();
    }

    [JsonPropertyName("requests_by_model")]
    public ChartDataSet RequestsByModel
    {
        get => _requestsByModel;
        init => _requestsByModel = value ?? new();
    }

    [JsonPropertyName("tokens_by_model")]
    public ChartDataSet TokensByModel
    {
        get => _tokensByModel;
        init => _tokensByModel = value ?? new();
    }

    [JsonPropertyName("success_error_rate")]
    public ChartDataSet SuccessErrorRate
    {
        get => _successErrorRate;
        init => _successErrorRate = value ?? new();
    }

    [JsonPropertyName("latency_trend")]
    public ChartDataSet LatencyTrend
    {
        get => _latencyTrend;
        init => _latencyTrend = value ?? new();
    }
}

public sealed record PromptSummary
{
    private IReadOnlyList<string> _models = [];
    private IReadOnlyList<string> _categories = [];

    public string Source { get; init; } = string.Empty;

    [JsonPropertyName("record_count")]
    [JsonNumberHandling(JsonNumberHandling.AllowReadingFromString)]
    public int RecordCount { get; init; }

    [JsonPropertyName("success_count")]
    [JsonNumberHandling(JsonNumberHandling.AllowReadingFromString)]
    public int SuccessCount { get; init; }

    [JsonPropertyName("error_count")]
    [JsonNumberHandling(JsonNumberHandling.AllowReadingFromString)]
    public int ErrorCount { get; init; }

    [JsonPropertyName("input_tokens")]
    [JsonNumberHandling(JsonNumberHandling.AllowReadingFromString)]
    public long InputTokens { get; init; }

    [JsonPropertyName("cached_input_tokens")]
    [JsonNumberHandling(JsonNumberHandling.AllowReadingFromString)]
    public long CachedInputTokens { get; init; }

    [JsonPropertyName("output_tokens")]
    [JsonNumberHandling(JsonNumberHandling.AllowReadingFromString)]
    public long OutputTokens { get; init; }

    public IReadOnlyList<string> Models
    {
        get => _models;
        init => _models = value ?? [];
    }

    public IReadOnlyList<string> Categories
    {
        get => _categories;
        init => _categories = value ?? [];
    }
}

public sealed record OperationConfigResult
{
    private JsonObject _config = [];

    [JsonPropertyName("aifactory_folder")]
    public string? AiFactoryFolder { get; init; }

    [JsonPropertyName("project_number")]
    public string ProjectNumber { get; init; } = string.Empty;

    public string Environment { get; init; } = string.Empty;

    public string Kind { get; init; } = string.Empty;

    public JsonObject Config
    {
        get => _config;
        init => _config = value ?? [];
    }

    [JsonPropertyName("is_saved")]
    [JsonConverter(typeof(FlexibleBooleanConverter))]
    public bool IsSaved { get; init; }

    [JsonPropertyName("updated_at")]
    public string? UpdatedAt { get; init; }
}

public record DraftFactoryAction
{
    [JsonPropertyName("request_id")]
    public string RequestId { get; init; } = string.Empty;

    [JsonPropertyName("aifactory_folder")]
    public string AiFactoryFolder { get; init; } = string.Empty;

    public string Action { get; init; } = string.Empty;

    [JsonPropertyName("target_region")]
    public string TargetRegion { get; init; } = string.Empty;

    [JsonPropertyName("source_region")]
    public string? SourceRegion { get; init; }

    public string Status { get; init; } = string.Empty;

    [JsonPropertyName("created_at")]
    public string CreatedAt { get; init; } = string.Empty;

    public string Message { get; init; } = string.Empty;
}

public sealed record DraftProjectAction : DraftFactoryAction
{
    [JsonPropertyName("request_type")]
    public string RequestType { get; init; } = string.Empty;

    [JsonPropertyName("project_number")]
    public string ProjectNumber { get; init; } = string.Empty;

    [JsonPropertyName("source_environment")]
    public string SourceEnvironment { get; init; } = string.Empty;

    [JsonPropertyName("target_environment")]
    public string TargetEnvironment { get; init; } = string.Empty;
}

public sealed record OperationsRegionsResult
{
    private IReadOnlyList<AzureRegionInfo> _regions = [];

    public IReadOnlyList<AzureRegionInfo> Regions
    {
        get => _regions;
        init => _regions = value ?? [];
    }

    [JsonNumberHandling(JsonNumberHandling.AllowReadingFromString)]
    public int Count { get; init; }
}

public sealed record OperationsPromptSearchResult
{
    private IReadOnlyList<PromptTelemetryRecord> _rows = [];
    private PromptFilterMetadata _filters = new();
    private PromptSummary _summary = new();

    public IReadOnlyList<PromptTelemetryRecord> Rows
    {
        get => _rows;
        init => _rows = value ?? [];
    }

    [JsonNumberHandling(JsonNumberHandling.AllowReadingFromString)]
    public int Total { get; init; }

    [JsonNumberHandling(JsonNumberHandling.AllowReadingFromString)]
    public int Limit { get; init; }

    [JsonNumberHandling(JsonNumberHandling.AllowReadingFromString)]
    public int Offset { get; init; }

    public string Source { get; init; } = string.Empty;

    public string? Warning { get; init; }

    public PromptFilterMetadata Filters
    {
        get => _filters;
        init => _filters = value ?? new();
    }

    public PromptSummary Summary
    {
        get => _summary;
        init => _summary = value ?? new();
    }
}

internal sealed class FlexibleBooleanConverter : JsonConverter<bool>
{
    public override bool Read(
        ref Utf8JsonReader reader,
        Type typeToConvert,
        JsonSerializerOptions options)
    {
        return reader.TokenType switch
        {
            JsonTokenType.True => true,
            JsonTokenType.False => false,
            JsonTokenType.Number when reader.TryGetInt64(out var value) => value != 0,
            JsonTokenType.String => Parse(reader.GetString()),
            JsonTokenType.Null => false,
            _ => throw new JsonException("Expected a boolean, boolean string, or number.")
        };
    }

    public override void Write(
        Utf8JsonWriter writer,
        bool value,
        JsonSerializerOptions options)
    {
        writer.WriteBooleanValue(value);
    }

    private static bool Parse(string? value)
    {
        return value?.Trim().ToLowerInvariant() switch
        {
            "true" or "1" or "yes" => true,
            "false" or "0" or "no" or "" or null => false,
            _ => throw new JsonException($"'{value}' is not a recognized boolean value.")
        };
    }
}

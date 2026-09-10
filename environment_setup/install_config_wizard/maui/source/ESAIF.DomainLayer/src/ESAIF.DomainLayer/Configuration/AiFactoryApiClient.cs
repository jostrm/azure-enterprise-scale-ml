using System.Net.Http.Json;
using System.Text.Json;
using System.Text.Json.Nodes;
using System.Text.Json.Serialization;
using ESAIF.BaseLayer.Networking;
using ESAIF.DomainLayer.Operations;

namespace ESAIF.DomainLayer.Configuration;

public sealed partial class AiFactoryApiClient : IAiFactoryApiClient, IFactoryConfigurationClient
{
    private const string ApiKeyHeader = "X-API-Key";
    private static readonly JsonSerializerOptions SerializerOptions = new(JsonSerializerDefaults.Web);
    private static readonly HashSet<string> Environments =
        ["dev", "stage", "prod"];
    private static readonly HashSet<string> OperationKinds =
        ["dataops", "mlops", "rag", "finetuning"];
    private static readonly HashSet<string> FactoryActions =
        ["create", "clone", "delete"];
    private static readonly HashSet<string> ProjectActions =
        ["promote", "deploy", "promotion", "deployment"];
    private static readonly HashSet<string> PromptCategories =
    [
        "Coding",
        "Data/Analytics",
        "MLOps",
        "Operations",
        "Security/Governance",
        "Search/RAG",
        "Content/Communication",
        "Planning",
        "General"
    ];
    private readonly IJsonApiTransport _transport;
    private readonly IAiFactoryConnectionProvider _connectionProvider;

    public AiFactoryApiClient(
        IJsonApiTransport transport,
        IAiFactoryConnectionProvider connectionProvider)
    {
        ArgumentNullException.ThrowIfNull(transport);
        ArgumentNullException.ThrowIfNull(connectionProvider);
        _transport = transport;
        _connectionProvider = connectionProvider;
    }

    public Task<HealthStatus> GetHealthAsync(CancellationToken cancellationToken = default)
    {
        return SendAsync<HealthStatus>(HttpMethod.Get, "/health", null, false, cancellationToken);
    }

    public Task<FactorySchema> GetSchemaAsync(CancellationToken cancellationToken = default)
    {
        return SendAsync<FactorySchema>(
            HttpMethod.Get,
            "/api/v1/schema",
            null,
            true,
            cancellationToken);
    }

    public Task<StateResult> GetDefaultsAsync(
        JsonObject state,
        CancellationToken cancellationToken = default)
    {
        return SendAsync<StateResult>(
            HttpMethod.Post,
            "/api/v1/state/defaults",
            new StateRequest(state),
            true,
            cancellationToken);
    }

    public Task<ValidationResult> ValidateAsync(
        JsonObject state,
        CancellationToken cancellationToken = default)
    {
        return SendAsync<ValidationResult>(
            HttpMethod.Post,
            "/api/v1/validation",
            new StateRequest(state),
            true,
            cancellationToken);
    }

    public Task<ImportResult> ImportAsync(
        string format,
        string content,
        JsonObject state,
        CancellationToken cancellationToken = default)
    {
        return SendAsync<ImportResult>(
            HttpMethod.Post,
            "/api/v1/import",
            new ImportRequest(state, NormalizeFormat(format), content, null),
            true,
            cancellationToken);
    }

    public Task<ExportResult> ExportAsync(
        string format,
        JsonObject state,
        string? destinationPath = null,
        CancellationToken cancellationToken = default)
    {
        return SendAsync<ExportResult>(
            HttpMethod.Post,
            "/api/v1/export",
            new ExportRequest(state, NormalizeFormat(format), destinationPath),
            true,
            cancellationToken);
    }

    public Task<StartupLoadResult> LoadStartupAsync(
        string aiFactoryFolder,
        string projectNumber,
        CancellationToken cancellationToken = default)
    {
        return SendAsync<StartupLoadResult>(
            HttpMethod.Post,
            "/api/v1/startup/load",
            new ProjectRequest(aiFactoryFolder, projectNumber),
            true,
            cancellationToken);
    }

    public Task<ProjectsResult> GetProjectsAsync(
        string aiFactoryFolder,
        CancellationToken cancellationToken = default)
    {
        return SendAsync<ProjectsResult>(
            HttpMethod.Post,
            "/api/v1/projects",
            new FolderRequest(aiFactoryFolder),
            true,
            cancellationToken);
    }

    public Task<ProjectLoadResult> LoadProjectAsync(
        string aiFactoryFolder,
        string projectNumber,
        CancellationToken cancellationToken = default)
    {
        return SendAsync<ProjectLoadResult>(
            HttpMethod.Post,
            "/api/v1/projects/load",
            new ProjectRequest(aiFactoryFolder, projectNumber),
            true,
            cancellationToken);
    }

    public Task<ProjectSaveResult> SaveProjectAsync(
        JsonObject state,
        bool writeVariables = true,
        CancellationToken cancellationToken = default)
    {
        return SendAsync<ProjectSaveResult>(
            HttpMethod.Post,
            "/api/v1/projects/save",
            new ProjectSaveRequest(state, writeVariables),
            true,
            cancellationToken);
    }

    public Task<ScaleSetsResult> GetScaleSetsAsync(
        string aiFactoryFolder,
        CancellationToken cancellationToken = default)
    {
        return SendAsync<ScaleSetsResult>(
            HttpMethod.Post,
            "/api/v1/scale-sets",
            new FolderRequest(aiFactoryFolder),
            true,
            cancellationToken);
    }

    public Task<ScaleSetLoadResult> LoadScaleSetAsync(
        string aiFactoryFolder,
        string scaleSetId,
        CancellationToken cancellationToken = default)
    {
        return SendAsync<ScaleSetLoadResult>(
            HttpMethod.Post,
            "/api/v1/scale-sets/load",
            new ScaleSetRequest(aiFactoryFolder, scaleSetId),
            true,
            cancellationToken);
    }

    public Task<PathResult> SaveScaleSetAsync(
        JsonObject state,
        CancellationToken cancellationToken = default)
    {
        return SendAsync<PathResult>(
            HttpMethod.Post,
            "/api/v1/scale-sets/save",
            new StateRequest(state),
            true,
            cancellationToken);
    }

    public Task<RecentProjectsResult> GetRecentProjectsAsync(
        CancellationToken cancellationToken = default)
    {
        return SendAsync<RecentProjectsResult>(
            HttpMethod.Get,
            "/api/v1/recent-projects",
            null,
            true,
            cancellationToken);
    }

    public Task<RecentProjectsResult> RecordRecentProjectAsync(
        string aiFactoryFolder,
        string projectNumber,
        string orchestrator,
        string prefixResourceGroup,
        string suffixResourceGroup,
        CancellationToken cancellationToken = default)
    {
        return SendAsync<RecentProjectsResult>(
            HttpMethod.Post,
            "/api/v1/recent-projects",
            new RecentProjectRequest(
                aiFactoryFolder,
                projectNumber,
                orchestrator,
                prefixResourceGroup,
                suffixResourceGroup),
            true,
            cancellationToken);
    }

    public Task<OperationsOverview> GetOperationsOverviewAsync(
        string aiFactoryFolder,
        bool includeAzure = true,
        bool forceRefresh = false,
        CancellationToken cancellationToken = default)
    {
        ValidateFolder(aiFactoryFolder);
        return SendAsync<OperationsOverview>(
            HttpMethod.Post,
            "/api/v1/operations/overview",
            new OperationsOverviewRequest(aiFactoryFolder, includeAzure, forceRefresh),
            true,
            cancellationToken);
    }

    public Task<OperationsRegionsResult> GetOperationsRegionsAsync(
        CancellationToken cancellationToken = default)
    {
        return SendAsync<OperationsRegionsResult>(
            HttpMethod.Get,
            "/api/v1/operations/regions",
            null,
            true,
            cancellationToken);
    }

    public Task<OperationConfigResult> LoadOperationsConfigAsync(
        string aiFactoryFolder,
        string projectNumber,
        string environment,
        string kind,
        CancellationToken cancellationToken = default)
    {
        ValidateOperationsConfig(aiFactoryFolder, projectNumber, environment, kind);
        return SendAsync<OperationConfigResult>(
            HttpMethod.Post,
            "/api/v1/operations/config/load",
            new OperationsConfigRequest(
                aiFactoryFolder,
                projectNumber,
                environment,
                kind),
            true,
            cancellationToken);
    }

    public Task<OperationConfigResult> SaveOperationsConfigAsync(
        string aiFactoryFolder,
        string projectNumber,
        string environment,
        string kind,
        JsonObject config,
        CancellationToken cancellationToken = default)
    {
        ValidateOperationsConfig(aiFactoryFolder, projectNumber, environment, kind);
        ArgumentNullException.ThrowIfNull(config);
        return SendAsync<OperationConfigResult>(
            HttpMethod.Post,
            "/api/v1/operations/config/save",
            new OperationsConfigSaveRequest(
                aiFactoryFolder,
                projectNumber,
                environment,
                kind,
                config),
            true,
            cancellationToken);
    }

    public Task<DraftFactoryAction> CreateFactoryActionAsync(
        string aiFactoryFolder,
        string action,
        string targetRegion,
        string? sourceRegion = null,
        CancellationToken cancellationToken = default)
    {
        ValidateFolder(aiFactoryFolder);
        ValidateSet(action, FactoryActions, nameof(action));
        ValidateRegion(targetRegion, nameof(targetRegion));
        if (sourceRegion is not null)
        {
            ValidateRegion(sourceRegion, nameof(sourceRegion));
        }

        if (string.Equals(action, "clone", StringComparison.Ordinal) &&
            string.IsNullOrWhiteSpace(sourceRegion))
        {
            throw new ArgumentException(
                "A source region is required for a clone action.",
                nameof(sourceRegion));
        }

        return SendAsync<DraftFactoryAction>(
            HttpMethod.Post,
            "/api/v1/operations/factory-actions",
            new FactoryActionRequest(
                aiFactoryFolder,
                action,
                targetRegion,
                sourceRegion),
            true,
            cancellationToken);
    }

    public Task<DraftProjectAction> CreateProjectActionAsync(
        string aiFactoryFolder,
        string projectNumber,
        string sourceEnvironment,
        string targetEnvironment,
        string action,
        CancellationToken cancellationToken = default)
    {
        ValidateFolder(aiFactoryFolder);
        ValidateProjectNumber(projectNumber);
        ValidateSet(sourceEnvironment, Environments, nameof(sourceEnvironment));
        ValidateSet(targetEnvironment, Environments, nameof(targetEnvironment));
        ValidateSet(action, ProjectActions, nameof(action));
        if (string.Equals(
            sourceEnvironment,
            targetEnvironment,
            StringComparison.Ordinal))
        {
            throw new ArgumentException(
                "Source and target environments must differ.",
                nameof(targetEnvironment));
        }

        return SendAsync<DraftProjectAction>(
            HttpMethod.Post,
            "/api/v1/operations/project-actions",
            new ProjectActionRequest(
                aiFactoryFolder,
                projectNumber,
                sourceEnvironment,
                targetEnvironment,
                action),
            true,
            cancellationToken);
    }

    public Task<OperationsPromptSearchResult> SearchPromptsAsync(
        string aiFactoryFolder,
        string? projectNumber = null,
        string? environment = null,
        string? model = null,
        string? category = null,
        string? search = null,
        bool? success = null,
        int limit = 100,
        int offset = 0,
        CancellationToken cancellationToken = default)
    {
        ValidateFolder(aiFactoryFolder);
        if (projectNumber is not null)
        {
            ValidateProjectNumber(projectNumber);
        }

        if (environment is not null)
        {
            ValidateSet(environment, Environments, nameof(environment));
        }

        if (category is not null)
        {
            ValidateSet(category, PromptCategories, nameof(category));
        }

        if (model?.Length > 200)
        {
            throw new ArgumentException(
                "Model cannot exceed 200 characters.",
                nameof(model));
        }

        if (search?.Length > 500)
        {
            throw new ArgumentException(
                "Search cannot exceed 500 characters.",
                nameof(search));
        }

        if (limit is < 1 or > 500)
        {
            throw new ArgumentOutOfRangeException(
                nameof(limit),
                limit,
                "Limit must be between 1 and 500.");
        }

        if (offset < 0)
        {
            throw new ArgumentOutOfRangeException(
                nameof(offset),
                offset,
                "Offset cannot be negative.");
        }

        return SendAsync<OperationsPromptSearchResult>(
            HttpMethod.Post,
            "/api/v1/operations/prompts/search",
            new PromptSearchRequest(
                aiFactoryFolder,
                projectNumber,
                environment,
                model,
                category,
                search,
                success,
                limit,
                offset),
            true,
            cancellationToken);
    }

    private async Task<TResponse> SendAsync<TResponse>(
        HttpMethod method,
        string path,
        object? body,
        bool secured,
        CancellationToken cancellationToken)
    {
        var connection = await _connectionProvider.GetConnectionAsync(cancellationToken);
        using var request = new HttpRequestMessage(
            method,
            new Uri(connection.BaseUri, path.TrimStart('/')));

        if (secured)
        {
            if (string.IsNullOrWhiteSpace(connection.ApiKey))
            {
                throw new InvalidOperationException(
                    "Enter the API key configured for the Python AIFactory API.");
            }

            request.Headers.Add(ApiKeyHeader, connection.ApiKey);
        }

        if (body is not null)
        {
            request.Content = JsonContent.Create(body, options: SerializerOptions);
        }

        return await _transport.SendAsync<TResponse>(request, cancellationToken);
    }

    private static string NormalizeFormat(string format)
    {
        var normalized = format.Trim().TrimStart('.').ToLowerInvariant();
        return normalized switch
        {
            "yml" => "yaml",
            "yaml" or "env" or "json" => normalized,
            _ => throw new ArgumentOutOfRangeException(
                nameof(format),
                format,
                "Supported formats are yaml, env, and json.")
        };
    }

    private static void ValidateOperationsConfig(
        string aiFactoryFolder,
        string projectNumber,
        string environment,
        string kind)
    {
        ValidateFolder(aiFactoryFolder);
        ValidateProjectNumber(projectNumber);
        ValidateSet(environment, Environments, nameof(environment));
        ValidateSet(kind, OperationKinds, nameof(kind));
    }

    private static void ValidateFolder(string aiFactoryFolder)
    {
        if (string.IsNullOrWhiteSpace(aiFactoryFolder))
        {
            throw new ArgumentException(
                "The AIFactory folder is required.",
                nameof(aiFactoryFolder));
        }
    }

    private static void ValidateProjectNumber(string projectNumber)
    {
        if (string.IsNullOrWhiteSpace(projectNumber) ||
            projectNumber.Length > 6 ||
            projectNumber.Any(character => !char.IsAsciiDigit(character)))
        {
            throw new ArgumentException(
                "Project number must contain between one and six digits.",
                nameof(projectNumber));
        }
    }

    private static void ValidateSet(
        string value,
        IReadOnlySet<string> allowedValues,
        string parameterName)
    {
        if (!allowedValues.Contains(value))
        {
            throw new ArgumentOutOfRangeException(
                parameterName,
                value,
                $"Supported values are {string.Join(", ", allowedValues)}.");
        }
    }

    private static void ValidateRegion(string region, string parameterName)
    {
        if (string.IsNullOrWhiteSpace(region) ||
            region.Any(character =>
                !char.IsAsciiLetterLower(character) &&
                !char.IsAsciiDigit(character)))
        {
            throw new ArgumentException(
                "Azure regions must contain only lowercase letters and digits.",
                parameterName);
        }
    }

    private sealed record StateRequest(
        [property: JsonPropertyName("state")] JsonObject State);

    private sealed record ImportRequest(
        [property: JsonPropertyName("state")] JsonObject State,
        [property: JsonPropertyName("format")] string Format,
        [property: JsonPropertyName("content")] string Content,
        [property: JsonPropertyName("path")] string? Path);

    private sealed record ExportRequest(
        [property: JsonPropertyName("state")] JsonObject State,
        [property: JsonPropertyName("format")] string Format,
        [property: JsonPropertyName("path")] string? Path);

    private sealed record FolderRequest(
        [property: JsonPropertyName("aifactory_folder")] string AiFactoryFolder);

    private sealed record ProjectRequest(
        [property: JsonPropertyName("aifactory_folder")] string AiFactoryFolder,
        [property: JsonPropertyName("project_number")] string ProjectNumber);

    private sealed record ProjectSaveRequest(
        [property: JsonPropertyName("state")] JsonObject State,
        [property: JsonPropertyName("write_variables")] bool WriteVariables);

    private sealed record ScaleSetRequest(
        [property: JsonPropertyName("aifactory_folder")] string AiFactoryFolder,
        [property: JsonPropertyName("scale_set_id")] string ScaleSetId);

    private sealed record RecentProjectRequest(
        [property: JsonPropertyName("aifactory_folder")] string AiFactoryFolder,
        [property: JsonPropertyName("project_number")] string ProjectNumber,
        [property: JsonPropertyName("orchestrator")] string Orchestrator,
        [property: JsonPropertyName("prefix_rg")] string PrefixResourceGroup,
        [property: JsonPropertyName("suffix_rg")] string SuffixResourceGroup);

    private sealed record OperationsOverviewRequest(
        [property: JsonPropertyName("aifactory_folder")] string AiFactoryFolder,
        [property: JsonPropertyName("include_azure")] bool IncludeAzure,
        [property: JsonPropertyName("force_refresh")] bool ForceRefresh);

    private sealed record OperationsConfigRequest(
        [property: JsonPropertyName("aifactory_folder")] string AiFactoryFolder,
        [property: JsonPropertyName("project_number")] string ProjectNumber,
        [property: JsonPropertyName("environment")] string Environment,
        [property: JsonPropertyName("kind")] string Kind);

    private sealed record OperationsConfigSaveRequest(
        [property: JsonPropertyName("aifactory_folder")] string AiFactoryFolder,
        [property: JsonPropertyName("project_number")] string ProjectNumber,
        [property: JsonPropertyName("environment")] string Environment,
        [property: JsonPropertyName("kind")] string Kind,
        [property: JsonPropertyName("config")] JsonObject Config);

    private sealed record FactoryActionRequest(
        [property: JsonPropertyName("aifactory_folder")] string AiFactoryFolder,
        [property: JsonPropertyName("action")] string Action,
        [property: JsonPropertyName("target_region")] string TargetRegion,
        [property: JsonPropertyName("source_region")]
        [property: JsonIgnore(Condition = JsonIgnoreCondition.WhenWritingNull)]
        string? SourceRegion);

    private sealed record ProjectActionRequest(
        [property: JsonPropertyName("aifactory_folder")] string AiFactoryFolder,
        [property: JsonPropertyName("project_number")] string ProjectNumber,
        [property: JsonPropertyName("source_environment")] string SourceEnvironment,
        [property: JsonPropertyName("target_environment")] string TargetEnvironment,
        [property: JsonPropertyName("action")] string Action);

    private sealed record PromptSearchRequest(
        [property: JsonPropertyName("aifactory_folder")] string AiFactoryFolder,
        [property: JsonPropertyName("project_number")]
        [property: JsonIgnore(Condition = JsonIgnoreCondition.WhenWritingNull)]
        string? ProjectNumber,
        [property: JsonPropertyName("environment")]
        [property: JsonIgnore(Condition = JsonIgnoreCondition.WhenWritingNull)]
        string? Environment,
        [property: JsonPropertyName("model")]
        [property: JsonIgnore(Condition = JsonIgnoreCondition.WhenWritingNull)]
        string? Model,
        [property: JsonPropertyName("category")]
        [property: JsonIgnore(Condition = JsonIgnoreCondition.WhenWritingNull)]
        string? Category,
        [property: JsonPropertyName("search")]
        [property: JsonIgnore(Condition = JsonIgnoreCondition.WhenWritingNull)]
        string? Search,
        [property: JsonPropertyName("success")]
        [property: JsonIgnore(Condition = JsonIgnoreCondition.WhenWritingNull)]
        bool? Success,
        [property: JsonPropertyName("limit")] int Limit,
        [property: JsonPropertyName("offset")] int Offset);
}

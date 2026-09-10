using System.Text.Json.Nodes;
using ESAIF.DomainLayer.Operations;

namespace ESAIF.DomainLayer.Configuration;

public interface IAiFactoryApiClient
{
    Task<HealthStatus> GetHealthAsync(CancellationToken cancellationToken = default);

    Task<FactorySchema> GetSchemaAsync(CancellationToken cancellationToken = default);

    Task<StateResult> GetDefaultsAsync(
        JsonObject state,
        CancellationToken cancellationToken = default);

    Task<ValidationResult> ValidateAsync(
        JsonObject state,
        CancellationToken cancellationToken = default);

    Task<ImportResult> ImportAsync(
        string format,
        string content,
        JsonObject state,
        CancellationToken cancellationToken = default);

    Task<ExportResult> ExportAsync(
        string format,
        JsonObject state,
        string? destinationPath = null,
        CancellationToken cancellationToken = default);

    Task<StartupLoadResult> LoadStartupAsync(
        string aiFactoryFolder,
        string projectNumber,
        CancellationToken cancellationToken = default);

    Task<ProjectsResult> GetProjectsAsync(
        string aiFactoryFolder,
        CancellationToken cancellationToken = default);

    Task<ProjectLoadResult> LoadProjectAsync(
        string aiFactoryFolder,
        string projectNumber,
        CancellationToken cancellationToken = default);

    Task<ProjectSaveResult> SaveProjectAsync(
        JsonObject state,
        bool writeVariables = true,
        CancellationToken cancellationToken = default);

    Task<ScaleSetsResult> GetScaleSetsAsync(
        string aiFactoryFolder,
        CancellationToken cancellationToken = default);

    Task<ScaleSetLoadResult> LoadScaleSetAsync(
        string aiFactoryFolder,
        string scaleSetId,
        CancellationToken cancellationToken = default);

    Task<PathResult> SaveScaleSetAsync(
        JsonObject state,
        CancellationToken cancellationToken = default);

    Task<RecentProjectsResult> GetRecentProjectsAsync(
        CancellationToken cancellationToken = default);

    Task<RecentProjectsResult> RecordRecentProjectAsync(
        string aiFactoryFolder,
        string projectNumber,
        string orchestrator,
        string prefixResourceGroup,
        string suffixResourceGroup,
        CancellationToken cancellationToken = default);

    Task<OperationsOverview> GetOperationsOverviewAsync(
        string aiFactoryFolder,
        bool includeAzure = true,
        bool forceRefresh = false,
        CancellationToken cancellationToken = default);

    Task<OperationsRegionsResult> GetOperationsRegionsAsync(
        CancellationToken cancellationToken = default);

    Task<OperationConfigResult> LoadOperationsConfigAsync(
        string aiFactoryFolder,
        string projectNumber,
        string environment,
        string kind,
        CancellationToken cancellationToken = default);

    Task<OperationConfigResult> SaveOperationsConfigAsync(
        string aiFactoryFolder,
        string projectNumber,
        string environment,
        string kind,
        JsonObject config,
        CancellationToken cancellationToken = default);

    Task<DraftFactoryAction> CreateFactoryActionAsync(
        string aiFactoryFolder,
        string action,
        string targetRegion,
        string? sourceRegion = null,
        CancellationToken cancellationToken = default);

    Task<DraftProjectAction> CreateProjectActionAsync(
        string aiFactoryFolder,
        string projectNumber,
        string sourceEnvironment,
        string targetEnvironment,
        string action,
        CancellationToken cancellationToken = default);

    Task<OperationsPromptSearchResult> SearchPromptsAsync(
        string aiFactoryFolder,
        string? projectNumber = null,
        string? environment = null,
        string? model = null,
        string? category = null,
        string? search = null,
        bool? success = null,
        int limit = 100,
        int offset = 0,
        CancellationToken cancellationToken = default);
}

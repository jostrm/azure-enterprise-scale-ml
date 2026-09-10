using System.Net;
using System.Text.Json.Nodes;
using ESAIF.BaseLayer.Networking;
using ESAIF.DomainLayer.Configuration;
using ESAIF.DomainLayer.Operations;

namespace ESAIF.DomainLayer.Tests;

public sealed class RecentProjectLoaderTests
{
    private static readonly RecentProject AdoProject = new()
    {
        Folder = @"C:\aifactory",
        Project = "015",
        Orchestrator = "ado"
    };

    [Fact]
    public async Task LoadAsync_ReturnsSnapshotWhenProjectExists()
    {
        var api = new StubApiClient
        {
            ProjectResult = new ProjectLoadResult
            {
                Path = @"C:\aifactory\config-wizard\project-015\project_state.json",
                State = new JsonObject { ["project_number_000"] = "015" }
            }
        };
        var loader = new RecentProjectLoader(api);

        var result = await loader.LoadAsync(AdoProject);

        Assert.True(result.LoadedSnapshot);
        Assert.Equal("015", result.State["project_number_000"]?.GetValue<string>());
        Assert.Equal(0, api.StartupRequests);
    }

    [Fact]
    public async Task LoadAsync_FallsBackToPipelineVariablesWhenSnapshotIsMissing()
    {
        var api = new StubApiClient
        {
            ProjectError = new ApiRequestException(
                HttpStatusCode.NotFound,
                "Project not found",
                """{"detail":"Project not found"}"""),
            StartupResult = new StartupLoadResult
            {
                SourcePath = @"C:\aifactory\esml-infra\variables.yaml",
                Orchestrator = "ado",
                FieldsLoaded = 179,
                State = new JsonObject { ["project_number_000"] = "015" }
            }
        };
        var loader = new RecentProjectLoader(api);

        var result = await loader.LoadAsync(AdoProject);

        Assert.False(result.LoadedSnapshot);
        Assert.Equal(179, result.FieldsLoaded);
        Assert.Equal(@"C:\aifactory\esml-infra\variables.yaml", result.SourcePath);
        Assert.Equal(1, api.StartupRequests);
    }

    [Fact]
    public async Task LoadAsync_DoesNotHideNonNotFoundErrors()
    {
        var expected = new ApiRequestException(
            HttpStatusCode.Unauthorized,
            "Invalid API key",
            """{"detail":"Invalid API key"}""");
        var loader = new RecentProjectLoader(new StubApiClient
        {
            ProjectError = expected
        });

        var actual = await Assert.ThrowsAsync<ApiRequestException>(
            () => loader.LoadAsync(AdoProject));

        Assert.Same(expected, actual);
    }

    private sealed class StubApiClient : IAiFactoryApiClient
    {
        public ProjectLoadResult? ProjectResult { get; init; }

        public Exception? ProjectError { get; init; }

        public StartupLoadResult? StartupResult { get; init; }

        public int StartupRequests { get; private set; }

        public Task<ProjectLoadResult> LoadProjectAsync(
            string aiFactoryFolder,
            string projectNumber,
            CancellationToken cancellationToken = default)
        {
            return ProjectError is not null
                ? Task.FromException<ProjectLoadResult>(ProjectError)
                : Task.FromResult(ProjectResult!);
        }

        public Task<StartupLoadResult> LoadStartupAsync(
            string aiFactoryFolder,
            string projectNumber,
            CancellationToken cancellationToken = default)
        {
            StartupRequests++;
            return Task.FromResult(StartupResult!);
        }

        public Task<HealthStatus> GetHealthAsync(CancellationToken cancellationToken = default) =>
            throw new NotSupportedException();

        public Task<FactorySchema> GetSchemaAsync(CancellationToken cancellationToken = default) =>
            throw new NotSupportedException();

        public Task<StateResult> GetDefaultsAsync(JsonObject state, CancellationToken cancellationToken = default) =>
            throw new NotSupportedException();

        public Task<ValidationResult> ValidateAsync(JsonObject state, CancellationToken cancellationToken = default) =>
            throw new NotSupportedException();

        public Task<ImportResult> ImportAsync(string format, string content, JsonObject state, CancellationToken cancellationToken = default) =>
            throw new NotSupportedException();

        public Task<ExportResult> ExportAsync(string format, JsonObject state, string? destinationPath = null, CancellationToken cancellationToken = default) =>
            throw new NotSupportedException();

        public Task<ProjectsResult> GetProjectsAsync(string aiFactoryFolder, CancellationToken cancellationToken = default) =>
            throw new NotSupportedException();

        public Task<ProjectSaveResult> SaveProjectAsync(JsonObject state, bool writeVariables = true, CancellationToken cancellationToken = default) =>
            throw new NotSupportedException();

        public Task<ScaleSetsResult> GetScaleSetsAsync(string aiFactoryFolder, CancellationToken cancellationToken = default) =>
            throw new NotSupportedException();

        public Task<ScaleSetLoadResult> LoadScaleSetAsync(string aiFactoryFolder, string scaleSetId, CancellationToken cancellationToken = default) =>
            throw new NotSupportedException();

        public Task<PathResult> SaveScaleSetAsync(JsonObject state, CancellationToken cancellationToken = default) =>
            throw new NotSupportedException();

        public Task<RecentProjectsResult> GetRecentProjectsAsync(CancellationToken cancellationToken = default) =>
            throw new NotSupportedException();

        public Task<RecentProjectsResult> RecordRecentProjectAsync(
            string aiFactoryFolder,
            string projectNumber,
            string orchestrator,
            string prefixResourceGroup,
            string suffixResourceGroup,
            CancellationToken cancellationToken = default) =>
            throw new NotSupportedException();

        public Task<OperationsOverview> GetOperationsOverviewAsync(
            string aiFactoryFolder,
            bool includeAzure = true,
            bool forceRefresh = false,
            CancellationToken cancellationToken = default) =>
            throw new NotSupportedException();

        public Task<OperationsRegionsResult> GetOperationsRegionsAsync(
            CancellationToken cancellationToken = default) =>
            throw new NotSupportedException();

        public Task<OperationConfigResult> LoadOperationsConfigAsync(
            string aiFactoryFolder,
            string projectNumber,
            string environment,
            string kind,
            CancellationToken cancellationToken = default) =>
            throw new NotSupportedException();

        public Task<OperationConfigResult> SaveOperationsConfigAsync(
            string aiFactoryFolder,
            string projectNumber,
            string environment,
            string kind,
            JsonObject config,
            CancellationToken cancellationToken = default) =>
            throw new NotSupportedException();

        public Task<DraftFactoryAction> CreateFactoryActionAsync(
            string aiFactoryFolder,
            string action,
            string targetRegion,
            string? sourceRegion = null,
            CancellationToken cancellationToken = default) =>
            throw new NotSupportedException();

        public Task<DraftProjectAction> CreateProjectActionAsync(
            string aiFactoryFolder,
            string projectNumber,
            string sourceEnvironment,
            string targetEnvironment,
            string action,
            CancellationToken cancellationToken = default) =>
            throw new NotSupportedException();

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
            CancellationToken cancellationToken = default) =>
            throw new NotSupportedException();
    }
}

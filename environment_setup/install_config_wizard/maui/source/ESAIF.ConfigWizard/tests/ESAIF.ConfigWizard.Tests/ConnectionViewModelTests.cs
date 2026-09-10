using System.Text.Json.Nodes;
using ESAIF.DomainLayer.Configuration;
using ESAIF.DomainLayer.Operations;
using ESAIF.ConfigWizard.Services;
using ESAIF.ConfigWizard.ViewModels;

namespace ESAIF.ConfigWizard.Tests;

public sealed class ConnectionViewModelTests
{
    [Fact]
    public void GetDocumentationUri_UsesCurrentEndpoint()
    {
        var apiClient = new StubApiClient();
        var viewModel = new ConnectionViewModel(
            apiClient,
            new StubConnectionSettingsService(),
            new WizardSession(apiClient), new StubRecentLoader())
        {
            BaseAddress = "http://127.0.0.1:8765"
        };

        Assert.Equal(
            "http://127.0.0.1:8765/docs",
            viewModel.GetDocumentationUri().AbsoluteUri);
    }

    [Fact]
    public async Task ConnectAsync_SavesTestsLoadsSchemaAndReportsSuccess()
    {
        var apiClient = new StubApiClient();
        var settings = new StubConnectionSettingsService();
        var session = new WizardSession(apiClient);
        var viewModel = new ConnectionViewModel(
            apiClient,
            settings,
            session, new StubRecentLoader())
        {
            BaseAddress = "http://127.0.0.1:8765",
            ApiKey = "secret"
        };

        var connected = await viewModel.ConnectAsync();

        Assert.Equal("secret", settings.SavedConnection?.ApiKey);
        Assert.Equal(1, apiClient.HealthRequests);
        Assert.Equal(1, apiClient.SchemaRequests);
        Assert.True(connected);
        Assert.True(session.IsInitialized);
        Assert.True(viewModel.IsConnected);
        Assert.Contains("2 settings are ready", viewModel.StatusMessage);
    }

    [Fact]
    public async Task BundledConnectRereadsHostCredentialsWithoutSavingStaleFields()
    {
        var apiClient = new StubApiClient();
        var settings = new StubConnectionSettingsService
        {
            StoredConnection = new AiFactoryConnection("http://127.0.0.1:49152", "current-key")
        };
        var host = new StubBundledApiHost();
        var viewModel = new ConnectionViewModel(
            apiClient,
            settings,
            new WizardSession(apiClient),
            new StubRecentLoader(),
            host)
        {
            BaseAddress = "http://127.0.0.1:8765",
            ApiKey = "stale-key"
        };

        Assert.True(await viewModel.ConnectAsync());
        Assert.Equal(1, host.StartCalls);
        Assert.Equal(0, settings.SaveCalls);
        Assert.Equal("http://127.0.0.1:49152", viewModel.BaseAddress);
        Assert.Equal("current-key", viewModel.ApiKey);
    }

    [Fact]
    public async Task ConnectAsync_FailureSuccessFailure_UpdatesSharedStatusAndClearsError()
    {
        var api = new StubApiClient { SchemaError = new HttpRequestException("Invalid key") };
        var session = new WizardSession(api);
        var vm = new ConnectionViewModel(api, new StubConnectionSettingsService(), session, new StubRecentLoader());
        Assert.False(await vm.ConnectAsync());
        Assert.False(session.Connection.IsConnected);
        Assert.Equal("Invalid key", session.Connection.LastError);

        api.SchemaError = null;
        Assert.True(await vm.ConnectAsync());
        Assert.True(session.Connection.IsConnected);
        Assert.Empty(session.Connection.LastError);
        Assert.DoesNotContain("Invalid key", vm.StatusMessage);

        api.HealthError = new HttpRequestException("Server stopped");
        Assert.False(await vm.ConnectAsync());
        Assert.True(session.IsInitialized);
        Assert.False(session.Connection.IsConnected);
        Assert.Equal("Server stopped", session.Connection.LastError);
    }

    [Fact]
    public async Task ConnectingRestoresNewestProjectAndFolderWithItsLoadedOrchestrator()
    {
        var api = new StubApiClient
        {
            Recents = new RecentProjectsResult
            {
                RecentProjects = [
                    new() { Folder = @"C:\latest-factory", Project = "006", Orchestrator = "gha" },
                    new() { Folder = @"C:\older-factory", Project = "017", Orchestrator = "ado" }
                ]
            }
        };
        var loader = new StubRecentLoader();
        var session = new WizardSession(api, startupFolder: "");
        var vm = new ConnectionViewModel(api, new StubConnectionSettingsService(), session, loader);
        Assert.True(await vm.ConnectAsync());
        Assert.Equal("006", loader.Loaded?.Project);
        Assert.Equal(@"C:\latest-factory", session.GetString("_save_folder"));
        Assert.Equal("gha", session.GetString("orchestrator"));
        Assert.Equal("006", session.GetString("project_number_000"));
        Assert.Contains("most recent project 006", vm.StatusMessage);
        Assert.Equal(1, api.RecentRequests);
    }

    [Fact]
    public async Task ReconnectingPreservesLoadedFolderAndUnsavedEditsWithoutFetchingRecents()
    {
        var api = new StubApiClient();
        var session = new WizardSession(api, startupFolder: "");
        await session.InitializeAsync();
        session.ReplaceState(new JsonObject
        {
            ["_save_folder"] = @"C:\current", ["orchestrator"] = "gha",
            ["project_number_000"] = "006", ["projectPrefix"] = "", ["unsaved"] = "keep"
        });
        var vm = new ConnectionViewModel(api, new StubConnectionSettingsService(), session, new StubRecentLoader());
        Assert.True(await vm.ConnectAsync());
        Assert.Equal(@"C:\current", session.GetString("_save_folder"));
        Assert.Equal("keep", session.GetString("unsaved"));
        Assert.Equal("", session.GetString("projectPrefix"));
        Assert.Equal(0, api.RecentRequests);
    }

    [Fact]
    public async Task MissingRecentProjectDoesNotMisreportSuccessfulApiConnection()
    {
        var api = new StubApiClient
        {
            Recents = new RecentProjectsResult
            {
                RecentProjects = [new() { Folder = @"C:\gone", Project = "006", Orchestrator = "gha" }]
            }
        };
        var loader = new StubRecentLoader { Error = new IOException("Factory folder not found") };
        var session = new WizardSession(api, startupFolder: "");
        var vm = new ConnectionViewModel(api, new StubConnectionSettingsService(), session, loader);
        Assert.True(await vm.ConnectAsync());
        Assert.True(session.Connection.IsConnected);
        Assert.Empty(session.GetString("_save_folder"));
        Assert.Contains("Factory folder not found", vm.Warning);
        Assert.Empty(session.Connection.LastError);
    }

    [Fact]
    public async Task DelayedRecentLoadCannotReplaceANewUserSelection()
    {
        var api = new StubApiClient
        {
            Recents = new RecentProjectsResult
            {
                RecentProjects = [new() { Folder = @"C:\recent", Project = "006", Orchestrator = "gha" }]
            }
        };
        var release = new TaskCompletionSource<RecentProjectLoadResult>();
        var loader = new StubRecentLoader { Pending = release.Task };
        var session = new WizardSession(api, startupFolder: "");
        var vm = new ConnectionViewModel(api, new StubConnectionSettingsService(), session, loader);
        var connect = vm.ConnectAsync();
        Assert.NotNull(loader.Loaded);
        session.SetValue("_save_folder", JsonValue.Create(@"C:\chosen-while-loading"));
        release.SetResult(new RecentProjectLoadResult(new JsonObject(), null, 0, false));
        Assert.True(await connect);
        Assert.Equal(@"C:\chosen-while-loading", session.GetString("_save_folder"));
    }

    private sealed class StubRecentLoader : IRecentProjectLoader
    {
        public RecentProject? Loaded { get; private set; }
        public Exception? Error { get; init; }
        public Task<RecentProjectLoadResult>? Pending { get; init; }

        public Task<RecentProjectLoadResult> LoadAsync(RecentProject project, CancellationToken cancellationToken = default)
        {
            Loaded = project;
            return Error is not null ? Task.FromException<RecentProjectLoadResult>(Error) : Pending ??
                Task.FromResult(new RecentProjectLoadResult(new JsonObject
                {
                    ["project_number_000"] = project.Project, ["orchestrator"] = project.Orchestrator
                }, "snapshot.json", 0, true));
        }
    }

    private sealed class StubConnectionSettingsService : IConnectionSettingsService
    {
        public AiFactoryConnection? StoredConnection { get; init; }
        public AiFactoryConnection? SavedConnection { get; private set; }
        public int SaveCalls { get; private set; }

        public Task<AiFactoryConnection> GetConnectionAsync(
            CancellationToken cancellationToken = default)
        {
            return Task.FromResult(
                StoredConnection ?? SavedConnection ?? AiFactoryConnection.LocalDefault);
        }

        public Task SaveConnectionAsync(
            AiFactoryConnection connection,
            CancellationToken cancellationToken = default)
        {
            SaveCalls++;
            SavedConnection = connection;
            return Task.CompletedTask;
        }
    }

    private sealed class StubBundledApiHost : IBundledApiHost
    {
        public bool IsAvailable => true;
        public int StartCalls { get; private set; }

        public Task StartAsync(CancellationToken cancellationToken = default)
        {
            StartCalls++;
            return Task.CompletedTask;
        }

        public Task StopAsync(CancellationToken cancellationToken = default) =>
            Task.CompletedTask;

        public ValueTask DisposeAsync() => ValueTask.CompletedTask;
    }

    private sealed class StubApiClient : IAiFactoryApiClient
    {
        public Exception? HealthError { get; set; }
        public Exception? SchemaError { get; set; }
        public int HealthRequests { get; private set; }

        public int SchemaRequests { get; private set; }
        public int RecentRequests { get; private set; }
        public RecentProjectsResult Recents { get; init; } = new();

        public Task<HealthStatus> GetHealthAsync(
            CancellationToken cancellationToken = default)
        {
            HealthRequests++;
            if (HealthError is not null)
            {
                return Task.FromException<HealthStatus>(HealthError);
            }

            return Task.FromResult(new HealthStatus
            {
                Status = "ok",
                Version = "1.0.0"
            });
        }

        public Task<FactorySchema> GetSchemaAsync(
            CancellationToken cancellationToken = default)
        {
            SchemaRequests++;
            if (SchemaError is not null)
            {
                return Task.FromException<FactorySchema>(SchemaError);
            }

            return Task.FromResult(new FactorySchema
            {
                Defaults = new JsonObject
                {
                    ["orchestrator"] = "ado",
                    ["project_number_000"] = "001"
                }
            });
        }

        public Task<StateResult> GetDefaultsAsync(JsonObject state, CancellationToken cancellationToken = default) =>
            throw new NotSupportedException();

        public Task<ValidationResult> ValidateAsync(JsonObject state, CancellationToken cancellationToken = default) =>
            throw new NotSupportedException();

        public Task<ImportResult> ImportAsync(string format, string content, JsonObject state, CancellationToken cancellationToken = default) =>
            throw new NotSupportedException();

        public Task<ExportResult> ExportAsync(string format, JsonObject state, string? destinationPath = null, CancellationToken cancellationToken = default) =>
            throw new NotSupportedException();

        public Task<StartupLoadResult> LoadStartupAsync(string aiFactoryFolder, string projectNumber, CancellationToken cancellationToken = default) =>
            throw new NotSupportedException();

        public Task<ProjectsResult> GetProjectsAsync(string aiFactoryFolder, CancellationToken cancellationToken = default) =>
            throw new NotSupportedException();

        public Task<ProjectLoadResult> LoadProjectAsync(string aiFactoryFolder, string projectNumber, CancellationToken cancellationToken = default) =>
            throw new NotSupportedException();

        public Task<ProjectSaveResult> SaveProjectAsync(JsonObject state, bool writeVariables = true, CancellationToken cancellationToken = default) =>
            throw new NotSupportedException();

        public Task<ScaleSetsResult> GetScaleSetsAsync(string aiFactoryFolder, CancellationToken cancellationToken = default) =>
            throw new NotSupportedException();

        public Task<ScaleSetLoadResult> LoadScaleSetAsync(string aiFactoryFolder, string scaleSetId, CancellationToken cancellationToken = default) =>
            throw new NotSupportedException();

        public Task<PathResult> SaveScaleSetAsync(JsonObject state, CancellationToken cancellationToken = default) =>
            throw new NotSupportedException();

        public Task<RecentProjectsResult> GetRecentProjectsAsync(CancellationToken cancellationToken = default)
        {
            RecentRequests++;
            return Task.FromResult(Recents);
        }

        public Task<RecentProjectsResult> RecordRecentProjectAsync(
            string aiFactoryFolder,
            string projectNumber,
            string orchestrator,
            string prefixResourceGroup,
            string suffixResourceGroup,
            CancellationToken cancellationToken = default) =>
            throw new NotSupportedException();

        public Task<OperationsOverview> GetOperationsOverviewAsync(string aiFactoryFolder, bool includeAzure = true, bool forceRefresh = false, CancellationToken cancellationToken = default) => throw new NotSupportedException();
        public Task<OperationsRegionsResult> GetOperationsRegionsAsync(CancellationToken cancellationToken = default) => throw new NotSupportedException();
        public Task<OperationConfigResult> LoadOperationsConfigAsync(string aiFactoryFolder, string projectNumber, string environment, string kind, CancellationToken cancellationToken = default) => throw new NotSupportedException();
        public Task<OperationConfigResult> SaveOperationsConfigAsync(string aiFactoryFolder, string projectNumber, string environment, string kind, JsonObject config, CancellationToken cancellationToken = default) => throw new NotSupportedException();
        public Task<DraftFactoryAction> CreateFactoryActionAsync(string aiFactoryFolder, string action, string targetRegion, string? sourceRegion = null, CancellationToken cancellationToken = default) => throw new NotSupportedException();
        public Task<DraftProjectAction> CreateProjectActionAsync(string aiFactoryFolder, string projectNumber, string sourceEnvironment, string targetEnvironment, string action, CancellationToken cancellationToken = default) => throw new NotSupportedException();
        public Task<OperationsPromptSearchResult> SearchPromptsAsync(string aiFactoryFolder, string? projectNumber = null, string? environment = null, string? model = null, string? category = null, string? search = null, bool? success = null, int limit = 100, int offset = 0, CancellationToken cancellationToken = default) => throw new NotSupportedException();
    }
}

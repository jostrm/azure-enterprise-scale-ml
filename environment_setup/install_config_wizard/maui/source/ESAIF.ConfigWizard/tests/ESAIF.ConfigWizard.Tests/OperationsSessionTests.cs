using System.Text.Json.Nodes;
using ESAIF.BaseLayer.Monitoring;
using ESAIF.ConfigWizard.Services;
using ESAIF.DomainLayer.Configuration;
using ESAIF.DomainLayer.Operations;

namespace ESAIF.ConfigWizard.Tests;

public sealed class OperationsSessionTests
{
    [Fact]
    public async Task LoadAsync_MissingFolderDoesNotCallApi()
    {
        var api = new StubApiClient();
        var wizard = new WizardSession(api);
        var session = new OperationsSession(api, wizard);

        var result = await session.LoadAsync();

        Assert.Null(result);
        Assert.Equal(0, api.OverviewRequests);
        Assert.False(string.IsNullOrWhiteSpace(session.MissingFolderMessage));
    }

    [Fact]
    public async Task LoadAsync_ReusesOverviewUntilForced()
    {
        var api = new StubApiClient();
        var wizard = new WizardSession(api);
        var session = new OperationsSession(api, wizard);
        await wizard.InitializeAsync();
        wizard.SetValue("_save_folder", "factory");

        var first = await session.LoadAsync();
        var second = await session.LoadAsync();
        var refreshed = await session.LoadAsync(forceRefresh: true);

        Assert.Same(first, second);
        Assert.NotSame(first, refreshed);
        Assert.Equal(2, api.OverviewRequests);
        Assert.True(api.LastForceRefresh);
    }

    [Fact]
    public async Task FolderChange_InvalidatesCurrentOverview()
    {
        var api = new StubApiClient();
        var wizard = new WizardSession(api);
        var session = new OperationsSession(api, wizard);
        await wizard.InitializeAsync();
        wizard.SetValue("_save_folder", "one");
        await session.LoadAsync();

        wizard.SetValue("_save_folder", "two");

        Assert.False(session.HasOverview);
        Assert.Equal(string.Empty, session.MissingFolderMessage);
        await session.LoadAsync();
        Assert.Equal(2, api.OverviewRequests);
    }

    [Fact]
    public async Task ConcurrentLoads_AreCoalesced()
    {
        var api = new StubApiClient { Delay = TimeSpan.FromMilliseconds(40) };
        var wizard = new WizardSession(api);
        var session = new OperationsSession(api, wizard);
        await wizard.InitializeAsync();
        wizard.SetValue("_save_folder", "factory");

        await Task.WhenAll(
            session.LoadAsync(),
            session.LoadAsync(),
            session.LoadAsync());

        Assert.Equal(1, api.OverviewRequests);
    }

    [Fact]
    public async Task LocalOverview_DoesNotSatisfyAzureLoad()
    {
        var api = new StubApiClient();
        var wizard = new WizardSession(api);
        await wizard.InitializeAsync();
        wizard.SetValue("_save_folder", "factory");
        var session = new OperationsSession(api, wizard);

        await session.LoadAsync(includeAzure: false);
        await session.LoadAsync(includeAzure: true);

        Assert.Equal(2, api.OverviewRequests);
        Assert.True(api.LastIncludeAzure);
    }

    [Fact]
    public async Task ForcedRefresh_IsNotSatisfiedByInFlightCachedLoad()
    {
        var gate = new TaskCompletionSource(TaskCreationOptions.RunContinuationsAsynchronously);
        var api = new StubApiClient { BeforeResponse = () => gate.Task };
        var wizard = new WizardSession(api);
        await wizard.InitializeAsync();
        wizard.SetValue("_save_folder", "factory");
        var session = new OperationsSession(api, wizard);

        var cached = session.LoadAsync();
        var forced = session.LoadAsync(forceRefresh: true);
        gate.SetResult();
        await Task.WhenAll(cached, forced);

        Assert.Equal(2, api.OverviewRequests);
        Assert.True(api.LastForceRefresh);
    }

    [Fact]
    public async Task ConcurrentForcedRefreshes_AreCoalesced()
    {
        var gate = new TaskCompletionSource(TaskCreationOptions.RunContinuationsAsynchronously);
        var api = new StubApiClient { BeforeResponse = () => gate.Task };
        var wizard = new WizardSession(api);
        await wizard.InitializeAsync();
        wizard.SetValue("_save_folder", "factory");
        var session = new OperationsSession(api, wizard);

        var first = session.LoadAsync(forceRefresh: true);
        var second = session.LoadAsync(forceRefresh: true);
        gate.SetResult();
        await Task.WhenAll(first, second);

        Assert.Equal(1, api.OverviewRequests);
    }

    [Fact]
    public async Task Invalidate_ClearsSnapshotAndNotifiesWithoutAzureCalls()
    {
        var api = new StubApiClient();
        var wizard = new WizardSession(api);
        await wizard.InitializeAsync();
        wizard.SetValue("_save_folder", "factory");
        var session = new OperationsSession(api, wizard);
        await session.LoadAsync();
        var notifications = 0;
        session.OverviewChanged += (_, _) => notifications++;

        session.Invalidate();

        Assert.Null(session.Current);
        Assert.Equal(1, notifications);
        Assert.Equal(1, api.OverviewRequests);
        await session.LoadAsync(includeAzure: false);
        Assert.Equal(2, api.OverviewRequests);
        Assert.False(api.LastIncludeAzure);
    }

    [Theory]
    [InlineData(false)]
    [InlineData(true)]
    public async Task InvalidationDuringLoad_DiscardsStaleResponse(bool changeFolder)
    {
        var gate = new TaskCompletionSource(TaskCreationOptions.RunContinuationsAsynchronously);
        var api = new StubApiClient { BeforeResponse = () => gate.Task };
        var wizard = new WizardSession(api);
        await wizard.InitializeAsync();
        wizard.SetValue("_save_folder", "factory");
        var session = new OperationsSession(api, wizard);
        var loading = session.LoadAsync();

        if (changeFolder)
            wizard.SetValue("_save_folder", "other");
        else
            session.Invalidate();
        gate.SetResult();

        Assert.Null(await loading);
        Assert.Null(session.Current);
        Assert.Equal(1, api.OverviewRequests);
    }

    [Fact]
    public async Task FailedRefresh_PropagatesAndRetainsPreviousSnapshot()
    {
        var api = new StubApiClient();
        var wizard = new WizardSession(api);
        await wizard.InitializeAsync();
        wizard.SetValue("_save_folder", "factory");
        var session = new OperationsSession(api, wizard);
        var first = await session.LoadAsync();
        api.BeforeResponse = () => throw new HttpRequestException("HTTP 503");

        var error = await Assert.ThrowsAsync<HttpRequestException>(
            () => session.LoadAsync(forceRefresh: true));

        Assert.Equal("HTTP 503", error.Message);
        Assert.Same(first, session.Current);
    }

    [Fact]
    public async Task PostLoginRefresh_RefreshesCurrentConfigurationAndAzureWithoutResettingEdits()
    {
        var api = new StubApiClient();
        var wizard = new WizardSession(api);
        await wizard.InitializeAsync();
        wizard.SetValue("_save_folder", "active-factory");
        wizard.SetValue("project_number_000", "017");
        wizard.SetValue("adminVMBuildAgentName", "my-unsaved-agent");
        var operations = new OperationsSession(api, wizard);
        await operations.LoadAsync();
        var result = await new PostAzureLoginRefresh(wizard, new AzureRefreshCoordinator(operations, wizard)).RefreshAsync();
        Assert.Equal(2, api.OverviewRequests);
        Assert.True(api.LastForceRefresh);
        Assert.True(api.LastIncludeAzure);
        Assert.Equal("active-factory", operations.Current!.Factory.Folder);
        Assert.Equal("017", wizard.GetString("project_number_000"));
        Assert.Equal("my-unsaved-agent", wizard.GetString("adminVMBuildAgentName"));
        Assert.Contains("updated", result);
    }

    [Fact]
    public async Task GlobalRefresh_IsSingleFlightPublishesOnceToAllViewsAndCompletesGreen()
    {
        var started = new TaskCompletionSource(TaskCreationOptions.RunContinuationsAsynchronously);
        var release = new TaskCompletionSource(TaskCreationOptions.RunContinuationsAsynchronously);
        var api = new StubApiClient
        {
            Overview = CompleteOverview,
            BeforeResponse = () => { started.TrySetResult(); return release.Task; }
        };
        var wizard = new WizardSession(api);
        await wizard.InitializeAsync();
        wizard.SetValue("_save_folder", "factory");
        var operations = new OperationsSession(api, wizard);
        var publications = new int[3];
        for (var index = 0; index < publications.Length; index++)
        {
            var subscriber = index;
            operations.OverviewChanged += (_, _) => publications[subscriber]++;
        }
        var refresh = new AzureRefreshCoordinator(operations, wizard);
        var first = refresh.RefreshAsync();
        var second = refresh.RefreshAsync();
        Assert.Same(first, second);
        await started.Task.WaitAsync(TimeSpan.FromSeconds(5));
        Assert.True(refresh.IsRunning);
        Assert.False(refresh.CanRefresh);
        Assert.Equal("#22BBD0", refresh.LightColor);
        Assert.Equal(1, api.OverviewRequests);
        release.SetResult();
        await Task.WhenAll(first, second);
        Assert.Equal(new[] { 1, 1, 1 }, publications);
        Assert.Equal(AzureRefreshState.Succeeded, refresh.State);
        Assert.Equal("#22C9A7", refresh.LightColor);
        Assert.False(refresh.IsRunning);
        Assert.NotNull(refresh.CompletedAt);
        Assert.True(refresh.CanRefresh);
        await operations.LoadAsync(); // Opening another page reuses the published overview.
        Assert.Equal(1, api.OverviewRequests);
    }

    [Theory]
    [InlineData("azure", "Permission denied on one telemetry resource")]
    [InlineData("cached", "")]
    [InlineData("mixed", "")]
    public async Task GlobalRefresh_PartialDataHasSteadyWarningInsteadOfFalseGreen(string source, string warning)
    {
        var api = new StubApiClient { Overview = CompleteOverview with { Source = source, Warning = warning } };
        var wizard = new WizardSession(api);
        await wizard.InitializeAsync();
        wizard.SetValue("_save_folder", "factory");
        var refresh = new AzureRefreshCoordinator(new OperationsSession(api, wizard), wizard);
        await refresh.RefreshAsync();
        Assert.Equal(AzureRefreshState.Partial, refresh.State);
        Assert.Equal("#D79B32", refresh.LightColor);
        Assert.True(refresh.HasDetails);
        Assert.NotNull(refresh.CompletedAt);
        Assert.False(refresh.IsRunning);
    }

    [Fact]
    public async Task GlobalRefresh_FailureRetainsDataAndRetryClearsTheError()
    {
        var api = new StubApiClient { Overview = CompleteOverview };
        var wizard = new WizardSession(api);
        await wizard.InitializeAsync();
        wizard.SetValue("_save_folder", "factory");
        var operations = new OperationsSession(api, wizard);
        var existing = await operations.LoadAsync();
        api.BeforeResponse = () => throw new HttpRequestException("Network failure");
        var refresh = new AzureRefreshCoordinator(operations, wizard);
        await refresh.RefreshAsync();
        Assert.Equal(AzureRefreshState.Failed, refresh.State);
        Assert.Equal("#E45664", refresh.LightColor);
        Assert.Same(existing, operations.Current);
        Assert.Contains("Network failure", refresh.Details);
        Assert.Null(refresh.CompletedAt);
        api.BeforeResponse = null;
        await refresh.RefreshAsync();
        Assert.Equal(AzureRefreshState.Succeeded, refresh.State);
        Assert.Empty(refresh.Details);
    }

    [Fact]
    public async Task GlobalRefresh_FactoryChangeWhileRunningNeverShowsOldFactorySuccess()
    {
        var started = new TaskCompletionSource(TaskCreationOptions.RunContinuationsAsynchronously);
        var release = new TaskCompletionSource(TaskCreationOptions.RunContinuationsAsynchronously);
        var api = new StubApiClient { BeforeResponse = () => { started.TrySetResult(); return release.Task; } };
        var wizard = new WizardSession(api);
        await wizard.InitializeAsync();
        wizard.SetValue("_save_folder", "old");
        var operations = new OperationsSession(api, wizard);
        var refresh = new AzureRefreshCoordinator(operations, wizard);
        var pending = refresh.RefreshAsync();
        await started.Task.WaitAsync(TimeSpan.FromSeconds(5));
        wizard.SetValue("_save_folder", "new");
        Assert.True(refresh.IsRunning);
        release.SetResult();
        await pending;
        Assert.Equal(AzureRefreshState.Superseded, refresh.State);
        Assert.Null(operations.Current);
        Assert.Null(refresh.CompletedAt);
        Assert.True(refresh.CanRefresh);
    }

    [Fact]
    public async Task GlobalRefresh_MissingFolderDisablesCommandAndDoesNotCallAzure()
    {
        var api = new StubApiClient();
        var wizard = new WizardSession(api);
        await wizard.InitializeAsync();
        var refresh = new AzureRefreshCoordinator(new OperationsSession(api, wizard), wizard);
        Assert.False(refresh.CanRefresh);
        Assert.False(refresh.RefreshCommand.CanExecute(null));
        await refresh.RefreshAsync();
        Assert.Equal(0, api.OverviewRequests);
        Assert.Equal(AzureRefreshState.Superseded, refresh.State);
        Assert.False(refresh.IsRunning);
        wizard.SetValue("_save_folder", "selected");
        Assert.Equal(AzureRefreshState.Ready, refresh.State);
        Assert.True(refresh.CanRefresh);
    }

    private static OperationsOverview CompleteOverview => new()
    {
        Source = "azure",
        ResourceInventory = new ResourceInventorySummary { Source = "azure" },
        PromptSummary = new PromptSummary { Source = "azure" }
    };

    [Fact]
    public async Task ExistingSnapshotWarnings_AreAvailableToCopyWithoutAnotherRefresh()
    {
        var api = new StubApiClient { Overview = CompleteOverview with { Warning = "Permission denied.\nResource scope details." } };
        var wizard = new WizardSession(api);
        await wizard.InitializeAsync();
        wizard.SetValue("_save_folder", "factory");
        var operations = new OperationsSession(api, wizard);
        var refresh = new AzureRefreshCoordinator(operations, wizard);
        await operations.LoadAsync();
        Assert.Equal(AzureRefreshState.Ready, refresh.State);
        Assert.True(refresh.HasDetails);
        Assert.Equal(api.Overview.Warning, refresh.Details);
        Assert.Equal(1, api.OverviewRequests);
    }

    private sealed class StubApiClient : IAiFactoryApiClient
    {
        public int OverviewRequests { get; private set; }
        public bool LastForceRefresh { get; private set; }
        public bool LastIncludeAzure { get; private set; }
        public Func<Task>? BeforeResponse { get; set; }
        public TimeSpan Delay { get; init; }
        public OperationsOverview? Overview { get; init; }

        public Task<FactorySchema> GetSchemaAsync(CancellationToken cancellationToken = default) =>
            Task.FromResult(new FactorySchema
            {
                Defaults = new JsonObject { ["_save_folder"] = string.Empty }
            });

        public async Task<OperationsOverview> GetOperationsOverviewAsync(
            string aiFactoryFolder,
            bool includeAzure = true,
            bool forceRefresh = false,
            CancellationToken cancellationToken = default)
        {
            OverviewRequests++;
            LastForceRefresh = forceRefresh;
            LastIncludeAzure = includeAzure;
            if (BeforeResponse is not null)
            {
                await BeforeResponse();
            }
            if (Delay > TimeSpan.Zero)
            {
                await Task.Delay(Delay, cancellationToken);
            }

            return Overview ?? new OperationsOverview
            {
                GeneratedAt = OverviewRequests.ToString(),
                Source = "azure",
                Factory = new FactorySummary { Folder = aiFactoryFolder }
            };
        }

        public Task<HealthStatus> GetHealthAsync(CancellationToken cancellationToken = default) => throw new NotSupportedException();
        public Task<StateResult> GetDefaultsAsync(JsonObject state, CancellationToken cancellationToken = default) => throw new NotSupportedException();
        public Task<ValidationResult> ValidateAsync(JsonObject state, CancellationToken cancellationToken = default) => throw new NotSupportedException();
        public Task<ImportResult> ImportAsync(string format, string content, JsonObject state, CancellationToken cancellationToken = default) => throw new NotSupportedException();
        public Task<ExportResult> ExportAsync(string format, JsonObject state, string? destinationPath = null, CancellationToken cancellationToken = default) => throw new NotSupportedException();
        public Task<StartupLoadResult> LoadStartupAsync(string aiFactoryFolder, string projectNumber, CancellationToken cancellationToken = default) => throw new NotSupportedException();
        public Task<ProjectsResult> GetProjectsAsync(string aiFactoryFolder, CancellationToken cancellationToken = default) => throw new NotSupportedException();
        public Task<ProjectLoadResult> LoadProjectAsync(string aiFactoryFolder, string projectNumber, CancellationToken cancellationToken = default) => throw new NotSupportedException();
        public Task<ProjectSaveResult> SaveProjectAsync(JsonObject state, bool writeVariables = true, CancellationToken cancellationToken = default) => throw new NotSupportedException();
        public Task<ScaleSetsResult> GetScaleSetsAsync(string aiFactoryFolder, CancellationToken cancellationToken = default) => throw new NotSupportedException();
        public Task<ScaleSetLoadResult> LoadScaleSetAsync(string aiFactoryFolder, string scaleSetId, CancellationToken cancellationToken = default) => throw new NotSupportedException();
        public Task<PathResult> SaveScaleSetAsync(JsonObject state, CancellationToken cancellationToken = default) => throw new NotSupportedException();
        public Task<RecentProjectsResult> GetRecentProjectsAsync(CancellationToken cancellationToken = default) => throw new NotSupportedException();
        public Task<RecentProjectsResult> RecordRecentProjectAsync(string aiFactoryFolder, string projectNumber, string orchestrator, string prefixResourceGroup, string suffixResourceGroup, CancellationToken cancellationToken = default) => throw new NotSupportedException();
        public Task<OperationsRegionsResult> GetOperationsRegionsAsync(CancellationToken cancellationToken = default) => throw new NotSupportedException();
        public Task<OperationConfigResult> LoadOperationsConfigAsync(string aiFactoryFolder, string projectNumber, string environment, string kind, CancellationToken cancellationToken = default) => throw new NotSupportedException();
        public Task<OperationConfigResult> SaveOperationsConfigAsync(string aiFactoryFolder, string projectNumber, string environment, string kind, JsonObject config, CancellationToken cancellationToken = default) => throw new NotSupportedException();
        public Task<DraftFactoryAction> CreateFactoryActionAsync(string aiFactoryFolder, string action, string targetRegion, string? sourceRegion = null, CancellationToken cancellationToken = default) => throw new NotSupportedException();
        public Task<DraftProjectAction> CreateProjectActionAsync(string aiFactoryFolder, string projectNumber, string sourceEnvironment, string targetEnvironment, string action, CancellationToken cancellationToken = default) => throw new NotSupportedException();
        public Task<OperationsPromptSearchResult> SearchPromptsAsync(string aiFactoryFolder, string? projectNumber = null, string? environment = null, string? model = null, string? category = null, string? search = null, bool? success = null, int limit = 100, int offset = 0, CancellationToken cancellationToken = default) => throw new NotSupportedException();
    }
}

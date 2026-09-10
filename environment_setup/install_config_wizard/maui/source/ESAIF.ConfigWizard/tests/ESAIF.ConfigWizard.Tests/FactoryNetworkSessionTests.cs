using System.Text.Json.Nodes;
using ESAIF.BaseLayer.Networking;
using ESAIF.ConfigWizard.Services;
using ESAIF.ConfigWizard.ViewModels;
using ESAIF.DomainLayer.Configuration;
using ESAIF.DomainLayer.Operations;

namespace ESAIF.ConfigWizard.Tests;

public sealed class FactoryNetworkSessionTests
{
    [Fact]
    public async Task RefreshDeduplicatesFoldersAndKeepsEveryRequestInItsOwnFactory()
    {
        var fixture = new FactoryNetworkFixture();
        await fixture.Network.RefreshAsync("C:/ado/");
        Assert.Equal(2, fixture.Network.Snapshots.Count);
        Assert.Equal(2, fixture.Count<OperationsOverview>());
        Assert.Equal(2, fixture.Count<ProjectResourceGroupVerification>());
        Assert.Equal(2, fixture.Count<ScaleSetResourceGroupVerification>());
        foreach (var snapshot in fixture.Network.Snapshots)
        {
            Assert.True(FactoryNetworkSession.SameFolder(snapshot.Folder, snapshot.Overview!.Factory.Folder));
            Assert.All(snapshot.Projects.Concat(snapshot.ScaleSets), item =>
            {
                Assert.Equal(snapshot.Folder, item.Folder);
                Assert.True(item.IsResourceGroupVerified);
                Assert.Equal(snapshot.Folder == FactoryNetworkFixture.Ado ? FactoryNetworkFixture.AdoSub : FactoryNetworkFixture.GhaSub,
                    item.ResourceGroupLinks[0].SubscriptionId);
            });
        }
        var region = Assert.Single(fixture.Network.Regions);
        Assert.Equal(300, region.ResourceCount);
        Assert.Equal(2, region.ProjectCount);
        Assert.Equal(2, region.FactoryCount);
        Assert.Equal("complete", region.CountStatus);
    }

    [Fact]
    public async Task FailedFactoryDoesNotAbortOthersOrLeaveItsPreviousVerificationBlue()
    {
        var fixture = new FactoryNetworkFixture();
        await fixture.Network.RefreshAsync(FactoryNetworkFixture.Ado);
        fixture.FailedInventoryFolder = FactoryNetworkFixture.Ado;
        await fixture.Network.RefreshAsync(FactoryNetworkFixture.Gha);
        var failed = fixture.Network.Find(FactoryNetworkFixture.Ado)!;
        Assert.Contains("Inventory", failed.Error);
        Assert.All(failed.Projects.Concat(failed.ScaleSets), item => Assert.False(item.IsResourceGroupVerified));
        Assert.True(fixture.Network.Find(FactoryNetworkFixture.Gha)!.Projects[0].IsResourceGroupVerified);
        Assert.Equal("partial", Assert.Single(fixture.Network.Regions).CountStatus);
    }

    [Fact]
    public async Task WrongFolderInventoryCannotSupplyLinksOrSuccessfulVerification()
    {
        var fixture = new FactoryNetworkFixture { WrongInventoryFolder = FactoryNetworkFixture.Ado };
        await fixture.Network.RefreshAsync(FactoryNetworkFixture.Ado);
        var snapshot = fixture.Network.Find(FactoryNetworkFixture.Ado)!;
        Assert.Null(snapshot.Overview);
        Assert.Contains("different factory", snapshot.Error);
        Assert.All(snapshot.Projects, item => Assert.False(item.HasResourceGroupLink));
        Assert.Equal(1, fixture.Count<ProjectResourceGroupVerification>());
        Assert.Equal("partial", Assert.Single(fixture.Network.Regions).CountStatus);
    }

    [Fact]
    public async Task DiscoveryFailureStillRefreshesRememberedAndCurrentFactories()
    {
        var fixture = new FactoryNetworkFixture();
        await fixture.Network.RefreshAsync(FactoryNetworkFixture.Ado);
        fixture.FailDiscovery = true;
        await fixture.Network.RefreshAsync(FactoryNetworkFixture.Gha);
        Assert.Equal(4, fixture.Count<OperationsOverview>());
        Assert.Contains("recent", fixture.Network.DiscoveryError);
        Assert.Equal(2, fixture.Network.Snapshots.Count);
    }

    [Fact]
    public async Task CoordinatorWaitsForLastAccessCheckAndSharesOneFlight()
    {
        var fixture = new FactoryNetworkFixture { VerificationGate = new(TaskCreationOptions.RunContinuationsAsynchronously) };
        var wizard = new WizardSession(fixture.Api);
        var coordinator = new AzureRefreshCoordinator(new(fixture.Api, wizard), wizard, fixture.Network);
        var first = coordinator.RefreshAsync();
        var second = coordinator.RefreshAsync();
        Assert.Same(first, second);
        await fixture.VerificationStarted.Task.WaitAsync(TimeSpan.FromSeconds(5));
        Assert.True(coordinator.IsRunning);
        Assert.Null(coordinator.CompletedAt);
        fixture.VerificationGate.SetResult();
        await first;
        Assert.Equal(AzureRefreshState.Succeeded, coordinator.State);
        Assert.Equal(2, fixture.Count<OperationsOverview>());
        Assert.NotNull(coordinator.CompletedAt);
    }

    [Fact]
    public async Task UnverifiedOrMockInventoryNeverProducesGreenCompletion()
    {
        foreach (var mock in new[] { false, true })
        {
            var fixture = new FactoryNetworkFixture { WrongVerificationIds = !mock, MockInventory = mock };
            var wizard = new WizardSession(fixture.Api);
            var coordinator = new AzureRefreshCoordinator(new(fixture.Api, wizard), wizard, fixture.Network);
            await coordinator.RefreshAsync();
            Assert.Equal(AzureRefreshState.Partial, coordinator.State);
            Assert.All(fixture.Network.Snapshots.SelectMany(snapshot => snapshot.Projects),
                item => Assert.False(item.IsResourceGroupVerified));
            if (mock)
            {
                Assert.Equal(0, Assert.Single(fixture.Network.Regions).ResourceCount);
            }
        }
    }

    [Fact]
    public async Task ProjectsReuseVerifiedItemsAndRouteLoadDeleteByItemFolderAndPath()
    {
        var fixture = new FactoryNetworkFixture();
        var wizard = new WizardSession(fixture.Api);
        await wizard.InitializeAsync();
        wizard.SetValue("_save_folder", FactoryNetworkFixture.Ado);
        wizard.SetValue("unsaved", "preserve");
        await fixture.Network.RefreshAsync(FactoryNetworkFixture.Ado);
        var projects = new ProjectsViewModel(fixture.Api, wizard, fixture.Api, fixture.Network);
        var item = projects.Projects.Single(project => project.Folder == FactoryNetworkFixture.Gha);
        var before = fixture.Count<ProjectResourceGroupVerification>();
        await projects.RefreshAsync();
        await projects.RefreshAsync();
        Assert.Same(item, projects.Projects.Single(project => project.Folder == FactoryNetworkFixture.Gha));
        Assert.Equal(before, fixture.Count<ProjectResourceGroupVerification>());
        Assert.True(item.IsResourceGroupVerified);
        Assert.Equal("preserve", wizard.GetString("unsaved"));
        await projects.DeleteConfigurationAsync(item);
        Assert.Equal(FactoryNetworkFixture.Gha, fixture.Requests.Last(request => request.Type == typeof(ProjectConfigurationDeleteResult)).Folder);
        Assert.Equal(FactoryNetworkFixture.Ado, wizard.GetString("_save_folder"));
        Assert.Single(projects.Projects);
        await projects.RefreshAsync();
        Assert.Single(projects.Projects);
        await projects.LoadProjectAsync(projects.Projects[0]);
        Assert.Equal(FactoryNetworkFixture.Ado, fixture.Requests.Last(request => request.Type == typeof(ProjectLoadResult)).Folder);
        Assert.Empty(projects.ErrorMessage);
    }

    [Fact]
    public async Task CrossFactoryLoadUsesItsOwnFolderAndRejectsWrongSnapshotPath()
    {
        var fixture = new FactoryNetworkFixture();
        var wizard = new WizardSession(fixture.Api);
        await wizard.InitializeAsync();
        wizard.SetValue("_save_folder", FactoryNetworkFixture.Ado);
        await fixture.Network.RefreshAsync(FactoryNetworkFixture.Ado);
        var projects = new ProjectsViewModel(fixture.Api, wizard, fixture.Api, fixture.Network);
        var item = projects.Projects.Single(project => project.Folder == FactoryNetworkFixture.Gha);
        fixture.WrongLoadPath = true;
        await projects.LoadProjectAsync(item);
        Assert.Equal(FactoryNetworkFixture.Ado, wizard.GetString("_save_folder"));
        Assert.Contains("path changed", projects.ErrorMessage);
        fixture.WrongLoadPath = false;
        await projects.LoadProjectAsync(item);
        Assert.Equal(FactoryNetworkFixture.Gha, wizard.GetString("_save_folder"));
    }

    [Fact]
    public async Task ScaleSetsReuseGlobalVerificationAndRouteToTheSelectedFactory()
    {
        var fixture = new FactoryNetworkFixture();
        var wizard = new WizardSession(fixture.Api);
        await wizard.InitializeAsync();
        wizard.SetValue("_save_folder", FactoryNetworkFixture.Ado);
        await fixture.Network.RefreshAsync(FactoryNetworkFixture.Ado);
        var scales = new ScaleSetsViewModel(fixture.Api, wizard, fixture.Api, fixture.Network);
        var item = scales.ScaleSets.Single(scale => scale.Folder == FactoryNetworkFixture.Gha);
        await scales.RefreshAsync();
        Assert.Same(item, scales.ScaleSets.Single(scale => scale.Folder == FactoryNetworkFixture.Gha));
        Assert.True(item.IsResourceGroupVerified);
        await scales.LoadScaleSetAsync(item);
        Assert.Equal(FactoryNetworkFixture.Gha, wizard.GetString("_save_folder"));
        await scales.DeleteConfigurationAsync(item);
        Assert.Equal(FactoryNetworkFixture.Gha, fixture.Requests.Last(request => request.Type == typeof(ScaleSetConfigurationDeleteResult)).Folder);
        Assert.Single(scales.ScaleSets);
    }

    [Fact]
    public void DuplicateScopeCountsOnceButAdoAndGhaRemainIndependent()
    {
        var ado = FactoryNetworkFixture.Overview(FactoryNetworkFixture.Ado);
        FactoryNetworkSnapshot Snapshot(string folder, OperationsOverview overview) => new(folder, overview, [], [], "");
        var result = FactoryNetworkSession.AggregateRegions([
            Snapshot(FactoryNetworkFixture.Ado, ado),
            Snapshot(@"C:\alias", ado with { Factory = ado.Factory with { Folder = @"C:\alias" } }),
            Snapshot(FactoryNetworkFixture.Gha, ado with { Factory = ado.Factory with { Orchestrator = "gha" } })
        ]);
        Assert.Equal(200, Assert.Single(result).ResourceCount);
        Assert.Equal(2, result[0].FactoryCount);
    }

    [Fact]
    public async Task LocalListNavigationDoesNotForceAzureOrVerifyResourceAccess()
    {
        var fixture = new FactoryNetworkFixture();
        await fixture.Network.EnsureLoadedAsync(FactoryNetworkFixture.Ado);
        Assert.Equal(0, fixture.Count<ProjectResourceGroupVerification>());
        Assert.Equal(0, fixture.Count<ScaleSetResourceGroupVerification>());
        Assert.All(fixture.Requests.Where(request => request.Type == typeof(OperationsOverview)), request =>
        {
            Assert.False(request.Body["include_azure"]!.GetValue<bool>());
            Assert.False(request.Body["force_refresh"]!.GetValue<bool>());
        });
    }

    [Fact]
    public async Task LoadPreservesEditsMadeWhileRequestWasPending()
    {
        var fixture = new FactoryNetworkFixture();
        var wizard = new WizardSession(fixture.Api);
        await wizard.InitializeAsync();
        wizard.SetValue("_save_folder", FactoryNetworkFixture.Ado);
        await fixture.Network.RefreshAsync(FactoryNetworkFixture.Ado);
        var projects = new ProjectsViewModel(fixture.Api, wizard, fixture.Api, fixture.Network);
        fixture.BeforeProjectLoad = () => wizard.SetValue("unsaved", "new edit");
        await projects.LoadProjectAsync(projects.Projects[0]);
        Assert.Equal("new edit", wizard.GetString("unsaved"));
        Assert.Contains("editor changed", projects.ErrorMessage);
    }

    [Fact]
    public async Task CurrentFolderAddedDuringCollectionCannotProduceFalseGlobalCompletion()
    {
        var fixture = new FactoryNetworkFixture { VerificationGate = new(TaskCreationOptions.RunContinuationsAsynchronously) };
        var wizard = new WizardSession(fixture.Api);
        await wizard.InitializeAsync();
        wizard.SetValue("_save_folder", FactoryNetworkFixture.Ado);
        var operations = new OperationsSession(fixture.Api, wizard);
        var coordinator = new AzureRefreshCoordinator(operations, wizard, fixture.Network);
        var refresh = coordinator.RefreshAsync();
        await fixture.VerificationStarted.Task.WaitAsync(TimeSpan.FromSeconds(5));
        wizard.SetValue("_save_folder", @"C:\new-factory");
        fixture.VerificationGate.SetResult();
        await refresh;
        Assert.Equal(AzureRefreshState.Partial, coordinator.State);
        Assert.Contains(@"C:\new-factory", coordinator.Details);
        Assert.Null(operations.Current);
    }
}

internal sealed class FactoryNetworkFixture : IJsonApiTransport, IAiFactoryConnectionProvider
{
    public const string Ado = @"C:\ado";
    public const string Gha = @"C:\gha";
    public const string AdoSub = "11111111-1111-4111-8111-111111111111";
    public const string GhaSub = "22222222-2222-4222-8222-222222222222";
    public AiFactoryApiClient Api { get; }
    public FactoryNetworkSession Network { get; }
    public List<(Type Type, string Folder, JsonObject Body)> Requests { get; } = [];
    public string? FailedInventoryFolder { get; set; }
    public string? WrongInventoryFolder { get; set; }
    public bool FailDiscovery { get; set; }
    public bool WrongVerificationIds { get; set; }
    public bool MockInventory { get; set; }
    public bool WrongLoadPath { get; set; }
    public Action? BeforeProjectLoad { get; set; }
    public bool SignedIn { get; set; }
    public string? ExpiredFolder { get; set; }
    public bool FailAuth { get; set; }
    public TaskCompletionSource? AuthenticationGate { get; set; }
    public TaskCompletionSource? VerificationGate { get; set; }
    public TaskCompletionSource VerificationStarted { get; } = new(TaskCreationOptions.RunContinuationsAsynchronously);
    public TaskCompletionSource AuthenticationStarted { get; } = new(TaskCreationOptions.RunContinuationsAsynchronously);
    public FactoryNetworkFixture()
    {
        Api = new(this, this);
        Network = new(Api, Api, Api);
    }
    public int Count<T>() => Requests.Count(request => request.Type == typeof(T));
    public Task<AiFactoryConnection> GetConnectionAsync(CancellationToken cancellationToken = default) =>
        Task.FromResult(new AiFactoryConnection("http://localhost:8765", "offline-test"));
    public static ProjectDeploymentScope Scope(string folder) => new()
    {
        PrefixResourceGroup = folder == Ado ? "ado-" : "gha-", SuffixResourceGroup = "-001", Region = "swedencentral",
        SubscriptionIds = [folder == Ado ? AdoSub : GhaSub]
    };
    public static OperationsOverview Overview(string folder)
    {
        var scope = Scope(folder);
        return new()
        {
            Source = "azure", GeneratedAt = "2026-09-08T12:00:00Z",
            Factory = new()
            {
                Folder = folder.Replace('\\', '/'), Name = folder, Orchestrator = folder == Ado ? "ado" : "gha",
                PrefixResourceGroup = scope.PrefixResourceGroup, SuffixResourceGroup = scope.SuffixResourceGroup,
                SubscriptionIds = scope.SubscriptionIds, MonitoringRegions = ["swedencentral"]
            },
            ResourceInventory = new() { Source = "azure", IsComplete = true, Subscriptions = scope.SubscriptionIds },
            PromptSummary = new() { Source = "azure" },
            Regions = [new() { Name = "swedencentral", HasFactory = true, FactoryCount = 1, ProjectCount = 1,
                ResourceCount = folder == Ado ? 100 : 200, CountStatus = "complete" }],
            Projects = [new() { ProjectNumber = "017", Environments = [new()
            {
                ResourceGroup = scope.PrefixResourceGroup + "project017-sdc-dev-001",
                SubscriptionId = scope.SubscriptionIds[0]
            }] }],
            CommonResourceGroups = [new() { Name = scope.PrefixResourceGroup + "esml-common-sdc-dev-001",
                SubscriptionId = scope.SubscriptionIds[0] }]
        };
    }
    public async Task<TResponse> SendAsync<TResponse>(HttpRequestMessage request, CancellationToken cancellationToken = default)
    {
        var body = request.Content is null ? new JsonObject() :
            JsonNode.Parse(await request.Content.ReadAsStringAsync(cancellationToken))!.AsObject();
        var folder = body["aifactory_folder"]?.ToString() ?? "";
        Requests.Add((typeof(TResponse), folder, body));
        object result;
        if (typeof(TResponse) == typeof(FactorySchema))
            result = new FactorySchema();
        else if (typeof(TResponse) == typeof(RecentProjectsResult))
        {
            if (FailDiscovery) { throw new HttpRequestException("Cannot list recent factories"); }
            result = new RecentProjectsResult { RecentProjects = [
                new() { Folder = Ado, Orchestrator = "ado" }, new() { Folder = "C:/ado/", Orchestrator = "ADO" },
                new() { Folder = Gha, Orchestrator = "gha" }
            ] };
        }
        else if (typeof(TResponse) == typeof(OperationsOverview))
        {
            if (folder == FailedInventoryFolder) { throw new HttpRequestException("Factory unreachable"); }
            var overview = Overview(folder == WrongInventoryFolder ? Gha : folder);
            result = MockInventory ? overview with { Source = "mock", ResourceInventory = new() { Source = "mock" } } : overview;
        }
        else if (typeof(TResponse) == typeof(ProjectsResult))
            result = new ProjectsResult { Projects = [new() {
                ProjectNumber = "017", Path = folder + @"\project017.json", DeploymentScope = Scope(folder) }] };
        else if (typeof(TResponse) == typeof(ScaleSetsResult))
            result = new ScaleSetsResult { ScaleSets = [new() {
                ScaleSetId = "001", Path = folder + @"\scaleset001.json", DeploymentScope = Scope(folder) }] };
        else if (typeof(TResponse) == typeof(ProjectResourceGroupVerification) ||
                 typeof(TResponse) == typeof(ScaleSetResourceGroupVerification))
        {
            VerificationStarted.TrySetResult();
            if (VerificationGate is not null) { await VerificationGate.Task.WaitAsync(cancellationToken); }
            var project = typeof(TResponse) == typeof(ProjectResourceGroupVerification);
            Assert.Equal(folder + (project ? @"\project017.json" : @"\scaleset001.json"), body["path"]!.ToString());
            var scope = Scope(folder);
            var checks = new ResourceGroupHttpCheck[] { new()
            {
                ResourceId = $"/subscriptions/{scope.SubscriptionIds[0]}/resourceGroups/{scope.PrefixResourceGroup}" +
                    (WrongVerificationIds ? "wrong" : project ? "project017-sdc-dev-001" : "esml-common-sdc-dev-001"),
                Verified = true, HttpStatus = 200
            } };
            result = project
                ? new ProjectResourceGroupVerification { ProjectNumber = "017", Checks = checks }
                : new ScaleSetResourceGroupVerification { ScaleSetId = "001", Checks = checks };
        }
        else if (typeof(TResponse) == typeof(AzureAuthenticationStatus))
        {
            Assert.EndsWith("/azure/auth/status", request.RequestUri!.AbsolutePath);
            AuthenticationStarted.TrySetResult();
            if (AuthenticationGate is not null) { await AuthenticationGate.Task.WaitAsync(cancellationToken); }
            if (FailAuth) { throw new HttpRequestException("Status unavailable"); }
            var signedIn = SignedIn && folder != ExpiredFolder;
            result = new AzureAuthenticationStatus
            {
                State = signedIn ? "authenticated" : "login_required", IsLoggedIn = signedIn,
                Message = signedIn ? "Verified" : "Token expired",
                Tenants = [new() { TenantId = folder == Ado ? AdoSub : GhaSub, NeedsLogin = !signedIn }]
            };
        }
        else if (typeof(TResponse) == typeof(ProjectConfigurationDeleteResult))
            result = new ProjectConfigurationDeleteResult { DeletedPath = body["path"]!.ToString(), Message = "Deleted" };
        else if (typeof(TResponse) == typeof(ScaleSetConfigurationDeleteResult))
            result = new ScaleSetConfigurationDeleteResult { DeletedPath = body["path"]!.ToString(), Message = "Deleted" };
        else if (typeof(TResponse) == typeof(ProjectLoadResult))
        {
            BeforeProjectLoad?.Invoke();
            result = new ProjectLoadResult { Path = WrongLoadPath ? "wrong.json" : folder + @"\project017.json",
                State = new() { ["project_number_000"] = "017" } };
        }
        else if (typeof(TResponse) == typeof(ScaleSetLoadResult))
            result = new ScaleSetLoadResult { Path = folder + @"\scaleset001.json", State = new() { ["admin_aifactorySuffixRG"] = "001" } };
        else throw new NotSupportedException($"Unexpected offline request: {request.RequestUri}");
        return (TResponse)result;
    }
}

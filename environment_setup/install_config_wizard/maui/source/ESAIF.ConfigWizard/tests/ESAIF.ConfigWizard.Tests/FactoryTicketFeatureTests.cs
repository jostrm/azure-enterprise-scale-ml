using System.Text.Json.Nodes;
using ESAIF.BaseLayer.Networking;
using ESAIF.ConfigWizard.Services;
using ESAIF.ConfigWizard.ViewModels;
using ESAIF.DomainLayer.Configuration;
using ESAIF.DomainLayer.Operations;

namespace ESAIF.ConfigWizard.Tests;

public sealed partial class FactoryTicketFeatureTests
{
    private const string ResourceGroup = "mrvel-1-project011-sdc-dev-007";
    private static TicketResourceIdentity ResourceIdentity(string group = ResourceGroup) => new()
    {
        ResourceGroup = group, ProjectNumber = "011", Region = "sdc", Environment = "dev",
        AiFactoryPrefix = "mrvel-1-", AiFactorySuffix = "-007"
    };
    [Fact]
    public void GenericAnalytics_PreservesSourceRowsAndUnknownsWithoutInventingCounts()
    {
        var section = new AnalyticsSectionViewModel(new FactoryAnalyticsSection
        {
            Title = "Agents by department",
            Source = "project configuration",
            Columns = ["Department", "Agent count", "Cost center"],
            Rows = [new[] { "Engineering", "" }]
        });
        Assert.Equal("project configuration", section.Source);
        Assert.Equal("Engineering", section.Rows.Single().Cells[0].Value);
        Assert.Equal("Unknown", section.Rows.Single().Cells[1].Value);
        Assert.Equal("Unknown", section.Rows.Single().Cells[2].Value);
        Assert.False(section.IsEmpty);
    }

    [Fact]
    public async Task Analytics_CoalescesRepeatedLoadsAndRefreshesPublishedSnapshots()
    {
        var (wizard, operations) = await CreateSessions();
        var pending = new TaskCompletionSource<FactoryAnalytics>();
        var analytics = new AnalyticsClient { Handler = _ => pending.Task };
        var tickets = new TicketClient();
        var vm = new CurrentFactoryAnalyticsViewModel(analytics, tickets, operations);

        var first = vm.RefreshAsync();
        Assert.Same(first, vm.RefreshAsync());
        pending.SetResult(new FactoryAnalytics { Source = "configuration" });
        await first;
        await vm.RefreshAsync();
        Assert.Equal(1, analytics.Calls);
        Assert.Equal(1, tickets.ListCalls);
        Assert.Equal(wizard.GetString("_save_folder"), tickets.LastListFolder);

        operations.ApplyRefreshedOverview(operations.Folder, new OperationsOverview());
        await vm.RefreshAsync();
        Assert.Equal(2, analytics.Calls);
        Assert.Equal(2, tickets.ListCalls);
    }

    [Fact]
    public async Task Analytics_FolderGuardDiscardsLatePreviousFactoryResults()
    {
        var (wizard, operations) = await CreateSessions();
        var previous = new TaskCompletionSource<FactoryAnalytics>();
        var analytics = new AnalyticsClient
        {
            Handler = folder => folder.EndsWith("FactoryA", StringComparison.Ordinal)
                ? previous.Task : Task.FromResult(new FactoryAnalytics { Title = "Factory B" })
        };
        var vm = new CurrentFactoryAnalyticsViewModel(analytics, new TicketClient(), operations);
        var oldLoad = vm.RefreshAsync();
        await Task.Yield();
        wizard.SetValue("_save_folder", @"C:\FactoryB");
        await vm.RefreshAsync();
        previous.SetResult(new FactoryAnalytics { Title = "Factory A" });
        await oldLoad;
        Assert.Equal("Factory B", vm.Title);
        Assert.Equal(@"C:\FactoryB", vm.Folder);

        wizard.SetValue("_save_folder", "");
        await vm.RefreshAsync();
        Assert.True(vm.IsMissingFolder);
        Assert.Empty(vm.Sections);
        Assert.Equal("Unknown", vm.NewTickets);
        Assert.False(vm.IsBusy);
    }

    [Fact]
    public async Task Analytics_TicketAuthenticationErrorLeavesAnalyticsUsableAndCountsUnknown()
    {
        var (_, operations) = await CreateSessions();
        var vm = new CurrentFactoryAnalyticsViewModel(
            new AnalyticsClient(),
            new TicketClient { ListError = new UnauthorizedAccessException("Azure login required") },
            operations);
        await vm.RefreshAsync();
        Assert.Equal("configuration", vm.Source);
        Assert.Equal("Unknown", vm.NewTickets);
        Assert.Contains("Sign in to Azure", vm.TicketError);
        Assert.Empty(vm.ErrorMessage);
        Assert.False(vm.IsBusy);
    }

    [Fact]
    public async Task Analytics_ApiFailureIsActionableAndExplicitReloadRetries()
    {
        var (_, operations) = await CreateSessions();
        var api = new AnalyticsClient { Handler = _ => throw new HttpRequestException("offline") };
        var vm = new CurrentFactoryAnalyticsViewModel(api, new TicketClient(), operations);
        await vm.RefreshAsync();
        Assert.Contains("Check the API connection", vm.ErrorMessage);
        Assert.Equal("Unknown", vm.Source);
        await vm.RefreshAsync();
        Assert.Equal(1, api.Calls);
        await vm.RefreshAsync(true);
        Assert.Equal(2, api.Calls);
    }

    [Fact]
    public async Task Analytics_ProgrammingErrorsPropagateWithoutLeavingBusyState()
    {
        var (_, operations) = await CreateSessions();
        var api = new AnalyticsClient { Handler = _ => throw new NullReferenceException("programming defect") };
        var vm = new CurrentFactoryAnalyticsViewModel(api, new TicketClient(), operations);
        await Assert.ThrowsAsync<NullReferenceException>(() => vm.RefreshAsync());
        Assert.False(vm.IsBusy);
        Assert.Empty(vm.ErrorMessage);
    }

    [Fact]
    public async Task Analytics_TicketProgrammingErrorsAreNotReportedAsSignInFailures()
    {
        var (_, operations) = await CreateSessions();
        var vm = new CurrentFactoryAnalyticsViewModel(new AnalyticsClient(),
            new TicketClient { ListError = new NullReferenceException("programming defect") }, operations);
        await Assert.ThrowsAsync<NullReferenceException>(() => vm.RefreshAsync());
        Assert.False(vm.IsBusy);
        Assert.Empty(vm.TicketError);
    }

    [Fact]
    public async Task Tickets_ProjectIdentityComesOnlyFromResourceGroupNotWizardProject()
    {
        var (wizard, _) = await CreateSessions();
        var vm = new TicketsViewModel(new TicketClient(), wizard);
        Assert.Empty(vm.ProjectNumber);
        vm.ResourceGroup = ResourceGroup;
        await vm.ExtractResourceGroupAsync();
        Assert.Equal("011", vm.ProjectNumber);
        wizard.SetValue("project_number_000", "018");
        Assert.Equal("011", vm.ProjectNumber);
        await vm.LoadAsync();
        Assert.Equal("011", vm.ProjectNumber);
        wizard.SetValue("_save_folder", @"C:\FactoryB");
        Assert.Empty(vm.ProjectNumber);
        Assert.Empty(vm.ResourceGroup);
    }

    [Fact]
    public async Task Tickets_ExpectedProfileErrorsKeepTicketListButProgrammingErrorsPropagate()
    {
        var (wizard, _) = await CreateSessions();
        var vm = new TicketsViewModel(new TicketClient { ConnectionsError = new IOException("offline") }, wizard);
        await vm.LoadAsync();
        Assert.Single(vm.Tickets);
        Assert.Contains("Connector profiles unavailable", vm.Warning);

        var broken = new TicketsViewModel(new TicketClient { ConnectionsError = new NullReferenceException("programming defect") }, wizard);
        await Assert.ThrowsAsync<NullReferenceException>(() => broken.LoadAsync());
        Assert.False(broken.IsBusy);
        Assert.Empty(broken.Warning);
    }

    [Fact]
    public async Task Tickets_CreateAndUpdateDoNotSendToExternalConnectors()
    {
        var (wizard, _) = await CreateSessions();
        var api = new TicketClient();
        var vm = new TicketsViewModel(api, wizard);
        await vm.LoadAsync();
        vm.Title = "Request a service";
        vm.Description = "Private project context";
        vm.ResourceGroup = ResourceGroup;
        vm.Severity = "blocker";
        vm.CostCenter = "12345";
        vm.DepartmentName = "hr";
        vm.RequestedService = "Azure AI Search";
        await vm.CreateAsync();

        Assert.Null(api.Created!.AiFactoryFolder);
        Assert.Null(api.Created.ProjectNumber);
        Assert.Equal(ResourceGroup, api.Created.ResourceGroup);
        Assert.Equal("blocker", api.Created.Severity);
        Assert.Equal("12345", api.Created.CostCenter);
        Assert.Equal("hr", api.Created.DepartmentName);
        Assert.Equal("Azure AI Search", api.Created.RequestedService);
        Assert.Equal("owner@example.test", vm.SelectedTicket!.Owner);
        Assert.Equal("owner@example.test", vm.Owner);
        vm.SelectedStatus = "Active";
        vm.SelectedSeverity = "major";
        await vm.SaveStatusAsync();
        Assert.Equal("Active", vm.SelectedTicket!.Status);
        Assert.Equal("major", vm.SelectedTicket.Severity);
        Assert.Equal(0, api.PreviewCalls);
        Assert.Equal(0, api.SyncCalls);
    }

    [Fact]
    public async Task Tickets_ServiceRequestsRequireRequestedServiceButBugReportsDoNot()
    {
        var (wizard, _) = await CreateSessions();
        var api = new TicketClient();
        var vm = new TicketsViewModel(api, wizard)
        {
            Title = "New request",
            Description = "Details",
            ResourceGroup = ResourceGroup
        };
        await vm.CreateAsync();
        Assert.Null(api.Created);
        Assert.Contains("requested Azure service", vm.ErrorMessage);
        vm.TicketType = "Bug report";
        vm.ResourceGroup = ResourceGroup;
        await vm.CreateAsync();
        Assert.NotNull(api.Created);
        Assert.Null(api.Created.RequestedService);
    }

    [Fact]
    public async Task Tickets_RequirePreviewAndExplicitConfirmationAndUseOnlyConfirmationId()
    {
        var (wizard, _) = await CreateSessions();
        var api = new TicketClient();
        var vm = new TicketsViewModel(api, wizard);
        await vm.LoadAsync();
        await vm.ConfirmSyncAsync();
        Assert.Equal(0, api.SyncCalls);
        Assert.Contains("fresh preview", vm.ErrorMessage);

        vm.SelectedTicket = vm.Tickets.Single();
        vm.SelectedConnection = vm.Connections.Single();
        await vm.PreviewSyncAsync();
        Assert.Equal(1, api.PreviewCalls);
        Assert.Equal(0, api.SyncCalls);
        Assert.True(vm.HasPreview);
        Assert.Equal("Jira · https://example.test · OPS", vm.PreviewRecipient);
        Assert.Equal("{\"title\":\"private title\",\"owner\":\"owner@example.test\"}", vm.PreviewContent);

        await vm.ConfirmSyncAsync();
        Assert.Equal("confirmation-1", api.ConfirmationId);
        Assert.Equal(1, api.SyncCalls);
        Assert.False(vm.HasPreview);
        await vm.ConfirmSyncAsync();
        Assert.Equal(1, api.SyncCalls);
    }

    [Fact]
    public async Task Tickets_ChangingStatusOrConnectionInvalidatesDisclosure()
    {
        var (wizard, _) = await CreateSessions();
        var api = new TicketClient();
        var vm = new TicketsViewModel(api, wizard);
        await vm.LoadAsync();
        vm.SelectedTicket = vm.Tickets.Single();
        vm.SelectedConnection = vm.Connections.Single();
        await vm.PreviewSyncAsync();
        vm.SelectedStatus = "Solved";
        Assert.False(vm.HasPreview);
        await vm.PreviewSyncAsync();
        Assert.Equal(1, api.PreviewCalls);
        Assert.Contains("Save the changed status", vm.ErrorMessage);
        vm.SelectedStatus = "New";
        await vm.PreviewSyncAsync();
        vm.SelectedConnection = null;
        Assert.False(vm.HasPreview);
        await vm.ConfirmSyncAsync();
        Assert.Equal(0, api.SyncCalls);
    }

    [Fact]
    public async Task Tickets_FolderChangeDiscardsInFlightPreviewAndOldSelection()
    {
        var (wizard, _) = await CreateSessions();
        var pending = new TaskCompletionSource<TicketSyncPreview>();
        var api = new TicketClient { PreviewHandler = () => pending.Task };
        var vm = new TicketsViewModel(api, wizard);
        await vm.LoadAsync();
        vm.SelectedTicket = vm.Tickets.Single();
        vm.SelectedConnection = vm.Connections.Single();
        var load = vm.PreviewSyncAsync();
        wizard.SetValue("_save_folder", @"C:\FactoryB");
        pending.SetResult(TicketClient.Preview);
        await load;
        Assert.False(vm.HasPreview);
        Assert.Null(vm.SelectedTicket);
        Assert.Empty(vm.Tickets);
        await vm.ConfirmSyncAsync();
        Assert.Equal(0, api.SyncCalls);
    }

    [Fact]
    public async Task Tickets_FailedListNeverShowsInventedZeroCounts()
    {
        var (wizard, _) = await CreateSessions();
        var vm = new TicketsViewModel(new TicketClient { ListError = new UnauthorizedAccessException("Sign in") }, wizard);
        await vm.LoadAsync();
        Assert.Contains("Unknown", vm.CountsLabel);
        Assert.Contains("Sign in", vm.ErrorMessage);
        Assert.Empty(vm.Tickets);
        vm.Title = "Created after failed list";
        vm.Description = "Details";
        vm.TicketType = "Bug report";
        await vm.CreateAsync();
        Assert.Contains("Unknown", vm.CountsLabel);
    }

    [Fact]
    public async Task TicketConnections_SaveOnlyPersistsCredentialReferenceAndNeverSends()
    {
        var api = new TicketClient();
        var vm = new TicketConnectionsViewModel(api);
        await vm.LoadAsync();
        vm.Name = "Operations";
        vm.BaseUrl = "https://example.test";
        vm.ProjectKey = "OPS";
        vm.Username = "person@example.test";
        vm.CredentialEnv = "JIRA_API_TOKEN";
        await vm.SaveAsync();
        Assert.Equal("JIRA_API_TOKEN", api.Saved!.CredentialEnv);
        Assert.Contains("NOT tested", vm.StatusMessage);
        Assert.Equal(0, api.SyncCalls);
        Assert.Equal(0, api.PreviewCalls);
        vm.CredentialEnv = "secret value with spaces";
        await vm.SaveAsync();
        Assert.Contains("not a secret value", vm.ErrorMessage);
        Assert.Equal(1, api.SaveCalls);
    }

    [Fact]
    public async Task AzureIdentityInvalidationClearsPerUserTicketsProfilesCountsAndConfirmation()
    {
        var client = new AiFactoryApiClient(new SchemaTransport(), new ConnectionProvider());
        var wizard = new WizardSession(client, startupFolder: string.Empty);
        await wizard.InitializeAsync();
        var authentication = new AzureAuthenticationMonitor(client, wizard, new FactoryNetworkSession(client, client, client));
        await authentication.CheckAsync();
        Assert.True(authentication.IsLoggedIn);
        var ticketApi = new TicketClient();
        var tickets = new TicketsViewModel(ticketApi, wizard, authentication);
        var profiles = new TicketConnectionsViewModel(ticketApi, authentication);
        var analytics = new CurrentFactoryAnalyticsViewModel(
            new AnalyticsClient(), ticketApi, new OperationsSession(client, wizard), authentication);
        await tickets.LoadAsync();
        await profiles.LoadAsync();
        await analytics.RefreshAsync();
        tickets.SelectedTicket = tickets.Tickets.Single();
        tickets.SelectedConnection = tickets.Connections.Single();
        await tickets.PreviewSyncAsync();
        Assert.True(tickets.HasPreview);

        authentication.Invalidate("Signed out");

        Assert.Empty(tickets.Tickets);
        Assert.Empty(tickets.Connections);
        Assert.Empty(profiles.Connections);
        Assert.False(tickets.HasPreview);
        Assert.Equal("Unknown", analytics.NewTickets);
        Assert.Contains("identity changed", analytics.TicketError);
        await tickets.ConfirmSyncAsync();
        Assert.Equal(0, ticketApi.SyncCalls);
    }

    [Fact]
    public async Task Tickets_ExtractsAllReadOnlyIdentityFieldsAndClearsThemWhenInputChanges()
    {
        var (wizard, _) = await CreateSessions();
        var vm = new TicketsViewModel(new TicketClient(), wizard) { ResourceGroup = ResourceGroup };
        await vm.ExtractResourceGroupAsync();
        Assert.True(vm.HasResourceIdentity);
        Assert.Equal("011", vm.ProjectNumber);
        Assert.Equal("dev", vm.Environment);
        Assert.Equal("sdc", vm.Region);
        Assert.Equal("mrvel-1-", vm.AiFactoryPrefix);
        Assert.Equal("-007", vm.AiFactorySuffix);
        Assert.Equal(["minor", "major", "blocker"], vm.Severities);
        Assert.DoesNotContain("Blocker", vm.Types);
        Assert.Contains("does not verify", vm.StatusMessage);
        vm.ResourceGroup = "invalid";
        Assert.False(vm.HasResourceIdentity);
        Assert.Empty(vm.ProjectNumber);
        Assert.Empty(vm.AiFactoryPrefix);
    }

    [Fact]
    public async Task Tickets_ParsingFailuresCannotCreateTicketOrReuseOldMetadata()
    {
        var (wizard, _) = await CreateSessions();
        var api = new TicketClient { ParseHandler = _ => throw new InvalidOperationException("Invalid project resource group") };
        var vm = new TicketsViewModel(api, wizard)
        {
            ResourceGroup = "bad", Title = "Bug", Description = "Details", TicketType = "Bug report"
        };
        await vm.CreateAsync();
        Assert.Null(api.Created);
        Assert.Contains("Invalid project resource group", vm.ErrorMessage);
        Assert.False(vm.HasResourceIdentity);
    }

    [Fact]
    public async Task Tickets_LateParsedIdentityCannotOverwriteChangedResourceGroup()
    {
        var (wizard, _) = await CreateSessions();
        var pending = new TaskCompletionSource<TicketResourceIdentity>();
        var vm = new TicketsViewModel(new TicketClient { ParseHandler = _ => pending.Task }, wizard)
        {
            ResourceGroup = ResourceGroup
        };
        var task = vm.ExtractResourceGroupAsync();
        vm.ResourceGroup = "other-project001-eus2-prod-001";
        pending.SetResult(ResourceIdentity());
        await task;
        Assert.False(vm.HasResourceIdentity);
        Assert.Empty(vm.ProjectNumber);
        Assert.Contains("context changed", vm.StatusMessage);
    }

    [Fact]
    public async Task Tickets_ResourceGroupTicketNeedsNoLocalFactoryFolderAndOptionalMetadataIsOmitted()
    {
        var (wizard, _) = await CreateSessions();
        wizard.SetValue("_save_folder", "");
        var api = new TicketClient();
        var vm = new TicketsViewModel(api, wizard)
        {
            ResourceGroup = ResourceGroup, TicketType = "Bug report", Title = "Bug", Description = "Details"
        };
        await vm.CreateAsync();
        Assert.NotNull(api.Created);
        Assert.Null(api.Created.AiFactoryFolder);
        Assert.Equal("minor", api.Created.Severity);
        Assert.Null(api.Created.CostCenter);
        Assert.Null(api.Created.DepartmentName);
    }

    [Fact]
    public async Task Tickets_SeverityChangeInvalidatesPreviewAndMustBeSavedBeforeSync()
    {
        var (wizard, _) = await CreateSessions();
        var api = new TicketClient();
        var vm = new TicketsViewModel(api, wizard);
        await vm.LoadAsync();
        vm.SelectedTicket = vm.Tickets.Single();
        vm.SelectedConnection = vm.Connections.Single();
        await vm.PreviewSyncAsync();
        vm.SelectedSeverity = "blocker";
        Assert.False(vm.HasPreview);
        await vm.PreviewSyncAsync();
        Assert.Contains("severity", vm.ErrorMessage);
        Assert.Equal(1, api.PreviewCalls);
        await vm.SaveStatusAsync();
        await vm.PreviewSyncAsync();
        Assert.True(vm.HasPreview);
        Assert.Equal(0, api.SyncCalls);
    }

    private static async Task<(WizardSession Wizard, OperationsSession Operations)> CreateSessions()
    {
        var client = new AiFactoryApiClient(new SchemaTransport(), new ConnectionProvider());
        var wizard = new WizardSession(client, startupFolder: string.Empty);
        await wizard.InitializeAsync();
        return (wizard, new OperationsSession(client, wizard));
    }

    private sealed class ConnectionProvider : IAiFactoryConnectionProvider
    {
        public Task<AiFactoryConnection> GetConnectionAsync(CancellationToken cancellationToken = default) =>
            Task.FromResult(new AiFactoryConnection("http://localhost:8765", "test-key"));
    }

    private sealed class SchemaTransport : IJsonApiTransport
    {
        public Task<TResponse> SendAsync<TResponse>(HttpRequestMessage request, CancellationToken cancellationToken = default)
        {
            object response = typeof(TResponse) == typeof(AzureAuthenticationStatus)
                ? new AzureAuthenticationStatus { IsLoggedIn = true, AccountName = "owner@example.test", TenantId = "tenant-1" }
                : typeof(TResponse) == typeof(RecentProjectsResult) ? new RecentProjectsResult()
                : new FactorySchema
            {
                Defaults = new JsonObject { ["_save_folder"] = @"C:\FactoryA", ["project_number_000"] = "017" }
            };
            return Task.FromResult((TResponse)response);
        }
    }

    private sealed class AnalyticsClient : IFactoryAnalyticsClient
    {
        public int Calls { get; private set; }
        public Func<string, Task<FactoryAnalytics>> Handler { get; set; } =
            _ => Task.FromResult(new FactoryAnalytics { Source = "configuration" });
        public Task<FactoryAnalytics> GetCurrentFactoryAnalyticsAsync(string aiFactoryFolder, CancellationToken cancellationToken = default)
        {
            ++Calls;
            return Handler(aiFactoryFolder);
        }
    }

    private sealed class TicketClient : ITicketClient
    {
        public static TicketSyncPreview Preview { get; } = new()
        {
            ConfirmationId = "confirmation-1",
            Recipient = "Jira · https://example.test · OPS",
            Content = "{\"title\":\"private title\",\"owner\":\"owner@example.test\"}"
        };
        private FactoryTicket _ticket = new()
        {
            Id = "ticket-1", Title = "Blocker", Owner = "owner@example.test",
            Status = "New", AiFactoryFolder = @"C:\FactoryA", ProjectNumber = "017"
        };
        public int ListCalls { get; private set; }
        public int ConnectionsCalls { get; private set; }
        public int PreviewCalls { get; private set; }
        public int SyncCalls { get; private set; }
        public int SaveCalls { get; private set; }
        public string? LastListFolder { get; private set; }
        public string? ConfirmationId { get; private set; }
        public CreateTicketRequest? Created { get; private set; }
        public TicketConnection? Saved { get; private set; }
        public Exception? ListError { get; init; }
        public Exception? ConnectionsError { get; set; }
        public Func<Task<TicketListResult>>? ListHandler { get; init; }
        public Func<Task<TicketSyncPreview>> PreviewHandler { get; init; } = () => Task.FromResult(Preview);
        public Func<string, Task<TicketResourceIdentity>> ParseHandler { get; init; } =
            group => Task.FromResult(ResourceIdentity(group));
        public Task<TicketResourceIdentity> ParseTicketResourceGroupAsync(string group, CancellationToken cancellationToken = default) =>
            ParseHandler(group);

        public Task<TicketListResult> ListTicketsAsync(string? aiFactoryFolder = null, CancellationToken cancellationToken = default)
        {
            ++ListCalls;
            LastListFolder = aiFactoryFolder;
            if (ListError is not null) throw ListError;
            if (ListHandler is not null) return ListHandler();
            return Task.FromResult(new TicketListResult { Owner = _ticket.Owner, Tickets = [_ticket], Counts = new TicketCounts { New = 1 } });
        }
        public Task<FactoryTicket> CreateTicketAsync(CreateTicketRequest request, CancellationToken cancellationToken = default)
        {
            Created = request;
            _ticket = _ticket with
            {
                Id = "created", Title = request.Title, Severity = request.Severity ?? "minor",
                ResourceGroup = request.ResourceGroup ?? string.Empty
            };
            return Task.FromResult(_ticket);
        }
        public Task<FactoryTicket> UpdateTicketAsync(string id, string status, CancellationToken cancellationToken = default)
            => UpdateTicketAsync(id, status, null, cancellationToken);
        public Task<FactoryTicket> UpdateTicketAsync(string id, string status, string? severity, CancellationToken cancellationToken = default)
        {
            _ticket = _ticket with { Status = status, Severity = severity ?? _ticket.Severity };
            return Task.FromResult(_ticket);
        }
        public Task<TicketConnectionsResult> ListTicketConnectionsAsync(CancellationToken cancellationToken = default)
        {
            ++ConnectionsCalls;
            if (ConnectionsError is not null) throw ConnectionsError;
            return Task.FromResult(new TicketConnectionsResult { Connections = [new TicketConnection { Id = "connection-1", Name = "Jira profile" }] });
        }
        public Task<TicketConnection> SaveTicketConnectionAsync(TicketConnection request, CancellationToken cancellationToken = default)
        {
            ++SaveCalls;
            Saved = request;
            return Task.FromResult(request with { Id = request.Id ?? "new-connection" });
        }
        public Task<TicketSyncPreview> PreviewTicketSyncAsync(string ticketId, string connectionId, CancellationToken cancellationToken = default)
        {
            ++PreviewCalls;
            return PreviewHandler();
        }
        public Task<FactoryTicket> ConfirmTicketSyncAsync(string confirmationId, CancellationToken cancellationToken = default)
        {
            ++SyncCalls;
            ConfirmationId = confirmationId;
            return Task.FromResult(_ticket with { SyncState = "synced" });
        }
    }
}

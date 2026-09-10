using ESAIF.BaseLayer.Networking;
using ESAIF.ConfigWizard.Services;
using ESAIF.ConfigWizard.ViewModels;
using ESAIF.DomainLayer.Configuration;

namespace ESAIF.ConfigWizard.Tests;

public sealed partial class FactoryTicketFeatureTests
{
    [Fact]
    public async Task TicketTabs_DefaultToTicketsAndReuseInjectedModelsWithoutWritesOrReloads()
    {
        var (wizard, _) = await CreateSessions();
        var api = new TicketClient();
        var tickets = new TicketsViewModel(api, wizard);
        var profiles = new TicketConnectionsViewModel(api);
        var tabs = new TicketTabsViewModel(tickets, profiles);
        Assert.Same(tickets, tabs.Tickets);
        Assert.Same(profiles, tabs.TicketConnections);
        Assert.True(tabs.IsTicketsTab);
        Assert.False(tabs.IsConnectionsTab);
        Assert.Contains("selected", tabs.TicketsTabDescription);
        Assert.Equal(0, api.ListCalls);
        Assert.Equal(0, api.ConnectionsCalls);

        await tabs.LoadSelectedTabAsync();
        tickets.Title = "Keep draft";
        tickets.Description = "Private draft";
        tickets.ResourceGroup = ResourceGroup;
        tickets.SelectedTicket = tickets.Tickets.Single();
        tickets.SelectedStatus = "Active";
        tickets.SelectedSeverity = "blocker";
        await tabs.ShowTabAsync(true);
        Assert.True(tabs.IsConnectionsTab);
        Assert.Contains("selected", tabs.ConnectionsTabDescription);
        Assert.DoesNotContain("selected", tabs.TicketsTabDescription);
        profiles.Name = "Unfinished profile";
        profiles.CredentialEnv = "ENV_NAME_ONLY";

        await tabs.ShowTabAsync(false);
        await tabs.ShowTabAsync(true);
        await tabs.LoadSelectedTabAsync();
        Assert.Equal("Keep draft", tickets.Title);
        Assert.Equal("Private draft", tickets.Description);
        Assert.Equal(ResourceGroup, tickets.ResourceGroup);
        Assert.Equal("Active", tickets.SelectedStatus);
        Assert.Equal("blocker", tickets.SelectedSeverity);
        Assert.NotNull(tickets.SelectedTicket);
        Assert.Equal("Unfinished profile", profiles.Name);
        Assert.Equal("ENV_NAME_ONLY", profiles.CredentialEnv);
        Assert.Equal(1, api.ListCalls);
        Assert.Equal(2, api.ConnectionsCalls);
        Assert.Null(api.Created);
        Assert.Equal(0, api.SaveCalls);
        Assert.Equal(0, api.PreviewCalls);
        Assert.Equal(0, api.SyncCalls);
    }

    [Fact]
    public async Task TicketTabs_ConnectionsRouteLoadsOnlyProfilesUntilTicketsAreSelected()
    {
        var (wizard, _) = await CreateSessions();
        var api = new TicketClient();
        var tabs = new TicketTabsViewModel(new TicketsViewModel(api, wizard), new TicketConnectionsViewModel(api));
        tabs.SelectTab(true);
        Assert.Equal(0, api.ConnectionsCalls);
        await tabs.LoadSelectedTabAsync();
        Assert.Equal(0, api.ListCalls);
        Assert.Equal(1, api.ConnectionsCalls);
        Assert.Single(tabs.TicketConnections.Connections);
        await tabs.ShowTabAsync(false);
        Assert.True(tabs.IsTicketsTab);
        Assert.Equal(1, api.ListCalls);
    }

    [Fact]
    public async Task TicketTabs_RepeatedSelectionCoalescesPendingLoad()
    {
        var (wizard, _) = await CreateSessions();
        var pending = new TaskCompletionSource<TicketListResult>();
        var api = new TicketClient { ListHandler = () => pending.Task };
        var tabs = new TicketTabsViewModel(new TicketsViewModel(api, wizard), new TicketConnectionsViewModel(api));
        var first = tabs.LoadSelectedTabAsync();
        Assert.Same(first, tabs.ShowTabAsync(false));
        await tabs.ShowTabAsync(true);
        Assert.Same(first, tabs.ShowTabAsync(false));
        Assert.Equal(1, api.ListCalls);
        pending.SetResult(new TicketListResult { Owner = "owner@example.test" });
        await first;
        Assert.False(tabs.Tickets.IsBusy);
    }

    [Fact]
    public async Task TicketTabs_ProfileErrorsStayIsolatedAndRetryIsExplicit()
    {
        var (wizard, _) = await CreateSessions();
        var api = new TicketClient { ConnectionsError = new IOException("Profiles offline") };
        var tabs = new TicketTabsViewModel(new TicketsViewModel(api, wizard), new TicketConnectionsViewModel(api));
        await tabs.LoadSelectedTabAsync();
        await tabs.ShowTabAsync(true);
        var warning = tabs.Tickets.Warning;
        var error = tabs.TicketConnections.ErrorMessage;
        Assert.Contains("Profiles offline", error);
        Assert.Single(tabs.Tickets.Tickets);
        Assert.Empty(tabs.Tickets.ErrorMessage);
        await tabs.ShowTabAsync(false);
        await tabs.ShowTabAsync(true);
        Assert.Equal(error, tabs.TicketConnections.ErrorMessage);
        Assert.Equal(warning, tabs.Tickets.Warning);
        Assert.Equal(2, api.ConnectionsCalls);
        api.ConnectionsError = null;
        await tabs.TicketConnections.LoadAsync();
        Assert.Empty(tabs.TicketConnections.ErrorMessage);
        Assert.Single(tabs.Tickets.Connections);
        Assert.Equal(1, api.ListCalls);
    }

    [Fact]
    public async Task TicketTabs_PreservePreviewWhenSwitchingAndInvalidateOnlyForChangedSelectedProfile()
    {
        var (wizard, _) = await CreateSessions();
        var api = new TicketClient();
        var tickets = new TicketsViewModel(api, wizard);
        var profiles = new TicketConnectionsViewModel(api);
        var tabs = new TicketTabsViewModel(tickets, profiles);
        await tabs.LoadSelectedTabAsync();
        tickets.SelectedTicket = tickets.Tickets.Single();
        tickets.SelectedConnection = tickets.Connections.Single();
        await tickets.PreviewSyncAsync();
        await tabs.ShowTabAsync(true);
        await tabs.ShowTabAsync(false);
        Assert.True(tickets.HasPreview);
        Assert.Equal(TicketClient.Preview.Content, tickets.PreviewContent);

        await tabs.ShowTabAsync(true);
        profiles.SelectedConnection = profiles.Connections.Single();
        profiles.Name = "Updated profile";
        profiles.BaseUrl = "https://example.test";
        profiles.ProjectKey = "OPS";
        profiles.CredentialEnv = "JIRA_API_TOKEN";
        await profiles.SaveAsync(); // In-memory fake only, never a real profile write.
        Assert.False(tickets.HasPreview);
        Assert.Equal("Updated profile", tickets.SelectedConnection!.Name);
        Assert.Equal("https://example.test", tickets.SelectedConnection.BaseUrl);
        await tabs.ShowTabAsync(false);
        Assert.Equal(1, api.ListCalls);
        Assert.Equal(0, api.SyncCalls);
    }

    [Fact]
    public async Task TicketTabs_FolderChangeStillClearsTicketsAndDraftWithoutClearingPerUserProfileDraft()
    {
        var (wizard, _) = await CreateSessions();
        var api = new TicketClient();
        var tabs = new TicketTabsViewModel(new TicketsViewModel(api, wizard), new TicketConnectionsViewModel(api));
        await tabs.LoadSelectedTabAsync();
        await tabs.ShowTabAsync(true);
        tabs.Tickets.Title = "Old factory draft";
        tabs.TicketConnections.Name = "My per-user profile draft";
        wizard.SetValue("_save_folder", @"C:\FactoryB");
        await tabs.ShowTabAsync(false);
        Assert.Empty(tabs.Tickets.Tickets);
        Assert.Empty(tabs.Tickets.Title);
        Assert.Contains("Factory changed", tabs.Tickets.StatusMessage);
        Assert.Equal("My per-user profile draft", tabs.TicketConnections.Name);
        Assert.Equal(1, api.ListCalls);
    }

    [Fact]
    public async Task TicketTabs_AuthInvalidationClearsBothTabsAndCannotRestoreOldOwnerOnSwitch()
    {
        var client = new AiFactoryApiClient(new SchemaTransport(), new ConnectionProvider());
        var wizard = new WizardSession(client, startupFolder: string.Empty);
        await wizard.InitializeAsync();
        var authentication = new AzureAuthenticationMonitor(client, wizard, new FactoryNetworkSession(client, client, client));
        await authentication.CheckAsync();
        var api = new TicketClient();
        var tabs = new TicketTabsViewModel(
            new TicketsViewModel(api, wizard, authentication),
            new TicketConnectionsViewModel(api, authentication));
        await tabs.LoadSelectedTabAsync();
        await tabs.ShowTabAsync(true);
        tabs.Tickets.Title = "Old owner draft";
        tabs.TicketConnections.Name = "Old owner profile";
        authentication.Invalidate("Signed out");
        await tabs.ShowTabAsync(false);
        await tabs.ShowTabAsync(true);
        Assert.Empty(tabs.Tickets.Tickets);
        Assert.Empty(tabs.Tickets.Connections);
        Assert.Empty(tabs.TicketConnections.Connections);
        Assert.Empty(tabs.Tickets.Title);
        Assert.Empty(tabs.TicketConnections.Name);
        Assert.Contains("Unknown", tabs.Tickets.Owner);
        Assert.Contains("identity changed", tabs.Tickets.StatusMessage);
        Assert.Contains("identity changed", tabs.TicketConnections.StatusMessage);
        Assert.Equal(1, api.ListCalls);
        Assert.Equal(2, api.ConnectionsCalls);
        Assert.Equal(0, api.SyncCalls);
    }
}

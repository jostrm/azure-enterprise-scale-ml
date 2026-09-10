using System.Text.Json.Nodes;
using ESAIF.ConfigWizard.Services;
using ESAIF.ConfigWizard.ViewModels;
using ESAIF.DomainLayer.Configuration;
using ESAIF.DomainLayer.Operations;

namespace ESAIF.ConfigWizard.Tests;

public sealed partial class FactoryTicketFeatureTests
{
    private const string DraftSub = "11111111-1111-4111-8111-111111111111";
    private const string DraftFolder = @"C:\FactoryA";
    private const string DraftGroup = "mrvel-1-project017vm-sdc-dev-007";

    [Fact]
    public void ProjectTicket_RowButtonPassesItsOwnItemAndDraftContextIsReadOnly()
    {
        var projectView = System.Xml.Linq.XDocument.Load(Path.Combine(AppContext.BaseDirectory, "Assets", "ProjectsPage.xaml"));
        var button = Assert.Single(projectView.Descendants(), element =>
            (string?)element.Attribute("AutomationId") == "ProjectCreateTicket");
        Assert.Equal("Create ticket", (string?)button.Attribute("Text"));
        Assert.Equal("OnCreateTicketClicked", (string?)button.Attribute("Clicked"));
        Assert.Equal("{Binding .}", (string?)button.Attribute("CommandParameter"));
        var code = File.ReadAllText(Path.Combine(AppContext.BaseDirectory, "Assets", "ProjectsPage.xaml.cs"));
        Assert.Contains("OpenForProjectAsync(this, item)", code);
        var ticketView = System.Xml.Linq.XDocument.Load(Path.Combine(AppContext.BaseDirectory, "Assets", "TicketsView.xaml"));
        var hint = Assert.Single(ticketView.Descendants(), element =>
            (string?)element.Attribute("AutomationId") == "TicketDraftContext");
        Assert.Equal("TechnicalLabel", hint.Name.LocalName);
        Assert.Equal("{Binding DraftContextHint}", (string?)hint.Attribute("Value"));
    }

    [Fact]
    public async Task ProjectTicket_RowUsesObservedGroupAndParserWithoutCreatingOrSyncing()
    {
        var (wizard, operations) = await CreateSessions();
        var parsed = new List<string>();
        var api = DraftClient(parsed);
        var tabs = new TicketTabsViewModel(new TicketsViewModel(api, wizard), new TicketConnectionsViewModel(api));
        await tabs.ShowTabAsync(true);
        var item = DraftItem();
        item.UpdateDeployment(DraftOverview());
        wizard.SetValue("_save_folder", @"C:\UnrelatedFactory");
        wizard.SetValue("project_number_000", "099");

        await DraftLauncher(wizard, operations, tabs).OpenForProjectAsync(new Page(), item);

        Assert.True(tabs.IsTicketsTab);
        Assert.Equal([DraftGroup], parsed);
        Assert.Equal(DraftGroup, tabs.Tickets.ResourceGroup);
        Assert.Equal("017vm", tabs.Tickets.ProjectNumber);
        Assert.Equal("dev", tabs.Tickets.Environment);
        Assert.Equal("sdc", tabs.Tickets.Region);
        Assert.Equal("mrvel-1-", tabs.Tickets.AiFactoryPrefix);
        Assert.Equal("-007", tabs.Tickets.AiFactorySuffix);
        Assert.Equal("owner@example.test", tabs.Tickets.Owner);
        Assert.Contains("unsaved", tabs.Tickets.DraftContextHint);
        Assert.Empty(tabs.Tickets.Title);
        Assert.Empty(tabs.Tickets.Description);
        Assert.Equal(TicketChoices.Types[0], tabs.Tickets.TicketType);
        Assert.Null(api.Created);
        Assert.Equal(0, api.SyncCalls);
        Assert.Equal(0, api.PreviewCalls);
        Assert.Equal(0, api.SaveCalls);
        Assert.Equal(@"C:\UnrelatedFactory", wizard.Identity.Folder);
        await tabs.ShowTabAsync(true);
        await tabs.ShowTabAsync(false);
        await tabs.Tickets.LoadAsync();
        Assert.Equal("017vm", tabs.Tickets.ProjectNumber);
        Assert.Equal(DraftGroup, tabs.Tickets.ResourceGroup);
    }

    [Fact]
    public async Task ProjectTicket_MultipleObservedGroupsChooseDevStageProdAndCancelDoesNothing()
    {
        var (wizard, operations) = await CreateSessions();
        var parsed = new List<string>();
        var api = DraftClient(parsed);
        var tabs = new TicketTabsViewModel(new TicketsViewModel(api, wizard), new TicketConnectionsViewModel(api));
        var item = DraftItem();
        item.UpdateDeployment(DraftOverview("prod", "test", "dev"));
        var page = new Page
        {
            ChooseAction = labels =>
            {
                Assert.StartsWith("Dev · ", labels[0]);
                Assert.StartsWith("Stage · ", labels[1]);
                Assert.StartsWith("Prod · ", labels[2]);
                return Task.FromResult("Cancel");
            }
        };
        tabs.SelectTab(true);
        tabs.Tickets.Title = "Preserve draft";
        await DraftLauncher(wizard, operations, tabs).OpenForProjectAsync(page, item);
        Assert.True(tabs.IsConnectionsTab);
        Assert.Equal("Preserve draft", tabs.Tickets.Title);
        Assert.Empty(parsed);
        Assert.Equal(0, api.ListCalls);

        tabs.Tickets.Title = string.Empty;
        page.ChooseAction = labels => Task.FromResult(labels[1]);
        await DraftLauncher(wizard, operations, tabs).OpenForProjectAsync(page, item);
        Assert.Equal("mrvel-1-project017vm-sdc-test-007", Assert.Single(parsed));
        Assert.Equal("stage", tabs.Tickets.Environment);
    }

    [Fact]
    public async Task ProjectTicket_CurrentWizardUsesOperationsEvenBeforeNetworkSnapshotExists()
    {
        var (wizard, operations) = await CreateSessions();
        wizard.ReplaceState(DraftState());
        operations.ApplyRefreshedOverview(DraftFolder, DraftOverview());
        var api = DraftClient([]);
        var tabs = new TicketTabsViewModel(new TicketsViewModel(api, wizard), new TicketConnectionsViewModel(api));
        await DraftLauncher(wizard, operations, tabs).OpenForCurrentProjectAsync(new Page());
        Assert.Equal(DraftGroup, tabs.Tickets.ResourceGroup);
        Assert.Equal("017vm", tabs.Tickets.ProjectNumber);
        Assert.Empty(tabs.Tickets.ErrorMessage);
        Assert.Null(api.Created);
    }

    [Fact]
    public void ProjectTicket_CurrentWizardFallsBackToMatchingSnapshotNotOtherFactoryWithSameProjectId()
    {
        var state = DraftState();
        var observed = DraftOverview();
        var wrongFactory = observed with { Factory = observed.Factory with { Folder = @"C:\DifferentFactory" } };
        var context = ProjectTicketContext.FromState(state, wrongFactory, observed);
        Assert.Equal(DraftGroup, Assert.Single(context.ResourceGroups).Name);
        Assert.Empty(ProjectTicketContext.FromState(state, wrongFactory, null).ResourceGroups);
        foreach (var (key, value) in new[]
        {
            ("admin_aifactoryPrefixRG", "other-"), ("admin_aifactorySuffixRG", "-099"),
            ("admin_location", "eastus2"), ("project_number_000", "018vm"),
            ("dev_sub_id", "22222222-2222-4222-8222-222222222222")
        })
        {
            var changed = (JsonObject)state.DeepClone();
            changed[key] = value;
            Assert.Empty(ProjectTicketContext.FromState(changed, observed, observed).ResourceGroups);
        }
    }

    [Fact]
    public void ProjectTicket_RowRejectsSameProjectInAnotherFolderOrScaleSet()
    {
        var observed = DraftOverview();
        var wrongFolder = observed with { Factory = observed.Factory with { Folder = @"C:\OtherFactory" } };
        var wrongScale = observed with { Factory = observed.Factory with { SuffixResourceGroup = "-008" } };
        Assert.Empty(ProjectTicketContext.FromProject(DraftItem(), wrongFolder, wrongScale).ResourceGroups);
        var wrongProject = observed with { Projects = [observed.Projects[0] with { ProjectNumber = "018vm" }] };
        Assert.Empty(ProjectTicketContext.FromProject(DraftItem(), wrongProject, null).ResourceGroups);
    }

    [Fact]
    public async Task ProjectTicket_NoObservedGroupShowsSelectedNumberWithoutInventedIdentity()
    {
        var (wizard, operations) = await CreateSessions();
        var parsed = new List<string>();
        var api = DraftClient(parsed);
        var tabs = new TicketTabsViewModel(new TicketsViewModel(api, wizard), new TicketConnectionsViewModel(api));
        await DraftLauncher(wizard, operations, tabs).OpenForProjectAsync(new Page(), DraftItem());
        Assert.True(tabs.IsTicketsTab);
        Assert.Equal("017vm", tabs.Tickets.SelectedProjectNumber);
        Assert.Empty(tabs.Tickets.ResourceGroup);
        Assert.False(tabs.Tickets.HasResourceIdentity);
        Assert.Contains("Missing observed RG", tabs.Tickets.Warning);
        Assert.Empty(parsed);
        Assert.Null(api.Created);
        await tabs.Tickets.LoadAsync();
        Assert.Contains("Missing observed RG", tabs.Tickets.DraftContextHint);
    }

    [Fact]
    public async Task ProjectTicket_ReplaceCancellationPreservesDraftSelectionAndExactSyncPreview()
    {
        var (wizard, operations) = await CreateSessions();
        var api = DraftClient([]);
        var tickets = new TicketsViewModel(api, wizard);
        var tabs = new TicketTabsViewModel(tickets, new TicketConnectionsViewModel(api));
        await tabs.LoadSelectedTabAsync();
        tickets.Title = "Keep title";
        tickets.Description = "Private body";
        tickets.ResourceGroup = ResourceGroup;
        tickets.CostCenter = "123";
        tickets.DepartmentName = "HR";
        tickets.Severity = "blocker";
        tickets.RequestedService = "Service";
        tickets.SelectedTicket = tickets.Tickets.Single();
        tickets.SelectedConnection = tickets.Connections.Single();
        await tickets.PreviewSyncAsync();
        tabs.SelectTab(true);
        var revision = tickets.DraftRevision;
        var confirms = 0;
        var page = new Page { Confirm = () => { ++confirms; return Task.FromResult(false); } };
        await DraftLauncher(wizard, operations, tabs).OpenForProjectAsync(page, DraftItem());
        Assert.Equal(1, confirms);
        Assert.True(tabs.IsConnectionsTab);
        Assert.Equal(revision, tickets.DraftRevision);
        Assert.Equal("Keep title", tickets.Title);
        Assert.Equal("Private body", tickets.Description);
        Assert.Equal("blocker", tickets.Severity);
        Assert.Equal(ResourceGroup, tickets.ResourceGroup);
        Assert.Equal("123", tickets.CostCenter);
        Assert.Equal("HR", tickets.DepartmentName);
        Assert.Equal("Service", tickets.RequestedService);
        Assert.True(tickets.HasSelection);
        Assert.True(tickets.HasPreview);
        Assert.Equal(TicketClient.Preview.Content, tickets.PreviewContent);
        Assert.Equal(0, api.SyncCalls);
    }

    [Fact]
    public async Task ProjectTicket_ConfirmedReplacementClearsOldTextAndInvalidatesConfirmation()
    {
        var (wizard, _) = await CreateSessions();
        var api = DraftClient([]);
        var tickets = new TicketsViewModel(api, wizard);
        await tickets.LoadAsync();
        tickets.Title = "Old project title";
        tickets.SelectedTicket = tickets.Tickets.Single();
        tickets.SelectedConnection = tickets.Connections.Single();
        await tickets.PreviewSyncAsync();
        Assert.True(await tickets.BeginDraftFromResourceGroupAsync(DraftGroup, "017vm", () => Task.FromResult(true)));
        Assert.Empty(tickets.Title);
        Assert.False(tickets.HasSelection);
        Assert.False(tickets.HasPreview);
        Assert.False(tickets.HasDraftContent);
        await tickets.ConfirmSyncAsync();
        Assert.Equal(0, api.SyncCalls);
        var confirms = 0;
        await tickets.BeginDraftFromResourceGroupAsync(DraftGroup, "017vm", () => { ++confirms; return Task.FromResult(false); });
        Assert.Equal(0, confirms);
        Assert.Null(api.Created);
    }

    [Fact]
    public async Task ProjectTicket_DraftEditedWhileConfirmingCannotBeReplaced()
    {
        var (wizard, _) = await CreateSessions();
        var tickets = new TicketsViewModel(DraftClient([]), wizard) { Title = "First draft" };
        var confirmation = new TaskCompletionSource<bool>();
        var pending = tickets.BeginDraftFromResourceGroupAsync(DraftGroup, "017vm", () => confirmation.Task);
        tickets.Description = "New edits while waiting";
        confirmation.SetResult(true);
        Assert.False(await pending);
        Assert.Equal("First draft", tickets.Title);
        Assert.Equal("New edits while waiting", tickets.Description);
        Assert.Empty(tickets.ResourceGroup);
    }

    [Theory]
    [InlineData(nameof(TicketsViewModel.Title), "A title")]
    [InlineData(nameof(TicketsViewModel.Description), "A description")]
    [InlineData(nameof(TicketsViewModel.ResourceGroup), DraftGroup)]
    [InlineData(nameof(TicketsViewModel.CostCenter), "123")]
    [InlineData(nameof(TicketsViewModel.DepartmentName), "HR")]
    [InlineData(nameof(TicketsViewModel.Severity), "major")]
    [InlineData(nameof(TicketsViewModel.TicketType), "Bug report")]
    [InlineData(nameof(TicketsViewModel.RequestedService), "Service")]
    public async Task ProjectTicket_EachEditedDraftFieldRequiresExplicitReplacement(string field, string value)
    {
        var (wizard, _) = await CreateSessions();
        var tickets = new TicketsViewModel(DraftClient([]), wizard);
        var property = typeof(TicketsViewModel).GetProperty(field)!;
        property.SetValue(tickets, value);
        var confirms = 0;
        Assert.False(await tickets.BeginDraftFromResourceGroupAsync(DraftGroup, "017vm",
            () => { ++confirms; return Task.FromResult(false); }));
        Assert.Equal(1, confirms);
        Assert.Equal(value, property.GetValue(tickets));
    }

    [Fact]
    public async Task ProjectTicket_LoadCompletesBeforePrefillingAndEditsDuringLoadArePreserved()
    {
        var (wizard, _) = await CreateSessions();
        var pending = new TaskCompletionSource<TicketListResult>();
        var api = new TicketClient { ListHandler = () => pending.Task };
        var tickets = new TicketsViewModel(api, wizard);
        var tabs = new TicketTabsViewModel(tickets, new TicketConnectionsViewModel(api));
        var launch = tickets.BeginDraftFromResourceGroupAsync(DraftGroup, "017vm", () => Task.FromResult(true),
            async () => { await tabs.ShowTabAsync(false); return true; });
        tickets.Title = "Newer user draft";
        pending.SetResult(new() { Owner = "owner@example.test" });
        Assert.False(await launch);
        Assert.Equal("Newer user draft", tickets.Title);
        Assert.Empty(tickets.ResourceGroup);
    }

    [Fact]
    public async Task ProjectTicket_LateParseCannotRestorePreviousDraftAfterUserEditsResourceGroup()
    {
        var (wizard, _) = await CreateSessions();
        var pending = new TaskCompletionSource<TicketResourceIdentity>();
        var tickets = new TicketsViewModel(new TicketClient { ParseHandler = _ => pending.Task }, wizard);
        var launch = tickets.BeginDraftFromResourceGroupAsync(DraftGroup, "017vm", () => Task.FromResult(true));
        tickets.ResourceGroup = "other-project001-eus2-prod-001";
        pending.SetResult(ResourceIdentity(DraftGroup) with { ProjectNumber = "017vm" });
        Assert.False(await launch);
        Assert.Equal("other-project001-eus2-prod-001", tickets.ResourceGroup);
        Assert.False(tickets.HasResourceIdentity);
        Assert.Empty(tickets.SelectedProjectNumber);
    }

    [Fact]
    public async Task ProjectTicket_ParserFailureShowsActionableErrorWithoutCreatingOrGuessing()
    {
        var (wizard, _) = await CreateSessions();
        var api = new TicketClient { ParseHandler = _ => throw new InvalidOperationException("Unrecognized resource group") };
        var tickets = new TicketsViewModel(api, wizard);
        await tickets.BeginDraftFromResourceGroupAsync(DraftGroup, "017vm", () => Task.FromResult(true));
        Assert.Equal(DraftGroup, tickets.ResourceGroup);
        Assert.False(tickets.HasResourceIdentity);
        Assert.Contains("Unrecognized", tickets.ErrorMessage);
        Assert.Contains("Nothing was created or sent", tickets.Warning);
        Assert.Null(api.Created);
        Assert.Equal(0, api.SyncCalls);
    }

    [Fact]
    public async Task ProjectTicket_ParsedIdentityForAnotherProjectIsRejected()
    {
        var (wizard, _) = await CreateSessions();
        var api = new TicketClient();
        var tickets = new TicketsViewModel(api, wizard);
        await tickets.BeginDraftFromResourceGroupAsync(DraftGroup, "017vm", () => Task.FromResult(true));
        Assert.False(tickets.HasResourceIdentity);
        Assert.Contains("does not identify the selected project", tickets.ErrorMessage);
        Assert.Null(api.Created);
    }

    [Fact]
    public async Task ProjectTicket_StartupAuthenticationSettlesBeforePrefilling()
    {
        var client = new AiFactoryApiClient(new SchemaTransport(), new ConnectionProvider());
        var wizard = new WizardSession(client, startupFolder: string.Empty);
        await wizard.InitializeAsync();
        var network = new FactoryNetworkSession(client, client, client);
        var authentication = new AzureAuthenticationMonitor(client, wizard, network);
        var api = DraftClient([]);
        var tickets = new TicketsViewModel(api, wizard, authentication);
        var tabs = new TicketTabsViewModel(tickets, new TicketConnectionsViewModel(api, authentication));
        var check = authentication.CheckAsync();
        var item = DraftItem();
        item.UpdateDeployment(DraftOverview());
        await new ProjectTicketLauncher(wizard, new OperationsSession(client, wizard), network, tabs, authentication)
            .OpenForProjectAsync(new Page(), item);
        await check;
        Assert.Equal(DraftGroup, tickets.ResourceGroup);
        Assert.Equal("017vm", tickets.ProjectNumber);
        Assert.Equal("owner@example.test", tickets.Owner);
        authentication.Invalidate("Signed out");
        Assert.Empty(tickets.ResourceGroup);
        Assert.Empty(tickets.SelectedProjectNumber);
        Assert.False(tickets.HasResourceIdentity);
    }

    private static TicketClient DraftClient(List<string> parsed) => new()
    {
        ParseHandler = group =>
        {
            parsed.Add(group);
            return Task.FromResult(ResourceIdentity(group) with
            {
                ProjectNumber = "017vm",
                Environment = group.Contains("-test-") ? "stage" : group.Contains("-prod-") ? "prod" : "dev"
            });
        }
    };

    private static ProjectTicketLauncher DraftLauncher(WizardSession wizard, OperationsSession operations, TicketTabsViewModel tabs)
    {
        var client = new AiFactoryApiClient(new SchemaTransport(), new ConnectionProvider());
        return new(wizard, operations, new FactoryNetworkSession(client, client, client), tabs);
    }

    private static SavedConfigurationItemViewModel DraftItem() => new(new ProjectSummary
    {
        ProjectNumber = "017vm",
        DeploymentScope = new()
        {
            PrefixResourceGroup = "mrvel-1-", SuffixResourceGroup = "-007",
            Region = "swedencentral", SubscriptionIds = [DraftSub]
        }
    }, DraftFolder);

    private static JsonObject DraftState() => new()
    {
        ["_save_folder"] = DraftFolder, ["project_number_000"] = "017vm",
        ["admin_aifactoryPrefixRG"] = "mrvel-1-", ["admin_aifactorySuffixRG"] = "-007",
        ["admin_location"] = "swedencentral", ["dev_sub_id"] = DraftSub
    };

    private static OperationsOverview DraftOverview(params string[] environments) => new()
    {
        Factory = new()
        {
            Folder = DraftFolder, PrefixResourceGroup = "mrvel-1-", SuffixResourceGroup = "-007",
            MonitoringRegions = ["swedencentral"]
        },
        ResourceInventory = new() { Source = "azure", Subscriptions = [DraftSub] },
        Projects =
        [
            new()
            {
                ProjectNumber = "017vm",
                Environments = (environments.Length == 0 ? ["dev"] : environments).Select(environment => new ProjectEnvironment
                {
                    Environment = environment, SubscriptionId = DraftSub,
                    ResourceGroup = $"mrvel-1-project017vm-sdc-{environment}-007"
                }).ToArray()
            }
        ]
    };
}

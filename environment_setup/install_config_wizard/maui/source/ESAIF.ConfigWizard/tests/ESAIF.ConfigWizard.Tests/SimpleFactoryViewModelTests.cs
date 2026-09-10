using System.Net;
using System.Xml.Linq;
using ESAIF.BaseLayer.Networking;
using ESAIF.ConfigWizard.Services;
using ESAIF.ConfigWizard.ViewModels;
using ESAIF.DomainLayer.Configuration;

namespace ESAIF.ConfigWizard.Tests;

public sealed class SimpleFactoryViewModelTests
{
    [Fact]
    public async Task LoadsOnlySimpleOptionsWithMinimalDefaultsAndNoAdvancedSession()
    {
        var client = new Client();
        using var vm = new SimpleFactoryViewModel(client);
        Assert.Equal("swedencentral", vm.Location);
        Assert.Equal("aif-", vm.FactoryPrefix);
        Assert.Equal("123456", vm.CostCenter);
        Assert.Equal("124", vm.FactoryVersion);
        Assert.False(vm.CanPrepare);
        await vm.LoadOptionsAsync();
        Assert.Equal("sub-1", vm.SelectedAccount!.SubscriptionId);
        Assert.Equal("tenant-1", vm.TenantId);
        Assert.Equal("alice@example.com", vm.AzureAccount);
        Assert.Equal("alice", vm.GithubAccount);
        Assert.Equal("alice/new-factory", vm.GithubRepository);
        Assert.Equal(@"C:\backend-host\new-factory", vm.RepoRoot);
        Assert.Equal("alice-team", vm.TeamGroupName);
        Assert.False(vm.ShowAdditionalOptions);
        Assert.True(vm.CanPrepare);
        Assert.Equal(1, client.OptionsCalls);
        Assert.Equal(0, client.PrepareCalls + client.StartCalls + client.GetCalls);
    }

    [Fact]
    public async Task VersionDefaultsAndEditsAreExplicitAndSurviveOptionsReload()
    {
        var client = new Client();
        using var vm = await ReadyAsync(client);
        await vm.PrepareAsync();
        Assert.Equal("124", client.LastDraft!.FactoryVersion);
        vm.FactoryVersion = "125";
        Assert.False(vm.HasPlan);
        await vm.ConfirmAsync();
        Assert.Equal(0, client.StartCalls);
        await vm.LoadOptionsAsync();
        Assert.Equal("125", vm.FactoryVersion);
        await vm.PrepareAsync();
        Assert.Equal("125", client.LastDraft.FactoryVersion);
        vm.FactoryVersion = "main";
        Assert.False(vm.CanConfirm);
        await vm.PrepareAsync();
        Assert.Equal("main", client.LastDraft.FactoryVersion);
    }

    [Fact]
    public async Task EmptyNewFactoryVersionCannotSilentlySelectDefault()
    {
        var client = new Client();
        using var vm = await ReadyAsync(client);
        vm.FactoryVersion = " ";
        Assert.False(vm.CanPrepare);
        await vm.PrepareAsync();
        Assert.Equal(0, client.PrepareCalls);
    }

    [Fact]
    public async Task VersionReviewUsesBackendBranchAndKeepsExactRefBehindDisclosure()
    {
        var client = new Client();
        client.Plan = client.Plan with
        {
            RequestedVersion = "main", Branch = "main", ResolvedRef = "exact-main-ref"
        };
        using var vm = await ReadyAsync(client);
        vm.FactoryVersion = "main";
        await vm.PrepareAsync();
        Assert.Equal("main", vm.PlanTemplateBranch);
        Assert.Equal("exact-main-ref", vm.PlanTemplateRef);
        vm.FactoryVersion = "125";
        client.Plan = client.Plan with
        {
            RequestedVersion = "125", Branch = "release/v1.25", ResolvedRef = "release-ref"
        };
        await vm.PrepareAsync();
        Assert.Equal("release/v1.25", vm.PlanTemplateBranch);
        Assert.Equal("release-ref", vm.PlanTemplateRef);
        var document = XDocument.Load(Path.Combine(AppContext.BaseDirectory, "Assets", "SimpleFactoryPage.xaml"));
        var reference = document.Descendants().Single(element => element.Attribute("AutomationId")?.Value == "SimpleTemplateRef");
        Assert.Equal("True", reference.Attribute("Conceal")?.Value);
        Assert.Equal("{Binding PlanTemplateRef}", reference.Attribute("Value")?.Value);
    }

    [Fact]
    public async Task BackendVersionDefaultIsNotReplacedWithOlderRelease()
    {
        var client = new Client();
        client.Options = client.Options with { Defaults = client.Options.Defaults with { FactoryVersion = "2.134" } };
        using var vm = await ReadyAsync(client);
        Assert.Equal("2.134", vm.FactoryVersion);
        await vm.PrepareAsync();
        Assert.Equal("2.134", client.LastDraft!.FactoryVersion);
    }

    [Fact]
    public async Task EditingVersionDuringPrepareDiscardsLateConsent()
    {
        var client = new Client();
        var gate = new TaskCompletionSource<SimpleFactoryPlan>(TaskCreationOptions.RunContinuationsAsynchronously);
        client.Prepare = (_, _) => gate.Task;
        using var vm = await ReadyAsync(client);
        var preparing = vm.PrepareAsync();
        vm.FactoryVersion = "125";
        gate.SetResult(Plan());
        await preparing;
        Assert.False(vm.HasPlan);
        await vm.ConfirmAsync();
        Assert.Equal(0, client.StartCalls);
    }

    [Fact]
    public async Task VisibilityIsPrivateUntilExplicitlySelectedAndNeverChangesAzureChoices()
    {
        var client = new Client();
        client.Options = client.Options with { Defaults = client.Options.Defaults with { GithubVisibility = "public" } };
        using var vm = await ReadyAsync(client);
        Assert.Equal("private", vm.GithubVisibility);
        Assert.False(vm.IsPublicRepository);
        await vm.PrepareAsync();
        var privateDraft = client.LastDraft!;
        vm.GithubVisibility = "public";
        Assert.False(vm.HasPlan);
        Assert.True(vm.IsPublicRepository);
        await vm.PrepareAsync();
        Assert.Equal("public", client.LastDraft!.GithubVisibility);
        Assert.Equal(privateDraft.SubscriptionId, client.LastDraft.SubscriptionId);
        Assert.Equal(privateDraft.TenantId, client.LastDraft.TenantId);
        Assert.Equal(privateDraft.Location, client.LastDraft.Location);
        Assert.Equal(privateDraft.ProjectResources, client.LastDraft.ProjectResources);
        Assert.Contains("Repository visibility: public", vm.PlanScope);
        Assert.Contains("Azure networking: private configuration is unchanged", vm.PlanScope);
        await vm.LoadOptionsAsync();
        Assert.Equal("public", vm.GithubVisibility);
        Assert.Equal(0, client.StartCalls);
    }

    [Fact]
    public async Task RequiredResourceCheckboxesCannotBeUncheckedAndOnlyOptionalIdsAreSubmitted()
    {
        var client = new Client();
        using var vm = await ReadyAsync(client);
        Assert.All(vm.ProjectResources, resource => Assert.True(resource.IsSelected));
        Assert.Contains("Backend hub network", vm.HubResources);
        Assert.Contains("Backend common registry", vm.CommonResources);
        await vm.PrepareAsync();
        foreach (var required in vm.ProjectResources.Where(resource => resource.IsRequired))
        {
            Assert.False(required.CanChange);
            required.IsSelected = false;
            Assert.True(required.IsSelected);
        }
        Assert.True(vm.CanConfirm);
        Assert.Equal(new[] { "foundry", "ai-search", "application-insights" }, client.LastDraft!.ProjectResources);
        vm.ProjectResources.Single(resource => resource.Id == "ai-search").IsSelected = false;
        Assert.False(vm.HasPlan);
        await vm.PrepareAsync();
        Assert.Equal(new[] { "foundry", "application-insights" }, client.LastDraft!.ProjectResources);
        Assert.Contains("AI Search · Not selected", vm.PlanProjectResources);
        Assert.Contains("Storage · Required", vm.PlanProjectResources);
        Assert.Equal(0, client.StartCalls);
    }

    [Fact]
    public async Task AllOptionalResourcesCanBeUncheckedWithoutRemovingRequiredFoundations()
    {
        var client = new Client();
        using var vm = await ReadyAsync(client);
        foreach (var resource in vm.ProjectResources.Where(resource => !resource.IsRequired)) resource.IsSelected = false;
        await vm.PrepareAsync();
        Assert.Empty(client.LastDraft!.ProjectResources);
        Assert.True(vm.CanConfirm);
        Assert.All(vm.ProjectResources.Where(resource => resource.IsRequired), resource => Assert.True(resource.IsSelected));
        client.Plan = Plan() with { ResourceCatalog = Catalog() with { Project = [] } };
        await vm.PrepareAsync();
        Assert.False(vm.CanConfirm);
        Assert.Contains("required project resource", vm.PlanBlockers);
    }

    [Fact]
    public async Task CatalogDefaultsAreAuthoritativeWithoutClientInventedResources()
    {
        var client = new Client();
        client.Options = client.Options with { ResourceCatalog = new()
        {
            Project = [new() { Id = "backend-new-service", Label = "Backend-only service", Required = false, DefaultSelected = false },
                new() { Id = "backend-required", Label = "Backend-required service", Required = true, DefaultSelected = false }]
        } };
        using var vm = await ReadyAsync(client);
        Assert.Equal(2, vm.ProjectResources.Count);
        Assert.False(vm.ProjectResources[0].IsSelected);
        Assert.True(vm.ProjectResources[1].IsSelected);
        Assert.False(vm.ProjectResources[1].CanChange);
        Assert.DoesNotContain(vm.ProjectResources, resource => resource.Id == "foundry");
        Assert.Empty(vm.HubResources);
    }

    [Fact]
    public async Task DependencyDeselectionBlocksConfirmationWithoutSilentlyReenablingAnything()
    {
        var catalog = Catalog() with { Project = Catalog().Project.Select(resource =>
            resource.Id == "foundry" ? resource with { Dependencies = ["ai-search"] } : resource).ToArray() };
        var client = new Client { Plan = Plan() with { ResourceCatalog = catalog } };
        client.Options = client.Options with { ResourceCatalog = catalog };
        using var vm = await ReadyAsync(client);
        vm.ProjectResources.Single(resource => resource.Id == "ai-search").IsSelected = false;
        Assert.True(vm.HasResourceSelectionIssues);
        Assert.Contains("Foundry requires AI Search", vm.ResourceSelectionWarning);
        Assert.True(vm.CanPrepare);
        await vm.PrepareAsync();
        Assert.True(vm.HasBlockers);
        Assert.False(vm.CanConfirm);
        await vm.ConfirmAsync();
        Assert.Equal(0, client.StartCalls);
        Assert.False(vm.ProjectResources.Single(resource => resource.Id == "ai-search").IsSelected);
        vm.ProjectResources.Single(resource => resource.Id == "foundry").IsSelected = false;
        Assert.False(vm.HasResourceSelectionIssues);
        await vm.PrepareAsync();
        Assert.True(vm.CanConfirm);
    }

    [Fact]
    public async Task CatalogReloadPreservesEditsRemovesStaleSelectionsAndEnforcesNewRequiredFlags()
    {
        var client = new Client();
        using var vm = await ReadyAsync(client);
        vm.ProjectResources.Single(resource => resource.Id == "foundry").IsSelected = false;
        vm.ProjectResources.Single(resource => resource.Id == "ai-search").IsSelected = false;
        await vm.PrepareAsync();
        client.Options = client.Options with { ResourceCatalog = Catalog() with
        {
            Project = Catalog().Project.Where(resource => resource.Id != "application-insights")
                .Select(resource => resource.Id == "ai-search" ? resource with { Required = true } : resource).ToArray()
        } };
        await vm.LoadOptionsAsync();
        Assert.False(vm.HasPlan);
        Assert.False(vm.ProjectResources.Single(resource => resource.Id == "foundry").IsSelected);
        var requiredSearch = vm.ProjectResources.Single(resource => resource.Id == "ai-search");
        Assert.True(requiredSearch.IsSelected);
        Assert.False(requiredSearch.CanChange);
        Assert.DoesNotContain(vm.ProjectResources, resource => resource.Id == "application-insights");
        Assert.Contains("removed from the backend catalog", vm.ResourceSelectionWarning);
        Assert.Contains("now required", vm.ResourceSelectionWarning);
    }

    [Fact]
    public async Task MissingMetadataStaysHiddenBlocksConfirmationAndRetainsSelectionIntent()
    {
        var client = new Client();
        using var vm = await ReadyAsync(client);
        vm.ProjectResources.Single(resource => resource.Id == "foundry").IsSelected = false;
        client.Options = client.Options with { ResourceCatalog = null };
        await vm.LoadOptionsAsync();
        Assert.Empty(vm.ProjectResources);
        Assert.Empty(vm.HubResources);
        Assert.True(vm.CanPrepare);
        await vm.PrepareAsync();
        Assert.False(vm.CanConfirm);
        Assert.Contains("Resource metadata is unavailable", vm.PlanBlockers);
        client.Options = client.Options with { ResourceCatalog = Catalog() };
        await vm.LoadOptionsAsync();
        Assert.False(vm.ProjectResources.Single(resource => resource.Id == "foundry").IsSelected);
        client.Plan = Plan() with { ResourceCatalog = null };
        await vm.PrepareAsync();
        Assert.False(vm.CanConfirm);
        Assert.Contains("preview has no resource catalog", vm.PlanBlockers);
        Assert.Equal(0, client.StartCalls);
    }

    [Fact]
    public async Task PreviewMustDescribeEverySelectedOptionalResource()
    {
        var client = new Client { Plan = Plan() with { ResourceCatalog = Catalog() with { Project = [] } } };
        using var vm = await ReadyAsync(client);
        await vm.PrepareAsync();
        Assert.False(vm.CanConfirm);
        Assert.Contains("does not describe every selected", vm.PlanBlockers);
    }

    [Fact]
    public async Task GatewaySettingsComeOnlyFromRequiredCatalogMetadataAndCanPrepareWhileMissing()
    {
        var client = new Client();
        using var vm = await ReadyAsync(client);
        Assert.False(vm.RequiresApplicationGatewaySettings);
        var catalog = Catalog() with { Hub = [new() { Id = "application-gateway", Label = "HTTPS Application Gateway", Required = true }] };
        client.Options = client.Options with { ResourceCatalog = catalog };
        client.Plan = Plan() with { CanExecute = false, ResourceCatalog = catalog,
            Blockers = ["Application Gateway hostname, backend FQDN and certificate URI are required"] };
        await vm.LoadOptionsAsync();
        Assert.True(vm.RequiresApplicationGatewaySettings);
        Assert.True(vm.CanPrepare);
        await vm.PrepareAsync();
        Assert.False(vm.CanConfirm);
        Assert.Empty(client.LastDraft!.AppGatewayHostname);
        Assert.Contains("Application Gateway hostname", vm.PlanBlockers);
        client.Plan = Plan() with { ResourceCatalog = catalog };
        await vm.PrepareAsync();
        Assert.False(vm.CanConfirm);
        Assert.Contains("frontend hostname is required", vm.PlanBlockers);
        vm.AppGatewayHostname = "app.example.com";
        vm.AppGatewayBackendFqdn = "backend.example.com";
        vm.AppGatewayCertificateSecretId = "https://vault.vault.azure.net/secrets/certificate";
        Assert.False(vm.HasPlan);
        client.Plan = Plan() with { ResourceCatalog = catalog };
        await vm.PrepareAsync();
        Assert.True(vm.CanConfirm);
        Assert.Equal("app.example.com", client.LastDraft!.AppGatewayHostname);
        Assert.Equal("backend.example.com", client.LastDraft.AppGatewayBackendFqdn);
        Assert.Equal("https://vault.vault.azure.net/secrets/certificate", client.LastDraft.AppGatewayCertificateSecretId);
        Assert.Contains("Application Gateway frontend hostname: app.example.com", vm.PlanScope);
        await vm.LoadOptionsAsync();
        Assert.Equal("app.example.com", vm.AppGatewayHostname);
        Assert.Equal(0, client.StartCalls);
    }

    [Fact]
    public async Task SubscriptionDerivesTenantAndDefaultTeamEmailButPreservesManualNames()
    {
        using var vm = await ReadyAsync(new Client());
        vm.GithubRepository = "alice/explicit";
        vm.TeamGroupName = "explicit-team";
        vm.SelectedAccount = vm.Accounts[1];
        Assert.Equal("tenant-2", vm.TenantId);
        Assert.Equal("bob@example.com", vm.AzureAccount);
        Assert.Equal("bob@example.com", vm.TeamMemberEmail);
        vm.TeamMemberEmail = "manual@example.com";
        vm.SelectedAccount = vm.Accounts[0];
        Assert.Equal("manual@example.com", vm.TeamMemberEmail);
        Assert.Equal("alice/explicit", vm.GithubRepository);
        Assert.Equal("explicit-team", vm.TeamGroupName);
    }

    [Fact]
    public async Task PickerRebindingCannotEraseSelectionsOrTurnDefaultsIntoManualEdits()
    {
        var client = new Client();
        using var vm = new SimpleFactoryViewModel(client);
        vm.PropertyChanged += (_, args) =>
        {
            if (args.PropertyName == nameof(vm.Accounts)) vm.SelectedAccount = null;
            if (args.PropertyName == nameof(vm.Regions)) vm.Location = null!;
        };
        await vm.LoadOptionsAsync();
        Assert.Equal("sub-1", vm.SelectedAccount!.SubscriptionId);
        Assert.Equal("swedencentral", vm.Location);
        client.Options = client.Options with { Defaults = client.Options.Defaults with
            { SubscriptionId = "sub-2", TenantId = "tenant-2", Location = "westeurope" } };
        await vm.LoadOptionsAsync();
        Assert.Equal("sub-2", vm.SelectedAccount!.SubscriptionId);
        Assert.Equal("westeurope", vm.Location);
    }

    [Fact]
    public async Task DelayedPickerNullCallbacksPreserveValidSelectionsAndConfirmation()
    {
        var client = new Client();
        using var vm = await ReadyAsync(client);
        await vm.PrepareAsync();
        await Task.Yield();
        vm.SelectedAccount = null;
        vm.Location = null!;
        Assert.Equal("sub-1", vm.SelectedAccount!.SubscriptionId);
        Assert.Equal("swedencentral", vm.Location);
        Assert.True(vm.CanConfirm);
        Assert.True(vm.HasPlan);
        Assert.Equal(0, client.StartCalls);
    }

    [Fact]
    public async Task OptionsRefreshInternallyClearsSelectionsThatNoLongerExist()
    {
        var client = new Client();
        using var vm = await ReadyAsync(client);
        vm.SelectedAccount = vm.Accounts[1];
        vm.Location = "westeurope";
        await vm.PrepareAsync();
        client.Options = client.Options with
            { AzureAccounts = [client.Options.AzureAccounts[0]], Regions = ["swedencentral"] };
        await vm.LoadOptionsAsync();
        Assert.Null(vm.SelectedAccount);
        Assert.Empty(vm.TenantId);
        Assert.Empty(vm.Location);
        Assert.False(vm.HasPlan);
        Assert.False(vm.CanPrepare);
    }

    [Fact]
    public async Task PrefixUpdatesOnlyUneditedGeneratedNamesAndBackendHostFolder()
    {
        var client = new Client();
        using var vm = await ReadyAsync(client);
        await vm.PrepareAsync();
        vm.FactoryPrefix = " brand- ";
        Assert.Equal("brand-prj001-team", vm.TeamGroupName);
        Assert.Equal("alice/brandaifactory-001", vm.GithubRepository);
        Assert.Equal(@"C:\backend-host\brandaifactory-001", vm.RepoRoot);
        Assert.False(vm.HasPlan);
        vm.FactoryPrefix = "next-";
        Assert.Equal("next-prj001-team", vm.TeamGroupName);
        Assert.Equal("alice/nextaifactory-001", vm.GithubRepository);
        Assert.Equal(@"C:\backend-host\nextaifactory-001", vm.RepoRoot);
        await vm.LoadOptionsAsync();
        Assert.Equal("next-prj001-team", vm.TeamGroupName);
        Assert.Equal("alice/nextaifactory-001", vm.GithubRepository);
        Assert.Equal(@"C:\backend-host\nextaifactory-001", vm.RepoRoot);
        vm.FactoryPrefix = "aif-";
        Assert.Equal(client.Options.Defaults.TeamGroupName, vm.TeamGroupName);
        Assert.Equal(client.Options.Defaults.GithubRepository, vm.GithubRepository);
        Assert.Equal(client.Options.Defaults.RepoRoot, vm.RepoRoot);
    }

    [Fact]
    public async Task ExplicitNamesAndFolderSurvivePrefixChangesAndReload()
    {
        var client = new Client();
        using var vm = await ReadyAsync(client);
        vm.TeamGroupName = "custom-team";
        vm.GithubRepository = "organization/custom-repo";
        vm.RepoRoot = @"Z:\explicit\destination";
        vm.FactoryPrefix = "brand-";
        await vm.LoadOptionsAsync();
        Assert.Equal("custom-team", vm.TeamGroupName);
        Assert.Equal("organization/custom-repo", vm.GithubRepository);
        Assert.Equal(@"Z:\explicit\destination", vm.RepoRoot);
    }

    [Theory]
    [InlineData("aif-", "aif-prj001-team", "aifaifactory-001")]
    [InlineData("brand-", "brand-prj001-team", "brandaifactory-001")]
    [InlineData("brand", "brandprj001-team", "brandaifactory-001")]
    public async Task GeneratedNamesMatchExactBackendHyphenRules(string prefix, string group, string repositoryName)
    {
        var client = new Client();
        client.Options = client.Options with { Defaults = client.Options.Defaults with
        {
            GithubRepository = "alice/aifaifactory-001", TeamGroupName = "aif-prj001-team",
            RepoRoot = @"C:\backend-host\aifaifactory-001"
        } };
        using var vm = await ReadyAsync(client);
        vm.FactoryPrefix = prefix;
        Assert.Equal(group, vm.TeamGroupName);
        Assert.Equal($"alice/{repositoryName}", vm.GithubRepository);
        Assert.Equal($@"C:\backend-host\{repositoryName}", vm.RepoRoot);
    }

    [Fact]
    public async Task MissingGithubSignInNeverInventsARepositoryOwner()
    {
        var client = new Client();
        client.Options = client.Options with
            { GithubAccount = string.Empty, Defaults = client.Options.Defaults with { GithubRepository = string.Empty } };
        using var vm = await ReadyAsync(client);
        vm.FactoryPrefix = "brand-";
        Assert.Empty(vm.GithubRepository);
        Assert.Equal("brand-prj001-team", vm.TeamGroupName);
    }

    [Theory]
    [InlineData(@"C:\host\defaults", @"C:\host\custom-repo")]
    [InlineData(@"\\api-host\share\defaults", @"\\api-host\share\custom-repo")]
    [InlineData("/srv/factories/defaults", "/srv/factories/custom-repo")]
    [InlineData(@"C:\defaults", @"C:\custom-repo")]
    public async Task RepositoryChangesUseBackendParentAndItsPathSyntax(string backendDefault, string expected)
    {
        var client = new Client();
        client.Options = client.Options with { Defaults = client.Options.Defaults with { RepoRoot = backendDefault } };
        using var vm = await ReadyAsync(client);
        vm.GithubRepository = "organization/custom-repo";
        vm.FactoryPrefix = "brand-";
        Assert.Equal("organization/custom-repo", vm.GithubRepository);
        Assert.Equal(expected, vm.RepoRoot);
        Assert.Empty(vm.DefaultNameWarning);
    }

    [Fact]
    public async Task UnusableBackendRootNeverFallsBackToThisDevicesDirectories()
    {
        var client = new Client();
        client.Options = client.Options with { Defaults = client.Options.Defaults with { RepoRoot = "relative-folder" } };
        using var vm = await ReadyAsync(client);
        vm.FactoryPrefix = "brand-";
        Assert.Equal("relative-folder", vm.RepoRoot);
        Assert.Contains("could not be derived", vm.DefaultNameWarning);
    }

    [Fact]
    public async Task InvalidRepositoryNameCannotEscapeBackendParentDuringAutomaticDerivation()
    {
        var client = new Client();
        using var vm = await ReadyAsync(client);
        vm.GithubRepository = "organization/../../escape";
        Assert.Equal(client.Options.Defaults.RepoRoot, vm.RepoRoot);
        Assert.Contains("could not be derived", vm.DefaultNameWarning);
    }

    [Fact]
    public async Task ReloadPreservesChosenSubscriptionAndItsUneditedTeamEmail()
    {
        var client = new Client();
        using var vm = await ReadyAsync(client);
        vm.SelectedAccount = vm.Accounts[1];
        await vm.LoadOptionsAsync();
        Assert.Equal("sub-2", vm.SelectedAccount!.SubscriptionId);
        Assert.Equal("tenant-2", vm.TenantId);
        Assert.Equal("bob@example.com", vm.TeamMemberEmail);
    }

    [Theory]
    [InlineData("Location")]
    [InlineData("FactoryPrefix")]
    [InlineData("GithubRepository")]
    [InlineData("TeamMemberEmail")]
    [InlineData("TeamGroupName")]
    [InlineData("CostCenter")]
    [InlineData("RepoRoot")]
    [InlineData("SelectedAccount")]
    [InlineData("GithubVisibility")]
    [InlineData("AppGatewayHostname")]
    [InlineData("AppGatewayBackendFqdn")]
    [InlineData("AppGatewayCertificateSecretId")]
    public async Task EveryInputInvalidatesPreviewAndCannotStart(string field)
    {
        var client = new Client();
        using var vm = await ReadyAsync(client);
        await vm.PrepareAsync();
        Assert.True(vm.CanConfirm);
        if (field == "SelectedAccount") vm.SelectedAccount = vm.Accounts[1];
        else typeof(SimpleFactoryViewModel).GetProperty(field)!.SetValue(vm, field == "GithubVisibility" ? "public" : "changed");
        Assert.False(vm.HasPlan);
        Assert.False(vm.CanConfirm);
        await vm.ConfirmAsync();
        Assert.Equal(0, client.StartCalls);
    }

    [Fact]
    public async Task ReadOnlyPrepareThenExplicitConfirmSubmitsOnlyOnce()
    {
        var client = new Client();
        using var vm = await ReadyAsync(client);
        await vm.PrepareAsync();
        Assert.Equal(1, client.PrepareCalls);
        Assert.Equal(0, client.StartCalls);
        Assert.Contains("tenant-1", vm.PlanScope);
        Assert.Contains("123456", vm.PlanScope);
        Assert.Contains("COST_CENTER=123456", vm.PlanEnvironment);
        Assert.Contains("New private repository", vm.PlanEffects);
        var completion = new TaskCompletionSource<SimpleFactoryJob>();
        client.Start = _ => completion.Task;
        var first = vm.ConfirmAsync();
        Assert.True(vm.IsBusy);
        Assert.False(vm.CanConfirm);
        Assert.False(vm.CanEdit);
        await vm.ConfirmAsync();
        completion.SetResult(new() { Id = "job-1", Status = "queued" });
        await first;
        await vm.ConfirmAsync();
        Assert.Equal(1, client.StartCalls);
        Assert.Equal("plan-1", client.ConfirmationId);
        Assert.Equal("job-1", vm.JobId);
        Assert.Contains("alice", vm.JobOwner);
    }

    [Theory]
    [InlineData(false, false)]
    [InlineData(true, true)]
    public async Task BlockedOrNonExecutablePlanRemainsVisibleAndNeverStarts(bool canExecute, bool hasBlocker)
    {
        var client = new Client { Plan = Plan() with
            { CanExecute = canExecute, Blockers = hasBlocker ? ["Source has unpublished changes"] : [] } };
        using var vm = await ReadyAsync(client);
        await vm.PrepareAsync();
        Assert.True(vm.HasPlan);
        Assert.True(vm.HasBlockers);
        Assert.False(vm.CanConfirm);
        await vm.ConfirmAsync();
        Assert.Equal(0, client.StartCalls);
        Assert.True(vm.CanPrepare);
    }

    [Theory]
    [InlineData("")]
    [InlineData("unknown")]
    [InlineData("2020-01-01T00:00:00Z")]
    public async Task ExpiredOrUnknownExpiryFailsClosed(string expiresAt)
    {
        var client = new Client { Plan = Plan() with { ExpiresAt = expiresAt } };
        using var vm = await ReadyAsync(client);
        await vm.PrepareAsync();
        Assert.False(vm.CanConfirm);
        Assert.Contains("expired", vm.PlanExpiry);
        await vm.ConfirmAsync();
        Assert.Equal(0, client.StartCalls);
    }

    [Fact]
    public async Task ExpiryIsRecheckedAtClickEvenWithoutTimerNotification()
    {
        var clock = new Clock();
        var client = new Client { Plan = Plan() with { ExpiresAt = clock.Now.AddMinutes(10).ToString("O") } };
        using var vm = new SimpleFactoryViewModel(client, clock: clock);
        await vm.LoadOptionsAsync();
        await vm.PrepareAsync();
        Assert.True(vm.CanConfirm);
        clock.Now = clock.Now.AddMinutes(11);
        await vm.ConfirmAsync();
        Assert.Equal(0, client.StartCalls);
    }

    [Fact]
    public async Task CancelPreviewDoesNotStartOrModifyDraft()
    {
        var client = new Client();
        using var vm = await ReadyAsync(client);
        await vm.PrepareAsync();
        vm.DismissPlanCommand.Execute(null);
        Assert.False(vm.HasPlan);
        Assert.Equal("alice/new-factory", vm.GithubRepository);
        await vm.ConfirmAsync();
        Assert.Equal(0, client.StartCalls);
    }

    [Fact]
    public async Task LatePrepareResponseCannotRestoreConfirmationAfterAnEditOrIdentityChange()
    {
        var completion = new TaskCompletionSource<SimpleFactoryPlan>();
        var client = new Client { Prepare = (_, _) => completion.Task };
        using var vm = await ReadyAsync(client);
        var prepare = vm.PrepareAsync();
        vm.FactoryPrefix = "changed-";
        vm.InvalidateIdentity();
        completion.SetResult(Plan());
        await prepare;
        Assert.False(vm.HasPlan);
        Assert.False(vm.CanPrepare);
        Assert.Equal(0, client.StartCalls);
    }

    [Fact]
    public async Task CancellationDuringPrepareIsNotAnErrorAndNeverStarts()
    {
        var client = new Client { Prepare = async (_, token) =>
        {
            await Task.Delay(Timeout.Infinite, token);
            return Plan();
        } };
        using var vm = await ReadyAsync(client);
        using var cancellation = new CancellationTokenSource();
        var prepare = vm.PrepareAsync(cancellation.Token);
        cancellation.Cancel();
        await prepare;
        Assert.False(vm.HasPlan);
        Assert.Empty(vm.ErrorMessage);
        Assert.False(vm.IsBusy);
        Assert.Equal(0, client.StartCalls);
    }

    [Fact]
    public async Task ReloadWithChangedIdentityClearsPrivatePlanButDoesNotClobberEditedFields()
    {
        var client = new Client();
        using var vm = await ReadyAsync(client);
        vm.GithubRepository = "custom/new";
        vm.TeamGroupName = "custom-team";
        vm.TeamMemberEmail = "custom@example.com";
        vm.RepoRoot = @"C:\custom\new";
        await vm.PrepareAsync();
        client.Options = client.Options with { GithubAccount = "different-user",
            Defaults = client.Options.Defaults with { GithubRepository = "different/new", TeamGroupName = "different-team" } };
        await vm.LoadOptionsAsync();
        Assert.False(vm.HasPlan);
        Assert.Equal("custom/new", vm.GithubRepository);
        Assert.Equal("custom-team", vm.TeamGroupName);
        Assert.Equal("custom@example.com", vm.TeamMemberEmail);
        Assert.Equal(@"C:\custom\new", vm.RepoRoot);
        Assert.Contains("Sign-in", vm.Warning);
        Assert.Equal("different-user", vm.GithubAccount);
    }

    [Fact]
    public async Task SwitchingApiConnectionBeforeConfirmationFailsClosed()
    {
        var client = new Client();
        var connection = new Connection();
        using var vm = new SimpleFactoryViewModel(client, connection: connection);
        await vm.LoadOptionsAsync();
        await vm.PrepareAsync();
        connection.Address = "https://different.example.com";
        await vm.ConfirmAsync();
        Assert.Equal(0, client.StartCalls);
        Assert.False(vm.HasPlan);
        Assert.False(vm.CanPrepare);
        Assert.Contains("API host", vm.Warning);
    }

    [Fact]
    public async Task FailedJobRetainsExitEventsAndNeverSuggestsSuccess()
    {
        var client = new Client { Start = _ => Task.FromResult(new SimpleFactoryJob
            { Id = "job-1", Status = "failed", Stage = "deploy", Message = "Partial deployment", ExitCode = 9,
                Events = ["Created repo", "Deployment failed"], RepositoryUrl = "https://github.com/alice/new" }) };
        using var vm = await ReadyAsync(client);
        await vm.PrepareAsync();
        await vm.ConfirmAsync();
        Assert.True(vm.JobNeedsAttention);
        Assert.Equal("Exit code: 9", vm.JobExit);
        Assert.Contains("Created repo", vm.JobEvents);
        Assert.False(vm.CanOpenRepository);
        await vm.ConfirmAsync();
        Assert.Equal(1, client.StartCalls);
    }

    [Fact]
    public async Task UncertainSubmissionRetainsErrorAndDisallowsBlindNewCreation()
    {
        var client = new Client { Start = _ => throw new HttpRequestException("Lost response") };
        using var vm = await ReadyAsync(client);
        await vm.PrepareAsync();
        await vm.ConfirmAsync();
        Assert.Contains("Lost response", vm.ErrorMessage);
        Assert.Contains("Do not blindly rerun", vm.Warning);
        Assert.False(vm.CanPrepare);
        Assert.False(vm.CanConfirm);
        await vm.PrepareAsync();
        Assert.Equal(1, client.PrepareCalls);
        Assert.Equal(1, client.StartCalls);
        var reopened = vm.ActivateAsync();
        vm.Deactivate();
        await reopened;
        Assert.Contains("Lost response", vm.ErrorMessage);
        Assert.Equal(1, client.StartCalls);
    }

    [Fact]
    public async Task DefinitiveServerRejectionAllowsNewReviewButNeverAutomaticResubmission()
    {
        var client = new Client { Start = _ => throw new ApiRequestException(
            HttpStatusCode.Conflict, "Source changed after preparation", "{}") };
        using var vm = await ReadyAsync(client);
        await vm.PrepareAsync();
        await vm.ConfirmAsync();
        Assert.False(vm.HasPlan);
        Assert.False(vm.CanConfirm);
        Assert.True(vm.CanPrepare);
        Assert.Contains("Source changed", vm.ErrorMessage);
        Assert.Equal(1, client.StartCalls);
        await vm.PrepareAsync();
        Assert.True(vm.CanConfirm);
        Assert.Equal(1, client.StartCalls);
    }

    [Fact]
    public async Task ClosingCancelsPollingReopeningUsesSameJobAndDoesNotReloadOrRedeploy()
    {
        var client = new Client();
        using var vm = await ReadyAsync(client);
        await vm.PrepareAsync();
        await vm.ConfirmAsync();
        CancellationToken observed = default;
        client.Get = async (_, token) =>
        {
            observed = token;
            await Task.Delay(Timeout.Infinite, token);
            return new();
        };
        var active = vm.ActivateAsync();
        Assert.Equal(1, client.GetCalls);
        vm.Deactivate();
        await active;
        Assert.True(observed.IsCancellationRequested);
        Assert.Equal("job-1", vm.JobId);
        client.Get = (_, _) => Task.FromResult(new SimpleFactoryJob
            { Id = "job-1", Status = "succeeded", RepositoryUrl = "https://github.com/alice/new" });
        var reopened = vm.ActivateAsync();
        Assert.Equal("succeeded", vm.Job!.Status);
        Assert.True(vm.CanOpenRepository);
        vm.Deactivate();
        await reopened;
        Assert.Equal(2, client.GetCalls);
        Assert.Equal(1, client.OptionsCalls);
        Assert.Equal(1, client.StartCalls);
    }

    [Fact]
    public async Task DisposeCancelsMonitoringAndPreventsReactivation()
    {
        var client = new Client();
        var vm = await ReadyAsync(client);
        await vm.PrepareAsync();
        await vm.ConfirmAsync();
        client.Get = async (_, token) =>
        {
            await Task.Delay(Timeout.Infinite, token);
            return new();
        };
        var active = vm.ActivateAsync();
        vm.Dispose();
        await active;
        await Assert.ThrowsAsync<ObjectDisposedException>(vm.ActivateAsync);
        Assert.Equal(1, client.StartCalls);
    }

    [Fact]
    public async Task MonitoringOwnerDenialRetainsJobAndProgrammingErrorsPropagate()
    {
        var client = new Client();
        using var vm = await ReadyAsync(client);
        await vm.PrepareAsync();
        await vm.ConfirmAsync();
        vm.InvalidateIdentity();
        Assert.False(vm.HasPlan);
        client.Get = (_, _) => throw new ApiRequestException(HttpStatusCode.Forbidden, "Owner changed", "{}");
        await vm.RefreshJobAsync();
        Assert.Equal("job-1", vm.JobId);
        Assert.Contains("alice", vm.JobOwner);
        Assert.Contains("Owner changed", vm.MonitoringError);
        Assert.Equal(1, client.StartCalls);
        client.Get = (_, _) => throw new NullReferenceException("Bug");
        await Assert.ThrowsAsync<NullReferenceException>(() => vm.RefreshJobAsync());
    }

    [Fact]
    public async Task ExistingAuthenticationMonitorInvalidatesPlansAndDisposeUnsubscribes()
    {
        var fixture = new FactoryNetworkFixture { SignedIn = true };
        var monitor = new AzureAuthenticationMonitor(fixture.Api, new WizardSession(fixture.Api), fixture.Network);
        await monitor.CheckAsync();
        var client = new Client();
        var vm = new SimpleFactoryViewModel(client, authentication: monitor);
        await vm.LoadOptionsAsync();
        await vm.PrepareAsync();
        monitor.Invalidate("Signing out");
        Assert.False(vm.HasPlan);
        Assert.False(vm.CanPrepare);
        Assert.Equal(0, client.StartCalls);
        await vm.LoadOptionsAsync();
        await vm.PrepareAsync();
        vm.Dispose();
        await monitor.CheckAsync();
        Assert.True(vm.HasPlan);
    }

    [Fact]
    public void NativePageHasVisibilityResourceHierarchySeparateConfirmationAndNoSecretValueFields()
    {
        var document = XDocument.Load(Path.Combine(AppContext.BaseDirectory, "Assets", "SimpleFactoryPage.xaml"));
        XNamespace maui = "http://schemas.microsoft.com/dotnet/2021/maui";
        var primary = document.Descendants(maui + "VerticalStackLayout")
            .Single(element => element.Attribute("IsEnabled")?.Value == "{Binding CanEdit}" &&
                element.Elements().Any(child => child.Name.LocalName == "TechnicalPicker"));
        Assert.Equal(6, primary.Descendants().Count(element => element.Name.LocalName is "TechnicalEntry" or "TechnicalPicker"));
        Assert.Contains(primary.Descendants(), element =>
            element.Attribute("AutomationId")?.Value == "SimpleFactoryVersion" &&
            element.Attribute("Text")?.Value == "{Binding FactoryVersion, Mode=TwoWay}");
        foreach (var heading in new[] { "AI Factory hub", "AI Factory common", "AI Factory project 001" })
            Assert.Equal(2, document.Descendants(maui + "Label").Count(element => element.Attribute("Text")?.Value == heading));
        var checkbox = Assert.Single(document.Descendants(maui + "CheckBox"));
        Assert.Equal("{Binding IsSelected}", checkbox.Attribute("IsChecked")!.Value);
        Assert.Equal("{Binding CanChange}", checkbox.Attribute("IsEnabled")!.Value);
        Assert.Contains("PUBLIC REPOSITORY", document.ToString());
        Assert.Contains("Versionless Key Vault certificate secret URI, not a secret value", document.ToString());
        var buttons = document.Descendants().Where(element => element.Name.LocalName is "Button" or "TechnicalButton").ToArray();
        Assert.Contains(buttons, button => button.Attribute("Text")?.Value == "Create AI Factory" &&
            button.Attribute("Command")?.Value == "{Binding PrepareCommand}");
        Assert.Contains(buttons, button => button.Attribute("Text")?.Value == "Confirm and create" &&
            button.Attribute("Command")?.Value == "{Binding ConfirmCommand}");
        Assert.DoesNotContain(document.Descendants(maui + "Entry"), entry => entry.Attribute("IsPassword") is not null);
        Assert.DoesNotContain("Destination folder on the Python API host", document.ToString());
        Assert.Contains(buttons, button =>
            button.Attribute("AutomationId")?.Value == "SimpleMoreInfo" &&
            button.Attribute("Command")?.Value == "{Binding ToggleMoreInfoCommand}");
        Assert.Contains("No pre-created repository or group is required; existing targets must pass backend safety checks.",
            document.ToString());
        Assert.DoesNotContain("do not pre-create", document.ToString());
        var code = File.ReadAllText(Path.Combine(AppContext.BaseDirectory, "Assets", "SimpleFactoryPage.xaml.cs"));
        Assert.Contains("_viewModel.Deactivate()", code);
        Assert.DoesNotContain("InitializeAsync", code);
        Assert.DoesNotContain("WizardSession", code);
        var shell = File.ReadAllText(Path.Combine(AppContext.BaseDirectory, "Assets", "AppShell.cs"));
        Assert.Contains("base(ResolvePage<MainPage>(services))", shell);
        Assert.Contains("new WorkspaceNavigationItem(SimpleFactoryPageKey, \"Simple Mode\")", shell);
    }

    [Fact]
    public void MoreInfoIsCollapsedByDefaultAndToggles()
    {
        using var vm = new SimpleFactoryViewModel(new Client());
        Assert.False(vm.ShowMoreInfo);
        Assert.Equal("› More info", vm.MoreInfoLabel);
        vm.ToggleMoreInfoCommand.Execute(null);
        Assert.True(vm.ShowMoreInfo);
        Assert.Equal("⌄ More info", vm.MoreInfoLabel);
    }

    [Fact]
    public async Task MissingResourceMetadataDoesNotRenderFallbackCopy()
    {
        var client = new Client();
        client.Options = client.Options with { ResourceCatalog = null };
        using var vm = new SimpleFactoryViewModel(client);
        await vm.LoadOptionsAsync();
        Assert.Empty(vm.HubResources);
        Assert.Empty(vm.CommonResources);
    }

    private static async Task<SimpleFactoryViewModel> ReadyAsync(Client client)
    {
        var vm = new SimpleFactoryViewModel(client);
        await vm.LoadOptionsAsync();
        return vm;
    }
    private static SimpleFactoryPlan Plan() => new()
    {
        ConfirmationId = "plan-1", CanExecute = true, Summary = "Fixed Dev bootstrap",
        ExpiresAt = DateTimeOffset.UtcNow.AddMinutes(10).ToString("O"),
        ScriptPath = "fixed-purple.sh", Command = "bash fixed-purple.sh",
        Environment = new Dictionary<string, string> { ["COST_CENTER"] = "123456", ["PROJECT"] = "001" },
        Effects = ["New private repository", "Own Hub"], Requirements = ["Azure permissions"], Warnings = ["Costs apply"],
        ResourceCatalog = Catalog()
    };
    private static SimpleFactoryResourceCatalog Catalog() => new()
    {
        Hub = [new() { Id = "test-hub-network", Label = "Backend hub network", Description = "Test hub description", Required = true, DefaultSelected = true }],
        Common = [new() { Id = "test-registry", Label = "Backend common registry", Description = "Test common description", Required = true, DefaultSelected = true }],
        Project =
        [
            new() { Id = "storage", Label = "Storage", Required = true, DefaultSelected = true },
            new() { Id = "key-vault", Label = "Key Vault", Required = true, DefaultSelected = true },
            new() { Id = "managed-identities", Label = "Managed identities", Required = true, DefaultSelected = true },
            new() { Id = "foundry", Label = "Foundry", Description = "Test account and project", DefaultSelected = true, Dependencies = ["storage"] },
            new() { Id = "ai-search", Label = "AI Search", DefaultSelected = true },
            new() { Id = "application-insights", Label = "Application Insights", DefaultSelected = true }
        ]
    };
    private sealed class Clock : TimeProvider
    {
        public DateTimeOffset Now { get; set; } = DateTimeOffset.Parse("2026-09-09T12:00:00Z");
        public override DateTimeOffset GetUtcNow() => Now;
    }
    private sealed class Connection : IAiFactoryConnectionProvider
    {
        public string Address { get; set; } = "http://127.0.0.1:8765";
        public Task<AiFactoryConnection> GetConnectionAsync(CancellationToken cancellationToken = default) =>
            Task.FromResult(new AiFactoryConnection(Address, "test-key"));
    }
    private sealed class Client : ISimpleFactoryClient
    {
        public int OptionsCalls, PrepareCalls, StartCalls, GetCalls;
        public string ConfirmationId { get; private set; } = string.Empty;
        public SimpleFactoryDraft? LastDraft { get; private set; }
        public SimpleFactoryPlan Plan { get; set; } = SimpleFactoryViewModelTests.Plan();
        public SimpleFactoryOptions Options { get; set; } = new()
        {
            Defaults = new() { SubscriptionId = "sub-1", TenantId = "tenant-1", GithubRepository = "alice/new-factory",
                TeamMemberEmail = "alice@example.com", TeamGroupName = "alice-team", RepoRoot = @"C:\backend-host\new-factory" },
            GithubAccount = "alice", Regions = ["swedencentral", "westeurope"], ResourceCatalog = Catalog(),
            AzureAccounts = [
                new() { SubscriptionId = "sub-1", SubscriptionName = "Dev", TenantId = "tenant-1", AccountName = "alice@example.com" },
                new() { SubscriptionId = "sub-2", SubscriptionName = "Other", TenantId = "tenant-2", AccountName = "bob@example.com" }]
        };
        public Func<SimpleFactoryDraft, CancellationToken, Task<SimpleFactoryPlan>>? Prepare { get; set; }
        public Func<string, Task<SimpleFactoryJob>>? Start { get; set; }
        public Func<string, CancellationToken, Task<SimpleFactoryJob>>? Get { get; set; }
        public Task<SimpleFactoryOptions> GetSimpleFactoryOptionsAsync(CancellationToken cancellationToken = default)
        {
            OptionsCalls++;
            return Task.FromResult(Options);
        }
        public Task<SimpleFactoryPlan> PrepareSimpleFactoryAsync(SimpleFactoryDraft draft, CancellationToken cancellationToken = default)
        {
            PrepareCalls++;
            LastDraft = draft;
            return Prepare?.Invoke(draft, cancellationToken) ?? Task.FromResult(Plan);
        }
        public Task<SimpleFactoryJob> StartSimpleFactoryAsync(string confirmationId, CancellationToken cancellationToken = default)
        {
            StartCalls++;
            ConfirmationId = confirmationId;
            return Start?.Invoke(confirmationId) ?? Task.FromResult(new SimpleFactoryJob { Id = "job-1", Status = "queued" });
        }
        public Task<SimpleFactoryJob> GetSimpleFactoryJobAsync(string jobId, CancellationToken cancellationToken = default)
        {
            GetCalls++;
            return Get?.Invoke(jobId, cancellationToken) ?? Task.FromResult(new SimpleFactoryJob { Id = jobId, Status = "running" });
        }
    }
}

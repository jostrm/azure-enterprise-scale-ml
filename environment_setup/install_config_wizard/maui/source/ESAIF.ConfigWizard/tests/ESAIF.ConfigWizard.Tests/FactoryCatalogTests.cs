using ESAIF.BaseLayer.Networking;
using ESAIF.ConfigWizard.Services;
using ESAIF.ConfigWizard.ViewModels;
using ESAIF.DomainLayer.Configuration;
using ESAIF.DomainLayer.Operations;
using System.Text.Json.Nodes;

namespace ESAIF.ConfigWizard.Tests;

public sealed class FactoryCatalogTests
{
    [Fact]
    public async Task SelectionUsesIdsAndIsIsolatedPerRoot()
    {
        var fixture = new Fixture();
        await fixture.Session.RefreshAsync();
        fixture.Session.SelectFactory("factory-a");
        fixture.Session.SelectScaleSet("scale-a");
        fixture.Session.SelectFactory("factory-b");
        Assert.Null(fixture.Session.SelectedScaleSetId);
        Assert.Throws<InvalidOperationException>(() => fixture.Session.SelectScaleSet("scale-a"));
        fixture.Session.SelectScaleSet("scale-b");
        fixture.Wizard.SetValue("_save_folder", @"C:\other");
        Assert.Null(fixture.Session.Catalog);
        await fixture.Session.RefreshAsync();
        Assert.Null(fixture.Session.SelectedFactoryId);
        fixture.Wizard.SetValue("_save_folder", @"C:\catalog");
        await fixture.Session.RefreshAsync();
        Assert.Equal("factory-b", fixture.Session.SelectedFactoryId);
        Assert.Equal("scale-b", fixture.Session.SelectedScaleSetId);
    }

    [Theory]
    [InlineData("none")]
    [InlineData("all")]
    public async Task CloneSendsExactProjectPolicyWithoutChangingSourceOrWizard(string inclusion)
    {
        var fixture = await Fixture.SelectedAsync();
        var vm = fixture.ViewModel;
        vm.SetIntent("clone", "northeurope");
        vm.TargetPrefix = "dc";
        vm.IncludeProjects = vm.ProjectInclusions.Single(x => x.Value == inclusion);
        var before = fixture.Wizard.State.ToJsonString();
        await vm.PrepareAsync();
        var request = Assert.Single(fixture.Prepared);
        Assert.Equal("factory-a", request.FactoryId);
        Assert.Equal("dc", request.TargetPrefix);
        Assert.Equal("northeurope", request.TargetRegion);
        Assert.Equal(inclusion, request.IncludeProjects);
        Assert.Equal("revision-1", request.SourceRevision);
        Assert.Null(request.ScaleSets);
        Assert.Empty(fixture.Confirmed);
        Assert.Equal(before, fixture.Wizard.State.ToJsonString());
    }

    [Fact]
    public async Task CloneDefaultsToNoProjects()
    {
        var fixture = await Fixture.SelectedAsync();
        Assert.Equal("none", fixture.ViewModel.IncludeProjects.Value);
    }

    [Fact]
    public async Task CloneRegionMustComeFromCanonicalServerOptions()
    {
        var fixture = await Fixture.SelectedAsync();
        fixture.ViewModel.SetIntent("clone", "neu");
        fixture.ViewModel.TargetPrefix = "dc";
        await fixture.ViewModel.PrepareAsync();
        Assert.Empty(fixture.Prepared);
        Assert.Contains("canonical destination region", fixture.ViewModel.ErrorMessage);
        fixture.ViewModel.TargetRegionChoice = fixture.ViewModel.RegionChoices.Single(x => x.Value == "northeurope");
        await fixture.ViewModel.PrepareAsync();
        Assert.Equal("northeurope", Assert.Single(fixture.Prepared).TargetRegion);
    }

    [Fact]
    public async Task ExistingRuntimeInheritanceDoesNotTrustUnemittedFactoryVersionField()
    {
        var fixture = new Fixture();
        fixture.Catalog = fixture.Catalog with
        {
            Factories = fixture.Catalog.Factories.Select(x => x with { VersionRef = "125" }).ToArray()
        };
        await fixture.Session.RefreshAsync();
        fixture.Session.SelectFactory("factory-a");
        fixture.Session.SelectScaleSet("scale-a");
        fixture.ViewModel.SetIntent("deploy");
        Assert.Empty(fixture.ViewModel.VersionRef);
        Assert.Equal("inherit", fixture.ViewModel.VersionMode.Value);
        Assert.Null(fixture.ViewModel.BuildRequest().VersionRef);
        fixture.ViewModel.SetIntent("create-factory");
        Assert.Equal("124", fixture.ViewModel.LocalFactoryVersion);
        Assert.Empty(fixture.ViewModel.VersionRef);
    }

    [Fact]
    public async Task NewScaleSetRequiresExplicitEnvironmentSuffixAndSubscription()
    {
        var fixture = await Fixture.SelectedAsync();
        var vm = fixture.ViewModel;
        vm.SetIntent("create-scale-set");
        vm.Suffix = "002";
        vm.SubscriptionId = Fixture.Subscription;
        vm.TenantId = Fixture.Tenant;
        vm.VnetCidr = "10.42.0.0/16";
        vm.MaxProjects = "8";
        vm.OrchestratorChoice = vm.Orchestrators[0];
        await vm.PrepareAsync();
        Assert.Contains("Explicitly select an environment", vm.ErrorMessage);
        Assert.Empty(fixture.Prepared);
        vm.EnvironmentChoice = vm.Environments.Single(x => x.Value == "stage");
        await vm.PrepareAsync();
        var request = Assert.Single(fixture.Prepared);
        var scale = Assert.Single(request.ScaleSets!);
        Assert.Equal("stage", scale.Environment);
        Assert.Equal("002", scale.Suffix);
        Assert.Equal(Fixture.Subscription, scale.SubscriptionId);
        Assert.Equal(Fixture.Tenant, scale.TenantId);
        Assert.Equal(8, scale.Network.MaxProjects);
        Assert.Null(request.TargetRegion);
    }

    [Theory]
    [InlineData("0")]
    [InlineData("9")]
    [InlineData("2.5")]
    public void CapacityRejectsValuesOutsideOneThroughEight(string capacity) =>
        Assert.Throws<InvalidOperationException>(() => FactoryCatalogPresentation.ValidateCapacity(capacity));

    [Fact]
    public async Task DeletionRequiresExactSelectionPreviewReviewAndTypedPhrase()
    {
        var fixture = await Fixture.SelectedAsync();
        var vm = fixture.ViewModel;
        vm.SetIntent("delete-scale-set");
        await vm.PrepareAsync();
        Assert.Equal("scale-a", Assert.Single(fixture.Prepared).ScaleSetId);
        Assert.Empty(fixture.Confirmed);
        vm.Accepted = true;
        vm.TypedPhrase = vm.RequiredPhrase;
        Assert.False(vm.CanConfirm);
        vm.MarkReviewed(vm.ReviewDetails);
        Assert.True(vm.CanConfirm);
        await vm.ConfirmAsync();
        Assert.Equal((@"C:\catalog", "receipt"), Assert.Single(fixture.Confirmed));
        Assert.False(vm.HasPreview);
    }

    [Fact]
    public async Task ExpiredConsentCannotConfirmOrPrepareAutomatically()
    {
        var fixture = await Fixture.SelectedAsync();
        await fixture.PrepareDeleteAsync();
        fixture.Now = fixture.Now.AddMinutes(6);
        Assert.False(fixture.ViewModel.CanConfirm);
        await fixture.ViewModel.ConfirmAsync();
        Assert.Empty(fixture.Confirmed);
        Assert.Single(fixture.Prepared);
        Assert.Contains("expired", fixture.ViewModel.ErrorMessage);
    }

    [Theory]
    [InlineData("input")]
    [InlineData("root")]
    [InlineData("factory")]
    [InlineData("scale")]
    [InlineData("auth")]
    [InlineData("connection")]
    public async Task ChangedContextInvalidatesConsent(string change)
    {
        var fixture = await Fixture.SelectedAsync();
        await fixture.PrepareDeleteAsync();
        switch (change)
        {
            case "input": fixture.ViewModel.TargetPrefix = "changed"; break;
            case "root": fixture.Wizard.SetValue("_save_folder", @"C:\other"); break;
            case "factory": fixture.Session.SelectFactory("factory-b"); break;
            case "scale": fixture.Session.SelectScaleSet(null); break;
            case "auth": fixture.Session.InvalidateConsent(); break;
            case "connection": fixture.Connection = new("http://localhost:9876", "different"); break;
        }
        await fixture.ViewModel.ConfirmAsync();
        Assert.Empty(fixture.Confirmed);
        Assert.False(fixture.ViewModel.HasPreview);
    }

    [Fact]
    public async Task TransportFailureConsumesReceiptAndPreservesError()
    {
        var fixture = await Fixture.SelectedAsync();
        await fixture.PrepareDeleteAsync();
        fixture.ConfirmFailure = new HttpRequestException("Connection lost; operation outcome unknown");
        await fixture.ViewModel.ConfirmAsync();
        Assert.Contains("outcome unknown", fixture.ViewModel.ErrorMessage);
        Assert.False(fixture.ViewModel.HasPreview);
        await fixture.ViewModel.ConfirmAsync();
        Assert.Single(fixture.Confirmed);
        Assert.Single(fixture.Prepared);
    }

    [Fact]
    public async Task FailedJobIsAnErrorNotSuccessfulConfirmation()
    {
        var fixture = await Fixture.SelectedAsync();
        fixture.Result = new() { ContractVersion = 1, Job = new()
            { Id = "job-failed", FactoryId = "factory-a", Status = "failed", ExitCode = 2, Message = "Ownership denied" } };
        await fixture.PrepareDeleteAsync();
        await fixture.ViewModel.ConfirmAsync();
        Assert.Contains("Ownership denied", fixture.ViewModel.ErrorMessage);
        Assert.Equal("failed", Assert.Single(fixture.ViewModel.Jobs).Status);
    }

    [Theory]
    [InlineData("blocked")]
    [InlineData("reconciliation-required")]
    [InlineData("interrupted")]
    public async Task UncertainRuntimeOutcomesRequireExplicitAttentionWithoutRetry(string status)
    {
        var fixture = await Fixture.SelectedAsync();
        fixture.Result = fixture.Result with { Job = fixture.Result.Job! with { Status = status, Message = "Worker needs attention" } };
        await fixture.PrepareDeleteAsync();
        await fixture.ViewModel.ConfirmAsync();
        Assert.Contains(status, fixture.ViewModel.ErrorMessage);
        Assert.Contains("reconcile explicitly", fixture.ViewModel.ErrorMessage);
        Assert.Single(fixture.Confirmed);
        Assert.Single(fixture.Prepared);
    }

    [Theory]
    [InlineData(false)]
    [InlineData(true)]
    public async Task MissingOrAmbiguousConfirmationOutcomeIsNeverHidden(bool both)
    {
        var fixture = await Fixture.SelectedAsync();
        fixture.Result = both ? fixture.Result with { Catalog = fixture.Catalog } :
            new() { ContractVersion = 1 };
        await fixture.PrepareDeleteAsync();
        await fixture.ViewModel.ConfirmAsync();
        Assert.Contains("exactly one catalog or job", fixture.ViewModel.ErrorMessage);
        Assert.False(fixture.ViewModel.HasPreview);
        Assert.Empty(fixture.ViewModel.Jobs);
    }

    [Fact]
    public async Task WholeFactoryDeletionCannotBeMistakenForHighlightedScaleSet()
    {
        var fixture = await Fixture.SelectedAsync();
        fixture.ViewModel.SetIntent("delete-factory");
        await fixture.ViewModel.PrepareAsync();
        Assert.Null(Assert.Single(fixture.Prepared).ScaleSetId);
        Assert.Contains("ALL SCALE SETS", fixture.ViewModel.RequiredPhrase);
        Assert.Contains("ENTIRE FACTORY", fixture.ViewModel.ReviewDetails);
        Assert.Contains("not just the highlighted scale set", fixture.ViewModel.OperationScope);
    }

    [Fact]
    public async Task ProjectActionsAreAvailableButRequireExplicitTypedInputs()
    {
        var fixture = await Fixture.SelectedAsync();
        foreach (var action in new[] { "add-project", "add-project-placements" })
        {
            fixture.ViewModel.SetIntent(action);
            Assert.True(fixture.ViewModel.CanPrepare);
            await fixture.ViewModel.PrepareAsync();
            Assert.NotEmpty(fixture.ViewModel.ErrorMessage);
        }
        Assert.Empty(fixture.Prepared);
        Assert.Empty(fixture.Confirmed);
    }

    [Fact]
    public async Task NewFactoryPreparesAndConfirmsExactInitialPlacementWithoutLegacyMutation()
    {
        var fixture = await Fixture.SelectedAsync();
        var vm = fixture.ViewModel;
        vm.SetIntent("create-factory", "northeurope");
        vm.TargetPrefix = "dc";
        vm.EnvironmentChoice = vm.Environments.Single(x => x.Value == "prod");
        vm.OrchestratorChoice = vm.Orchestrators.Single(x => x.Value == "ado");
        vm.Suffix = "001";
        vm.SubscriptionId = Fixture.Subscription;
        vm.TenantId = Fixture.Tenant;
        vm.VnetCidr = "10.42.0.0/16";
        vm.MaxProjects = "2";
        var wizardBefore = fixture.Wizard.State.ToJsonString();
        await vm.PrepareAsync();
        var request = Assert.Single(fixture.Prepared);
        Assert.Equal("create-factory", request.Action);
        Assert.Null(request.FactoryId);
        Assert.Null(request.ScaleSetId);
        Assert.Null(request.VersionRef);
        Assert.Equal("124", request.FactoryVersion);
        var scale = Assert.Single(request.ScaleSets!);
        Assert.Equal("prod", scale.Environment);
        Assert.Equal("ado", scale.Orchestrator);
        Assert.Empty(fixture.Confirmed);
        fixture.Result = new() { ContractVersion = 1, Catalog = fixture.Catalog };
        vm.MarkReviewed(vm.ReviewDetails);
        vm.Accepted = true;
        await vm.ConfirmAsync();
        Assert.Single(fixture.Confirmed);
        Assert.Equal(wizardBefore, fixture.Wizard.State.ToJsonString());
    }

    [Fact]
    public async Task EmptyLegacyModeCanPrepareNewFactoryWithoutImplicitMigration()
    {
        var fixture = await Fixture.SelectedAsync();
        fixture.Catalog = new() { ContractVersion = 1, Mode = "legacy", Revision = "empty-root" };
        await fixture.ViewModel.RefreshAsync();
        fixture.ViewModel.SetIntent("create-factory", "northeurope");
        Assert.True(fixture.ViewModel.CanPrepare);
        Assert.Empty(fixture.Prepared);
        Assert.Empty(fixture.Confirmed);
    }

    [Fact]
    public async Task BindingSetupUsesTypedSingularActionAndRequiresReviewedEcho()
    {
        var fixture = await Fixture.SelectedAsync();
        var vm = fixture.ViewModel;
        vm.SetIntent("configure-binding");
        var editor = vm.BindingEditor;
        editor.WriterId = "writer-one";
        editor.Repository = "https://github.com/customer/config";
        editor.ConsumerRef = "refs/heads/main";
        editor.SharedRemote = true;
        editor.AuthNamespace = "customer-a";
        editor.DeploymentObjectId = "33333333-3333-4333-8333-333333333333";
        editor.LockAccountUrl = "https://lockaccount.blob.core.windows.net";
        editor.LockContainer = "factory-locks";
        editor.CoordinationBlob = "coordination/v1.json";
        editor.CoordinationHash = new string('a', 64);
        editor.CoordinationRevision = "1";
        editor.ResourceGroupIds = $"/subscriptions/{Fixture.Subscription}/resourceGroups/common-dev";
        editor.UseTargetExecution = true;
        editor.TargetWriterId = "dev001-writer";
        editor.TargetAuthNamespace = "dev001-auth";
        editor.TargetDeploymentObjectId = editor.DeploymentObjectId;
        editor.TargetRunner.Choice = editor.TargetRunner.Choices.Single(choice => choice.Value == "hosted");
        editor.TargetRunner.Image = editor.TargetRunner.Images.Single(choice => choice.Value == "ubuntu-24.04");
        await vm.PrepareAsync();
        var request = Assert.Single(fixture.Prepared);
        Assert.Equal("configure-binding", request.Action);
        Assert.Equal("factory-a", request.FactoryId);
        Assert.Null(request.ScaleSetId);
        Assert.Null(request.VersionRef);
        Assert.Equal("scale-a", Assert.Single(request.Binding!.Targets).ScaleSetId);
        Assert.Contains("Complete reviewed gha binding", vm.ReviewDetails);
        Assert.Contains("dev001-writer", vm.ReviewDetails);
        Assert.Empty(fixture.Confirmed);
        editor.TargetRunner.Image = editor.TargetRunner.Images.Single(choice => choice.Value == "ubuntu-22.04");
        Assert.False(vm.HasPreview);
        editor.WriterId = "writer-updated";
        Assert.False(vm.HasPreview);
        await vm.RefreshAsync();
        Assert.Equal("writer-updated", editor.WriterId);
        Assert.Equal("dev001-auth", editor.TargetAuthNamespace);
        Assert.Equal("ubuntu-22.04", editor.TargetRunner.Image!.Value);
        fixture.EchoBinding = false;
        await vm.PrepareAsync();
        Assert.Contains("did not echo", vm.ErrorMessage);
        Assert.False(vm.HasPreview);
    }

    [Fact]
    public async Task RefreshPreservesSelectedIdsAndDirtyInputsButInvalidatesConsent()
    {
        var fixture = await Fixture.SelectedAsync();
        fixture.ViewModel.TargetPrefix = "unsaved-destination";
        fixture.ViewModel.VersionRef = "release-125";
        await fixture.PrepareDeleteAsync();
        await fixture.ViewModel.RefreshAsync();
        Assert.Equal("factory-a", fixture.Session.SelectedFactoryId);
        Assert.Equal("scale-a", fixture.Session.SelectedScaleSetId);
        Assert.Equal("unsaved-destination", fixture.ViewModel.TargetPrefix);
        Assert.Equal("release-125", fixture.ViewModel.VersionRef);
        Assert.False(fixture.ViewModel.HasPreview);
    }

    [Fact]
    public async Task LatePreviewIsDiscardedAfterInputChanges()
    {
        var fixture = await Fixture.SelectedAsync();
        fixture.PrepareGate = new(TaskCreationOptions.RunContinuationsAsynchronously);
        fixture.ViewModel.SetIntent("delete-scale-set");
        var preparing = fixture.ViewModel.PrepareAsync();
        await fixture.PrepareStarted.Task;
        fixture.ViewModel.VersionRef = "different";
        fixture.PrepareGate.SetResult();
        await preparing;
        Assert.False(fixture.ViewModel.HasPreview);
        Assert.Empty(fixture.Confirmed);
    }

    [Fact]
    public async Task LateCatalogIsDiscardedAfterRootChanges()
    {
        var fixture = new Fixture();
        fixture.ReadGate = new(TaskCreationOptions.RunContinuationsAsynchronously);
        var reading = fixture.Session.RefreshAsync();
        await fixture.ReadStarted.Task;
        fixture.Wizard.SetValue("_save_folder", @"C:\other");
        fixture.ReadGate.SetResult();
        await reading;
        Assert.Null(fixture.Session.Catalog);
        Assert.Equal(@"C:\other", fixture.Session.Folder);
    }

    [Fact]
    public async Task LegacyModeRequiresExplicitMigrationNeverMigratesOnRead()
    {
        var fixture = new Fixture { Catalog = new() { ContractVersion = 1, Mode = "legacy", Revision = "legacy-hash" } };
        await fixture.Session.RefreshAsync();
        Assert.True(fixture.ViewModel.IsLegacy);
        Assert.Empty(fixture.Prepared);
        Assert.Empty(fixture.Confirmed);
        fixture.ViewModel.SetIntent("clone");
        await fixture.ViewModel.PrepareAsync();
        Assert.Empty(fixture.Prepared);
        fixture.ViewModel.SetIntent("migrate");
        Assert.Empty(fixture.ViewModel.VersionRef);
        fixture.ViewModel.VersionRef = "124";
        await fixture.ViewModel.PrepareAsync();
        Assert.Equal("migrate", Assert.Single(fixture.Prepared).Action);
        Assert.Empty(fixture.Confirmed);
    }

    [Fact]
    public async Task LegacyPermissionRequiresVerifiedMatchingRootAndIsRevokedOnRootChange()
    {
        var fixture = new Fixture();
        Assert.False(fixture.Session.AllowsLegacyFolder(@"C:\catalog"));
        fixture.Catalog = new() { ContractVersion = 1, Mode = "legacy", Revision = "legacy-hash" };
        await fixture.Session.RefreshAsync();
        Assert.True(fixture.Session.AllowsLegacyFolder(@"C:\catalog"));
        Assert.False(fixture.Session.AllowsLegacyFolder(@"C:\other"));
        fixture.Wizard.SetValue("_save_folder", @"C:\other");
        Assert.False(fixture.Session.AllowsLegacyFolder(@"C:\catalog"));
        Assert.False(fixture.Session.AllowsLegacyFolder(@"C:\other"));
    }

    [Fact]
    public async Task JobsReloadOnlyWhileVisibleAndNeverRetriesFailures()
    {
        var fixture = await Fixture.SelectedAsync();
        fixture.ViewModel.SetVisible(false);
        await fixture.ViewModel.ReloadJobsAsync();
        Assert.Equal(0, fixture.JobReads);
        fixture.ViewModel.SetVisible(true);
        await fixture.ViewModel.ReloadJobsAsync();
        Assert.Equal(1, fixture.JobReads);
        Assert.Empty(fixture.Confirmed);
    }

    [Fact]
    public async Task CatalogTerminalRevalidatesExactJobBeforeOpeningSharedFooter()
    {
        var fixture = await Fixture.SelectedAsync();
        var job = fixture.Result.Job! with { TerminalAvailable = true, ScaleSetId = "scale-a" };
        fixture.Result = fixture.Result with { Job = job };
        fixture.ViewModel.Jobs.Add(job);
        await fixture.ViewModel.OpenTerminalAsync(job);
        Assert.Equal((@"C:\catalog", "job"), Assert.Single(fixture.OpenedTerminals));
        Assert.Empty(fixture.Confirmed);
        Assert.Empty(fixture.Prepared);
    }

    [Fact]
    public async Task CatalogTerminalRejectsReplacedJobIdentity()
    {
        var fixture = await Fixture.SelectedAsync();
        var job = fixture.Result.Job! with { TerminalAvailable = true, ScaleSetId = "scale-a" };
        fixture.ViewModel.Jobs.Add(job);
        fixture.Result = fixture.Result with { Job = job with { FactoryId = "another-factory" } };
        await fixture.ViewModel.OpenTerminalAsync(job);
        Assert.Empty(fixture.OpenedTerminals);
        Assert.Contains("different catalog scope", fixture.ViewModel.ErrorMessage);
    }

    [Fact]
    public void ChoiceDisplaysNeverUseRecordToString()
    {
        Assert.All(FactoryCatalogPresentation.Actions, choice =>
        {
            Assert.DoesNotContain("CatalogChoice", choice.Display);
            Assert.DoesNotContain("{", choice.Display);
        });
    }

    [Fact]
    public async Task ExactReviewContainsCanonicalVersionBranchAndPinnedCommit()
    {
        var fixture = await Fixture.SelectedAsync();
        await fixture.PrepareDeleteAsync();
        Assert.Contains("Canonical source version: 124", fixture.ViewModel.ReviewDetails);
        Assert.Contains("Server version input echo: 124", fixture.ViewModel.ReviewDetails);
        Assert.Contains("Source branch: release/v1.24", fixture.ViewModel.ReviewDetails);
        Assert.Contains("Pinned source commit: " + new string('a', 40), fixture.ViewModel.ReviewDetails);
        Assert.DoesNotContain(new string('a', 40), fixture.ViewModel.PreviewSummary);
    }

    [Fact]
    public async Task InheritedRuntimeVersionIsResolvedByServerAndExplicitlyReviewed()
    {
        var fixture = await Fixture.SelectedAsync();
        var vm = fixture.ViewModel;
        vm.SetIntent("deploy");
        vm.VersionMode = vm.VersionModes.Single(choice => choice.Value == "inherit");
        fixture.PreviewSourceVersion = new() { RequestedVersion = "125", Branch = "release/v1.25", ResolvedRef = new string('b', 40) };
        await vm.PrepareAsync();
        Assert.Null(Assert.Single(fixture.Prepared).VersionRef);
        Assert.Contains("Inherit selected factory release", vm.ReviewDetails);
        Assert.Contains("Canonical source version: 125", vm.ReviewDetails);
        Assert.Contains(new string('b', 40), vm.ReviewDetails);
        Assert.False(vm.CanConfirm);
        vm.MarkReviewed(vm.ReviewDetails);
        vm.Accepted = true;
        Assert.True(vm.CanConfirm);
        vm.VersionMode = vm.VersionModes.Single(choice => choice.Value == "override");
        Assert.False(vm.HasPreview);
        Assert.False(vm.CanConfirm);
        Assert.Empty(fixture.Confirmed);
    }

    [Fact]
    public async Task ExplicitRuntimeVersionRequiresAnInputAndNeverChangesAtConfirmation()
    {
        var fixture = await Fixture.SelectedAsync();
        var vm = fixture.ViewModel;
        vm.SetIntent("deploy");
        vm.VersionRef = string.Empty;
        await vm.PrepareAsync();
        Assert.Empty(fixture.Prepared);
        Assert.Contains("explicit AI Factory version", vm.ErrorMessage);
        vm.VersionRef = "125";
        fixture.PreviewSourceVersion = new() { FactoryVersion = "125", RequestedVersion = "125", Branch = "release/v1.25", ResolvedRef = new string('b', 40) };
        await vm.PrepareAsync();
        Assert.Equal("125", Assert.Single(fixture.Prepared).VersionRef);
        vm.MarkReviewed(vm.ReviewDetails);
        vm.Accepted = true;
        await vm.ConfirmAsync();
        Assert.Equal("125", vm.VersionRef);
        Assert.Equal("override", vm.VersionMode.Value);
        Assert.Single(fixture.Confirmed);
    }

    [Theory]
    [InlineData("add-project")]
    [InlineData("add-project-placements")]
    public async Task ProjectChangesRequireExactReviewedConfigurationReceipt(string action)
    {
        var fixture = await ProjectFixtureAsync();
        var vm = fixture.ViewModel;
        vm.SetIntent(action);
        vm.ProjectEditor.Number = "002";
        vm.ProjectEditor.DisplayName = "A separate logical project";
        ChoosePlacement(vm, action == "add-project" ? "dev" : "stage", action == "add-project" ? "scale-other-dev" : "scale-stage");
        var request = vm.BuildRequest();
        var source = fixture.Session.SelectedFactory!;
        var existing = Assert.Single(source.Projects);
        fixture.PreviewTarget = source with
        {
            Projects = action == "add-project"
                ? [existing, new() { Id = "new-project-id", Key = "project-002-2", Number = request.Project!.Number,
                    DisplayName = request.Project.DisplayName, Placements = request.Project.Placements, Status = "draft" }]
                : [existing with { Placements = existing.Placements.Concat(request.Placements!).ToArray() }]
        };
        var before = fixture.Wizard.State.ToJsonString();
        await vm.PrepareAsync();
        Assert.Empty(vm.ErrorMessage);
        Assert.Single(fixture.Prepared);
        Assert.Empty(fixture.Confirmed);
        Assert.Null(request.VersionRef);
        Assert.Null(request.ScaleSetId);
        Assert.Equal("factory-a", request.FactoryId);
        Assert.Equal(action == "add-project" ? null : existing.Id, request.ProjectId);
        Assert.Contains(action == "add-project" ? "new-project-id" : "scale-stage", vm.ReviewDetails);
        vm.MarkReviewed(vm.ReviewDetails);
        vm.Accepted = true;
        Assert.True(vm.CanConfirm);
        fixture.Result = new() { ContractVersion = 1, Catalog = fixture.Catalog with
            { Revision = "revision-2", Factories = [fixture.PreviewTarget, fixture.Catalog.Factories[1]] } };
        await vm.ConfirmAsync();
        Assert.Empty(vm.ErrorMessage);
        Assert.Equal((@"C:\catalog", "receipt"), Assert.Single(fixture.Confirmed));
        Assert.Equal(before, fixture.Wizard.State.ToJsonString());
        Assert.Equal("revision-2", fixture.Session.Catalog!.Revision);
        Assert.Contains(fixture.Session.SelectedFactory!.Projects, project => project.Placements.Any(placement =>
            placement.ScaleSetId == (action == "add-project" ? "scale-other-dev" : "scale-stage")));
    }

    [Fact]
    public async Task NewProjectNumberConflictsArePerPhysicalScaleEvenWhenExistingProjectIsSelected()
    {
        var fixture = await ProjectFixtureAsync();
        var vm = fixture.ViewModel;
        vm.SetIntent("add-project");
        vm.ProjectEditor.Number = "002";
        vm.ProjectEditor.DisplayName = "Forecasting again";
        ChoosePlacement(vm, "dev", "scale-a");
        Assert.Contains("already placed", Assert.Throws<InvalidOperationException>(() => vm.BuildRequest()).Message);
        ChoosePlacement(vm, "dev", "scale-other-dev");
        Assert.Equal("scale-other-dev", Assert.Single(vm.BuildRequest().Project!.Placements).ScaleSetId);
    }

    [Fact]
    public async Task ProjectPlacementHonorsConfiguredPhysicalCapacity()
    {
        var fixture = await ProjectFixtureAsync(1);
        var vm = fixture.ViewModel;
        vm.SetIntent("add-project");
        vm.ProjectEditor.Number = "003";
        vm.ProjectEditor.DisplayName = "New project";
        ChoosePlacement(vm, "dev", "scale-a");
        Assert.Contains("no configured project capacity", Assert.Throws<InvalidOperationException>(() => vm.BuildRequest()).Message);
        Assert.Empty(fixture.Prepared);
        ChoosePlacement(vm, "stage", "scale-stage");
        ChoosePlacement(vm, "dev", null);
        Assert.Equal("scale-stage", Assert.Single(vm.BuildRequest().Project!.Placements).ScaleSetId);
    }

    [Fact]
    public async Task AppendPreservesExistingPlacementAndNeverOffersRetargeting()
    {
        var fixture = await ProjectFixtureAsync();
        var vm = fixture.ViewModel;
        vm.SetIntent("add-project-placements");
        var dev = vm.ProjectEditor.Environments.Single(row => row.Environment == "dev");
        Assert.True(dev.IsExisting);
        Assert.False(dev.CanAdd);
        ChoosePlacement(vm, "dev", "scale-other-dev");
        Assert.Null(dev.Selected!.ScaleSetId);
        Assert.Throws<InvalidOperationException>(() => vm.BuildRequest());
        ChoosePlacement(vm, "stage", "scale-stage");
        var request = vm.BuildRequest();
        Assert.Null(request.Project);
        Assert.Equal("project-existing", request.ProjectId);
        Assert.Equal("stage", Assert.Single(request.Placements!).Environment);
        Assert.Equal("scale-a", Assert.Single(fixture.Session.SelectedProject!.Placements).ScaleSetId);
    }

    [Fact]
    public async Task ProjectSelectionAndDraftPlacementsCannotLeakAcrossFactoryOrRoot()
    {
        var fixture = await ProjectFixtureAsync();
        var vm = fixture.ViewModel;
        vm.SetIntent("add-project-placements");
        ChoosePlacement(vm, "stage", "scale-stage");
        fixture.Wizard.SetValue("_save_folder", @"C:\other");
        await vm.RefreshAsync();
        Assert.Null(fixture.Session.SelectedProjectId);
        Assert.All(vm.ProjectEditor.Environments, row => Assert.Null(row.Selected?.ScaleSetId));
        fixture.Wizard.SetValue("_save_folder", @"C:\catalog");
        await vm.RefreshAsync();
        Assert.Equal("project-existing", fixture.Session.SelectedProjectId);
        fixture.Session.SelectFactory("factory-b");
        Assert.Null(fixture.Session.SelectedProjectId);
        Assert.Throws<InvalidOperationException>(() => fixture.Session.SelectProject("project-existing"));
        Assert.Throws<InvalidOperationException>(() => vm.BuildRequest());
    }

    [Fact]
    public async Task CatalogRefreshPreservesDirtyProjectInputsAndExactPlacementIds()
    {
        var fixture = await ProjectFixtureAsync();
        var vm = fixture.ViewModel;
        vm.SetIntent("add-project");
        vm.ProjectEditor.Number = "003";
        vm.ProjectEditor.DisplayName = "Unsaved readable name";
        ChoosePlacement(vm, "stage", "scale-stage");
        await vm.RefreshAsync();
        Assert.Equal("003", vm.ProjectEditor.Number);
        Assert.Equal("Unsaved readable name", vm.ProjectEditor.DisplayName);
        Assert.Equal("scale-stage", Assert.Single(vm.BuildRequest().Project!.Placements).ScaleSetId);
    }

    [Fact]
    public async Task AlteredProjectPreviewCannotAuthorizeRetargeting()
    {
        var fixture = await ProjectFixtureAsync();
        var vm = fixture.ViewModel;
        vm.SetIntent("add-project-placements");
        ChoosePlacement(vm, "stage", "scale-stage");
        var source = fixture.Session.SelectedFactory!;
        fixture.PreviewTarget = source with { Projects = [source.Projects[0] with
            { Placements = [new() { Environment = "dev", ScaleSetId = "scale-other-dev" }, new() { Environment = "stage", ScaleSetId = "scale-stage" }] }] };
        await vm.PrepareAsync();
        Assert.Contains("changed an existing project", vm.ErrorMessage);
        Assert.False(vm.HasPreview);
        Assert.Empty(fixture.Confirmed);
    }

    [Fact]
    public async Task PlacementEditsInvalidatePreviouslyReviewedConsent()
    {
        var fixture = await ProjectFixtureAsync();
        var vm = fixture.ViewModel;
        vm.SetIntent("add-project-placements");
        ChoosePlacement(vm, "stage", "scale-stage");
        var source = fixture.Session.SelectedFactory!;
        fixture.PreviewTarget = source with { Projects = [source.Projects[0] with
            { Placements = source.Projects[0].Placements.Concat(vm.BuildRequest().Placements!).ToArray() }] };
        await vm.PrepareAsync();
        vm.MarkReviewed(vm.ReviewDetails);
        vm.Accepted = true;
        Assert.True(vm.CanConfirm);
        ChoosePlacement(vm, "stage", null);
        Assert.False(vm.CanConfirm);
        await vm.ConfirmAsync();
        Assert.Empty(fixture.Confirmed);
    }

    [Fact]
    public async Task DeploymentSelectsOneProjectOnlyWhenExplicitlyEnabledAndAlreadyPlaced()
    {
        var fixture = await ProjectFixtureAsync();
        var vm = fixture.ViewModel;
        vm.SetIntent("deploy");
        Assert.Null(vm.BuildRequest().ProjectId);
        vm.DeploySelectedProject = true;
        Assert.Equal("project-existing", vm.BuildRequest().ProjectId);
        fixture.Session.SelectScaleSet("scale-stage");
        Assert.Throws<InvalidOperationException>(() => vm.BuildRequest());
        vm.DeploySelectedProject = false;
        Assert.Null(vm.BuildRequest().ProjectId);
        Assert.Contains("Common-only", vm.OperationScope);
    }

    [Fact]
    public async Task JobReloadDoesNotEraseCanonicalRegionChoicesOrDestinationDraft()
    {
        var fixture = await Fixture.SelectedAsync();
        fixture.ViewModel.SetIntent("clone", "northeurope");
        await fixture.ViewModel.ReloadJobsAsync();
        Assert.Equal("northeurope", fixture.ViewModel.TargetRegionChoice!.Value);
    }

    private static void ChoosePlacement(FactoryCatalogViewModel vm, string environment, string? scaleId)
    {
        var row = vm.ProjectEditor.Environments.Single(row => row.Environment == environment);
        row.Selected = row.Choices.Single(choice => choice.ScaleSetId == scaleId);
    }

    [Theory]
    [InlineData("")]
    [InlineData("124")]
    public async Task CloneSavedVersionCanInheritOrOverrideWithoutChangingSource(string version)
    {
        var fixture = await Fixture.SelectedAsync();
        var source = fixture.Catalog.Factories[0] with { FactoryVersion = "125", VersionRef = "phantom-do-not-use" };
        fixture.Catalog = fixture.Catalog with { Factories = [source, fixture.Catalog.Factories[1]] };
        await fixture.ViewModel.RefreshAsync();
        var vm = fixture.ViewModel;
        vm.SetIntent("clone", "northeurope");
        vm.TargetPrefix = "dc";
        Assert.Empty(vm.LocalFactoryVersion);
        vm.LocalFactoryVersion = version;
        await vm.RefreshAsync();
        Assert.Equal(version, vm.LocalFactoryVersion);
        Assert.Equal("125", vm.SavedFactoryVersion);
        Assert.DoesNotContain("phantom", vm.SelectionDetails);
        var savedVersion = version.Length == 0 ? "125" : version;
        var cloned = source with { Id = "cloned", Key = "dc-neu", Prefix = "dc", Region = "northeurope", FactoryVersion = savedVersion };
        fixture.PreviewTarget = cloned;
        await vm.PrepareAsync();
        Assert.Empty(vm.ErrorMessage);
        var request = Assert.Single(fixture.Prepared);
        Assert.Equal(version.Length == 0 ? null : version, request.FactoryVersion);
        Assert.Null(request.VersionRef);
        Assert.Contains("Saved target factory version: " + savedVersion, vm.ReviewDetails);
        fixture.Result = new() { ContractVersion = 1, Catalog = fixture.Catalog with
            { Revision = "revision-2", Factories = fixture.Catalog.Factories.Append(cloned).ToArray() } };
        vm.MarkReviewed(vm.ReviewDetails);
        vm.Accepted = true;
        await vm.ConfirmAsync();
        Assert.Equal("125", fixture.Session.Catalog!.Factories.Single(factory => factory.Id == source.Id).FactoryVersion);
        Assert.Equal(savedVersion, fixture.Session.Catalog.Factories.Single(factory => factory.Id == cloned.Id).FactoryVersion);
        Assert.Single(fixture.Confirmed);
    }

    [Fact]
    public async Task NewFactorySavedVersionIsSeparateFromRuntimeOverrideAndInvalidatesConsent()
    {
        var fixture = await Fixture.SelectedAsync();
        var vm = fixture.ViewModel;
        FillScaleDraft(vm, "create-factory");
        Assert.Equal("124", vm.LocalFactoryVersion);
        await vm.PrepareAsync();
        Assert.Equal("124", Assert.Single(fixture.Prepared).FactoryVersion);
        vm.MarkReviewed(vm.ReviewDetails);
        vm.Accepted = true;
        Assert.True(vm.CanConfirm);
        vm.LocalFactoryVersion = "125";
        Assert.False(vm.HasPreview);
        Assert.False(vm.CanConfirm);
        Assert.Equal("125", vm.BuildRequest().FactoryVersion);
        Assert.Null(vm.BuildRequest().VersionRef);
        vm.SetIntent("deploy");
        Assert.Null(vm.BuildRequest().FactoryVersion);
        vm.VersionMode = vm.VersionModes.Single(choice => choice.Value == "inherit");
        Assert.Null(vm.BuildRequest().VersionRef);
        Assert.Empty(fixture.Confirmed);
    }

    [Fact]
    public async Task OlderBackendLocalVersionRejectionIsVisibleAndNeverRetriedWithoutField()
    {
        var fixture = await Fixture.SelectedAsync();
        FillScaleDraft(fixture.ViewModel, "create-factory");
        fixture.PrepareFailure = new HttpRequestException("422: aifactory_version is not supported by this older companion.");
        await fixture.ViewModel.PrepareAsync();
        Assert.Contains("422", fixture.ViewModel.ErrorMessage);
        Assert.Equal("124", Assert.Single(fixture.Prepared).FactoryVersion);
        Assert.Empty(fixture.Confirmed);
        Assert.False(fixture.ViewModel.HasPreview);
    }

    [Fact]
    public async Task SavedFactoryVersionMustBeEchoedBeforeConsent()
    {
        var fixture = await Fixture.SelectedAsync();
        FillScaleDraft(fixture.ViewModel, "create-factory");
        fixture.OmitFactoryVersionEcho = true;
        await fixture.ViewModel.PrepareAsync();
        Assert.Contains("did not echo the saved factory version", fixture.ViewModel.ErrorMessage);
        Assert.False(fixture.ViewModel.HasPreview);
        Assert.Empty(fixture.Confirmed);
    }

    [Fact]
    public async Task OptionalCommonSubnetsStayExactAcrossRefreshAndAreReviewed()
    {
        var fixture = await Fixture.SelectedAsync();
        var vm = fixture.ViewModel;
        FillScaleDraft(vm, "create-scale-set");
        Assert.Null(Assert.Single(vm.BuildRequest().ScaleSets!).Network.CommonSubnets);
        FillCommonSubnets(vm);
        var expected = new CatalogCommonSubnets { Common = vm.CommonSubnet, Scoring = vm.ScoringSubnet,
            Powerbi = vm.PowerbiSubnet, Bastion = vm.BastionSubnet };
        await vm.RefreshAsync();
        Assert.True(vm.UseCustomCommonSubnets);
        Assert.Equal(expected, Assert.Single(vm.BuildRequest().ScaleSets!).Network.CommonSubnets);
        await vm.PrepareAsync();
        Assert.Empty(vm.ErrorMessage);
        foreach (var cidr in new[] { expected.Common, expected.Scoring, expected.Powerbi, expected.Bastion }) Assert.Contains(cidr, vm.ReviewDetails);
        vm.MarkReviewed(vm.ReviewDetails);
        vm.Accepted = true;
        Assert.True(vm.CanConfirm);
        vm.CommonSubnet = "10.42.4.0/24";
        Assert.False(vm.HasPreview);
        vm.UseCustomCommonSubnets = false;
        Assert.Null(Assert.Single(vm.BuildRequest().ScaleSets!).Network.CommonSubnets);
        vm.UseCustomCommonSubnets = true;
        Assert.Equal("10.42.4.0/24", Assert.Single(vm.BuildRequest().ScaleSets!).Network.CommonSubnets!.Common);
        Assert.Empty(fixture.Confirmed);
    }

    [Fact]
    public async Task CommonSubnetOverridesRequireAllFourAndCannotBeSilentlyDropped()
    {
        var fixture = await Fixture.SelectedAsync();
        var vm = fixture.ViewModel;
        FillScaleDraft(vm, "create-scale-set");
        vm.UseCustomCommonSubnets = true;
        vm.CommonSubnet = "10.42.0.0/24";
        await vm.PrepareAsync();
        Assert.Contains("all four", vm.ErrorMessage);
        Assert.Empty(fixture.Prepared);
        FillCommonSubnets(vm);
        fixture.OmitCustomSubnetEcho = true;
        await vm.PrepareAsync();
        Assert.Contains("did not echo the exact custom network", vm.ErrorMessage);
        Assert.False(vm.HasPreview);
        Assert.Empty(fixture.Confirmed);
    }

    [Fact]
    public async Task ClonePreservesSourceCustomSubnetsWithoutSubmittingReplacementNetworks()
    {
        var fixture = await Fixture.SelectedAsync();
        var source = fixture.Catalog.Factories[0];
        var subnets = new CatalogCommonSubnets { Common = "10.0.0.0/24", Scoring = "10.0.1.0/24",
            Powerbi = "10.0.2.0/24", Bastion = "10.0.3.0/26" };
        source = source with { ScaleSets = [source.ScaleSets[0] with { Network = source.ScaleSets[0].Network with { CommonSubnets = subnets } }] };
        fixture.Catalog = fixture.Catalog with { Factories = [source, fixture.Catalog.Factories[1]] };
        await fixture.ViewModel.RefreshAsync();
        fixture.ViewModel.SetIntent("clone", "northeurope");
        fixture.ViewModel.TargetPrefix = "dc";
        await fixture.ViewModel.PrepareAsync();
        Assert.Null(Assert.Single(fixture.Prepared).ScaleSets);
        Assert.Equal(subnets, fixture.Session.SelectedScaleSet!.Network.CommonSubnets);
        Assert.Contains("Bastion subnet: 10.0.3.0/26", fixture.ViewModel.ReviewDetails);
    }

    private static void FillScaleDraft(FactoryCatalogViewModel vm, string action)
    {
        vm.SetIntent(action, "northeurope");
        vm.TargetPrefix = "dc";
        vm.EnvironmentChoice = vm.Environments.Single(choice => choice.Value == "stage");
        vm.OrchestratorChoice = vm.Orchestrators.Single(choice => choice.Value == "gha");
        vm.Suffix = "002";
        vm.SubscriptionId = Fixture.Subscription;
        vm.TenantId = Fixture.Tenant;
        vm.VnetCidr = "10.42.0.0/16";
        vm.MaxProjects = "8";
    }

    private static void FillCommonSubnets(FactoryCatalogViewModel vm)
    {
        vm.UseCustomCommonSubnets = true;
        vm.CommonSubnet = "10.42.0.0/24";
        vm.ScoringSubnet = "10.42.1.0/24";
        vm.PowerbiSubnet = "10.42.2.0/24";
        vm.BastionSubnet = "10.42.3.0/26";
    }

    [Theory]
    [InlineData("000")]
    [InlineData("00")]
    [InlineData("1000")]
    [InlineData("1a2")]
    public async Task NewProjectNumberMatchesStrictNonzeroDomainContract(string number)
    {
        var fixture = await Fixture.SelectedAsync();
        var vm = fixture.ViewModel;
        vm.SetIntent("add-project");
        vm.ProjectEditor.Number = number;
        vm.ProjectEditor.DisplayName = "Forecasting";
        ChoosePlacement(vm, "dev", "scale-a");
        await vm.PrepareAsync();
        Assert.Contains("001 through 999", vm.ErrorMessage);
        Assert.Empty(fixture.Prepared);
        Assert.Empty(fixture.Confirmed);
    }

    private static async Task<Fixture> ProjectFixtureAsync(int capacity = 8)
    {
        var fixture = await Fixture.SelectedAsync();
        var factory = fixture.Catalog.Factories[0];
        var scale = factory.ScaleSets[0] with { Network = factory.ScaleSets[0].Network with { MaxProjects = capacity } };
        factory = factory with
        {
            ScaleSets = [scale, scale with { Id = "scale-other-dev", Suffix = "002" },
                scale with { Id = "scale-stage", Environment = "stage", Suffix = "002" }],
            Projects = [new() { Id = "project-existing", Key = "project-002", Number = "002", DisplayName = "Forecasting",
                Placements = [new() { Environment = "dev", ScaleSetId = scale.Id }], Status = "draft" }]
        };
        fixture.Catalog = fixture.Catalog with { Factories = [factory, fixture.Catalog.Factories[1]] };
        await fixture.ViewModel.RefreshAsync();
        fixture.Session.SelectProject("project-existing");
        return fixture;
    }

    [Theory]
    [InlineData("factory", null, null)]
    [InlineData("scale-set", "scale-a", null)]
    [InlineData("project", null, "project-existing")]
    public async Task ScopedSettingsLoadAndConfirmOnlyEditedValuesWithoutWizardMutation(string mode, string? scaleId, string? projectId)
    {
        var fixture = await ProjectFixtureAsync();
        var vm = fixture.ViewModel;
        vm.SetIntent("configure-settings");
        vm.SettingsScope = vm.SettingsScopes.Single(choice => choice.Value == mode);
        var wizardBefore = fixture.Wizard.State.ToJsonString();
        Assert.False(vm.CanPrepare);
        await vm.LoadSettingsAsync();
        Assert.Empty(vm.ErrorMessage);
        var read = Assert.Single(fixture.SettingsReads);
        Assert.Equal((scaleId, projectId), (read.ScaleSetId, read.ProjectId));
        var field = vm.SettingsEditor.Fields.Single(field => field.Key == "technical_admins_ad_object_id");
        field.Value = "AAAAAAAA-AAAA-4AAA-8AAA-AAAAAAAAAAAA";
        await vm.PrepareAsync();
        Assert.Empty(vm.ErrorMessage);
        var request = Assert.Single(fixture.Prepared);
        Assert.Equal("configure-settings", request.Action);
        Assert.Equal((scaleId, projectId), (request.ScaleSetId, request.ProjectId));
        Assert.Single(request.Settings!);
        Assert.Equal(field.Value, request.Settings![field.Key]!.GetValue<string>());
        Assert.Null(request.VersionRef);
        Assert.Null(request.FactoryVersion);
        Assert.Contains(field.Value, vm.ReviewDetails);
        Assert.Contains("Settings scope:", vm.ReviewDetails);
        if (mode == "project") Assert.Contains("across all existing placements", vm.ReviewDetails);
        Assert.Empty(fixture.Confirmed);
        fixture.Result = new() { ContractVersion = 1, Catalog = fixture.Catalog with { Revision = "revision-2" } };
        vm.MarkReviewed(vm.ReviewDetails);
        vm.Accepted = true;
        await vm.ConfirmAsync();
        Assert.Single(fixture.Confirmed);
        Assert.Empty(vm.ErrorMessage);
        Assert.False(vm.SettingsEditor.IsLoaded);
        await vm.LoadSettingsAsync();
        Assert.Equal(field.Value, vm.SettingsEditor.Fields.Single(candidate => candidate.Key == field.Key).Value);
        Assert.False(vm.SettingsEditor.IsDirty);
        Assert.Equal(wizardBefore, fixture.Wizard.State.ToJsonString());
    }

    [Fact]
    public async Task SettingsReadForPreviousScopeIsDiscarded()
    {
        var fixture = await Fixture.SelectedAsync();
        var vm = fixture.ViewModel;
        vm.SetIntent("configure-settings");
        fixture.SettingsGate = new(TaskCreationOptions.RunContinuationsAsynchronously);
        var pending = vm.LoadSettingsAsync();
        await fixture.SettingsStarted.Task;
        vm.SettingsScope = vm.SettingsScopes.Single(choice => choice.Value == "scale-set");
        fixture.SettingsGate.SetResult();
        await pending;
        Assert.False(vm.SettingsEditor.IsLoaded);
        Assert.Empty(vm.SettingsEditor.Fields);
        Assert.Contains("discarded", vm.StatusMessage);
        Assert.Empty(fixture.Prepared);
    }

    [Theory]
    [InlineData("api")]
    [InlineData("root")]
    [InlineData("edit")]
    public async Task SettingsReloadCannotReplaceNewContextOrNewerEdits(string change)
    {
        var fixture = await Fixture.SelectedAsync();
        var vm = fixture.ViewModel;
        vm.SetIntent("configure-settings");
        await vm.LoadSettingsAsync();
        fixture.SettingsGate = new(TaskCreationOptions.RunContinuationsAsynchronously);
        var pending = vm.LoadSettingsAsync();
        if (change == "api") fixture.Connection = new("http://localhost:9999", "different-api-key");
        else if (change == "root") fixture.Wizard.SetValue("_save_folder", @"C:\other");
        else vm.SettingsEditor.Fields.Single(field => field.Key == "technical_admins_ad_object_id").Value = "newer-edit";
        fixture.SettingsGate.SetResult();
        await pending;
        Assert.Contains("discarded", vm.StatusMessage);
        if (change == "edit")
        {
            Assert.Equal("newer-edit", vm.SettingsEditor.Fields.Single(field => field.Key == "technical_admins_ad_object_id").Value);
            Assert.True(vm.SettingsEditor.IsDirty);
        }
        else Assert.Empty(vm.SettingsEditor.Fields);
        Assert.Empty(fixture.Prepared);
    }

    [Fact]
    public async Task SettingsReadRejectsMismatchedRevisionAndIdentity()
    {
        var fixture = await Fixture.SelectedAsync();
        fixture.ViewModel.SetIntent("configure-settings");
        fixture.SettingsResponse = new() { ContractVersion = 1, FactoryId = "factory-a", Revision = "other-revision" };
        await fixture.ViewModel.LoadSettingsAsync();
        Assert.Contains("different catalog revision", fixture.ViewModel.ErrorMessage);
        fixture.SettingsResponse = fixture.SettingsResponse with { Revision = fixture.Catalog.Revision, FactoryId = "factory-b" };
        await fixture.ViewModel.LoadSettingsAsync();
        Assert.Contains("different or incomplete scope", fixture.ViewModel.ErrorMessage);
        Assert.False(fixture.ViewModel.SettingsEditor.IsLoaded);
    }

    [Fact]
    public async Task CatalogRevisionChangeKeepsSettingsDraftButBlocksStaleSubmission()
    {
        var fixture = await Fixture.SelectedAsync();
        var vm = fixture.ViewModel;
        vm.SetIntent("configure-settings");
        await vm.LoadSettingsAsync();
        vm.SettingsEditor.Fields.Single(field => field.Key == "technical_admins_ad_object_id").Value = "unsaved";
        fixture.Catalog = fixture.Catalog with { Revision = "revision-2" };
        await vm.RefreshAsync();
        Assert.True(vm.SettingsEditor.IsStale);
        Assert.Equal("unsaved", vm.SettingsEditor.Fields.Single(field => field.Key == "technical_admins_ad_object_id").Value);
        Assert.False(vm.CanPrepare);
        await vm.PrepareAsync();
        Assert.Empty(fixture.Prepared);
        Assert.Contains("Reload settings", vm.ErrorMessage);
    }

    [Fact]
    public async Task SettingsEditInvalidatesConsentAndNonConfigurationConfirmationIsFailure()
    {
        var fixture = await Fixture.SelectedAsync();
        var vm = fixture.ViewModel;
        vm.SetIntent("configure-settings");
        await vm.LoadSettingsAsync();
        var field = vm.SettingsEditor.Fields.Single(field => field.Key == "technical_admins_ad_object_id");
        field.Value = "first";
        await vm.PrepareAsync();
        vm.MarkReviewed(vm.ReviewDetails);
        vm.Accepted = true;
        Assert.True(vm.CanConfirm);
        field.Value = "second";
        Assert.False(vm.HasPreview);
        Assert.False(vm.CanConfirm);
        await vm.PrepareAsync();
        vm.MarkReviewed(vm.ReviewDetails);
        vm.Accepted = true;
        await vm.ConfirmAsync();
        Assert.Contains("unexpectedly returned a runtime job", vm.ErrorMessage);
        Assert.False(vm.HasPreview);
        Assert.Single(fixture.Confirmed);
    }

    private sealed class Fixture : IFactoryCatalogClient, IAiFactoryConnectionProvider, IJsonApiTransport, IFactoryCatalogTerminalSession, IFactoryCatalogSettingsClient
    {
        public const string Subscription = "11111111-1111-4111-8111-111111111111";
        public const string Tenant = "22222222-2222-4222-8222-222222222222";
        public WizardSession Wizard { get; }
        public FactoryCatalogSession Session { get; }
        public FactoryCatalogViewModel ViewModel { get; }
        public DateTimeOffset Now { get; set; } = DateTimeOffset.Parse("2026-09-09T18:00:00Z");
        public AiFactoryConnection Connection { get; set; } = new("http://localhost:8765", "offline-test");
        public FactoryCatalog Catalog { get; set; } = new()
        {
            ContractVersion = 1, Mode = "catalog", Revision = "revision-1", RequiresSelection = true,
            Factories =
            [
                new() { Id = "factory-a", Key = "mrvel-1-sdc", Prefix = "mrvel-1", Region = "sdc", Status = "configured", VersionRef = "124",
                    ScaleSets = [Scale("scale-a")], Projects = [] },
                new() { Id = "factory-b", Key = "dc-neu", Prefix = "dc", Region = "neu", Status = "draft", VersionRef = "124",
                    ScaleSets = [Scale("scale-b")], Projects = [] }
            ]
        };
        public FactoryCatalogConfirmation Result { get; set; } = new()
        {
            ContractVersion = 1, Job = new() { Id = "job", FactoryId = "factory-a", Status = "queued", Message = "Accepted" }
        };
        public List<FactoryCatalogRequest> Prepared { get; } = [];
        public List<(string Folder, string Receipt)> Confirmed { get; } = [];
        public List<(string Folder, string JobId)> OpenedTerminals { get; } = [];
        public Exception? ConfirmFailure { get; set; }
        public Exception? PrepareFailure { get; set; }
        public bool EchoBinding { get; set; } = true;
        public CatalogFactory? PreviewTarget { get; set; }
        public CatalogSourceVersion? PreviewSourceVersion { get; set; }
        public bool OmitFactoryVersionEcho { get; set; }
        public bool OmitCustomSubnetEcho { get; set; }
        public FactoryCatalogSettings? SettingsResponse { get; set; }
        public List<CatalogSettingsScope> SettingsReads { get; } = [];
        private readonly Dictionary<CatalogSettingsScope, JsonObject> _settings = [];
        public TaskCompletionSource? SettingsGate { get; set; }
        public TaskCompletionSource SettingsStarted { get; } = new(TaskCreationOptions.RunContinuationsAsynchronously);
        public TaskCompletionSource? PrepareGate { get; set; }
        public TaskCompletionSource PrepareStarted { get; } = new(TaskCreationOptions.RunContinuationsAsynchronously);
        public TaskCompletionSource? ReadGate { get; set; }
        public TaskCompletionSource ReadStarted { get; } = new(TaskCreationOptions.RunContinuationsAsynchronously);
        public int JobReads { get; private set; }
        public Fixture()
        {
            var api = new AiFactoryApiClient(this, this);
            Wizard = new(api);
            Wizard.ReplaceState(new() { ["_save_folder"] = @"C:\catalog", ["unsaved"] = "preserve me" });
            Session = new(this, Wizard, this);
            ViewModel = new(this, Session, () => Now, api, this);
            ViewModel.SetVisible(true);
        }
        public static async Task<Fixture> SelectedAsync()
        {
            var fixture = new Fixture();
            await fixture.ViewModel.RefreshAsync();
            fixture.Session.SelectFactory("factory-a");
            fixture.Session.SelectScaleSet("scale-a");
            fixture.ViewModel.VersionRef = "124";
            fixture.ViewModel.VersionMode = fixture.ViewModel.VersionModes.Single(choice => choice.Value == "override");
            return fixture;
        }
        public async Task PrepareDeleteAsync()
        {
            ViewModel.SetIntent("delete-scale-set");
            await ViewModel.PrepareAsync();
            ViewModel.MarkReviewed(ViewModel.ReviewDetails);
            ViewModel.Accepted = true;
            ViewModel.TypedPhrase = ViewModel.RequiredPhrase;
        }
        private static CatalogScaleSet Scale(string id) => new()
        {
            Id = id, Environment = "dev", Suffix = "001", SubscriptionId = Subscription, TenantId = Tenant,
            Orchestrator = "gha", Network = new() { VnetCidr = "10.0.0.0/16", MaxProjects = 8 }, Status = "configured"
        };
        public Task<AiFactoryConnection> GetConnectionAsync(CancellationToken cancellationToken = default) => Task.FromResult(Connection);
        public async Task<FactoryCatalog> GetFactoryCatalogAsync(string folder, CancellationToken cancellationToken = default)
        {
            ReadStarted.TrySetResult();
            if (ReadGate is not null) await ReadGate.Task;
            return Catalog;
        }
        public async Task<FactoryCatalogPreview> PrepareFactoryCatalogAsync(FactoryCatalogRequest request, CancellationToken cancellationToken = default)
        {
            Prepared.Add(request);
            PrepareStarted.TrySetResult();
            if (PrepareGate is not null) await PrepareGate.Task;
            if (PrepareFailure is not null) throw PrepareFailure;
            var target = PreviewTarget ?? DefaultPreviewTarget(request);
            if (target is not null && OmitFactoryVersionEcho) target = target with { FactoryVersion = null };
            if (target is not null && OmitCustomSubnetEcho) target = target with
            {
                ScaleSets = target.ScaleSets.Select(scale => scale with { Network = scale.Network with { CommonSubnets = null } }).ToArray()
            };
            return new()
            {
                ContractVersion = 1, ConfirmationId = "receipt", CanExecute = true,
                SourceRevision = Catalog.Revision, ExpiresAt = Now.AddMinutes(5).ToString("O"),
                OperationMode = request.Action is "deploy" or "delete-factory" or "delete-scale-set" ? "runtime" : "configuration",
                SourceVersion = PreviewSourceVersion ?? new() { FactoryVersion = request.VersionRef, RequestedVersion = "124", Branch = "release/v1.24", ResolvedRef = new string('a', 40) },
                Binding = EchoBinding ? request.Binding : null,
                Target = target,
                Summary = "Reviewed server plan", Effects = ["One exact target"], Warnings = [], Blockers = [],
                Inventory = [new() { ResourceId = $"/subscriptions/{Subscription}/resourceGroups/owned" }]
            };
        }
        private CatalogFactory? DefaultPreviewTarget(FactoryCatalogRequest request)
        {
            var source = Catalog.Factories.SingleOrDefault(factory => factory.Id == request.FactoryId);
            var scales = request.ScaleSets?.Select(input => new CatalogScaleSet
            {
                Id = "new-" + input.Environment + input.Suffix, Environment = input.Environment, Suffix = input.Suffix,
                SubscriptionId = input.SubscriptionId, TenantId = input.TenantId, Orchestrator = input.Orchestrator,
                Network = input.Network, Status = "draft"
            }).ToArray() ?? [];
            return request.Action switch
            {
                "create-factory" => new() { Id = "new-factory", Key = request.TargetPrefix + "-" + request.TargetRegion,
                    Prefix = request.TargetPrefix!, Region = request.TargetRegion!, FactoryVersion = request.FactoryVersion, ScaleSets = scales },
                "clone" => source! with { Id = "cloned-factory", Key = request.TargetPrefix + "-" + request.TargetRegion,
                    Prefix = request.TargetPrefix!, Region = request.TargetRegion!, FactoryVersion = request.FactoryVersion ?? source!.FactoryVersion },
                "create-scale-set" => source! with { ScaleSets = source!.ScaleSets.Concat(scales).ToArray() },
                "configure-settings" => source,
                _ => null
            };
        }
        public Task<FactoryCatalogConfirmation> ConfirmFactoryCatalogAsync(string folder, string confirmationId, CancellationToken cancellationToken = default)
        {
            Confirmed.Add((folder, confirmationId));
            if (ConfirmFailure is not null) throw ConfirmFailure;
            if (Prepared.LastOrDefault() is { Action: "configure-settings", Settings: { } delta } settingsRequest && Result.Catalog is not null)
            {
                var scope = new CatalogSettingsScope(folder, settingsRequest.FactoryId!, settingsRequest.ScaleSetId, settingsRequest.ProjectId);
                var state = _settings.GetValueOrDefault(scope) ?? DefaultSettingsState();
                foreach (var item in delta) state[item.Key] = item.Value?.DeepClone();
                _settings[scope] = state;
                Catalog = Result.Catalog;
            }
            return Task.FromResult(Result);
        }
        private static JsonObject DefaultSettingsState() => new() { ["technical_admins_ad_object_id"] = "previous-reference", ["enabled"] = true };
        public async Task<FactoryCatalogSettings> GetFactoryCatalogSettingsAsync(string folder, string factoryId,
            string? scaleSetId = null, string? projectId = null, CancellationToken cancellationToken = default)
        {
            var scope = new CatalogSettingsScope(folder, factoryId, scaleSetId, projectId);
            SettingsReads.Add(scope);
            var result = SettingsResponse ?? new()
            {
                ContractVersion = 1, Revision = Catalog.Revision, FactoryId = factoryId, ScaleSetId = scaleSetId, ProjectId = projectId,
                State = (JsonObject)(_settings.GetValueOrDefault(scope) ?? DefaultSettingsState()).DeepClone(),
                FieldKeys = ["technical_admins_ad_object_id", "enabled"]
            };
            SettingsStarted.TrySetResult();
            if (SettingsGate is not null) await SettingsGate.Task;
            return result;
        }
        public Task<FactoryCatalogJobs> GetFactoryCatalogJobsAsync(string folder, CancellationToken cancellationToken = default)
        {
            JobReads++;
            return Task.FromResult(new FactoryCatalogJobs { ContractVersion = 1, Jobs = [] });
        }
        public Task<FactoryCatalogJob> GetFactoryCatalogJobAsync(string folder, string jobId, CancellationToken cancellationToken = default) =>
            Task.FromResult(Result.Job ?? throw new InvalidOperationException("No job is available."));
        public Task OpenCatalogAsync(string folder, FactoryCatalogJob job)
        {
            OpenedTerminals.Add((folder, job.Id));
            return Task.CompletedTask;
        }
        public Task<TResponse> SendAsync<TResponse>(HttpRequestMessage request, CancellationToken cancellationToken = default)
        {
            if (typeof(TResponse) == typeof(FactorySchema))
                return Task.FromResult((TResponse)(object)new FactorySchema { Defaults = DefaultSettingsState() });
            if (typeof(TResponse) == typeof(OperationsRegionsResult))
                return Task.FromResult((TResponse)(object)new OperationsRegionsResult
                {
                    Regions = [new() { Name = "northeurope", DisplayName = "North Europe" },
                        new() { Name = "swedencentral", DisplayName = "Sweden Central" }]
                });
            throw new InvalidOperationException("Catalog tests must never call legacy scope or Azure APIs.");
        }
    }
}

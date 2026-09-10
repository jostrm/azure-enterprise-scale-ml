using ESAIF.ConfigWizard.Services;
using ESAIF.ConfigWizard.ViewModels;
using ESAIF.DomainLayer.Configuration;
using ESAIF.DomainLayer.Operations;

namespace ESAIF.ConfigWizard.Tests;

public sealed class ProjectDeploymentBoardTests
{
    [Fact]
    public async Task CatalogRootNeverReachesLegacyProjectEndpointsEvenThroughDirectCalls()
    {
        var fixture = new Fixture { CatalogScope = true };
        await fixture.Vm.LoadAsync();
        Assert.Contains("factory catalog", fixture.Vm.ErrorMessage);
        await fixture.Vm.RefreshDraftsAsync();
        await fixture.Vm.DeployAsync(fixture.Vm.ProjectRows[0].Dev);
        await fixture.Vm.UpdateAsync(fixture.Vm.ProjectRows[0].Dev);
        Assert.False(fixture.Vm.CanPollDrafts);
        Assert.Equal(0, fixture.Client.Lists);
        Assert.Equal(0, fixture.Client.Plans);
        Assert.Equal(0, fixture.Client.Prepares);
        Assert.Equal(0, fixture.Client.Starts);
    }

    [Fact]
    public async Task BecomingCatalogScopeRevokesExistingConfirmation()
    {
        var fixture = new Fixture();
        await fixture.Vm.RefreshDraftsAsync();
        await fixture.Vm.DeployAsync(fixture.Vm.ProjectRows[0].Stage);
        fixture.CatalogScope = true;
        Assert.False(fixture.Vm.CanConfirmDeployment);
        await fixture.Vm.ConfirmDeploymentAsync();
        Assert.Equal(0, fixture.Client.Starts);
    }

    [Fact]
    public async Task PlanCreatesStageDraftWithoutLoadingConfigOrStartingScript()
    {
        var fixture = new Fixture();
        var state = fixture.Wizard.State.ToJsonString();
        await fixture.Vm.DeployAsync(fixture.Vm.ProjectRows[0].Dev);
        var row = Assert.Single(fixture.Vm.ProjectRows);
        Assert.True(row.Stage.IsDraft);
        Assert.False(row.Stage.IsPlaceholder);
        Assert.False(row.Stage.IsDeployed);
        Assert.False(row.Stage.IsActive);
        Assert.True(row.Stage.CanSubmitDraft);
        Assert.Equal("Not deployed", row.Stage.Status);
        Assert.True(row.Stage.IsSelected);
        Assert.True(row.Stage.ShowDeployButton);
        Assert.False(row.Stage.CanUpdate);
        Assert.Equal("Stage (0 deployed, 1 draft)", fixture.Vm.StageHeader);
        Assert.Equal(0, fixture.Vm.StageCount);
        Assert.Equal(1, fixture.Client.Plans);
        Assert.Equal(0, fixture.Client.Starts);
        Assert.False(fixture.Vm.DeployCommand.CanExecute(row.Dev));
        Assert.Equal(state, fixture.Wizard.State.ToJsonString());
    }

    [Fact]
    public async Task SavedDraftRestoresOnReloadAndDifferentFactoryNeverInheritsIt()
    {
        var fixture = new Fixture();
        await fixture.Vm.RefreshDraftsAsync();
        Assert.True(fixture.Vm.ProjectRows[0].Stage.IsDraft);
        Assert.Equal("Not deployed", fixture.Vm.ProjectRows[0].Stage.Status);
        Assert.True(fixture.Vm.ProjectRows[0].Stage.ShowDeployButton);
        fixture.Wizard.SetValue("_save_folder", FactoryNetworkFixture.Ado);
        fixture.Operations.ApplyRefreshedOverview(FactoryNetworkFixture.Ado, Overview("dev"));
        Assert.True(fixture.Vm.ProjectRows[0].Stage.IsPlaceholder);
        Assert.Equal(0, fixture.Vm.DraftCount);
        Assert.False(fixture.Vm.HasDeploymentPlan);
    }

    [Fact]
    public async Task DeployOnlyPreparesAndExplicitConfirmStartsOnce()
    {
        var fixture = new Fixture();
        await fixture.Vm.RefreshDraftsAsync();
        await fixture.Vm.DeployAsync(fixture.Vm.ProjectRows[0].Stage);
        Assert.True(fixture.Vm.HasDeploymentPlan);
        Assert.True(fixture.Vm.CanConfirmDeployment);
        Assert.Equal(0, fixture.Client.Starts);
        await fixture.Vm.ConfirmDeploymentAsync();
        Assert.Equal(1, fixture.Client.Starts);
        Assert.True(fixture.Vm.ProjectRows[0].Stage.IsDeploying);
        Assert.False(fixture.Vm.HasDeploymentPlan);
        await fixture.Vm.ConfirmDeploymentAsync();
        Assert.Equal(1, fixture.Client.Starts);
        Assert.Equal(FactoryNetworkFixture.Gha, fixture.Terminal.OpenedFolder);
        Assert.Equal("job", fixture.Terminal.OpenedDraft?.JobId);
    }

    [Fact]
    public async Task TerminalDisplayFailureDoesNotLoseTheRunningJob()
    {
        var fixture = new Fixture();
        fixture.Terminal.Fail = true;
        await fixture.Vm.RefreshDraftsAsync();
        await fixture.Vm.DeployAsync(fixture.Vm.ProjectRows[0].Stage);
        await fixture.Vm.ConfirmDeploymentAsync();
        Assert.Contains("Terminal unavailable", fixture.Vm.ErrorMessage);
        Assert.True(fixture.Vm.ProjectRows[0].Stage.IsDeploying);
        Assert.True(fixture.Vm.ProjectRows[0].Stage.HasTerminal);
        Assert.Equal(1, fixture.Client.Starts);
    }

    [Fact]
    public async Task OpeningTerminalDoesNotStartAnotherDeployment()
    {
        var fixture = new Fixture();
        fixture.Client.CurrentDraft = Draft with { Status = "failed", JobId = "existing-job" };
        await fixture.Vm.RefreshDraftsAsync();
        await fixture.Vm.OpenTerminalAsync(fixture.Vm.ProjectRows[0].Stage);
        Assert.Equal("existing-job", fixture.Terminal.OpenedDraft?.JobId);
        Assert.Equal(0, fixture.Client.Starts);
    }

    [Theory]
    [InlineData(false, "2099-01-01T00:00:00Z", false)]
    [InlineData(true, "bad", false)]
    [InlineData(true, "2000-01-01T00:00:00Z", false)]
    [InlineData(true, "2099-01-01T00:00:00Z", true)]
    public async Task BlockedExpiredOrUnknownConfirmationsNeverStart(bool executable, string expiry, bool blocked)
    {
        var fixture = new Fixture();
        fixture.Client.Plan = fixture.Client.Plan with
        {
            CanExecute = executable, ExpiresAt = expiry, Blockers = blocked ? ["Missing script"] : []
        };
        await fixture.Vm.RefreshDraftsAsync();
        await fixture.Vm.DeployAsync(fixture.Vm.ProjectRows[0].Stage);
        Assert.False(fixture.Vm.CanConfirmDeployment);
        await fixture.Vm.ConfirmDeploymentAsync();
        Assert.Equal(0, fixture.Client.Starts);
    }

    [Fact]
    public async Task CancelClearsConsentButKeepsTheSavedDraft()
    {
        var fixture = new Fixture();
        await fixture.Vm.RefreshDraftsAsync();
        await fixture.Vm.DeployAsync(fixture.Vm.ProjectRows[0].Stage);
        fixture.Vm.DismissDeployment();
        Assert.False(fixture.Vm.HasDeploymentPlan);
        Assert.True(fixture.Vm.ProjectRows[0].Stage.IsDraft);
        Assert.Equal(0, fixture.Client.Starts);
    }

    [Fact]
    public async Task FactoryChangeDuringPrepareDiscardsLateConsent()
    {
        var fixture = new Fixture();
        fixture.Client.PrepareGate = new(TaskCreationOptions.RunContinuationsAsynchronously);
        await fixture.Vm.RefreshDraftsAsync();
        var prepare = fixture.Vm.DeployAsync(fixture.Vm.ProjectRows[0].Stage);
        fixture.Wizard.SetValue("_save_folder", FactoryNetworkFixture.Ado);
        fixture.Operations.ApplyRefreshedOverview(FactoryNetworkFixture.Ado, Overview("dev"));
        fixture.Client.PrepareGate.SetResult(fixture.Client.Plan);
        await prepare;
        Assert.False(fixture.Vm.HasDeploymentPlan);
        Assert.True(fixture.Vm.ProjectRows[0].Stage.IsPlaceholder);
        Assert.Equal(0, fixture.Client.Starts);
    }

    [Fact]
    public async Task LeavingPageDuringPrepareDoesNotRestoreHiddenConsent()
    {
        var fixture = new Fixture();
        fixture.Client.PrepareGate = new(TaskCreationOptions.RunContinuationsAsynchronously);
        await fixture.Vm.RefreshDraftsAsync();
        var prepare = fixture.Vm.DeployAsync(fixture.Vm.ProjectRows[0].Stage);
        fixture.Vm.DismissDeployment();
        fixture.Client.PrepareGate.SetResult(fixture.Client.Plan);
        await prepare;
        Assert.False(fixture.Vm.HasDeploymentPlan);
        Assert.Equal(0, fixture.Client.Starts);
    }

    [Fact]
    public async Task InventoryRefreshRetainsDraftSelectionAndKnownFailure()
    {
        var fixture = new Fixture();
        fixture.Client.CurrentDraft = Draft with { Status = "failed", JobId = "job" };
        await fixture.Vm.RefreshDraftsAsync();
        fixture.Vm.SelectProject(fixture.Vm.ProjectRows[0].Stage);
        fixture.Operations.ApplyRefreshedOverview(FactoryNetworkFixture.Gha, Overview("dev", "stage"));
        var stage = fixture.Vm.ProjectRows[0].Stage;
        Assert.True(stage.IsSelected);
        Assert.True(stage.IsFailure);
        Assert.False(stage.IsActive);
        Assert.True(stage.HasTerminal);
    }

    [Fact]
    public async Task PollingFailureStopsAutomaticRequestsUntilExplicitReload()
    {
        var fixture = new Fixture();
        fixture.Client.CurrentDraft = Draft with { Status = "running", JobId = "job" };
        await fixture.Vm.RefreshDraftsAsync();
        Assert.True(fixture.Vm.CanPollDrafts);
        fixture.Client.FailList = true;
        await fixture.Vm.RefreshDraftsAsync();
        Assert.False(fixture.Vm.CanPollDrafts);
        Assert.Contains("Status unavailable", fixture.Vm.ErrorMessage);
        fixture.Client.FailList = false;
        await fixture.Vm.RefreshDraftsAsync();
        Assert.True(fixture.Vm.CanPollDrafts);
    }

    [Fact]
    public async Task ApiConnectionChangeRequiresAnotherReview()
    {
        var fixture = new Fixture();
        await fixture.Vm.RefreshDraftsAsync();
        await fixture.Vm.DeployAsync(fixture.Vm.ProjectRows[0].Stage);
        fixture.Connection.Current = new("http://127.0.0.1:9999", "changed");
        await fixture.Vm.ConfirmDeploymentAsync();
        Assert.Equal(0, fixture.Client.Starts);
        Assert.Contains("connection changed", fixture.Vm.ErrorMessage);
    }

    [Fact]
    public async Task ExistingObservedTargetPreventsPlanning()
    {
        var fixture = new Fixture();
        fixture.Operations.ApplyRefreshedOverview(FactoryNetworkFixture.Gha, Overview("dev", "stage"));
        await fixture.Vm.DeployAsync(fixture.Vm.ProjectRows[0].Dev);
        Assert.Equal(0, fixture.Client.Plans);
        Assert.Equal(0, fixture.Client.Starts);
    }

    [Theory]
    [InlineData("draft", false, "#555C66", false, false)]
    [InlineData("queued", false, "#35C878", true, false)]
    [InlineData("running", false, "#35C878", true, false)]
    [InlineData("submitted", false, "#35C878", true, false)]
    [InlineData("failed", false, "#F05252", false, false)]
    [InlineData("interrupted", false, "#F05252", false, false)]
    [InlineData("running", true, "#35C878", true, false)]
    [InlineData("submitted", true, "#409EFF", true, true)]
    [InlineData("failed", true, "#F05252", false, false)]
    public void DeploymentLightsDistinguishJobProgressFromObservedActivity(
        string status, bool observed, string color, bool pulse, bool active)
    {
        var row = Assert.Single(ProjectEnvironmentCardViewModel.BuildRows(
            observed ? Overview("dev", "stage") : Overview("dev"), [Draft with { Status = status }]));
        Assert.Equal(color, row.Stage.StatusColor);
        Assert.Equal(pulse, row.Stage.IsStatusPulsing);
        Assert.Equal(active, row.Stage.IsActive);
        Assert.Equal(observed, row.Stage.IsDeployed);
        Assert.Equal(!observed, row.Stage.IsDraft);
    }

    [Fact]
    public void SavedDraftSurvivesUnavailableInventoryWithoutInventingAnObservedSource()
    {
        var row = Assert.Single(ProjectEnvironmentCardViewModel.BuildRows(null, [Draft]));
        Assert.True(row.Dev.IsPlaceholder);
        Assert.True(row.Stage.IsDraft);
        Assert.False(row.Stage.IsDeployed);
        Assert.False(row.Stage.HasResourceGroupLink);
    }

    [Fact]
    public void StageToProdUsesTheSameDraftRendering()
    {
        var row = Assert.Single(ProjectEnvironmentCardViewModel.BuildRows(Overview("stage"),
            [Draft with { SourceEnvironment = "stage", TargetEnvironment = "prod" }]));
        Assert.True(row.Stage.IsDeployed);
        Assert.True(row.Prod.IsDraft);
        Assert.Equal("Prod", row.Prod.EnvironmentLabel);
    }

    [Fact]
    public async Task FailedRequestSurfacesErrorAndDoesNotInventADraft()
    {
        var fixture = new Fixture();
        fixture.Client.FailPlan = true;
        await fixture.Vm.DeployAsync(fixture.Vm.ProjectRows[0].Dev);
        Assert.Contains("Draft cannot be saved", fixture.Vm.ErrorMessage);
        Assert.True(fixture.Vm.ProjectRows[0].Stage.IsPlaceholder);
        Assert.Equal(0, fixture.Client.Starts);
    }

    [Theory]
    [InlineData(false)]
    [InlineData(true)]
    public async Task PatchChoiceTransfersToDraftAndReviewedLaunch(bool patch)
    {
        var fixture = new Fixture();
        Assert.False(fixture.Vm.ProjectRows[0].Dev.Patch);
        fixture.Vm.ProjectRows[0].Dev.Patch = patch;
        await fixture.Vm.DeployAsync(fixture.Vm.ProjectRows[0].Dev);
        Assert.Equal(patch, fixture.Client.PlannedPatch);
        Assert.Equal(patch, fixture.Vm.ProjectRows[0].Stage.Patch);
        await fixture.Vm.DeployAsync(fixture.Vm.ProjectRows[0].Stage);
        Assert.Equal(patch, fixture.Client.PreparedPatch);
        Assert.True(fixture.Vm.CanConfirmDeployment);
        await fixture.Vm.ConfirmDeploymentAsync();
        Assert.Equal(patch, fixture.Terminal.OpenedDraft?.Patch);
    }

    [Fact]
    public async Task EditingPatchInvalidatesConsentAndRequiresFreshReview()
    {
        var fixture = new Fixture();
        await fixture.Vm.RefreshDraftsAsync();
        await fixture.Vm.DeployAsync(fixture.Vm.ProjectRows[0].Stage);
        fixture.Vm.ProjectRows[0].Stage.Patch = true;
        Assert.False(fixture.Vm.HasDeploymentPlan);
        await fixture.Vm.ConfirmDeploymentAsync();
        Assert.Equal(0, fixture.Client.Starts);
        await fixture.Vm.DeployAsync(fixture.Vm.ProjectRows[0].Stage);
        Assert.True(fixture.Client.PreparedPatch);
        Assert.True(fixture.Vm.CanConfirmDeployment);
    }

    [Fact]
    public async Task EditingPatchWhilePreparingDiscardsLateConsent()
    {
        var fixture = new Fixture();
        fixture.Client.PrepareGate = new(TaskCreationOptions.RunContinuationsAsynchronously);
        await fixture.Vm.RefreshDraftsAsync();
        var prepare = fixture.Vm.DeployAsync(fixture.Vm.ProjectRows[0].Stage);
        fixture.Vm.ProjectRows[0].Stage.Patch = true;
        fixture.Client.PrepareGate.SetResult(fixture.Client.Plan);
        await prepare;
        Assert.False(fixture.Vm.HasDeploymentPlan);
        Assert.Equal(0, fixture.Client.Starts);
    }

    [Fact]
    public async Task UnknownInstalledVersionShowsBackendBlockersWithoutInventingAnOlderDefault()
    {
        var fixture = new Fixture();
        fixture.Client.VersionBlockers = ["Saved factory version is unknown; inspect the installed source."];
        await fixture.Vm.RefreshDraftsAsync();
        Assert.Empty(fixture.Vm.ProjectRows[0].Dev.FactoryVersion);
        Assert.Contains("Saved factory version is unknown", fixture.Vm.FactoryVersionWarnings);
        fixture.Vm.ProjectRows[0].Dev.FactoryVersion = "main";
        fixture.Client.VersionBlockers = ["Selected source must be fetched."];
        await fixture.Vm.RefreshDraftsAsync();
        Assert.Equal("main", fixture.Vm.ProjectRows[0].Dev.FactoryVersion);
        Assert.Contains("must be fetched", fixture.Vm.FactoryVersionWarnings);
    }

    [Fact]
    public async Task CardsInheritSavedFactoryVersionAndDraftOverrideWithoutDowngrade()
    {
        var fixture = new Fixture();
        fixture.Client.FactoryVersion = Version("2.134", "release/v2.134");
        fixture.Client.CurrentDraft = Draft with { RequestedVersion = "125", Branch = "release/v1.25", ResolvedRef = "saved-ref" };
        await fixture.Vm.RefreshDraftsAsync();
        Assert.Equal("2.134", fixture.Vm.ProjectRows[0].Dev.FactoryVersion);
        Assert.Equal("125", fixture.Vm.ProjectRows[0].Stage.FactoryVersion);
        Assert.Equal("release/v2.134", fixture.Vm.ProjectRows[0].Dev.SavedTemplateBranch);
        Assert.Equal("release/v1.25", fixture.Vm.ProjectRows[0].Stage.SavedTemplateBranch);
        await fixture.Vm.DeployAsync(fixture.Vm.ProjectRows[0].Stage);
        Assert.Equal("125", fixture.Client.PreparedVersion);
        Assert.True(fixture.Vm.CanConfirmDeployment);
        Assert.Equal(0, fixture.Client.Starts);
    }

    [Fact]
    public async Task UneditedSourceVersionRefreshesEvenWhenDraftListIsUnchanged()
    {
        var fixture = new Fixture();
        fixture.Client.FactoryVersion = Version("125", "release/v1.25");
        await fixture.Vm.RefreshDraftsAsync();
        fixture.Client.FactoryVersion = Version("2.134", "release/v2.134");
        await fixture.Vm.RefreshDraftsAsync();
        Assert.Equal("2.134", fixture.Vm.ProjectRows[0].Dev.FactoryVersion);
        fixture.Vm.ProjectRows[0].Dev.FactoryVersion = "";
        fixture.Client.FactoryVersion = Version("main", "main");
        await fixture.Vm.RefreshDraftsAsync();
        Assert.Empty(fixture.Vm.ProjectRows[0].Dev.FactoryVersion);
        Assert.True(fixture.Vm.ProjectRows[0].Dev.HasVersionEdit);
        await fixture.Vm.UpdateAsync(fixture.Vm.ProjectRows[0].Dev);
        Assert.Null(fixture.Client.PlannedVersion);
        Assert.Null(fixture.Client.PreparedVersion);
    }

    [Theory]
    [InlineData("125", "release/v1.25")]
    [InlineData("main", "main")]
    public async Task ReviewedBranchAndRefComeFromBackendNotDevelopmentBranch(string requested, string branch)
    {
        var fixture = new Fixture();
        fixture.Client.Plan = fixture.Client.Plan with { RequestedVersion = requested, Branch = branch, ResolvedRef = "reviewed-ref" };
        await fixture.Vm.RefreshDraftsAsync();
        fixture.Vm.ProjectRows[0].Stage.FactoryVersion = requested;
        await fixture.Vm.DeployAsync(fixture.Vm.ProjectRows[0].Stage);
        Assert.Equal(branch, fixture.Vm.DeploymentTemplateBranch);
        Assert.Equal("reviewed-ref", fixture.Vm.DeploymentTemplateRef);
    }

    [Fact]
    public async Task VersionEditRevokesReviewAndIsSentToNextPrepare()
    {
        var fixture = new Fixture();
        await fixture.Vm.RefreshDraftsAsync();
        var card = fixture.Vm.ProjectRows[0].Stage;
        card.FactoryVersion = "125";
        await fixture.Vm.DeployAsync(card);
        Assert.Equal("125", fixture.Client.PreparedVersion);
        Assert.True(fixture.Vm.CanConfirmDeployment);
        card.FactoryVersion = "main";
        Assert.False(fixture.Vm.HasDeploymentPlan);
        await fixture.Vm.ConfirmDeploymentAsync();
        Assert.Equal(0, fixture.Client.Starts);
        await fixture.Vm.DeployAsync(card);
        Assert.Equal("main", fixture.Client.PreparedVersion);
    }

    [Fact]
    public async Task VersionChangeDuringConfirmationConnectionCheckNeverStarts()
    {
        var fixture = new Fixture();
        await fixture.Vm.RefreshDraftsAsync();
        await fixture.Vm.DeployAsync(fixture.Vm.ProjectRows[0].Stage);
        fixture.Connection.Gate = new(TaskCreationOptions.RunContinuationsAsynchronously);
        var confirming = fixture.Vm.ConfirmDeploymentAsync();
        fixture.Vm.ProjectRows[0].Stage.FactoryVersion = "125";
        fixture.Connection.Gate.SetResult(fixture.Connection.Current);
        await confirming;
        Assert.Equal(0, fixture.Client.Starts);
        Assert.Contains("choice changed", fixture.Vm.ErrorMessage);
    }

    [Fact]
    public async Task VersionChangeDuringPrepareDiscardsLateReview()
    {
        var fixture = new Fixture();
        fixture.Client.PrepareGate = new(TaskCreationOptions.RunContinuationsAsynchronously);
        await fixture.Vm.RefreshDraftsAsync();
        var preparing = fixture.Vm.DeployAsync(fixture.Vm.ProjectRows[0].Stage);
        fixture.Vm.ProjectRows[0].Stage.FactoryVersion = "125";
        fixture.Client.PrepareGate.SetResult(fixture.Client.Plan);
        await preparing;
        Assert.False(fixture.Vm.HasDeploymentPlan);
        await fixture.Vm.ConfirmDeploymentAsync();
        Assert.Equal(0, fixture.Client.Starts);
    }

    [Fact]
    public async Task UnsavedVersionSurvivesInventoryAndDraftPollingButNotScopeChange()
    {
        var fixture = new Fixture();
        await fixture.Vm.RefreshDraftsAsync();
        fixture.Vm.ProjectRows[0].Dev.FactoryVersion = "3.142";
        fixture.Vm.ProjectRows[0].Stage.FactoryVersion = "main";
        fixture.Vm.ProjectRows[0].Stage.Patch = true;
        fixture.Operations.ApplyRefreshedOverview(FactoryNetworkFixture.Gha, Overview("dev"));
        Assert.Equal("3.142", fixture.Vm.ProjectRows[0].Dev.FactoryVersion);
        fixture.Client.CurrentDraft = fixture.Client.CurrentDraft with { Message = "Refreshed" };
        await fixture.Vm.RefreshDraftsAsync();
        Assert.Equal("main", fixture.Vm.ProjectRows[0].Stage.FactoryVersion);
        Assert.True(fixture.Vm.ProjectRows[0].Stage.Patch);
        fixture.Wizard.SetValue("_save_folder", FactoryNetworkFixture.Ado);
        fixture.Operations.ApplyRefreshedOverview(FactoryNetworkFixture.Ado, Overview("dev"));
        Assert.Empty(fixture.Vm.ProjectRows[0].Dev.FactoryVersion);
        Assert.False(fixture.Vm.ProjectRows[0].Dev.HasVersionEdit);
    }

    [Fact]
    public async Task TemporaryInventoryAbsenceAndTerminalStatusDoNotDiscardUnsavedVersion()
    {
        var fixture = new Fixture();
        await fixture.Vm.RefreshDraftsAsync();
        fixture.Vm.ProjectRows[0].Dev.FactoryVersion = "2.134";
        fixture.Vm.ProjectRows[0].Stage.FactoryVersion = "main";
        fixture.Operations.ApplyRefreshedOverview(FactoryNetworkFixture.Gha, Overview());
        fixture.Operations.ApplyRefreshedOverview(FactoryNetworkFixture.Gha, Overview("dev"));
        Assert.Equal("2.134", fixture.Vm.ProjectRows[0].Dev.FactoryVersion);
        fixture.Client.CurrentDraft = Draft with { Status = "failed", JobId = "job" };
        await fixture.Vm.RefreshDraftsAsync();
        Assert.Equal("main", fixture.Vm.ProjectRows[0].Stage.FactoryVersion);
        Assert.False(fixture.Vm.ProjectRows[0].Stage.CanEditPatch);
        Assert.True(fixture.Vm.ProjectRows[0].Stage.CanReviewOutcome);
        Assert.Equal(0, fixture.Client.Starts);
    }

    [Fact]
    public void NativeCardsOfferVersionBeforeActionsAndConcealExactReferences()
    {
        var card = System.Xml.Linq.XDocument.Load(Path.Combine(AppContext.BaseDirectory, "Assets", "ProjectEnvironmentCardView.xaml"));
        var entry = card.Descendants().Single(element => element.Attribute("AutomationId")?.Value == "ProjectFactoryVersion");
        Assert.Equal("{Binding FactoryVersion, Mode=TwoWay}", entry.Attribute("Text")?.Value);
        Assert.Equal("{Binding CanEditPatch}", entry.Attribute("IsEnabled")?.Value);
        Assert.All(card.Descendants().Where(element => element.Attribute("Value")?.Value == "{Binding SavedTemplateRef}"),
            element => Assert.Equal("True", element.Attribute("Conceal")?.Value));
        var page = System.Xml.Linq.XDocument.Load(Path.Combine(AppContext.BaseDirectory, "Assets", "AiFactoryPage.xaml"));
        var reference = page.Descendants().Single(element => element.Attribute("AutomationId")?.Value == "ProjectDeploymentTemplateRef");
        Assert.Equal("True", reference.Attribute("Conceal")?.Value);
        Assert.Equal("{Binding DeploymentTemplateRef}", reference.Attribute("Value")?.Value);
    }

    [Fact]
    public async Task DifferentVersionWithPatchOffRemainsBlockedAndNeverSilentlyEnablesPatch()
    {
        var fixture = new Fixture();
        fixture.Client.Plan = fixture.Client.Plan with
        {
            CanExecute = false,
            Blockers = ["Selected template version differs from installed code. Upgrade the factory first or enable Patch."]
        };
        await fixture.Vm.RefreshDraftsAsync();
        fixture.Vm.ProjectRows[0].Stage.FactoryVersion = "125";
        await fixture.Vm.DeployAsync(fixture.Vm.ProjectRows[0].Stage);
        Assert.False(fixture.Client.PreparedPatch);
        Assert.Equal("125", fixture.Client.PreparedVersion);
        Assert.Contains("Upgrade the factory first or enable Patch", fixture.Vm.DeploymentBlockers);
        Assert.False(fixture.Vm.CanConfirmDeployment);
        await fixture.Vm.ConfirmDeploymentAsync();
        Assert.Equal(0, fixture.Client.Starts);
        Assert.False(fixture.Vm.ProjectRows[0].Stage.Patch);
        Assert.Equal("125", fixture.Vm.ProjectRows[0].Stage.FactoryVersion);
    }

    [Fact]
    public async Task UpdateSendsIndependentVersionAndPatchWithoutPromotion()
    {
        var fixture = new Fixture();
        fixture.Vm.ProjectRows[0].Dev.FactoryVersion = "125";
        fixture.Vm.ProjectRows[0].Dev.Patch = true;
        await fixture.Vm.UpdateAsync(fixture.Vm.ProjectRows[0].Dev);
        Assert.Equal("125", fixture.Client.PlannedVersion);
        Assert.Equal("125", fixture.Client.PreparedVersion);
        Assert.Equal("dev", fixture.Client.CurrentDraft.TargetEnvironment);
        Assert.Equal("update", fixture.Client.CurrentDraft.Operation);
        Assert.True(fixture.Vm.CanConfirmDeployment);
        Assert.Equal(0, fixture.Client.Starts);
    }

    [Fact]
    public async Task PatchChoiceSurvivesInventoryRefreshButNotFactorySwitch()
    {
        var fixture = new Fixture();
        await fixture.Vm.RefreshDraftsAsync();
        fixture.Vm.ProjectRows[0].Stage.Patch = true;
        await fixture.Vm.DeployAsync(fixture.Vm.ProjectRows[0].Stage);
        fixture.Operations.ApplyRefreshedOverview(FactoryNetworkFixture.Gha, Overview("dev"));
        Assert.True(fixture.Vm.ProjectRows[0].Stage.Patch);
        Assert.True(fixture.Vm.CanConfirmDeployment);
        fixture.Wizard.SetValue("_save_folder", FactoryNetworkFixture.Ado);
        fixture.Operations.ApplyRefreshedOverview(FactoryNetworkFixture.Ado, Overview("dev"));
        Assert.False(fixture.Vm.ProjectRows[0].Dev.Patch);
        Assert.False(fixture.Vm.HasDeploymentPlan);
    }

    [Theory]
    [InlineData("dev", false)]
    [InlineData("dev", true)]
    [InlineData("stage", false)]
    [InlineData("stage", true)]
    [InlineData("prod", false)]
    [InlineData("prod", true)]
    public async Task UpdateReviewsSameEnvironmentAndUsesPatchWithoutPromoting(string environment, bool patch)
    {
        var fixture = new Fixture();
        var state = fixture.Wizard.State.ToJsonString();
        fixture.Operations.ApplyRefreshedOverview(FactoryNetworkFixture.Gha, Overview(environment));
        var card = Card(fixture, environment);
        card.Patch = patch;
        await fixture.Vm.UpdateAsync(card);
        Assert.Equal("update", fixture.Client.CurrentDraft.Operation);
        Assert.Equal(environment, fixture.Client.CurrentDraft.SourceEnvironment);
        Assert.Equal(environment, fixture.Client.CurrentDraft.TargetEnvironment);
        Assert.Equal(patch, fixture.Client.PreparedPatch);
        Assert.True(Card(fixture, environment).CanSubmitDraft);
        Assert.False(Card(fixture, environment).ShowDeployButton);
        Assert.True(fixture.Vm.CanConfirmDeployment);
        Assert.Equal("Confirm and update", fixture.Vm.ConfirmDeploymentText);
        Assert.Equal(0, fixture.Client.Starts);
        await fixture.Vm.ConfirmDeploymentAsync();
        Assert.Equal(1, fixture.Client.Starts);
        Assert.Equal(environment, fixture.Terminal.OpenedDraft?.TargetEnvironment);
        Assert.Equal("#35C878", Card(fixture, environment).StatusColor);
        Assert.False(Card(fixture, environment).CanUpdate);
        Assert.Equal(state, fixture.Wizard.State.ToJsonString());
    }

    [Fact]
    public async Task CancelledUpdateCanBeReviewedAgainWithoutAnotherDraft()
    {
        var fixture = new Fixture();
        await fixture.Vm.UpdateAsync(fixture.Vm.ProjectRows[0].Dev);
        fixture.Vm.DismissDeployment();
        await fixture.Vm.RefreshDraftsAsync();
        Assert.True(fixture.Vm.ProjectRows[0].Dev.CanUpdate);
        await fixture.Vm.UpdateAsync(fixture.Vm.ProjectRows[0].Dev);
        Assert.Equal(1, fixture.Client.Plans);
        Assert.Equal(2, fixture.Client.Prepares);
        Assert.Equal(0, fixture.Client.Starts);
        Assert.True(fixture.Vm.CanConfirmDeployment);
    }

    [Fact]
    public async Task PendingUpdateDoesNotTurnPlanToStageIntoAnUpdate()
    {
        var fixture = new Fixture();
        await fixture.Vm.UpdateAsync(fixture.Vm.ProjectRows[0].Dev);
        await fixture.Vm.DeployAsync(fixture.Vm.ProjectRows[0].Dev);
        Assert.Equal("deploy", fixture.Client.CurrentDraft.Operation);
        Assert.Equal("stage", fixture.Client.CurrentDraft.TargetEnvironment);
        Assert.True(fixture.Vm.ProjectRows[0].Stage.IsDraft);
        Assert.Equal(1, fixture.Client.Prepares);
        Assert.Equal(0, fixture.Client.Starts);
    }

    [Theory]
    [InlineData("running", null)]
    [InlineData("failed", null)]
    [InlineData("interrupted", null)]
    [InlineData("failed", "2026-09-09T12:00:00Z")]
    public async Task RunningAndFailedUpdatesCannotBeRetried(string status, string? reconciledAt)
    {
        var fixture = new Fixture();
        fixture.Client.CurrentDraft = Draft with
        {
            Operation = "update", SourceEnvironment = "dev", TargetEnvironment = "dev",
            Status = status, JobId = "old-job", ReconciledAt = reconciledAt
        };
        await fixture.Vm.RefreshDraftsAsync();
        Assert.False(fixture.Vm.ProjectRows[0].Dev.CanUpdate);
        await fixture.Vm.UpdateAsync(fixture.Vm.ProjectRows[0].Dev);
        Assert.Equal(0, fixture.Client.Plans);
        Assert.Equal(0, fixture.Client.Prepares);
        Assert.Equal(0, fixture.Client.Starts);
    }

    [Fact]
    public async Task MissingObservedUpdateTargetRevokesConfirmation()
    {
        var fixture = new Fixture();
        await fixture.Vm.UpdateAsync(fixture.Vm.ProjectRows[0].Dev);
        fixture.Operations.ApplyRefreshedOverview(FactoryNetworkFixture.Gha, Overview());
        Assert.False(fixture.Vm.ProjectRows[0].Dev.CanSubmitDraft);
        Assert.False(fixture.Vm.HasDeploymentPlan);
        await fixture.Vm.ConfirmDeploymentAsync();
        Assert.Equal(0, fixture.Client.Starts);
    }

    [Theory]
    [InlineData("failed")]
    [InlineData("interrupted")]
    public async Task ReconciliationNeedsExplicitAcknowledgementAndNeverRetriesOrClearsFailure(string status)
    {
        var fixture = new Fixture();
        fixture.Client.CurrentDraft = Draft with { Status = status, JobId = "failed-job" };
        fixture.Client.Plan = fixture.Client.Plan with { Command = "" };
        await fixture.Vm.RefreshDraftsAsync();
        Assert.True(fixture.Vm.ProjectRows[0].Stage.CanReviewOutcome);
        await fixture.Vm.ReviewOutcomeAsync(fixture.Vm.ProjectRows[0].Stage);
        Assert.True(fixture.Vm.IsReconciliationReview);
        Assert.True(fixture.Vm.CanConfirmDeployment);
        Assert.Equal("Acknowledge reviewed outcome", fixture.Vm.ConfirmDeploymentText);
        Assert.Equal("failed-job", fixture.Client.ReviewedJob);
        Assert.Equal(0, fixture.Client.Reconciliations);
        await fixture.Vm.ConfirmDeploymentAsync();
        Assert.Equal(1, fixture.Client.Reconciliations);
        Assert.Equal(0, fixture.Client.Starts);
        Assert.Null(fixture.Terminal.OpenedDraft);
        Assert.True(fixture.Vm.ProjectRows[0].Stage.IsFailure);
        Assert.Equal("#F05252", fixture.Vm.ProjectRows[0].Stage.StatusColor);
        Assert.True(fixture.Vm.ProjectRows[0].Stage.IsOutcomeReviewed);
        Assert.False(fixture.Vm.ProjectRows[0].Stage.CanReviewOutcome);
        Assert.False(fixture.Vm.ProjectRows[0].Stage.CanSubmitDraft);
        Assert.False(fixture.Vm.HasDeploymentPlan);
        await fixture.Vm.ConfirmDeploymentAsync();
        Assert.Equal(1, fixture.Client.Reconciliations);
    }

    [Fact]
    public async Task CancellingReconciliationLeavesFailureUnacknowledged()
    {
        var fixture = new Fixture();
        fixture.Client.CurrentDraft = Draft with { Status = "failed", JobId = "failed-job" };
        await fixture.Vm.RefreshDraftsAsync();
        await fixture.Vm.ReviewOutcomeAsync(fixture.Vm.ProjectRows[0].Stage);
        fixture.Vm.DismissDeployment();
        await fixture.Vm.ConfirmDeploymentAsync();
        Assert.Equal(0, fixture.Client.Reconciliations);
        Assert.True(fixture.Vm.ProjectRows[0].Stage.CanReviewOutcome);
    }

    [Theory]
    [InlineData(false, "2099-01-01T00:00:00Z")]
    [InlineData(true, "2000-01-01T00:00:00Z")]
    [InlineData(true, "invalid")]
    public async Task BlockedOrExpiredReconciliationCannotReleaseHold(bool executable, string expiry)
    {
        var fixture = new Fixture();
        fixture.Client.CurrentDraft = Draft with { Status = "failed", JobId = "failed-job" };
        fixture.Client.Plan = fixture.Client.Plan with { CanExecute = executable, ExpiresAt = expiry };
        await fixture.Vm.RefreshDraftsAsync();
        await fixture.Vm.ReviewOutcomeAsync(fixture.Vm.ProjectRows[0].Stage);
        await fixture.Vm.ConfirmDeploymentAsync();
        Assert.Equal(0, fixture.Client.Reconciliations);
    }

    [Fact]
    public async Task ApiConnectionChangeInvalidatesOutcomeAcknowledgement()
    {
        var fixture = new Fixture();
        fixture.Client.CurrentDraft = Draft with { Status = "failed", JobId = "failed-job" };
        await fixture.Vm.RefreshDraftsAsync();
        await fixture.Vm.ReviewOutcomeAsync(fixture.Vm.ProjectRows[0].Stage);
        fixture.Connection.Current = new("http://127.0.0.1:9999", "changed");
        await fixture.Vm.ConfirmDeploymentAsync();
        Assert.Equal(0, fixture.Client.Reconciliations);
        Assert.Contains("connection changed", fixture.Vm.ErrorMessage);
    }

    [Fact]
    public async Task LateReconciliationPreviewAfterFactorySwitchIsDiscarded()
    {
        var fixture = new Fixture();
        fixture.Client.CurrentDraft = Draft with { Status = "failed", JobId = "failed-job" };
        fixture.Client.PrepareGate = new(TaskCreationOptions.RunContinuationsAsynchronously);
        await fixture.Vm.RefreshDraftsAsync();
        var prepare = fixture.Vm.ReviewOutcomeAsync(fixture.Vm.ProjectRows[0].Stage);
        fixture.Wizard.SetValue("_save_folder", FactoryNetworkFixture.Ado);
        fixture.Operations.ApplyRefreshedOverview(FactoryNetworkFixture.Ado, Overview("dev"));
        fixture.Client.PrepareGate.SetResult(fixture.Client.Plan);
        await prepare;
        Assert.False(fixture.Vm.HasDeploymentPlan);
        Assert.Equal(0, fixture.Client.Reconciliations);
    }

    [Theory]
    [InlineData("draft", null, null)]
    [InlineData("running", "job", null)]
    [InlineData("submitted", "job", null)]
    [InlineData("failed", null, null)]
    [InlineData("failed", "job", "2026-09-09T12:00:00Z")]
    public async Task OnlyUnreconciledFailuresWithAJobCanBeReviewed(string status, string? job, string? reconciledAt)
    {
        var fixture = new Fixture();
        fixture.Client.CurrentDraft = Draft with { Status = status, JobId = job, ReconciledAt = reconciledAt };
        await fixture.Vm.RefreshDraftsAsync();
        await fixture.Vm.ReviewOutcomeAsync(fixture.Vm.ProjectRows[0].Stage);
        Assert.False(fixture.Vm.HasDeploymentPlan);
        Assert.Null(fixture.Client.ReviewedJob);
    }

    private static ProjectEnvironmentCardViewModel Card(Fixture fixture, string environment) =>
        environment switch
        {
            "dev" => fixture.Vm.ProjectRows[0].Dev,
            "stage" => fixture.Vm.ProjectRows[0].Stage,
            _ => fixture.Vm.ProjectRows[0].Prod
        };

    private static ProjectDeploymentDraft Draft => new()
    {
        Id = "draft-001-stage", ProjectNumber = "001", SourceEnvironment = "dev", TargetEnvironment = "stage",
        Status = "draft", Route = "gha", ScriptPath = @"C:\factory\GH-update-aifactory-and-run-project.sh"
    };

    private static FactoryVersionSelection Version(string requested, string branch) => new()
    {
        RequestedVersion = requested, Branch = branch, ResolvedRef = "reviewed-ref"
    };

    private static OperationsOverview Overview(params string[] environments) => new()
    {
        ResourceInventory = new() { Source = "cached" },
        Projects = [new FactoryProject
        {
            ProjectNumber = "001", DisplayName = "Project 001",
            Environments = environments.Select(environment => new ProjectEnvironment
            {
                Environment = environment, ResourceGroup = $"rg-001-{environment}", Status = "active"
            }).ToArray()
        }]
    };

    private sealed class Fixture
    {
        public WizardSession Wizard { get; }
        public OperationsSession Operations { get; }
        public Client Client { get; } = new();
        public Connection Connection { get; } = new();
        public Terminal Terminal { get; } = new();
        public AiFactoryViewModel Vm { get; }
        public bool CatalogScope;
        public Fixture()
        {
            var api = new FactoryNetworkFixture().Api;
            Wizard = new(api);
            Wizard.ReplaceState(new() { ["_save_folder"] = FactoryNetworkFixture.Gha, ["unsaved"] = "preserve" });
            Operations = new(api, Wizard);
            Operations.ApplyRefreshedOverview(FactoryNetworkFixture.Gha, Overview("dev"));
            Vm = new(Operations, Client, Connection, terminal: Terminal, isCatalogScope: _ => CatalogScope);
        }
    }

    private sealed class Terminal : IDeploymentTerminalSession
    {
        public string? OpenedFolder;
        public ProjectDeploymentDraft? OpenedDraft;
        public bool Fail;
        public Task OpenAsync(string folder, ProjectDeploymentDraft draft)
        {
            OpenedFolder = folder;
            OpenedDraft = draft;
            return Fail ? Task.FromException(new IOException("Terminal unavailable")) : Task.CompletedTask;
        }
    }

    private sealed class Connection : IAiFactoryConnectionProvider
    {
        public AiFactoryConnection Current { get; set; } = new("http://127.0.0.1:8765", "test");
        public TaskCompletionSource<AiFactoryConnection>? Gate;
        public Task<AiFactoryConnection> GetConnectionAsync(CancellationToken cancellationToken = default) =>
            Gate?.Task ?? Task.FromResult(Current);
    }

    private sealed class Client : IProjectDeploymentClient
    {
        public int Lists, Plans, Prepares, Starts, Reconciliations;
        public bool PlannedPatch, PreparedPatch;
        public string? PlannedVersion, PreparedVersion;
        public string? ReviewedJob;
        public bool FailPlan, FailList;
        public ProjectDeploymentDraft CurrentDraft = Draft;
        public FactoryVersionSelection? FactoryVersion;
        public IReadOnlyList<string> VersionBlockers = [];
        public TaskCompletionSource<ProjectDeploymentPlan>? PrepareGate;
        public ProjectDeploymentPlan Plan = new()
        {
            ConfirmationId = "confirmation", CanExecute = true, Command = "bash reviewed-script.sh",
            WorkingDirectory = @"C:\factory", ExpiresAt = "2099-01-01T00:00:00Z"
        };
        public Task<ProjectDeploymentList> GetProjectDeploymentsAsync(string folder, CancellationToken cancellationToken = default)
        {
            Lists++;
            return FailList ? Task.FromException<ProjectDeploymentList>(new InvalidOperationException("Status unavailable"))
                : Task.FromResult(new ProjectDeploymentList
                {
                    Drafts = [CurrentDraft], VersionSelection = FactoryVersion, VersionBlockers = VersionBlockers
                });
        }
        public Task<ProjectDeploymentDraft> PlanProjectDeploymentAsync(string folder, string projectNumber,
            string sourceEnvironment, string targetEnvironment, bool patch = false, string operation = "deploy",
            CancellationToken cancellationToken = default, string? factoryVersion = null)
        {
            Plans++;
            PlannedPatch = patch;
            PlannedVersion = factoryVersion;
            if (!FailPlan)
                CurrentDraft = Draft with
                {
                    Id = $"draft-{Plans}", ProjectNumber = projectNumber, SourceEnvironment = sourceEnvironment,
                    TargetEnvironment = targetEnvironment, Patch = patch, Operation = operation
                };
            return FailPlan ? Task.FromException<ProjectDeploymentDraft>(new InvalidOperationException("Draft cannot be saved"))
                : Task.FromResult(CurrentDraft);
        }
        public Task<ProjectDeploymentPlan> PrepareProjectDeploymentAsync(string folder, string draftId,
            bool patch = false, CancellationToken cancellationToken = default, string? factoryVersion = null)
        {
            Prepares++;
            PreparedPatch = patch;
            PreparedVersion = factoryVersion;
            return PrepareGate?.Task ?? Task.FromResult(Plan);
        }
        public Task<ProjectDeploymentDraft> StartProjectDeploymentAsync(string folder, string confirmationId,
            CancellationToken cancellationToken = default)
        {
            Starts++;
            CurrentDraft = CurrentDraft with { Status = "running", JobId = "job", Patch = PreparedPatch };
            return Task.FromResult(CurrentDraft);
        }
        public Task<ProjectDeploymentPlan> PrepareProjectReconciliationAsync(string folder, string jobId,
            CancellationToken cancellationToken = default)
        {
            ReviewedJob = jobId;
            return PrepareGate?.Task ?? Task.FromResult(Plan);
        }
        public Task<ProjectDeploymentDraft> ReconcileProjectDeploymentAsync(string folder, string confirmationId,
            CancellationToken cancellationToken = default)
        {
            Reconciliations++;
            CurrentDraft = CurrentDraft with { ReconciledAt = "2026-09-09T12:00:00Z" };
            return Task.FromResult(CurrentDraft);
        }
    }
}

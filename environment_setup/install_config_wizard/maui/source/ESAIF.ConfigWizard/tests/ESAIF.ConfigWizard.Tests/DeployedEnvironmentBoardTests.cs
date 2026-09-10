using ESAIF.ConfigWizard.ViewModels;
using ESAIF.DomainLayer.Operations;
using ESAIF.ConfigWizard.Services;

namespace ESAIF.ConfigWizard.Tests;

public sealed class DeployedEnvironmentBoardTests
{
    [Theory]
    [InlineData("active", "rg", true)]
    [InlineData("Active", "rg", true)]
    [InlineData("inactive", "rg", false)]
    [InlineData("Unknown", "rg", false)]
    [InlineData("active", null, false)]
    public void OnlyObservedActiveEnvironmentGetsBluePulse(string status, string? group, bool active)
    {
        var environment = Environment("dev", group) with { Status = status };
        var card = new ProjectEnvironmentCardViewModel(Project("001", environment), environment);
        Assert.Equal(active, card.IsActive);
        Assert.Equal(active ? "#409EFF" : "#555C66", card.StatusColor);
        card.SetSelected(true);
        Assert.Equal(group is not null, card.IsSelected);
    }

    [Fact]
    public void SelectingEnvironmentHighlightsOnlyThatCardAndNeverChangesTheConfiguration()
    {
        var fixture = new FactoryNetworkFixture();
        var wizard = new WizardSession(fixture.Api);
        wizard.ReplaceState(new() { ["_save_folder"] = FactoryNetworkFixture.Gha });
        var operations = new OperationsSession(fixture.Api, wizard);
        var overview = Overview(
            Project("001", Environment("dev", "gh-project001-sdc-dev-001")),
            Project("002", Environment("prod", "gh-project002-sdc-prod-001")));
        operations.ApplyRefreshedOverview(FactoryNetworkFixture.Gha, overview);
        var vm = new AiFactoryViewModel(operations, fixture.Api);
        var before = wizard.State.ToJsonString();
        vm.SelectProject(vm.ProjectRows[0].Dev);
        Assert.True(vm.ProjectRows[0].Dev.IsSelected);
        vm.SelectProject(vm.ProjectRows[0].Stage);
        Assert.True(vm.ProjectRows[0].Dev.IsSelected);
        Assert.False(vm.ProjectRows[0].Stage.IsSelected);
        vm.SelectProject(vm.ProjectRows[1].Prod);
        Assert.False(vm.ProjectRows[0].Dev.IsSelected);
        Assert.True(vm.ProjectRows[1].Prod.IsSelected);
        operations.ApplyRefreshedOverview(FactoryNetworkFixture.Gha, overview);
        Assert.True(vm.ProjectRows[1].Prod.IsSelected);
        Assert.Equal(before, wizard.State.ToJsonString());
        wizard.SetValue("_save_folder", FactoryNetworkFixture.Ado);
        operations.ApplyRefreshedOverview(FactoryNetworkFixture.Ado, overview);
        Assert.Null(vm.SelectedProject);
        Assert.All(vm.ProjectRows, row => Assert.False(row.Prod.IsSelected));
    }

    private static ProjectEnvironment Environment(string name, string? group = null) =>
        new() { Environment = name, ResourceGroup = group, Status = group is null ? "not_deployed" : "active" };

    private static FactoryProject Project(string number, params ProjectEnvironment[] environments) =>
        new() { ProjectNumber = number, DisplayName = $"Project {number}", Owner = "Owner", Environments = environments };

    private static OperationsOverview Overview(params FactoryProject[] projects) =>
        new() { Projects = projects, ResourceInventory = new() { Source = "azure", IsComplete = true } };

    [Fact]
    public void DevOnlyProjectHasOneCardAndTwoEmptyActionlessPlaceholders()
    {
        var row = Assert.Single(ProjectEnvironmentCardViewModel.BuildRows(Overview(
            Project("001", Environment("dev", "project001-dev"), Environment("stage"), Environment("prod")),
            Project("002", Environment("dev"), Environment("stage"), Environment("prod")))));
        Assert.True(row.Dev.IsDeployed);
        Assert.True(row.Stage.IsPlaceholder);
        Assert.True(row.Prod.IsPlaceholder);
        Assert.False(row.Stage.CanDeploy);
        Assert.False(row.Prod.CanDeploy);
        Assert.False(row.Stage.HasResourceGroupLink);
        Assert.Same(row.Dev.Project, row.Stage.Project);
        Assert.Same(row.Dev.Project, row.Prod.Project);
        Assert.Contains("Stage", row.Stage.PlaceholderDescription);
        Assert.Equal("Owner", row.Dev.Owner);
    }

    [Fact]
    public void RowsStayAlignedAndNumericallySortedAcrossDifferentEnvironments()
    {
        var rows = ProjectEnvironmentCardViewModel.BuildRows(Overview(
            Project("10", Environment("prod", "project010-prod")),
            Project("2", Environment("dev", "project002-dev"), Environment("test", "project002-test")),
            Project("1", Environment("stage", "project001-stage"))));
        Assert.Equal(["1", "2", "10"], rows.Select(row => row.Dev.ProjectNumber));
        Assert.True(rows[0].Dev.IsPlaceholder);
        Assert.True(rows[0].Stage.IsDeployed);
        Assert.True(rows[0].Prod.IsPlaceholder);
        Assert.True(rows[1].Dev.IsDeployed);
        Assert.True(rows[1].Stage.IsDeployed);
        Assert.Equal("stage", rows[1].Stage.Environment);
        Assert.True(rows[2].Prod.IsDeployed);
        Assert.All(rows, row => Assert.Equal(row.Dev.ProjectNumber, row.Prod.ProjectNumber));
    }

    [Fact]
    public void ExplicitGroupReferenceCountsAsDeployedEvenWithZeroResources()
    {
        var project = Project("001", new ProjectEnvironment
        {
            Environment = "dev", ResourceCount = 0,
            ResourceGroupReferences = [new() { Name = "project001-dev" }]
        });
        Assert.True(Assert.Single(ProjectEnvironmentCardViewModel.BuildRows(Overview(project))).Dev.IsDeployed);
    }

    [Fact]
    public void StatusAndResourceCountAloneCannotInventADeployedCard()
    {
        var result = ProjectEnvironmentCardViewModel.BuildRows(Overview(Project("001", new ProjectEnvironment
        {
            Environment = "dev", ResourceGroup = " ", ResourceGroups = [" "],
            ResourceGroupReferences = [new()], Status = "active", ResourceCount = 100
        })));
        Assert.Empty(result);
    }

    [Theory]
    [InlineData("mock")]
    [InlineData("local")]
    [InlineData("unavailable")]
    public void NonAzureEvidenceCannotCreateDeploymentCards(string source)
    {
        var overview = Overview(Project("001", Environment("dev", "project001-dev")));
        Assert.Empty(ProjectEnvironmentCardViewModel.BuildRows(overview with
        {
            ResourceInventory = new() { Source = source }
        }));
    }

    [Fact]
    public void CachedPartialInventoryStillShowsObservedGroupsButNotMissingOnes()
    {
        var overview = Overview(Project("001", Environment("prod", "project001-prod")));
        var row = Assert.Single(ProjectEnvironmentCardViewModel.BuildRows(overview with
        {
            ResourceInventory = new() { Source = "cached", IsComplete = false }
        }));
        Assert.True(row.Prod.IsDeployed);
        Assert.True(row.Dev.IsPlaceholder);
    }
}

using ESAIF.ConfigWizard.Services;
using ESAIF.ConfigWizard.ViewModels;
using ESAIF.DomainLayer.Configuration;
using ESAIF.DomainLayer.Operations;

namespace ESAIF.ConfigWizard.Tests;

public sealed class ProjectFilterOwnerTests
{
    [Fact]
    public async Task RowSelectionHighlightsWithoutChangingLoadedConfigurationAndSurvivesRefresh()
    {
        var fixture = new FactoryNetworkFixture();
        await fixture.Network.RefreshAsync(FactoryNetworkFixture.Ado);
        var session = new WizardSession(fixture.Api);
        var model = new ProjectsViewModel(fixture.Api, session, fixture.Api, fixture.Network);
        var before = session.State.ToJsonString();
        var selected = model.Projects[1];
        model.SelectedProject = selected;
        Assert.True(selected.IsHighlighted);
        Assert.False(model.Projects[0].IsHighlighted);
        Assert.Equal(before, session.State.ToJsonString());
        model.SelectedProject = null;
        Assert.Same(selected, model.SelectedProject);
        selected.SetVerificationUnavailable("Refresh access state");
        Assert.True(selected.IsHighlighted);
        await fixture.Network.RefreshAsync(FactoryNetworkFixture.Ado);
        Assert.Equal(selected.Path, model.SelectedProject!.Path);
        Assert.Single(model.Projects, item => item.IsHighlighted);
        Assert.Equal(before, session.State.ToJsonString());
        model.ProdEnvironment = true;
        Assert.Null(model.SelectedProject);
        model.AllEnvironments = true;
        Assert.Equal(selected.Path, model.SelectedProject!.Path);
        Assert.True(model.SelectedProject.IsHighlighted);
    }

    [Fact]
    public async Task AccessibleProjectsSortFirstAndFiltersKeepTheSameVerifiedItems()
    {
        var fixture = new FactoryNetworkFixture();
        await fixture.Network.RefreshAsync(FactoryNetworkFixture.Ado);
        var model = new ProjectsViewModel(fixture.Api, new WizardSession(fixture.Api), fixture.Api, fixture.Network);
        var first = model.Projects[0];
        first.SetVerificationUnavailable("Access expired");
        Assert.True(model.Projects[0].IsResourceGroupVerified);
        Assert.Same(first, model.Projects[^1]);
        Assert.Contains(first.FactoryScaleSet, model.FactoryChoices);
        model.SelectedFactory = first.FactoryScaleSet;
        Assert.Same(first, Assert.Single(model.Projects));
        model.SelectedFactory = null;
        Assert.Same(first, Assert.Single(model.Projects));
        model.SelectedFactory = "All AI Factories";
        Assert.Equal(2, model.Projects.Count);
        model.ProdEnvironment = true;
        Assert.Empty(model.Projects);
        model.AllEnvironments = true;
        Assert.Equal(2, model.Projects.Count);
    }

    [Fact]
    public void OwnerAndAllDeployedEnvironmentsRemainVisible()
    {
        const string sub = "11111111-1111-4111-8111-111111111111";
        var project = new ProjectSummary
        {
            ProjectNumber = "017", Owner = "owner@example.com", PlannedEnvironments = ["dev", "stage", "prod"],
            DeploymentScope = new() { PrefixResourceGroup = "gh-", SuffixResourceGroup = "-001", Region = "swedencentral", SubscriptionIds = [sub] }
        };
        var observed = new FactoryProject
        {
            ProjectNumber = "017", Owner = project.Owner,
            Environments = [
                new() { Environment = "dev", ResourceGroup = "gh-project017-sdc-dev-001" },
                new() { Environment = "stage", ResourceGroup = "gh-project017-sdc-test-001" },
                new() { Environment = "prod", ResourceGroup = "gh-project017-sdc-prod-001" }
            ]
        };
        var overview = new OperationsOverview
        {
            Factory = new() { Folder = @"C:\factory", PrefixResourceGroup = "gh-", SuffixResourceGroup = "-001", MonitoringRegions = ["swedencentral"] },
            ResourceInventory = new() { Source = "azure", IsComplete = true, Subscriptions = [sub] },
            Projects = [observed]
        };
        var item = new SavedConfigurationItemViewModel(project, @"C:\factory");
        item.UpdateDeployment(overview);
        Assert.Equal("owner@example.com", item.Owner);
        Assert.Equal("gh-001", item.FactoryScaleSet);
        Assert.Equal("Dev · Stage · Prod", item.EnvironmentStatus);
        Assert.True(item.MatchesEnvironment("Prod"));
        Assert.True(item.MatchesEnvironment("Stage"));
        Assert.True(item.MatchesEnvironment("Dev"));
        var card = new ProjectEnvironmentCardViewModel(observed, observed.Environments[0]);
        Assert.Equal(item.Owner, card.Owner);
        Assert.Equal(item.EnvironmentStatus, card.DeploymentEnvironments);
    }

    [Fact]
    public void PlannedStatusIsExplicitAndUnknownOwnerNeverDisappears()
    {
        var item = new SavedConfigurationItemViewModel(new ProjectSummary
        {
            ProjectNumber = "017", PlannedEnvironments = ["test", "dev"]
        }, @"C:\factory");
        Assert.Equal("Not specified", item.Owner);
        Assert.Equal("Planned: Dev · Stage", item.EnvironmentStatus);
        Assert.True(item.MatchesEnvironment("Stage"));
        Assert.False(item.MatchesEnvironment("Prod"));
        Assert.True(item.MatchesEnvironment("All"));
    }
}

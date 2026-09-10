using ESAIF.ConfigWizard.Services;
using ESAIF.ConfigWizard.ViewModels;
using ESAIF.DomainLayer.Configuration;
using ESAIF.DomainLayer.Operations;

namespace ESAIF.ConfigWizard.Tests;

public sealed class ProjectDeploymentPresentationTests
{
    private const string Sub = "11111111-1111-4111-8111-111111111111";
    private const string Folder = @"C:\factory";
    private static ProjectDeploymentScope Scope => new()
    {
        PrefixResourceGroup = "mrvel-1-", SuffixResourceGroup = "-007",
        Region = "swedencentral", SubscriptionIds = [Sub]
    };
    private static ProjectSummary Project(ProjectDeploymentScope? scope = null) => new()
    {
        ProjectNumber = "017", DeploymentScope = scope ?? Scope
    };
    private static OperationsOverview Overview(bool deployed = true, string source = "azure", bool complete = true) => new()
    {
        Factory = new FactorySummary
        {
            Folder = Folder, PrefixResourceGroup = "mrvel-1-", SuffixResourceGroup = "-007",
            MonitoringRegions = ["swedencentral"]
        },
        ResourceInventory = new ResourceInventorySummary
        {
            Source = source, IsComplete = complete, Subscriptions = [Sub], CollectedAt = "2026-09-08T07:30:00Z"
        },
        Projects =
        [
            new FactoryProject
            {
                ProjectNumber = "17",
                Environments =
                [
                    new ProjectEnvironment
                    {
                        Environment = "dev", ResourceGroup = deployed ? "mrvel-1-project017-sdc-dev-007" : null,
                        Status = deployed ? "active" : "not_deployed", SubscriptionId = Sub
                    }
                ]
            }
        ]
    };

    [Theory]
    [InlineData("azure")]
    [InlineData("cached")]
    public void ObservedProjectGroup_IsDeployedBlueRegardlessOfSelection(string source)
    {
        var item = new SavedConfigurationItemViewModel(Project(), Folder);
        item.UpdateDeployment(Overview(source: source));
        Assert.True(item.IsDeployed);
        Assert.Equal("Deployed", item.DeploymentLabel);
        Assert.Equal("#409EFF", item.DeploymentColor);
        Assert.False(item.IsSelected);
        item.UpdateSelection(new WizardIdentity(Folder, "017", "007"));
        Assert.True(item.IsSelected);
        Assert.True(item.IsDeployed);
        if (source == "cached")
        {
            Assert.Contains("cached", item.DeploymentDescription);
        }
    }

    [Fact]
    public void CompleteInventoryWithoutGroup_IsNotDeployedAndGray()
    {
        var status = ProjectDeploymentPresentation.FromOverview(Project(), Folder, Overview(false));
        Assert.False(status.IsDeployed);
        Assert.Equal("Not deployed", status.Label);
        Assert.Equal("#8C929C", status.Color);
    }

    [Theory]
    [InlineData("azure", false)]
    [InlineData("cached", false)]
    [InlineData("local", true)]
    [InlineData("seeded", true)]
    [InlineData("unavailable", false)]
    public void IncompleteOrNonAzureAbsence_IsUnknownNotFalseNotDeployed(string source, bool complete)
    {
        var status = ProjectDeploymentPresentation.FromOverview(Project(), Folder, Overview(false, source, complete));
        Assert.False(status.IsDeployed);
        Assert.Equal("Not checked", status.Label);
    }

    [Fact]
    public void DifferentFactoryWithSameProjectNumber_IsNotMarkedDeployed()
    {
        var variants = new[]
        {
            Scope with { PrefixResourceGroup = "gh-" }, Scope with { SuffixResourceGroup = "-001" },
            Scope with { Region = "eastus2" }, Scope with { SubscriptionIds = ["other-sub"] }
        };
        foreach (var variant in variants)
        {
            Assert.Equal("Not checked", ProjectDeploymentPresentation.FromOverview(Project(variant), Folder, Overview()).Label);
        }
        Assert.Equal("Not checked", ProjectDeploymentPresentation.FromOverview(Project(), @"C:\other", Overview()).Label);
        Assert.Equal("Not checked", ProjectDeploymentPresentation.FromOverview(new ProjectSummary { ProjectNumber = "017" }, Folder, Overview()).Label);
    }

    [Fact]
    public void SavedProjectLink_TracksObservedGroupsAndIsDisabledWhenEvidenceIsMissing()
    {
        var item = new SavedConfigurationItemViewModel(Project(), Folder);
        Assert.False(item.HasResourceGroupLink);
        item.UpdateDeployment(Overview());
        Assert.True(item.HasResourceGroupLink);
        var link = Assert.Single(item.ResourceGroupLinks);
        Assert.Contains($"/subscriptions/{Sub}/resourceGroups/mrvel-1-project017-sdc-dev-007/overview", link.Url.AbsoluteUri);
        item.UpdateDeployment(Overview(false));
        Assert.False(item.HasResourceGroupLink);
        Assert.Empty(item.ResourceGroupLinks);
        item.UpdateDeployment(null);
        Assert.False(item.HasResourceGroupLink);
    }

    [Fact]
    public void SavedProjectLinks_ExcludeOtherProjectsAndDeduplicateAcrossEnvironments()
    {
        var baseline = Overview();
        var dev = baseline.Projects[0].Environments[0];
        var stage = dev with { Environment = "stage", ResourceGroup = "mrvel-1-project017-sdc-stage-007" };
        var overview = baseline with
        {
            Projects =
            [
                baseline.Projects[0] with { Environments = [dev, stage, dev] },
                new FactoryProject
                {
                    ProjectNumber = "018",
                    Environments = [dev with { ResourceGroup = "another-project" }]
                }
            ]
        };
        var links = ProjectDeploymentPresentation.ResourceGroupLinks(Project(), Folder, overview);
        Assert.Equal(2, links.Count);
        Assert.DoesNotContain(links, link => link.Name == "another-project");
        Assert.Empty(ProjectDeploymentPresentation.ResourceGroupLinks(
            Project(Scope with { Region = "eastus2" }), Folder, overview));
        Assert.Empty(ProjectDeploymentPresentation.ResourceGroupLinks(Project(), @"C:\different", overview));
    }

    [Fact]
    public void SharedRefreshUpdatesDeploymentInPlaceAndInvalidationStopsPulse()
    {
        var item = new SavedConfigurationItemViewModel(Project(), Folder);
        item.UpdateDeployment(Overview());
        Assert.True(item.IsDeployed);
        item.UpdateDeployment(Overview(false));
        Assert.Equal("Not deployed", item.DeploymentLabel);
        Assert.False(item.IsDeployed);
        item.UpdateDeployment(null);
        Assert.Equal("Not checked", item.DeploymentLabel);
        Assert.False(item.IsDeployed);
    }
}

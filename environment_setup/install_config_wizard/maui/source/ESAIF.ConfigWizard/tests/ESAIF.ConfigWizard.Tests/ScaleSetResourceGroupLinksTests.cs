using ESAIF.ConfigWizard.Services;
using ESAIF.ConfigWizard.ViewModels;
using ESAIF.DomainLayer.Configuration;
using ESAIF.DomainLayer.Operations;

namespace ESAIF.ConfigWizard.Tests;

public sealed class ScaleSetResourceGroupLinksTests
{
    private const string Folder = @"C:\factory";
    private const string Sub = "11111111-1111-4111-8111-111111111111";
    private const string Tenant = "22222222-2222-4222-8222-222222222222";
    private static ScaleSetSummary ScaleSet => new()
    {
        ScaleSetId = "007", DeploymentScope = new ProjectDeploymentScope
        {
            PrefixResourceGroup = "mrvel-1-", SuffixResourceGroup = "-007",
            Region = "swedencentral", SubscriptionIds = [Sub]
        }
    };
    private static AzureResourceGroup Group(string environment = "dev") => new()
    {
        Name = $"mrvel-1-esml-common-sdc-{environment}-007", SubscriptionId = Sub, TenantId = Tenant,
        Id = $"/subscriptions/{Sub}/resourceGroups/mrvel-1-esml-common-sdc-{environment}-007",
        Location = "swedencentral"
    };
    private static OperationsOverview Overview => new()
    {
        Factory = new FactorySummary
        {
            Folder = Folder, PrefixResourceGroup = "mrvel-1-", SuffixResourceGroup = "-007",
            MonitoringRegions = ["swedencentral"]
        },
        ResourceInventory = new ResourceInventorySummary
        {
            Source = "azure", Subscriptions = [Sub], ResourceGroups = [Group()]
        },
        CommonResourceGroups = [Group()],
        Projects = [new FactoryProject
        {
            ProjectNumber = "017",
            Environments = [new() { ResourceGroup = "a-project-group", SubscriptionId = Sub }]
        }]
    };

    [Fact]
    public void LinkUsesObservedCommonGroupNotAProjectGroup()
    {
        var item = new SavedConfigurationItemViewModel(ScaleSet, Folder);
        item.UpdateDeployment(Overview);
        var link = Assert.Single(item.ResourceGroupLinks);
        Assert.Equal(Group().Name, link.Name);
        Assert.Equal($"https://portal.azure.com/#@{Tenant}/resource/subscriptions/{Sub}/resourceGroups/{Group().Name}/overview", link.Url.AbsoluteUri);
        Assert.True(item.HasResourceGroupLink);
        Assert.Contains("common", item.ResourceGroupLinkHint);
    }

    [Fact]
    public void MultipleEnvironmentsAreOfferedWithoutDuplicatingCommonGroup()
    {
        var links = ScaleSetResourceGroupLinks.FromOverview(ScaleSet, Folder, Overview with
        {
            CommonResourceGroups = [Group(), Group("stage"), Group(), Group("prod")]
        });
        Assert.Equal(3, links.Count);
        Assert.Contains(links, link => link.Name == Group("prod").Name);
    }

    [Fact]
    public void UnknownOtherFactoryAndOtherScaleSetNeverLinkToTheCurrentCommonGroup()
    {
        Assert.Empty(ScaleSetResourceGroupLinks.FromOverview(ScaleSet, @"C:\other", Overview));
        Assert.Empty(ScaleSetResourceGroupLinks.FromOverview(ScaleSet, Folder, null));
        Assert.Empty(ScaleSetResourceGroupLinks.FromOverview(new ScaleSetSummary { ScaleSetId = "007" }, Folder, Overview));
        Assert.Empty(ScaleSetResourceGroupLinks.FromOverview(new ScaleSetSummary
        {
            ScaleSetId = "008", DeploymentScope = ScaleSet.DeploymentScope
        }, Folder, Overview));
        Assert.Empty(ScaleSetResourceGroupLinks.FromOverview(new ScaleSetSummary
        {
            ScaleSetId = "007",
            DeploymentScope = ScaleSet.DeploymentScope! with { Region = "eastus2" }
        }, Folder, Overview));
    }

    [Fact]
    public void ExistingCacheCanRecoverMissingCommonGroupMetadataOnlyWhenUnambiguous()
    {
        var legacy = Overview with { CommonResourceGroups = [new AzureResourceGroup { Name = Group().Name }] };
        Assert.Single(ScaleSetResourceGroupLinks.FromOverview(ScaleSet, Folder, legacy));
        var ambiguous = legacy with
        {
            ResourceInventory = legacy.ResourceInventory with { ResourceGroups = [Group(), Group()] }
        };
        Assert.Empty(ScaleSetResourceGroupLinks.FromOverview(ScaleSet, Folder, ambiguous));
    }

    [Theory]
    [InlineData(200, true, true)]
    [InlineData(200, false, false)]
    [InlineData(202, true, false)]
    [InlineData(204, true, false)]
    [InlineData(301, true, false)]
    [InlineData(403, false, false)]
    [InlineData(404, false, false)]
    [InlineData(null, false, false)]
    public void OnlyValidatedHttp200TurnsOnTheBluePulse(int? httpStatus, bool verified, bool expected)
    {
        var item = new SavedConfigurationItemViewModel(ScaleSet, Folder);
        item.UpdateDeployment(Overview);
        item.UpdateSelection(new WizardIdentity(Folder, "017", "007"));
        Assert.True(item.IsSelected);
        Assert.False(item.IsResourceGroupVerified); // Inventory/selection alone never lights the indicator.
        item.SetVerificationPending();
        Assert.False(item.IsResourceGroupVerified);
        item.ApplyVerification(new ScaleSetResourceGroupVerification
        {
            ScaleSetId = "007", CheckedAt = "2026-09-08T10:00:00Z", Message = "Checked",
            Checks = [new ResourceGroupHttpCheck
            {
                ResourceId = Group().Id, HttpStatus = httpStatus, Verified = verified, Message = "Result"
            }]
        });
        Assert.Equal(expected, item.IsResourceGroupVerified);
        Assert.Equal(expected ? "#409EFF" : "#555C66", item.VerificationColor);
        Assert.Contains("2026-09-08T10:00:00Z", item.VerificationDetails);
        item.UpdateDeployment(null);
        Assert.False(item.IsResourceGroupVerified);
    }

    [Fact]
    public void WrongGroupOrScaleSetSuccessfulResponseCannotLightThisItem()
    {
        var item = new SavedConfigurationItemViewModel(ScaleSet, Folder);
        item.UpdateDeployment(Overview);
        foreach (var result in new[]
        {
            new ScaleSetResourceGroupVerification { ScaleSetId = "008", Checks = [new() { ResourceId = Group().Id, HttpStatus = 200, Verified = true }] },
            new ScaleSetResourceGroupVerification { ScaleSetId = "007", Checks = [new() { ResourceId = Group("prod").Id, HttpStatus = 200, Verified = true }] },
            new ScaleSetResourceGroupVerification { ScaleSetId = "007", Checks = [] }
        })
        {
            item.ApplyVerification(result);
            Assert.False(item.IsResourceGroupVerified);
        }
    }

    [Fact]
    public void AllLinkedGroupsMustReturn200AndNetworkFailureClearsEarlierSuccess()
    {
        var item = new SavedConfigurationItemViewModel(ScaleSet, Folder);
        item.UpdateDeployment(Overview with { CommonResourceGroups = [Group(), Group("prod")] });
        var result = new ScaleSetResourceGroupVerification
        {
            ScaleSetId = "007",
            Checks =
            [
                new() { ResourceId = Group().Id, HttpStatus = 200, Verified = true },
                new() { ResourceId = Group("prod").Id, HttpStatus = 403, Verified = false }
            ]
        };
        item.ApplyVerification(result);
        Assert.False(item.IsResourceGroupVerified);
        item.ApplyVerification(result with { Checks = [.. result.Checks.Select(check => check with { HttpStatus = 200, Verified = true })] });
        Assert.True(item.IsResourceGroupVerified);
        item.SetVerificationUnavailable("Request timed out");
        Assert.False(item.IsResourceGroupVerified);
        Assert.Contains("timed out", item.VerificationDetails);
    }

    [Fact]
    public void RefreshInvalidationClearsLinksAndDoesNotAlterSelection()
    {
        var item = new SavedConfigurationItemViewModel(ScaleSet, Folder);
        item.UpdateSelection(new WizardIdentity(Folder, "017", "007"));
        item.UpdateDeployment(Overview);
        Assert.True(item.HasResourceGroupLink);
        item.UpdateDeployment(null);
        Assert.False(item.HasResourceGroupLink);
        Assert.True(item.IsSelected);
        item.UpdateDeployment(Overview with { CommonResourceGroups = [] });
        Assert.False(item.HasResourceGroupLink);
    }
}

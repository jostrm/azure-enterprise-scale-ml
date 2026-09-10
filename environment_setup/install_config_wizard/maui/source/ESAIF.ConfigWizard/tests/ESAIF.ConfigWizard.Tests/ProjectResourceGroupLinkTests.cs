using ESAIF.ConfigWizard.Services;
using ESAIF.ConfigWizard.ViewModels;
using ESAIF.DomainLayer.Operations;

namespace ESAIF.ConfigWizard.Tests;

public sealed class ProjectResourceGroupLinkTests
{
    private const string Subscription = "11111111-1111-4111-8111-111111111111";
    private const string Tenant = "22222222-2222-4222-8222-222222222222";
    private const string Group = "mrvel-1-project017-sdc-dev-007";

    [Fact]
    public void UsesObservedGroupSubscriptionAndTenantNotCurrentGlobalAccount()
    {
        var environment = new ProjectEnvironment
        {
            ResourceGroupReferences =
            [
                new()
                {
                    Name = Group, Id = $"/subscriptions/{Subscription}/resourceGroups/{Group}",
                    SubscriptionId = Subscription, TenantId = Tenant
                }
            ]
        };
        var link = Assert.Single(ProjectResourceGroupLink.FromEnvironment(environment));
        Assert.Equal($"https://portal.azure.com/#@{Tenant}/resource/subscriptions/{Subscription}/resourceGroups/{Group}/overview", link.Url.AbsoluteUri);
    }

    [Fact]
    public void NotDeployedCardDoesNotInventAResourceGroupLink()
    {
        var card = new ProjectEnvironmentCardViewModel(
            new FactoryProject { ProjectNumber = "017" },
            new ProjectEnvironment { Environment = "stage", Status = "not_deployed", SubscriptionId = Subscription });
        Assert.False(card.HasResourceGroupLink);
        Assert.Empty(card.ResourceGroupLinks);
    }

    [Fact]
    public void MultipleObservedGroupsHaveDistinctLinksAndLegacySingularStillWorks()
    {
        var links = ProjectResourceGroupLink.FromEnvironment(new ProjectEnvironment
        {
            ResourceGroupReferences =
            [
                new() { Name = Group, SubscriptionId = Subscription },
                new() { Name = Group + "-rg", SubscriptionId = Subscription },
                new() { Name = Group, SubscriptionId = Subscription }
            ]
        });
        Assert.Equal(2, links.Count);
        Assert.Equal(Subscription, links[0].SubscriptionId);
        Assert.Single(ProjectResourceGroupLink.FromEnvironment(new ProjectEnvironment
        {
            ResourceGroup = Group, SubscriptionId = Subscription
        }));
        Assert.Empty(ProjectResourceGroupLink.FromEnvironment(new ProjectEnvironment
        {
            ResourceGroups = [Group, Group + "-other"], SubscriptionId = Subscription
        })); // Legacy lists have no per-group subscription mapping.
    }

    [Theory]
    [InlineData("invalid-sub", "normal-group")]
    [InlineData(Subscription, "../other")]
    [InlineData(Subscription, "name#tenant")]
    [InlineData(Subscription, "name?query")]
    public void InvalidIdentityDoesNotOpenAnUnrelatedPortalDestination(string sub, string group)
    {
        Assert.Empty(ProjectResourceGroupLink.FromEnvironment(new ProjectEnvironment
        {
            ResourceGroup = group, SubscriptionId = sub
        }));
    }

    [Fact]
    public void ConflictingCanonicalIdRejectsRatherThanCombiningIdentities()
    {
        Assert.Empty(ProjectResourceGroupLink.FromEnvironment(new ProjectEnvironment
        {
            ResourceGroupReferences =
            [
                new()
                {
                    Name = Group, SubscriptionId = Subscription,
                    Id = $"/subscriptions/{Tenant}/resourceGroups/{Group}"
                }
            ]
        }));
    }
}

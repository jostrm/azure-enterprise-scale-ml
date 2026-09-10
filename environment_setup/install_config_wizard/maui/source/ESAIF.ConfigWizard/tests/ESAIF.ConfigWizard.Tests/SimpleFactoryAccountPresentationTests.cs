using ESAIF.ConfigWizard.Services;
using ESAIF.DomainLayer.Configuration;

namespace ESAIF.ConfigWizard.Tests;

public sealed class SimpleFactoryAccountPresentationTests
{
    private static SimpleFactoryAzureAccount Account => new()
    {
        SubscriptionId = "12345678-9abc-4def-8012-123456789abc",
        SubscriptionName = "MSFT-ClientCAB-1",
        TenantId = "abcdef01-2345-4678-9012-abcdef012345"
    };

    [Fact]
    public void SubscriptionLabelShowsOnlyTheRequestedFiveCharacterPrefixes()
    {
        var account = Account;
        var label = SimpleFactoryAccountPresentation.Label(account);
        Assert.Equal("Sub-ID: 12345… | MSFT-… | Tenant: abcde…", label);
        Assert.Equal(label, TechnicalValuePresentation.Summary(label));
        Assert.DoesNotContain(account.SubscriptionId, label);
        Assert.DoesNotContain(account.SubscriptionName, label);
        Assert.DoesNotContain(account.TenantId, label);
        Assert.DoesNotContain("SimpleFactoryAzureAccount", label);
    }

    [Theory]
    [InlineData("", "Not set")]
    [InlineData("Dev", "Dev")]
    [InlineData("12345", "12345")]
    [InlineData("123456", "12345…")]
    public void ShortOrMissingValuesAreHandledWithoutPaddingOrExceptions(string value, string expected)
    {
        var account = new SimpleFactoryAzureAccount { SubscriptionId = value, SubscriptionName = value, TenantId = value };
        Assert.Equal($"Sub-ID: {expected} | {expected} | Tenant: {expected}", SimpleFactoryAccountPresentation.Label(account));
    }

    [Fact]
    public void FullDetailsRemainSeparateAndDoNotChangeTheSelectedAccount()
    {
        var account = Account;
        var details = SimpleFactoryAccountPresentation.Details(account);
        Assert.Equal($"Subscription name: {account.SubscriptionName}\nSubscription id: {account.SubscriptionId}\nTenant id: {account.TenantId}", details);
        Assert.Equal(Account, account);
        var other = account with { SubscriptionId = "12345999-9abc-4def-8012-123456789abc" };
        var labels = TechnicalValuePresentation.ChoiceLabels(new[]
        {
            SimpleFactoryAccountPresentation.Label(account), SimpleFactoryAccountPresentation.Label(other)
        });
        Assert.NotEqual(labels[0], labels[1]);
    }
}

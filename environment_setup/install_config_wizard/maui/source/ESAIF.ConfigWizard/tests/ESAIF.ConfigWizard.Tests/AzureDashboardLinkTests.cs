using ESAIF.ConfigWizard.Services;

namespace ESAIF.ConfigWizard.Tests;

public sealed class AzureDashboardLinkTests
{
    [Theory]
    [InlineData("https://portal.azure.com/#@example.onmicrosoft.com/dashboard/private/11111111-1111-1111-1111-111111111111")]
    [InlineData("https://portal.azure.com/#dashboard/arm/subscriptions/11111111-1111-1111-1111-111111111111/resourceGroups/shared/providers/Microsoft.Portal/dashboards/factory")]
    public void ConfiguredAzureDashboardLink_IsPreserved(string address)
    {
        Assert.Equal(address, AzureDashboardLink.Parse(address)!.OriginalString);
    }

    [Theory]
    [InlineData(null)]
    [InlineData("")]
    [InlineData("aifactory-dash-01")]
    [InlineData("http://portal.azure.com/#@tenant/dashboard/private/id")]
    [InlineData("https://example.org/#/dashboard/private/id")]
    [InlineData("https://portal.azure.com.example.org/#/dashboard/private/id")]
    [InlineData("https://name:password@portal.azure.com/#/dashboard/private/id")]
    [InlineData("file:///C:/dashboard/local")]
    [InlineData("javascript:alert(1)")]
    [InlineData("https://portal.azure.com/#home")]
    [InlineData("https://portal.azure.com/#dashboard/private/")]
    [InlineData("https://portal.azure.com/#dashboard/arm/")]
    public void MissingOrNonPortalDashboardAddress_IsNotOpened(string? address)
    {
        Assert.Null(AzureDashboardLink.Parse(address));
    }
}

using ESAIF.DomainLayer.Operations;

namespace ESAIF.ConfigWizard.Tests;

public sealed class RegionCountPresentationTests
{
    [Theory]
    [InlineData("out_of_scope", 0, "Not checked")]
    [InlineData("not_collected", 0, "Not checked")]
    [InlineData("partial", 0, "Unknown")]
    [InlineData("partial", 5, "5+")]
    [InlineData("complete", 0, "0")]
    [InlineData("complete", 5, "5")]
    public void UnknownCountsAreNotPresentedAsConfirmedZeros(string status, int count, string expected)
    {
        var region = new AzureRegionInfo { CountStatus = status, ProjectCount = count, ResourceCount = count };
        Assert.Equal(expected, region.ProjectCountLabel);
        Assert.Equal(expected, region.ResourceCountLabel);
    }
}

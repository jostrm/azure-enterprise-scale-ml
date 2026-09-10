using ESAIF.BaseLayer.Monitoring;
using ESAIF.ConfigWizard.Services;
using ESAIF.DomainLayer.Operations;

namespace ESAIF.ConfigWizard.Tests;

public sealed class StatusPresentationTests
{
    [Theory]
    [InlineData("azure", "Azure snapshot", "#22C9A7", true)]
    [InlineData("live_azure", "Azure snapshot", "#22C9A7", true)]
    [InlineData("cached_azure", "Cached snapshot", "#D79B32", false)]
    [InlineData("azure_seeded", "Seeded demo", "#D79B32", false)]
    [InlineData("mixed", "Mixed sources", "#D79B32", false)]
    [InlineData("seeded", "Seeded demo", "#D79B32", false)]
    [InlineData("mock", "Mock", "#D79B32", false)]
    [InlineData("sqlite", "Local data", "#D79B32", false)]
    [InlineData("disconnected", "Disconnected", "#E45664", false)]
    [InlineData("unavailable", "Data unavailable", "#D79B32", false)]
    [InlineData(null, "Source unverified", "#D79B32", false)]
    public void Sources_DoNotConfuseSnapshotsOrDemoWithStreamingHealth(
        string? source, string label, string color, bool real)
    {
        Assert.Equal(new SourceStatus(label, color, real), StatusPresentation.FromSource(source));
    }

    [Fact]
    public void Overview_AzureInventoryAndSeededPromptsIsMixed()
    {
        var overview = new OperationsOverview
        {
            Source = "azure",
            ResourceInventory = new ResourceInventorySummary { Source = "azure" },
            PromptSummary = new PromptSummary { Source = "seeded" }
        };
        Assert.Equal("Mixed sources", StatusPresentation.ForOverview(overview).Label);
        Assert.Equal("Azure snapshot", StatusPresentation.FromSource(overview.ResourceInventory.Source).Label);
        Assert.Equal("Seeded demo", StatusPresentation.FromSource(overview.PromptSummary.Source).Label);
    }

    [Fact]
    public void MockOverviewStaysExplicitEvenWhenActualInventoryIsUnavailable()
    {
        var overview = new OperationsOverview
        {
            Source = "mock",
            ResourceInventory = new ResourceInventorySummary { Source = "unavailable" },
            PromptSummary = new PromptSummary { Source = "mock" }
        };
        Assert.Equal("Mock", StatusPresentation.ForOverview(overview).Label);
        Assert.Equal("Mock", OperationsPresentation.GetSourceLabel("mock"));
        Assert.False(StatusPresentation.ForOverview(overview).IsRealCollection);
        Assert.Equal("Data unavailable", StatusPresentation.FromSource(overview.ResourceInventory.Source).Label);
    }

    [Fact]
    public void Chart_UsesItsOwnSourceBeforeFallback()
    {
        var chart = new ChartDataSet { Source = "seeded" };
        Assert.Equal("Seeded demo", StatusPresentation.ForChart(chart, "azure").Label);
        Assert.False(StatusPresentation.ForChart(chart, "azure").IsRealCollection);
    }

    [Fact]
    public void Chart_MultipleSourcesAreMixed()
    {
        var chart = new ChartDataSet { Source = "azure", Sources = ["azure", "seeded"] };
        Assert.Equal("Mixed sources", StatusPresentation.ForChart(chart, "azure").Label);
    }

    [Fact]
    public void MissingSources_AreNeverAssumedAzure()
    {
        Assert.Equal("Source unverified", StatusPresentation.ForChart(new ChartDataSet(), null).Label);
        Assert.False(StatusPresentation.ForOverview(null).IsRealCollection);
    }
}

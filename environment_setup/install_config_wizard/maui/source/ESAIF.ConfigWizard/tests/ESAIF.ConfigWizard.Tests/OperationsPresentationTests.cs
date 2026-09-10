using ESAIF.BaseLayer.Monitoring;
using ESAIF.ConfigWizard.Services;
using ESAIF.DomainLayer.Operations;

namespace ESAIF.ConfigWizard.Tests;

public sealed class OperationsPresentationTests
{
    [Theory]
    [InlineData("azure", "Azure live")]
    [InlineData("live_azure", "Azure live")]
    [InlineData("cache", "Cached")]
    [InlineData("cached_azure", "Cached")]
    [InlineData("seeded_azure", "Seeded")]
    [InlineData("unavailable", "Unavailable")]
    [InlineData("mixed", "Mixed")]
    [InlineData("seed", "Seeded")]
    [InlineData("sqlite", "Local")]
    [InlineData(null, "Local")]
    public void GetSourceLabel_MapsKnownSources(string? source, string expected)
    {
        Assert.Equal(expected, OperationsPresentation.GetSourceLabel(source));
    }

    [Theory]
    [InlineData("Value", "Value")]
    [InlineData("input", "Input")]
    [InlineData("cached_input", "Cached input")]
    [InlineData("output", "Output")]
    [InlineData("input_tokens", "Input")]
    [InlineData("cached_input_tokens", "Cached input")]
    [InlineData("output_tokens", "Output")]
    [InlineData("success", "Success")]
    [InlineData("error", "Error")]
    [InlineData("", "")]
    public void SeriesDisplayName_ReturnsTextNotLinqIteratorTypes(string name, string expected)
    {
        var label = OperationsPresentation.GetSeriesDisplayName(name);

        Assert.Equal(expected, label);
        Assert.DoesNotContain("System.Linq", label);
    }

    [Fact]
    public void UnavailableTelemetry_DoesNotCreateZeroValuedPieSlices()
    {
        var summary = new PromptSummary { Source = "unavailable" };

        Assert.Empty(OperationsPresentation.BuildTokenMix(summary).Values);
        Assert.Empty(OperationsPresentation.BuildSuccessError(summary).Values);
    }

    [Fact]
    public void BuildTokenMix_DoesNotDoubleCountCachedInput()
    {
        var chart = OperationsPresentation.BuildTokenMix(new PromptSummary
        {
            InputTokens = 100,
            CachedInputTokens = 30,
            OutputTokens = 40
        });

        Assert.Equal(["Input", "Cached input", "Output"], chart.Labels);
        Assert.Equal([70d, 30d, 40d], chart.Values);
    }

    [Fact]
    public void BuildSuccessError_AggregatesBothOutcomes()
    {
        var chart = OperationsPresentation.BuildSuccessError(new PromptSummary
        {
            SuccessCount = 17,
            ErrorCount = 3,
            Source = "azure"
        });

        Assert.Equal(["Success", "Error"], chart.Labels);
        Assert.Equal([17d, 3d], chart.Values);
        Assert.Equal("azure", chart.Source);
    }

    [Fact]
    public void GetWeightedAverage_UsesRequestVolume()
    {
        var latency = new ChartDataSet
        {
            Labels = ["day-one", "day-two"],
            Values = [100, 1000]
        };
        var requests = new ChartDataSet
        {
            Labels = ["day-one", "day-two"],
            Values = [9, 1]
        };

        Assert.Equal(190, OperationsPresentation.GetWeightedAverage(latency, requests));
    }

    [Theory]
    [InlineData("All", null)]
    [InlineData(" all ", null)]
    [InlineData("", null)]
    [InlineData(" project-001 ", "project-001")]
    public void NormalizeOptionalFilter_MapsAllToNull(
        string value,
        string? expected)
    {
        Assert.Equal(expected, OperationsPresentation.NormalizeOptionalFilter(value));
    }

    [Theory]
    [InlineData("All", null)]
    [InlineData("Success", true)]
    [InlineData("Errors", false)]
    public void ParseSuccessFilter_MapsUiSentinel(
        string value,
        bool? expected)
    {
        Assert.Equal(expected, OperationsPresentation.ParseSuccessFilter(value));
    }

    [Fact]
    public void GetChartSourceLabel_ReturnsMixedForDifferentPointSources()
    {
        var chart = new ChartDataSet
        {
            Labels = ["one", "two"],
            Values = [1, 2],
            Sources = ["azure", "cache"]
        };

        Assert.Equal("Mixed", OperationsPresentation.GetChartSourceLabel(chart));
    }
}

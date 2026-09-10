using ESAIF.BaseLayer.Monitoring;

namespace ESAIF.BaseLayer.Tests;

public sealed class MonitoringDataAdapterTests
{
    [Fact]
    public void BuildTokenMix_SplitsCachedInputWithoutDoubleCounting()
    {
        var chart = MonitoringDataAdapter.BuildTokenMix(
        [
            new PromptTelemetryRecord
            {
                InputTokens = 100,
                CachedInputTokens = 40,
                OutputTokens = 25
            }
        ]);

        Assert.Equal(["Input", "Cached input", "Output"], chart.Labels);
        Assert.Equal([60d, 40d, 25d], chart.Values);
    }

    [Fact]
    public void BuildTokenMix_DoesNotProduceNegativeValues()
    {
        var chart = MonitoringDataAdapter.BuildTokenMix(
        [
            new PromptTelemetryRecord
            {
                InputTokens = 20,
                CachedInputTokens = 30,
                OutputTokens = -5
            }
        ]);

        Assert.Equal([0d, 30d, 0d], chart.Values);
    }

    [Fact]
    public void ValidateAndAlign_RejectsMismatchedValues()
    {
        var chart = new ChartDataSet
        {
            Labels = ["one", "two"],
            Values = [1]
        };

        var exception = Assert.Throws<ArgumentException>(
            () => MonitoringDataAdapter.ValidateAndAlign(chart));

        Assert.Contains("values contain 1", exception.Message);
    }

    [Fact]
    public void ValidateAndAlign_RejectsMismatchedNamedSeries()
    {
        var chart = new ChartDataSet
        {
            Labels = ["one", "two"],
            Series = new Dictionary<string, IReadOnlyList<double>>
            {
                ["requests"] = [1]
            }
        };

        var exception = Assert.Throws<ArgumentException>(
            () => MonitoringDataAdapter.ValidateAndAlign(chart));

        Assert.Contains("series 'requests'", exception.Message);
    }

    [Fact]
    public void ValidateAndAlign_RejectsLabelsWithoutValuesOrSeries()
    {
        var chart = new ChartDataSet { Labels = ["orphaned"] };

        Assert.Throws<ArgumentException>(
            () => MonitoringDataAdapter.ValidateAndAlign(chart));
    }

    [Fact]
    public void FilterPrompts_AppliesAllFiltersCaseInsensitively()
    {
        var expected = new PromptTelemetryRecord
        {
            OperationId = "OP-1",
            ProjectNumber = "001",
            Environment = "DEV",
            Model = "GPT-4O",
            Category = "Coding",
            Prompt = "Refactor this API",
            Response = "Complete",
            Success = true
        };
        var rows = new[]
        {
            expected,
            expected with { OperationId = "OP-2", Model = "other" },
            expected with { OperationId = "OP-3", Success = false }
        };

        var filtered = MonitoringDataAdapter.FilterPrompts(
            rows,
            new PromptExplorerFilters
            {
                Search = "REFACTOR",
                ProjectNumber = "001",
                Environment = "dev",
                Model = "gpt-4o",
                Category = "coding",
                Success = true
            });

        Assert.Equal([expected], filtered);
    }

    [Fact]
    public void SummarizePrompts_CalculatesCountsTokensRatesAndLatency()
    {
        var summary = MonitoringDataAdapter.SummarizePrompts(
        [
            new PromptTelemetryRecord
            {
                InputTokens = 100,
                CachedInputTokens = 20,
                OutputTokens = 50,
                TotalTokens = 150,
                LatencyMilliseconds = 200,
                Success = true
            },
            new PromptTelemetryRecord
            {
                InputTokens = 40,
                CachedInputTokens = 10,
                OutputTokens = 10,
                TotalTokens = 50,
                LatencyMilliseconds = 400,
                Success = false
            }
        ]);

        Assert.Equal(2, summary.RequestCount);
        Assert.Equal(1, summary.SuccessCount);
        Assert.Equal(1, summary.ErrorCount);
        Assert.Equal(140, summary.InputTokens);
        Assert.Equal(30, summary.CachedInputTokens);
        Assert.Equal(60, summary.OutputTokens);
        Assert.Equal(200, summary.TotalTokens);
        Assert.Equal(50, summary.SuccessRate);
        Assert.Equal(300, summary.AverageLatencyMilliseconds);
    }

    [Fact]
    public void EmptyInputs_ReturnNormalizedEmptyResults()
    {
        var chart = MonitoringDataAdapter.BuildTokenMix([]);
        var summary = MonitoringDataAdapter.SummarizePrompts([]);
        var filtered = MonitoringDataAdapter.FilterPrompts([], null);
        var normalized = new ChartDataSet
        {
            Labels = null!,
            Values = null!,
            Series = null!,
            Sources = null!
        };

        Assert.Equal([0d, 0d, 0d], chart.Values);
        Assert.Equal(0, summary.RequestCount);
        Assert.Equal(0, summary.SuccessRate);
        Assert.Empty(filtered);
        Assert.Empty(normalized.Labels);
        Assert.Empty(normalized.Values);
        Assert.Empty(normalized.Series);
        Assert.Empty(normalized.Sources);
    }
}

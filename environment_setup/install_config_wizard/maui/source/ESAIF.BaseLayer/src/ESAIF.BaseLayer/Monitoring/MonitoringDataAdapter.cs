namespace ESAIF.BaseLayer.Monitoring;

public static class MonitoringDataAdapter
{
    public static ChartDataSet ValidateAndAlign(ChartDataSet chart)
    {
        ArgumentNullException.ThrowIfNull(chart);

        var labelCount = chart.Labels.Count;
        if (chart.Values.Count != labelCount &&
            (chart.Values.Count != 0 || chart.Series.Count == 0))
        {
            throw new ArgumentException(
                $"Chart values contain {chart.Values.Count} items, but labels contain {labelCount}.",
                nameof(chart));
        }

        foreach (var (name, values) in chart.Series)
        {
            if (values is null)
            {
                throw new ArgumentException(
                    $"Chart series '{name}' is null.",
                    nameof(chart));
            }

            if (values.Count != labelCount)
            {
                throw new ArgumentException(
                    $"Chart series '{name}' contains {values.Count} items, but labels contain {labelCount}.",
                    nameof(chart));
            }
        }

        if (chart.Sources.Count != 0 && chart.Sources.Count != labelCount)
        {
            throw new ArgumentException(
                $"Chart sources contain {chart.Sources.Count} items, but labels contain {labelCount}.",
                nameof(chart));
        }

        return chart;
    }

    public static ChartDataSet BuildTokenMix(IEnumerable<PromptTelemetryRecord> records)
    {
        ArgumentNullException.ThrowIfNull(records);

        long nonCachedInput = 0;
        long cachedInput = 0;
        long output = 0;

        foreach (var record in records)
        {
            var input = Math.Max(0, record.InputTokens);
            var cached = Math.Max(0, record.CachedInputTokens);
            nonCachedInput += Math.Max(0, input - cached);
            cachedInput += cached;
            output += Math.Max(0, record.OutputTokens);
        }

        return new ChartDataSet
        {
            Labels = ["Input", "Cached input", "Output"],
            Values = [nonCachedInput, cachedInput, output],
            ChartType = "pie",
            Unit = "tokens"
        };
    }

    public static TokenUsageSummary SummarizePrompts(
        IEnumerable<PromptTelemetryRecord> records)
    {
        ArgumentNullException.ThrowIfNull(records);

        var rows = records.ToArray();
        var successCount = rows.Count(row => row.Success);
        var latencies = rows
            .Where(row => row.LatencyMilliseconds is not null)
            .Select(row => Math.Max(0, row.LatencyMilliseconds!.Value))
            .ToArray();

        return new TokenUsageSummary
        {
            RequestCount = rows.Length,
            SuccessCount = successCount,
            ErrorCount = rows.Length - successCount,
            InputTokens = rows.Sum(row => Math.Max(0, row.InputTokens)),
            CachedInputTokens = rows.Sum(row => Math.Max(0, row.CachedInputTokens)),
            OutputTokens = rows.Sum(row => Math.Max(0, row.OutputTokens)),
            TotalTokens = rows.Sum(row =>
                row.TotalTokens > 0
                    ? row.TotalTokens
                    : Math.Max(0, row.InputTokens) + Math.Max(0, row.OutputTokens)),
            SuccessRate = rows.Length == 0
                ? 0
                : 100d * successCount / rows.Length,
            AverageLatencyMilliseconds = latencies.Length == 0
                ? 0
                : latencies.Average()
        };
    }

    public static IReadOnlyList<PromptTelemetryRecord> FilterPrompts(
        IEnumerable<PromptTelemetryRecord> records,
        PromptExplorerFilters? filters)
    {
        ArgumentNullException.ThrowIfNull(records);
        filters ??= new PromptExplorerFilters();

        return records.Where(row =>
            Matches(row.ProjectNumber, filters.ProjectNumber) &&
            Matches(row.Environment, filters.Environment) &&
            Matches(row.Model, filters.Model) &&
            Matches(row.Category, filters.Category) &&
            (filters.Success is null || row.Success == filters.Success) &&
            MatchesSearch(row, filters.Search)).ToArray();
    }

    private static bool Matches(string? value, string? filter)
    {
        return string.IsNullOrWhiteSpace(filter) ||
               string.Equals(value, filter, StringComparison.OrdinalIgnoreCase);
    }

    private static bool MatchesSearch(PromptTelemetryRecord row, string? search)
    {
        if (string.IsNullOrWhiteSpace(search))
        {
            return true;
        }

        return Contains(row.Prompt, search) ||
               Contains(row.Response, search) ||
               Contains(row.OperationId, search);
    }

    private static bool Contains(string? value, string search)
    {
        return value?.Contains(search, StringComparison.OrdinalIgnoreCase) == true;
    }
}

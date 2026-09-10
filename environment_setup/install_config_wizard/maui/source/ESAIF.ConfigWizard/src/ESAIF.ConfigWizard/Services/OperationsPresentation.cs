using ESAIF.BaseLayer.Monitoring;
using ESAIF.DomainLayer.Operations;

namespace ESAIF.ConfigWizard.Services;

public static class OperationsPresentation
{
    public const string AllFilter = "All";
    public const string MissingFolderMessage =
        "Choose an AI Factory folder in the Configuration wizard to load operations data.";

    public static string GetSourceLabel(string? source)
    {
        var normalized = source?.Trim().ToLowerInvariant() ?? string.Empty;
        if (normalized == "mock")
        {
            return "Mock";
        }
        if (normalized.Contains("mixed", StringComparison.Ordinal))
        {
            return "Mixed";
        }

        if (normalized.Contains("cache", StringComparison.Ordinal))
        {
            return "Cached";
        }

        if (normalized.Contains("seed", StringComparison.Ordinal))
        {
            return "Seeded";
        }

        if (normalized.Contains("azure", StringComparison.Ordinal) ||
            normalized.Contains("live", StringComparison.Ordinal))
        {
            return "Azure live";
        }

        if (normalized == "unavailable")
        {
            return "Unavailable";
        }

        return "Local";
    }

    public static string GetSeriesDisplayName(string name)
    {
        ArgumentNullException.ThrowIfNull(name);
        return name.Replace("_", " ", StringComparison.Ordinal) switch
        {
            "input tokens" => "Input",
            "cached input tokens" => "Cached input",
            "output tokens" => "Output",
            "" => string.Empty,
            var value => char.ToUpperInvariant(value[0]) + value[1..]
        };
    }

    public static string GetChartSourceLabel(
        ChartDataSet chart,
        string? overviewSource = null)
    {
        ArgumentNullException.ThrowIfNull(chart);

        var sources = chart.Sources
            .Append(chart.Source)
            .Where(source => !string.IsNullOrWhiteSpace(source))
            .Select(GetSourceLabel)
            .Distinct(StringComparer.Ordinal)
            .ToArray();

        return sources.Length switch
        {
            > 1 => "Mixed",
            1 => sources[0],
            _ => GetSourceLabel(overviewSource)
        };
    }

    public static ChartDataSet BuildTokenMix(PromptSummary summary)
    {
        ArgumentNullException.ThrowIfNull(summary);
        if (summary.Source == "unavailable")
        {
            return new ChartDataSet { Source = summary.Source, ChartType = "pie", Unit = "tokens" };
        }

        var input = Math.Max(0, summary.InputTokens);
        var cached = Math.Max(0, summary.CachedInputTokens);

        return new ChartDataSet
        {
            Labels = ["Input", "Cached input", "Output"],
            Values =
            [
                Math.Max(0, input - cached),
                cached,
                Math.Max(0, summary.OutputTokens)
            ],
            ChartType = "pie",
            Unit = "tokens",
            Source = summary.Source
        };
    }

    public static ChartDataSet BuildSuccessError(PromptSummary summary)
    {
        ArgumentNullException.ThrowIfNull(summary);
        if (summary.Source == "unavailable")
        {
            return new ChartDataSet { Source = summary.Source, ChartType = "pie" };
        }

        return new ChartDataSet
        {
            Labels = ["Success", "Error"],
            Values =
            [
                Math.Max(0, summary.SuccessCount),
                Math.Max(0, summary.ErrorCount)
            ],
            ChartType = "pie",
            Source = summary.Source
        };
    }

    public static string? NormalizeOptionalFilter(string? value)
    {
        var normalized = value?.Trim();
        return string.IsNullOrWhiteSpace(normalized) ||
               string.Equals(normalized, AllFilter, StringComparison.OrdinalIgnoreCase)
            ? null
            : normalized;
    }

    public static bool? ParseSuccessFilter(string? value)
    {
        return NormalizeOptionalFilter(value)?.ToLowerInvariant() switch
        {
            "success" or "successful" => true,
            "error" or "errors" or "failed" => false,
            _ => null
        };
    }

    public static double GetSuccessRate(PromptSummary summary)
    {
        ArgumentNullException.ThrowIfNull(summary);
        return summary.RecordCount == 0
            ? 0
            : 100d * summary.SuccessCount / summary.RecordCount;
    }

    public static double? GetAverage(ChartDataSet chart)
    {
        ArgumentNullException.ThrowIfNull(chart);
        var values = chart.Series.Count > 0
            ? chart.Series.Values.SelectMany(values => values).ToArray()
            : chart.Values.ToArray();
        return values.Length == 0 ? null : values.Average();
    }

    public static double? GetWeightedAverage(
        ChartDataSet values,
        ChartDataSet weights)
    {
        ArgumentNullException.ThrowIfNull(values);
        ArgumentNullException.ThrowIfNull(weights);
        MonitoringDataAdapter.ValidateAndAlign(values);
        MonitoringDataAdapter.ValidateAndAlign(weights);
        if (!values.Labels.SequenceEqual(weights.Labels, StringComparer.Ordinal) ||
            values.Values.Count != weights.Values.Count)
        {
            return GetAverage(values);
        }

        var totalWeight = weights.Values.Sum(value => Math.Max(0, value));
        if (totalWeight <= 0)
        {
            return GetAverage(values);
        }

        return values.Values
            .Zip(
                weights.Values,
                (value, weight) => Math.Max(0, value) * Math.Max(0, weight))
            .Sum() / totalWeight;
    }
}

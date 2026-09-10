using ESAIF.BaseLayer.Monitoring;
using ESAIF.DomainLayer.Operations;

namespace ESAIF.ConfigWizard.Services;

public sealed record SourceStatus(string Label, string ColorHex, bool IsRealCollection = false);

public static class StatusPresentation
{
    public static SourceStatus FromSource(string? source)
    {
        var value = source?.Trim().ToLowerInvariant() ?? string.Empty;
        if (value == "mock")
        {
            return new("Mock", "#D79B32");
        }
        if (value == "unavailable")
        {
            return new("Data unavailable", "#D79B32");
        }
        if (value.Contains("disconnect", StringComparison.Ordinal) ||
            value == "offline")
        {
            return new("Disconnected", "#E45664");
        }

        if (value.Contains("mixed", StringComparison.Ordinal))
        {
            return new("Mixed sources", "#D79B32");
        }

        // Cache/demo qualifiers take precedence over an embedded provider name.
        if (value.Contains("cache", StringComparison.Ordinal))
        {
            return new("Cached snapshot", "#D79B32");
        }

        if (value.Contains("seed", StringComparison.Ordinal) || value.Contains("demo", StringComparison.Ordinal))
        {
            return new("Seeded demo", "#D79B32");
        }

        if (value.Contains("azure", StringComparison.Ordinal) || value.Contains("live", StringComparison.Ordinal))
        {
            return new("Azure snapshot", "#22C9A7", true);
        }

        return new(value.Length == 0 ? "Source unverified" : "Local data", "#D79B32");
    }

    public static SourceStatus ForChart(ChartDataSet chart, string? fallback)
    {
        var sources = chart.Sources.Append(chart.Source)
            .Where(source => !string.IsNullOrWhiteSpace(source))
            .Select(FromSource).Distinct().ToArray();
        return sources.Length switch
        {
            0 => FromSource(fallback),
            1 => sources[0],
            _ => FromSource("mixed")
        };
    }

    public static SourceStatus ForOverview(OperationsOverview? overview)
    {
        if (overview is null)
        {
            return new("No snapshot", "#D79B32");
        }
        if (overview.Source == "mock")
        {
            return FromSource("mock");
        }

        var sources = new[]
        {
            FromSource(overview.Source),
            FromSource(overview.ResourceInventory.Source),
            FromSource(overview.PromptSummary.Source)
        }.Distinct().ToArray();
        return sources.Length == 1 ? sources[0] : FromSource("mixed");
    }
}

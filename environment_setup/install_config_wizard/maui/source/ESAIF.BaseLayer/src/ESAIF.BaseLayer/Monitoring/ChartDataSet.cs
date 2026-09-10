using System.Text.Json.Serialization;

namespace ESAIF.BaseLayer.Monitoring;

public sealed record ChartDataSet
{
    private IReadOnlyList<string> _labels = [];
    private IReadOnlyList<double> _values = [];
    private IReadOnlyDictionary<string, IReadOnlyList<double>> _series =
        new Dictionary<string, IReadOnlyList<double>>(StringComparer.Ordinal);
    private IReadOnlyList<string> _sources = [];

    public IReadOnlyList<string> Labels
    {
        get => _labels;
        init => _labels = value ?? [];
    }

    [JsonNumberHandling(JsonNumberHandling.AllowReadingFromString)]
    public IReadOnlyList<double> Values
    {
        get => _values;
        init => _values = value ?? [];
    }

    [JsonConverter(typeof(NumericSeriesDictionaryConverter))]
    public IReadOnlyDictionary<string, IReadOnlyList<double>> Series
    {
        get => _series;
        init => _series = value
            ?? new Dictionary<string, IReadOnlyList<double>>(StringComparer.Ordinal);
    }

    public IReadOnlyList<string> Sources
    {
        get => _sources;
        init => _sources = value ?? [];
    }

    public string Source { get; init; } = string.Empty;

    [JsonPropertyName("chart_type")]
    public string ChartType { get; init; } = string.Empty;

    public bool Stacked { get; init; }

    public string? Unit { get; init; }

    [JsonPropertyName("success_rate")]
    [JsonNumberHandling(JsonNumberHandling.AllowReadingFromString)]
    public double? SuccessRate { get; init; }

    [JsonPropertyName("error_rate")]
    [JsonNumberHandling(JsonNumberHandling.AllowReadingFromString)]
    public double? ErrorRate { get; init; }
}

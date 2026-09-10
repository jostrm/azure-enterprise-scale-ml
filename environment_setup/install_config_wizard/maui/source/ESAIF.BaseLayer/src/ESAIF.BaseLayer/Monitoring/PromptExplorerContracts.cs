using System.Text.Json.Serialization;

namespace ESAIF.BaseLayer.Monitoring;

public sealed record PromptExplorerFilters
{
    public string? Search { get; init; }

    public string? ProjectNumber { get; init; }

    public string? Environment { get; init; }

    public string? Model { get; init; }

    public string? Category { get; init; }

    public bool? Success { get; init; }
}

public sealed record PromptFilterMetadata
{
    private IReadOnlyList<string> _projectNumbers = [];
    private IReadOnlyList<string> _environments = [];
    private IReadOnlyList<string> _models = [];
    private IReadOnlyList<string> _categories = [];
    private IReadOnlyList<bool> _successValues = [];

    [JsonPropertyName("project_numbers")]
    public IReadOnlyList<string> ProjectNumbers
    {
        get => _projectNumbers;
        init => _projectNumbers = value ?? [];
    }

    public IReadOnlyList<string> Environments
    {
        get => _environments;
        init => _environments = value ?? [];
    }

    public IReadOnlyList<string> Models
    {
        get => _models;
        init => _models = value ?? [];
    }

    public IReadOnlyList<string> Categories
    {
        get => _categories;
        init => _categories = value ?? [];
    }

    [JsonPropertyName("success_values")]
    public IReadOnlyList<bool> SuccessValues
    {
        get => _successValues;
        init => _successValues = value ?? [];
    }
}

public sealed record PromptExplorerPage
{
    private IReadOnlyList<PromptTelemetryRecord> _rows = [];

    public IReadOnlyList<PromptTelemetryRecord> Rows
    {
        get => _rows;
        init => _rows = value ?? [];
    }

    public int Total { get; init; }

    public int Limit { get; init; }

    public int Offset { get; init; }
}

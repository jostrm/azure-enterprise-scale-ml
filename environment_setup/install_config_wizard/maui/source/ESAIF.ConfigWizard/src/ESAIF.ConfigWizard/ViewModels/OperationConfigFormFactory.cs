using System.Collections.ObjectModel;
using System.Globalization;
using System.Text.Json.Nodes;
using ESAIF.BaseLayer.Application;

namespace ESAIF.ConfigWizard.ViewModels;

public enum OperationConfigFieldType
{
    Text,
    Number,
    Boolean,
    Choice,
    Multiline
}

public sealed class OperationConfigFieldViewModel : ObservableObject
{
    private readonly bool _integerNumber;
    private string _value;
    private bool _booleanValue;
    private bool _isVisible = true;
    private string _validationMessage = string.Empty;

    internal OperationConfigFieldViewModel(
        string key,
        string label,
        string description,
        OperationConfigFieldType type,
        JsonNode? value,
        IEnumerable<string>? choices = null)
    {
        Key = key;
        Label = label;
        Description = description;
        Type = type;
        _value = Display(value);
        _booleanValue = ReadBoolean(value);
        _integerNumber = IsInteger(value);
        Choices = new ObservableCollection<string>(choices ?? []);
    }

    public event EventHandler? ValueChanged;

    public string Key { get; }

    public string Label { get; }

    public string Description { get; }

    public OperationConfigFieldType Type { get; }

    public ObservableCollection<string> Choices { get; }

    public bool IsText => Type == OperationConfigFieldType.Text;

    public bool IsNumber => Type == OperationConfigFieldType.Number;

    public bool IsBoolean => Type == OperationConfigFieldType.Boolean;

    public bool IsChoice => Type == OperationConfigFieldType.Choice;

    public bool IsMultiline => Type == OperationConfigFieldType.Multiline;

    public bool IsVisible
    {
        get => _isVisible;
        internal set => SetProperty(ref _isVisible, value);
    }

    public string ValidationMessage
    {
        get => _validationMessage;
        private set
        {
            if (SetProperty(ref _validationMessage, value))
            {
                OnPropertyChanged(nameof(IsInvalid));
            }
        }
    }

    public bool IsInvalid => !string.IsNullOrWhiteSpace(ValidationMessage);

    public string Value
    {
        get => _value;
        set
        {
            if (SetProperty(ref _value, value ?? string.Empty))
            {
                ValidationMessage = string.Empty;
                if (bool.TryParse(_value, out var parsed))
                {
                    SetProperty(ref _booleanValue, parsed, nameof(BooleanValue));
                }

                ValueChanged?.Invoke(this, EventArgs.Empty);
            }
        }
    }

    public string SelectedChoice
    {
        get => Value;
        set => Value = value;
    }

    public bool BooleanValue
    {
        get => _booleanValue;
        set
        {
            if (SetProperty(ref _booleanValue, value))
            {
                Value = value ? "true" : "false";
            }
        }
    }

    public bool TryConvert(out JsonNode? value)
    {
        ValidationMessage = string.Empty;
        switch (Type)
        {
            case OperationConfigFieldType.Boolean:
                if (bool.TryParse(Value, out var boolean))
                {
                    value = JsonValue.Create(boolean);
                    return true;
                }

                ValidationMessage = $"{Label} must be true or false.";
                break;
            case OperationConfigFieldType.Number:
                if (_integerNumber &&
                    long.TryParse(
                        Value,
                        NumberStyles.Integer,
                        CultureInfo.InvariantCulture,
                        out var integer))
                {
                    value = JsonValue.Create(integer);
                    return true;
                }

                if (double.TryParse(
                    Value,
                    NumberStyles.Float,
                    CultureInfo.InvariantCulture,
                    out var number) &&
                    double.IsFinite(number))
                {
                    value = JsonValue.Create(number);
                    return true;
                }

                ValidationMessage = $"{Label} must be a valid number.";
                break;
            default:
                value = JsonValue.Create(Value);
                return true;
        }

        value = null;
        return false;
    }

    internal void ReplaceChoices(IEnumerable<string> choices)
    {
        var values = choices
            .Where(value => !string.IsNullOrWhiteSpace(value))
            .Distinct(StringComparer.Ordinal)
            .ToArray();
        Choices.Clear();
        foreach (var value in values)
        {
            Choices.Add(value);
        }

        if (values.Length > 0 && !values.Contains(Value, StringComparer.Ordinal))
        {
            Value = values[0];
        }
    }

    private static bool ReadBoolean(JsonNode? node) =>
        node is JsonValue value &&
        ((value.TryGetValue<bool>(out var boolean) && boolean) ||
         (value.TryGetValue<string>(out var text) &&
          bool.TryParse(text, out boolean) &&
          boolean));

    private static bool IsInteger(JsonNode? node) =>
        node is JsonValue value &&
        (value.TryGetValue<int>(out _) || value.TryGetValue<long>(out _));

    private static string Display(JsonNode? node)
    {
        if (node is null)
        {
            return string.Empty;
        }

        return node is JsonValue value && value.TryGetValue<string>(out var text)
            ? text
            : node.ToJsonString().Trim('"');
    }
}

public sealed record OperationGuidanceCard(string Title, string Description);

public sealed class OperationConfigForm
{
    internal OperationConfigForm(
        IReadOnlyList<OperationConfigFieldViewModel> fields,
        IReadOnlyList<OperationGuidanceCard> guidance)
    {
        Fields = fields;
        Guidance = guidance;
    }

    public IReadOnlyList<OperationConfigFieldViewModel> Fields { get; }

    public IReadOnlyList<OperationGuidanceCard> Guidance { get; }

    public OperationConfigFieldViewModel? Find(string key) =>
        Fields.FirstOrDefault(field =>
            string.Equals(field.Key, key, StringComparison.Ordinal));

    public bool TryBuildConfig(out JsonObject config, out string validationMessage)
    {
        config = [];
        var errors = new List<string>();
        foreach (var field in Fields)
        {
            if (field.TryConvert(out var value))
            {
                config[field.Key] = value;
            }
            else
            {
                errors.Add(field.ValidationMessage);
            }
        }

        validationMessage = string.Join(" ", errors);
        return errors.Count == 0;
    }
}

public static class OperationConfigFormFactory
{
    private sealed record FieldDefinition(
        string Key,
        string Label,
        string Description,
        OperationConfigFieldType Type,
        string? ChoiceSource = null,
        string[]? FallbackChoices = null);

    private static readonly IReadOnlyDictionary<string, FieldDefinition[]> Definitions =
        new Dictionary<string, FieldDefinition[]>(StringComparer.OrdinalIgnoreCase)
        {
            ["dataops"] =
            [
                Text("frequency", "Frequency", "Human-readable execution cadence."),
                Text("schedule", "Schedule", "Cron schedule used by the operation."),
                Choice("load_mode", "Load mode", "Load only changes or reload all source data.", choices: ["delta", "full"]),
                Text("source_watermark_column", "Source watermark column", "Source column used to identify new or changed records."),
                Number("late_arrival_minutes", "Late arrival minutes", "Grace period for records arriving after their event time."),
                Choice("window_type", "Window type", "Streaming aggregation window.", "window_types", ["sliding", "hopping", "tumbling", "session"]),
                Number("window_size_minutes", "Window size minutes", "Length of each processing window."),
                Number("slide_minutes", "Slide minutes", "How often sliding or hopping windows advance."),
                Number("session_gap_minutes", "Session gap minutes", "Inactivity gap that ends a session window."),
                Number("retry_count", "Retry count", "Number of retries after a failed operation.")
            ],
            ["mlops"] =
            [
                Text("frequency", "Frequency", "Human-readable retraining cadence."),
                Text("schedule", "Schedule", "Cron schedule used by the operation."),
                Choice("task_type", "Task type", "Machine learning problem type.", "metric_catalogs"),
                Choice("metric", "Metric", "Metric used to evaluate promotion."),
                Number("threshold", "Metric threshold", "Minimum result required for promotion."),
                Choice("promotion_environment", "Promotion environment", "Environment that receives an approved model.", choices: ["dev", "stage", "prod"]),
                Boolean("retrain_on_data_drift", "Retrain on data drift", "Retrain when input distributions change."),
                Boolean("retrain_on_concept_drift", "Retrain on concept drift", "Retrain when the input-output relationship changes."),
                Boolean("retrain_on_model_drift", "Retrain on model drift", "Retrain when model behavior degrades."),
                Number("drift_threshold", "Drift threshold", "Threshold that triggers drift handling."),
                Number("minimum_samples", "Minimum samples", "Minimum observations required before drift evaluation.")
            ],
            ["rag"] =
            [
                Text("frequency", "Frequency", "Human-readable index refresh cadence."),
                Text("schedule", "Schedule", "Cron schedule used by the operation."),
                Choice("index_update_mode", "Index update mode", "Update changed content or rebuild the full index.", "index_update_modes", ["delta", "full"]),
                Text("vector_store", "Vector store", "Vector storage service used for retrieval."),
                Text("embedding_model", "Embedding model", "Model used to produce document vectors."),
                Number("chunk_size", "Chunk size", "Maximum content units in each chunk."),
                Number("chunk_overlap", "Chunk overlap", "Content units shared between adjacent chunks."),
                Number("retrieval_top_k", "Retrieval top K", "Maximum results retrieved for each query."),
                Boolean("hybrid_search", "Hybrid search", "Combine keyword and vector search."),
                Boolean("semantic_reranking", "Semantic reranking", "Rerank retrieved results semantically."),
                Number("freshness_threshold_hours", "Freshness threshold hours", "Maximum acceptable index age."),
                Text("evaluation_metric", "Evaluation metric", "Metric used to evaluate retrieval quality."),
                Number("evaluation_threshold", "Evaluation threshold", "Minimum result required for promotion."),
                Choice("promotion_environment", "Promotion environment", "Environment that receives an approved index.", choices: ["dev", "stage", "prod"])
            ],
            ["finetuning"] =
            [
                Choice("training_type", "Training type", "Fine-tuning method.", "training_types", ["SFT", "DPO", "RFT"]),
                Text("base_model", "Base model", "Microsoft Foundry base model to evaluate before training."),
                Text("dataset_uri", "Dataset URI", "Training dataset location.", OperationConfigFieldType.Multiline),
                Number("validation_split", "Validation split", "Fraction reserved as held-out evaluation data."),
                Number("epochs", "Epochs", "Training passes through the dataset."),
                Number("learning_rate_multiplier", "Learning-rate multiplier", "Multiplier applied to the base learning rate."),
                Number("batch_size", "Batch size", "Training examples processed per optimization step."),
                Text("evaluation_metric", "Evaluation metric", "Held-out metric used to compare checkpoints."),
                Number("evaluation_threshold", "Evaluation threshold", "Minimum result required for promotion."),
                Choice("promotion_environment", "Promotion environment", "Environment that receives an approved checkpoint.", choices: ["dev", "stage", "prod"]),
                Text("checkpoint_strategy", "Checkpoint strategy", "Method used to select the checkpoint."),
                Boolean("responsible_ai_evaluation", "Responsible AI evaluation", "Run Responsible AI evaluation before promotion."),
                Number("estimated_training_examples", "Estimated training examples", "Expected number of training examples.")
            ]
        };

    private static readonly IReadOnlyDictionary<string, string[]> MetricFallbacks =
        new Dictionary<string, string[]>(StringComparer.Ordinal)
        {
            ["classification"] =
            [
                "accuracy", "precision", "recall", "f1_score", "roc_auc",
                "log_loss", "average_precision", "matthews_correlation",
                "balanced_accuracy", "cohen_kappa"
            ],
            ["regression"] =
            [
                "mae", "mse", "rmse", "r2", "mape", "smape",
                "median_absolute_error", "explained_variance", "max_error",
                "mean_squared_log_error"
            ],
            ["forecasting"] =
            [
                "mae", "mse", "rmse", "mape", "smape", "wape", "mase",
                "rmsle", "normalized_rmse", "forecast_bias"
            ]
        };

    public static OperationConfigForm Create(string kind, JsonObject config)
    {
        ArgumentNullException.ThrowIfNull(config);
        var normalizedKind = NormalizeKind(kind);
        if (!Definitions.TryGetValue(normalizedKind, out var definitions))
        {
            throw new NotSupportedException($"Operation kind '{kind}' is not supported.");
        }

        var fields = definitions
            .Select(definition => CreateField(definition, config))
            .ToArray();
        var form = new OperationConfigForm(fields, BuildGuidance(normalizedKind, config));
        WireDependencies(normalizedKind, config, form);
        return form;
    }

    public static string NormalizeKind(string? kind) =>
        kind?.Trim().ToLowerInvariant().Replace("-", string.Empty, StringComparison.Ordinal) switch
        {
            "dataops" => "dataops",
            "mlops" => "mlops",
            "rag" => "rag",
            "finetuning" => "finetuning",
            _ => kind?.Trim().ToLowerInvariant() ?? string.Empty
        };

    public static string GetTitle(string? kind) => NormalizeKind(kind) switch
    {
        "dataops" => "DataOps configuration",
        "mlops" => "MLOps configuration",
        "rag" => "GenAIOps · RAG configuration",
        "finetuning" => "GenAIOps · Fine-tuning configuration",
        _ => "Operation configuration"
    };

    private static OperationConfigFieldViewModel CreateField(
        FieldDefinition definition,
        JsonObject config)
    {
        IEnumerable<string> choices = definition.FallbackChoices ?? [];
        if (!string.IsNullOrWhiteSpace(definition.ChoiceSource) &&
            config[definition.ChoiceSource] is JsonArray array)
        {
            choices = ReadArray(array);
        }

        if (definition.Key == "task_type")
        {
            choices = ReadMetricCatalogs(config).Keys;
        }

        return new OperationConfigFieldViewModel(
            definition.Key,
            definition.Label,
            definition.Description,
            definition.Type,
            config[definition.Key],
            choices);
    }

    private static void WireDependencies(
        string kind,
        JsonObject config,
        OperationConfigForm form)
    {
        if (kind == "mlops")
        {
            var catalogs = ReadMetricCatalogs(config);
            var task = form.Find("task_type")!;
            var metric = form.Find("metric")!;
            void UpdateMetricChoices() =>
                metric.ReplaceChoices(
                    catalogs.TryGetValue(task.Value, out var choices)
                        ? choices
                        : []);
            task.ValueChanged += (_, _) => UpdateMetricChoices();
            UpdateMetricChoices();
        }

        if (kind == "dataops")
        {
            var windowType = form.Find("window_type")!;
            var slide = form.Find("slide_minutes")!;
            var gap = form.Find("session_gap_minutes")!;
            void UpdateVisibility()
            {
                slide.IsVisible = windowType.Value is "sliding" or "hopping";
                gap.IsVisible = windowType.Value == "session";
            }

            windowType.ValueChanged += (_, _) => UpdateVisibility();
            UpdateVisibility();
        }
    }

    private static IReadOnlyDictionary<string, string[]> ReadMetricCatalogs(JsonObject config)
    {
        var catalogs = new Dictionary<string, string[]>(StringComparer.Ordinal);
        if (config["metric_catalogs"] is JsonObject source)
        {
            foreach (var pair in source)
            {
                if (pair.Value is JsonArray values)
                {
                    catalogs[pair.Key] = ReadArray(values);
                }
            }
        }

        return catalogs.Count > 0 ? catalogs : MetricFallbacks;
    }

    private static IReadOnlyList<OperationGuidanceCard> BuildGuidance(
        string kind,
        JsonObject config)
    {
        var key = kind switch
        {
            "mlops" => "drift_explanations",
            "finetuning" => "training_guidance",
            _ => string.Empty
        };
        if (string.IsNullOrEmpty(key) || config[key] is not JsonObject guidance)
        {
            return [];
        }

        return guidance
            .Where(item => item.Value is not null)
            .Select(item => new OperationGuidanceCard(
                GuidanceTitle(kind, item.Key),
                item.Value!.GetValue<string>()))
            .ToArray();
    }

    private static string GuidanceTitle(string kind, string key)
    {
        if (kind == "mlops")
        {
            return key switch
            {
                "data" => "Data drift",
                "concept" => "Concept drift",
                "model" => "Model drift",
                _ => Humanize(key)
            };
        }

        return key switch
        {
            "SFT" => "SFT · Supervised fine-tuning",
            "DPO" => "DPO · Direct preference optimization",
            "RFT" => "RFT · Reinforcement fine-tuning",
            "baseline" => "Microsoft Foundry baseline first",
            "ranges" => "Held-out evaluation and checkpoint selection",
            _ => Humanize(key)
        };
    }

    private static string[] ReadArray(JsonArray array) =>
        array
            .Select(node => node?.GetValue<string>())
            .Where(value => !string.IsNullOrWhiteSpace(value))
            .Cast<string>()
            .ToArray();

    private static string Humanize(string key)
    {
        var text = key.Replace("_", " ", StringComparison.Ordinal);
        return string.IsNullOrWhiteSpace(text)
            ? text
            : char.ToUpperInvariant(text[0]) + text[1..];
    }

    private static FieldDefinition Text(
        string key,
        string label,
        string description,
        OperationConfigFieldType type = OperationConfigFieldType.Text) =>
        new(key, label, description, type);

    private static FieldDefinition Number(
        string key,
        string label,
        string description) =>
        new(key, label, description, OperationConfigFieldType.Number);

    private static FieldDefinition Boolean(
        string key,
        string label,
        string description) =>
        new(key, label, description, OperationConfigFieldType.Boolean);

    private static FieldDefinition Choice(
        string key,
        string label,
        string description,
        string? source = null,
        string[]? choices = null) =>
        new(
            key,
            label,
            description,
            OperationConfigFieldType.Choice,
            source,
            choices);
}

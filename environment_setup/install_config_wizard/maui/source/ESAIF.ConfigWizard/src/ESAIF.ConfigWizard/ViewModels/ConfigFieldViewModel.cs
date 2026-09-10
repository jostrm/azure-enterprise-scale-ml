using System.Globalization;
using System.Text.Json.Nodes;
using ESAIF.BaseLayer.Application;

namespace ESAIF.ConfigWizard.ViewModels;

public sealed class ConfigFieldViewModel : ObservableObject
{
    private readonly Action<string, JsonNode?> _setValue;
    private readonly JsonNode? _typeTemplate;
    private readonly IReadOnlyList<string> _schemaOptions;
    private string _value;
    private bool _booleanValue;
    private string _issueMessage = string.Empty;

    public ConfigFieldViewModel(
        string key,
        string label,
        string description,
        JsonNode? value,
        JsonNode? defaultValue,
        IReadOnlyList<string> options,
        Action<string, JsonNode?> setValue,
        NetworkModeViewModel? networkMode = null,
        HubTopologyViewModel? hubTopology = null,
        RunnerConfigurationViewModel? runnerConfiguration = null,
        ScalingModeViewModel? scalingMode = null)
    {
        Key = key;
        Label = label;
        Description = description;
        _schemaOptions = options;
        _setValue = setValue;
        NetworkMode = networkMode;
        HubTopology = hubTopology;
        RunnerConfiguration = runnerConfiguration;
        ScalingMode = scalingMode;
        _typeTemplate = value?.DeepClone() ?? defaultValue?.DeepClone();
        _value = ToDisplayValue(value);
        DefaultValue = ToDisplayValue(defaultValue);
        _booleanValue = bool.TryParse(_value, out var parsed) && parsed;
        IsBoolean = !IsScalingMode && !IsHubTopology && !IsRunnerConfiguration && IsBooleanNode(_typeTemplate);
        IsChoice = !IsScalingMode && !IsBoolean && !IsNetworkMode && !IsHubTopology && !IsRunnerConfiguration && options.Count > 0;
        IsText = !IsScalingMode && !IsBoolean && !IsChoice && !IsNetworkMode && !IsHubTopology && !IsRunnerConfiguration;
        Options = GetOptions(_value);
    }

    public string Key { get; }

    public NetworkModeViewModel? NetworkMode { get; }
    public bool IsNetworkMode => NetworkMode is not null;
    public bool IsNetworkFlag => NetworkModeViewModel.FlagKeys.Contains(Key, StringComparer.Ordinal);
    public HubTopologyViewModel? HubTopology { get; }
    public bool IsHubTopology => HubTopology is not null;
    public RunnerConfigurationViewModel? RunnerConfiguration { get; }
    public bool IsRunnerConfiguration => RunnerConfiguration is not null;
    public ScalingModeViewModel? ScalingMode { get; }
    public bool IsScalingMode => ScalingMode is not null;
    public bool IsRunnerDetail => RunnerConfigurationViewModel.DetailKeys.Contains(Key, StringComparer.Ordinal);
    public IReadOnlyList<string> DisplayOptions => Options.Select(OptionLabel).ToArray();
    public string? SelectedDisplayOption
    {
        get => SelectedOption is { } value ? OptionLabel(value) : null;
        set
        {
            if (value is not null)
            {
                SelectedOption = Options.FirstOrDefault(option => OptionLabel(option) == value) ?? value;
            }
        }
    }

    private string OptionLabel(string value) => Key == "orchestrator" ? value switch
    {
        "ado" => "Azure DevOps",
        "gha" => "GitHub",
        _ => value
    } : value;

    public string Label { get; }

    public string Description { get; }

    public string DefaultValue { get; }

    public IReadOnlyList<string> Options { get; private set; }

    public bool IsBoolean { get; }

    public bool IsChoice { get; }

    public bool IsText { get; }

    public bool IsChanged => !string.Equals(Value, DefaultValue, StringComparison.Ordinal);

    public bool IsInvalid => !string.IsNullOrWhiteSpace(IssueMessage);

    public string Value
    {
        get => _value;
        set
        {
            if (!SetProperty(ref _value, value ?? string.Empty))
            {
                return;
            }

            RefreshOptions();
            _setValue(Key, ConvertToJsonValue(_value));
            if (bool.TryParse(_value, out var parsed) &&
                SetProperty(ref _booleanValue, parsed, nameof(BooleanValue)))
            {
                OnPropertyChanged(nameof(BooleanValue));
            }

            OnPropertyChanged(nameof(IsChanged));
            OnPropertyChanged(nameof(SelectedOption));
            OnPropertyChanged(nameof(SelectedDisplayOption));
        }
    }

    public string? SelectedOption
    {
        get => Value;
        set
        {
            // MAUI clears selection while rebinding items (including hidden pickers).
            if (IsChoice && value is not null)
            {
                Value = value;
            }
        }
    }

    public bool BooleanValue
    {
        get => _booleanValue;
        set
        {
            if (!SetProperty(ref _booleanValue, value))
            {
                return;
            }

            Value = value ? "true" : "false";
        }
    }

    public string IssueMessage
    {
        get => _issueMessage;
        set
        {
            if (SetProperty(ref _issueMessage, value))
            {
                OnPropertyChanged(nameof(IsInvalid));
            }
        }
    }

    public void SynchronizeValue(JsonNode? value)
    {
        // Session-driven flag changes must update existing fields without writing back or rebuilding the form.
        if (SetProperty(ref _value, ToDisplayValue(value), nameof(Value)))
        {
            RefreshOptions();
            _booleanValue = bool.TryParse(_value, out var parsed) && parsed;
            OnPropertyChanged(nameof(BooleanValue));
            OnPropertyChanged(nameof(SelectedOption));
            OnPropertyChanged(nameof(SelectedDisplayOption));
            OnPropertyChanged(nameof(IsChanged));
        }
    }

    private IReadOnlyList<string> GetOptions(string value)
    {
        IReadOnlyList<string> options = IsChoice && !_schemaOptions.Contains(value, StringComparer.Ordinal)
            ? [.. _schemaOptions, value]
            : _schemaOptions;
        return Key == "admin_location"
            ? options.Order(StringComparer.OrdinalIgnoreCase).ToArray()
            : options;
    }

    private void RefreshOptions()
    {
        var options = GetOptions(_value);
        if (!Options.SequenceEqual(options))
        {
            Options = options;
            OnPropertyChanged(nameof(Options));
            OnPropertyChanged(nameof(DisplayOptions));
        }
    }

    private JsonNode? ConvertToJsonValue(string value)
    {
        if (_typeTemplate is JsonValue template)
        {
            if (template.TryGetValue<bool>(out _))
            {
                return JsonValue.Create(bool.TryParse(value, out var result) && result);
            }

            if (template.TryGetValue<int>(out _) &&
                int.TryParse(value, NumberStyles.Integer, CultureInfo.InvariantCulture, out var integer))
            {
                return JsonValue.Create(integer);
            }

            if (template.TryGetValue<double>(out _) &&
                double.TryParse(value, NumberStyles.Float, CultureInfo.InvariantCulture, out var number))
            {
                return JsonValue.Create(number);
            }
        }

        return JsonValue.Create(value);
    }

    private static bool IsBooleanNode(JsonNode? node)
    {
        if (node is not JsonValue value)
        {
            return false;
        }

        if (value.TryGetValue<bool>(out _))
        {
            return true;
        }

        return value.TryGetValue<string>(out var text) &&
               bool.TryParse(text, out _);
    }

    private static string ToDisplayValue(JsonNode? node)
    {
        if (node is null)
        {
            return string.Empty;
        }

        if (node is JsonValue value && value.TryGetValue<string>(out var text))
        {
            return text;
        }

        return node.ToJsonString().Trim('"');
    }
}

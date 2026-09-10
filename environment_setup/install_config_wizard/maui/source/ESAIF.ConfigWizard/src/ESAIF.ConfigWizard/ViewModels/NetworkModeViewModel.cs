using System.Text.Json.Nodes;
using ESAIF.BaseLayer.Application;

namespace ESAIF.ConfigWizard.ViewModels;

public sealed class NetworkModeViewModel : ObservableObject
{
    public static IReadOnlyList<string> FlagKeys { get; } = Array.AsReadOnly(new[]
    {
        "allowPublicAccessWhenBehindVnet", "enablePublicGenAIAccess", "enablePublicAccessWithPerimeter"
    });
    private readonly JsonObject _mappings;
    private readonly Action<string> _selectMode;
    private string? _selectedMode;
    private bool _selecting;
    private bool _notifying;

    public NetworkModeViewModel(JsonObject mappings, JsonObject state, Action<string> selectMode)
    {
        _mappings = (JsonObject)mappings.DeepClone();
        _selectMode = selectMode;
        Synchronize(state);
    }

    public bool IsPrivate { get => _selectedMode == "private"; set { if (value) Select("private"); } }
    public bool IsHybrid { get => _selectedMode == "hybrid"; set { if (value) Select("hybrid"); } }
    public bool IsPublic { get => _selectedMode == "public"; set { if (value) Select("public"); } }
    public bool CanSelectPrivate => HasMapping("private");
    public bool CanSelectHybrid => HasMapping("hybrid");
    public bool CanSelectPublic => HasMapping("public");
    public bool HasUnrecognizedFlags => _selectedMode is null;
    public string SelectionMessage => HasUnrecognizedFlags
        ? "Loaded flags do not match an API-provided mode. Values are preserved; choose a mode to replace them."
        : "Mode values come from the Python API. These settings are not applied to Azure until you deploy.";
    public string AllowPublicAccess { get; private set; } = string.Empty;
    public string PublicGenAIAccess { get; private set; } = string.Empty;
    public string PublicPerimeterAccess { get; private set; } = string.Empty;

    public void Synchronize(JsonObject state)
    {
        AllowPublicAccess = Display(state[FlagKeys[0]]);
        PublicGenAIAccess = Display(state[FlagKeys[1]]);
        PublicPerimeterAccess = Display(state[FlagKeys[2]]);
        var matches = new[] { "private", "hybrid", "public" }.Where(mode =>
            HasMapping(mode) && FlagKeys.All(key =>
                TryBoolean(state[key], out var actual) &&
                TryBoolean(_mappings[mode]![key], out var expected) && actual == expected)).ToArray();
        _selectedMode = matches.Length == 1 ? matches[0] : null;
        Notify();
    }

    private void Select(string mode)
    {
        if (_selecting || _notifying || _selectedMode == mode)
        {
            return;
        }
        if (!HasMapping(mode))
        {
            throw new InvalidOperationException($"The Python API did not provide a complete mapping for {mode}.");
        }
        _selecting = true;
        try
        {
            _selectMode(mode);
            Synchronize((JsonObject)_mappings[mode]!);
        }
        finally
        {
            _selecting = false;
        }
    }

    private bool HasMapping(string mode) =>
        _mappings[mode] is JsonObject flags && FlagKeys.All(key => TryBoolean(flags[key], out _));

    private static bool TryBoolean(JsonNode? value, out bool result) =>
        bool.TryParse(value?.ToString(), out result);

    private static string Display(JsonNode? value) => value is null ? "(not set)" :
        TryBoolean(value, out var flag) ? flag.ToString().ToLowerInvariant() : value.ToString();

    private void Notify()
    {
        if (_notifying)
        {
            return;
        }
        _notifying = true;
        try
        {
            foreach (var property in new[]
            {
                nameof(IsPrivate), nameof(IsHybrid), nameof(IsPublic), nameof(HasUnrecognizedFlags),
                nameof(SelectionMessage), nameof(AllowPublicAccess), nameof(PublicGenAIAccess), nameof(PublicPerimeterAccess)
            })
            {
                OnPropertyChanged(property);
            }
        }
        finally
        {
            _notifying = false;
        }
    }
}

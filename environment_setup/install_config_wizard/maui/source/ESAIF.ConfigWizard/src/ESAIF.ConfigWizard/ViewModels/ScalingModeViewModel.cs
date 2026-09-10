using System.Text.Json.Nodes;
using ESAIF.BaseLayer.Application;
using ESAIF.ConfigWizard.Services;
using ESAIF.DomainLayer.Configuration;

namespace ESAIF.ConfigWizard.ViewModels;

public sealed class ScalingModeViewModel : ObservableObject, IDisposable
{
    private readonly FactorySchema _schema;
    private readonly Action<string> _select;
    private readonly Action? _applyDefaults;
    private readonly INetworkPlacementClient? _placementClient;
    private readonly Action<JsonObject, JsonObject>? _applyOptimization;
    private JsonObject? _networkSnapshot;
    private NetworkPlacementPreview? _placement;
    private CancellationTokenSource? _guidanceCancellation;
    private long _networkVersion;
    private bool _disposed;
    private string _mode = string.Empty;
    private bool _selecting;

    public ScalingModeViewModel(FactorySchema schema, JsonObject state, Action<string> select, Action? applyDefaults,
        INetworkPlacementClient? placementClient = null, Action<JsonObject, JsonObject>? applyOptimization = null)
    {
        _schema = schema;
        _select = select;
        _applyDefaults = applyDefaults;
        _placementClient = placementClient;
        _applyOptimization = applyOptimization;
        Synchronize(state);
    }

    public bool IsOwn { get => _mode == ScalingModeConfiguration.Own; set { if (value) Select(ScalingModeConfiguration.Own); } }
    public bool IsShared { get => _mode == ScalingModeConfiguration.Shared; set { if (value) Select(ScalingModeConfiguration.Shared); } }
    public IReadOnlyList<VNetFormatExample> FormatExamples =>
        (_schema.Options["vnet_format_help"]?["examples"] as JsonArray)?.OfType<JsonObject>()
            .Select(example => new VNetFormatExample(example["mode"]?.ToString() ?? "",
                example["template"]?.ToString() ?? "", example["ranges"]?.ToString() ?? "")).ToArray() ?? [];
    public IReadOnlyList<string> FormatNotes =>
        (_schema.Options["vnet_format_help"]?["notes"] as JsonArray)?.Select(note => note?.ToString() ?? "").ToArray()
        ?? ["Reconnect to the updated Python API to load supported format examples. Second-octet XX placeholders are not supported yet."];
    public bool CanApplyDefaults => _applyDefaults is not null &&
        ScalingModeConfiguration.Profile(_schema, _mode)?["network_defaults"] is JsonObject defaults &&
        EnvironmentVNetAddressing.ValidationError(defaults).Length == 0;
    public string Description { get; private set; } = string.Empty;
    public string CapacityDescription { get; private set; } = string.Empty;
    public string DefaultCidr { get; private set; } = string.Empty;
    public string CurrentCidr { get; private set; } = string.Empty;
    public string PreservationMessage { get; private set; } = string.Empty;
    public string CurrentRanges { get; private set; } = string.Empty;
    public string PeeringError { get; private set; } = string.Empty;
    public string PeeringStatus => PeeringError.Length > 0 ? PeeringError :
        "Dev, Stage/Test and Prod VNet address spaces do not overlap. Peering still requires connectivity and routing configuration.";
    public string OptimizationDescription => _placement?.OptimizationDescription ?? string.Empty;
    public bool IsGuidanceLoading { get; private set; }
    public bool CanOptimize => !_disposed && !IsGuidanceLoading && PeeringError.Length == 0 && _applyOptimization is not null &&
        _placement is { IsPeerable: true, CanOptimize: true, OptimizationChanges.Count: > 0 };
    public Task GuidanceTask { get; private set; } = Task.CompletedTask;
    public string DefaultChanges => string.Join(System.Environment.NewLine,
        ScalingModeConfiguration.Defaults(_schema, _mode).Select(item => $"{item.Key}: {item.Value}"));

    public void ApplyDefaults() =>
        (_applyDefaults ?? throw new InvalidOperationException("Network default editing is unavailable."))();

    public void Synchronize(JsonObject state)
    {
        _mode = ScalingModeConfiguration.SelectedMode(state);
        var profile = ScalingModeConfiguration.Profile(_schema, _mode);
        Description = profile?["description"]?.ToString() ?? "Unknown scaling mode. Choose one of the supported modes.";
        DefaultCidr = profile?["network_defaults"]?["common_vnet_cidr"]?.ToString() ?? "Unavailable";
        CurrentCidr = state["common_vnet_cidr"]?.ToString() ?? "Not set";
        CurrentRanges = $"Common subnet starts - Dev: {Range(state, "dev_cidr_range")}, Stage/Test: {Range(state, "test_cidr_range")}, Prod: {Range(state, "prod_cidr_range")}.";
        PeeringError = EnvironmentVNetAddressing.ValidationError(state);
        PreservationMessage = ScalingModeConfiguration.MatchesProfile(state, _schema, _mode)
            ? "The draft matches this mode's network defaults. Switching mode changes only matching default addressing."
            : ScalingModeConfiguration.MatchesKnownProfile(state, _schema)
            ? "Legacy default addressing is retained. Switching mode applies its network defaults; Apply network defaults updates this mode's draft only."
            : "Existing or custom addressing is retained. Use Apply network defaults only for a new network; it replaces the draft's VNet and common subnet ranges.";
        foreach (var property in new[] { nameof(IsOwn), nameof(IsShared), nameof(CanApplyDefaults), nameof(Description),
            nameof(CapacityDescription), nameof(DefaultCidr), nameof(CurrentCidr), nameof(CurrentRanges),
            nameof(PeeringError), nameof(PeeringStatus), nameof(PreservationMessage) })
            OnPropertyChanged(property);
        var snapshot = NetworkPlacementInput.Capture(state);
        if (!JsonNode.DeepEquals(snapshot, _networkSnapshot) && !_disposed)
        {
            _networkSnapshot = snapshot;
            ++_networkVersion;
            _guidanceCancellation?.Cancel();
            _guidanceCancellation?.Dispose();
            _guidanceCancellation = new CancellationTokenSource();
            _placement = null;
            IsGuidanceLoading = _placementClient is not null;
            CapacityDescription = _placementClient is null
                ? "Capacity unavailable. Connect to the updated API to calculate from the current network settings."
                : "Calculating capacity from the current VNet and subnet ranges...";
            NotifyPlacement();
            GuidanceTask = RefreshGuidanceAsync(snapshot, _networkVersion, _guidanceCancellation.Token);
        }
    }

    private static string Range(JsonObject state, string key) =>
        string.IsNullOrWhiteSpace(state[key]?.ToString()) ? "not set" : state[key]!.ToString();

    private async Task RefreshGuidanceAsync(JsonObject snapshot, long version, CancellationToken cancellationToken)
    {
        if (_placementClient is null) return;
        try
        {
            await Task.Delay(250, cancellationToken);
            var result = await _placementClient.PreviewNetworkPlacementAsync(snapshot, cancellationToken);
            if (_disposed || version != _networkVersion) return;
            if (string.IsNullOrWhiteSpace(result.Guidance) ||
                result.CanOptimize && (result.OptimizationChanges.Count == 0 || string.IsNullOrWhiteSpace(result.OptimizationDescription)))
                throw new InvalidDataException("The API returned an incomplete network placement preview.");
            if (result.IsPeerable && result.CanOptimize)
                ScalingModeConfiguration.ApplyOptimization((JsonObject)snapshot.DeepClone(), snapshot, result.OptimizationChanges);
            _placement = result;
            CapacityDescription = PeeringError.Length > 0
                ? $"{PeeringError} Apply network defaults to create a new non-overlapping draft; existing Azure networks are not migrated."
                : result.Guidance;
        }
        catch (OperationCanceledException) when (cancellationToken.IsCancellationRequested)
        {
            return;
        }
        catch (Exception error) when (error is HttpRequestException or IOException or System.Text.Json.JsonException or
            InvalidOperationException or ArgumentException or NotSupportedException or OperationCanceledException)
        {
            if (!_disposed && version == _networkVersion)
            {
                _placement = null;
                CapacityDescription = $"Capacity unavailable for the current configuration: {error.Message}";
            }
        }
        finally
        {
            if (!_disposed && version == _networkVersion)
            {
                IsGuidanceLoading = false;
                NotifyPlacement();
            }
        }
    }

    public NetworkOptimizationConfirmation PrepareOptimization()
    {
        if (!CanOptimize || _networkSnapshot is null || _placement is null)
            throw new InvalidOperationException("Wait for a valid optimization preview for the current network settings.");
        var changes = (JsonObject)_placement.OptimizationChanges.DeepClone();
        var details = string.Join(System.Environment.NewLine,
            changes.Select(item => $"{item.Key}: {_networkSnapshot[item.Key]} -> {item.Value}"));
        return new(_networkVersion, (JsonObject)_networkSnapshot.DeepClone(), changes,
            $"{details}\n\nVNet CIDR template stays {CurrentCidr}; subnet templates and sizes stay unchanged. All three resolved VNet address spaces must remain non-overlapping.\n\nDraft only. No Azure subnets are moved. Do not use this to renumber a deployed network.");
    }

    public bool ApplyOptimization(NetworkOptimizationConfirmation confirmation)
    {
        if (_disposed || !CanOptimize || confirmation.Version != _networkVersion) return false;
        (_applyOptimization ?? throw new InvalidOperationException("Network optimization is unavailable."))(
            confirmation.Expected, confirmation.Changes);
        return true;
    }

    private void NotifyPlacement()
    {
        foreach (var property in new[] { nameof(CapacityDescription), nameof(IsGuidanceLoading),
            nameof(CanOptimize), nameof(OptimizationDescription) }) OnPropertyChanged(property);
    }

    public void Dispose()
    {
        _disposed = true;
        _guidanceCancellation?.Cancel();
        _guidanceCancellation?.Dispose();
    }

    private void Select(string mode)
    {
        if (_selecting || _mode == mode) return;
        _selecting = true;
        try
        {
            _select(mode);
        }

        finally
        {
            _selecting = false;
        }
    }
}

public sealed record NetworkOptimizationConfirmation(long Version, JsonObject Expected, JsonObject Changes, string Message);

public sealed record VNetFormatExample(string Mode, string Template, string Ranges);

using System.Collections.ObjectModel;
using System.Text.Json.Nodes;
using ESAIF.BaseLayer.Application;
using ESAIF.ConfigWizard.Services;
using ESAIF.DomainLayer.Configuration;

namespace ESAIF.ConfigWizard.ViewModels;

public sealed class FactoryConfigurationViewModel : OperationViewModel
{
    private readonly IFactoryConfigurationClient _client;
    private readonly INetworkPlacementClient? _networkPlacementClient;
    private JsonObject _state = [];
    private string _destinationFolder = string.Empty;
    private bool _isPrepared;
    private FactoryConfigurationSaveResult? _saved;
    private string _guidance = string.Empty;
    private FactorySchema? _schema;

    public FactoryConfigurationViewModel(IFactoryConfigurationClient client, INetworkPlacementClient? networkPlacementClient = null)
    {
        _client = client;
        _networkPlacementClient = networkPlacementClient;
        PropertyChanged += (_, e) =>
        {
            if (e.PropertyName == nameof(IsNotBusy))
            {
                OnPropertyChanged(nameof(CanSave));
                OnPropertyChanged(nameof(CanEdit));
            }
        };
    }

    public string Kind { get; private set; } = "factory";
    public string TargetRegion { get; private set; } = string.Empty;
    public string? SourceFolder { get; private set; }
    public string Title => Kind switch
    {
        "scale-set" => "Add AI Factory scale set",
        "clone" => "Clone AI Factory",
        _ => "Add AI Factory"
    };
    public string SaveLabel => Kind == "scale-set" ? "Save new scale set" : "Save new AI Factory";
    public bool IsNewFolder => Kind != "scale-set";
    public bool IsScaleSet => Kind == "scale-set";
    public bool HasSource => Kind != "factory";
    public bool IsPrepared => _isPrepared;
    public bool IsSaved => _saved is not null;
    public bool CanSave => IsPrepared && !IsSaved && IsNotBusy;
    public bool CanEdit => IsPrepared && !IsSaved && IsNotBusy;
    public string Guidance => _guidance;
    public string SavedPath => _saved?.Path ?? string.Empty;
    public ObservableCollection<ConfigFieldViewModel> Fields { get; } = [];
    public string DestinationFolder
    {
        get => _destinationFolder;
        set => SetProperty(ref _destinationFolder, value);
    }
    public JsonObject GetSavedState() => _saved is null
        ? throw new InvalidOperationException("Save this configuration before opening it.")
        : (JsonObject)_saved.State.DeepClone();

    public Task PrepareAsync(string kind, string region, string? sourceFolder, FactorySchema schema) =>
        ExecuteOperationAsync(async () =>
        {
            Kind = kind;
            _schema = schema;
            TargetRegion = region;
            SourceFolder = sourceFolder;
            _isPrepared = false;
            _saved = null;
            foreach (var field in Fields) field.ScalingMode?.Dispose();
            Fields.Clear();
            NotifyState();
            var prepared = await _client.PrepareFactoryConfigurationAsync(kind, region, sourceFolder);
            _state = (JsonObject)prepared.State.DeepClone();
            DestinationFolder = kind == "scale-set" ? sourceFolder ?? string.Empty : string.Empty;
            _guidance = prepared.Message;
            var catalog = WizardFieldCatalog.Build(schema, _state, SetConfigurationValue, ApplyScalingNetworkDefaults,
                _networkPlacementClient, ApplyNetworkOptimization)
                .SelectMany(step => step.Fields).ToDictionary(field => field.Key, StringComparer.Ordinal);
            var hasNetworkEditor = prepared.FieldKeys.Contains("network_mode") &&
                catalog.TryGetValue("network_mode", out var modeField) && modeField.IsNetworkMode;
            var hasRunnerEditor = prepared.FieldKeys.Contains(RunnerConfigurationViewModel.SelectionKey) &&
                catalog.TryGetValue(RunnerConfigurationViewModel.SelectionKey, out var runnerField) && runnerField.IsRunnerConfiguration;
            var hasHubEditor = prepared.FieldKeys.Contains(HubTopologyViewModel.DnsKey) &&
                catalog.TryGetValue(HubTopologyViewModel.DnsKey, out var hubField) && hubField.IsHubTopology;
            foreach (var key in prepared.FieldKeys.Where(key =>
                key != "admin_location" && WizardFieldCatalog.IsUserFacing(key)).Distinct())
            {
                if (!catalog.TryGetValue(key, out var field))
                {
                    throw new InvalidDataException($"The API returned an unknown setup field: {key}.");
                }
                if (hasNetworkEditor && field.IsNetworkFlag || hasRunnerEditor && field.IsRunnerDetail ||
                    hasHubEditor && field.Key == HubTopologyViewModel.OwnHubKey)
                {
                    continue;
                }
                Fields.Add(field);
            }
            _isPrepared = true;
            StatusMessage = "Review the settings and destination, then save. No Azure resources will be deployed.";
            NotifyState();
        }, "Preparing configuration through the Python API...");

    public Task SaveAsync() => ExecuteOperationAsync(async () =>
    {
        if (!IsPrepared || IsSaved)
        {
            throw new InvalidOperationException("Prepare an unsaved configuration first.");
        }
        if (string.IsNullOrWhiteSpace(DestinationFolder))
        {
            throw new ArgumentException("Enter a destination folder before saving.");
        }
        ConfigurationStateEditing.ValidateTopology(_state, _schema);
        _saved = await _client.SaveFactoryConfigurationAsync(
            Kind, TargetRegion, SourceFolder, DestinationFolder.Trim(), (JsonObject)_state.DeepClone());
        StatusMessage = _saved.Message;
        NotifyState();
    }, "Saving configuration files through the Python API...");

    private void SetConfigurationValue(string key, JsonNode? value)
    {
        ConfigurationStateEditing.SetValue(_state, _schema, key, value);
        SynchronizeFields();
    }

    private void ApplyScalingNetworkDefaults()
    {
        ScalingModeConfiguration.ApplyDefaults(_state, _schema);
        SynchronizeFields();
    }

    private void ApplyNetworkOptimization(JsonObject expected, JsonObject changes)
    {
        ScalingModeConfiguration.ApplyOptimization(_state, expected, changes);
        SynchronizeFields();
    }

    private void SynchronizeFields()
    {
        foreach (var field in Fields)
        {
            field.SynchronizeValue(_state[field.Key]);
            field.NetworkMode?.Synchronize(_state);
            field.HubTopology?.Synchronize(_state);
            field.RunnerConfiguration?.Synchronize(_state);
            field.ScalingMode?.Synchronize(_state);
        }
    }

    private void NotifyState()
    {
        foreach (var property in new[]
        {
            nameof(Title), nameof(SaveLabel), nameof(TargetRegion), nameof(SourceFolder),
            nameof(IsNewFolder), nameof(IsScaleSet), nameof(HasSource), nameof(IsPrepared), nameof(IsSaved),
            nameof(CanSave), nameof(CanEdit), nameof(Guidance), nameof(SavedPath)
        })
        {
            OnPropertyChanged(property);
        }
    }
}

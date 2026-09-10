using System.Collections.ObjectModel;
using ESAIF.BaseLayer.Application;
using ESAIF.DomainLayer.Configuration;
using ESAIF.ConfigWizard.Services;

namespace ESAIF.ConfigWizard.ViewModels;

public sealed class ScaleSetsViewModel : OperationViewModel
{
    private readonly IAiFactoryApiClient _api;
    private readonly WizardSession _session;
    private readonly IScaleSetConfigurationClient _configuration;
    private readonly FactoryNetworkSession _network;
    private readonly FactoryCatalogSession? _catalog;

    public ScaleSetsViewModel(IAiFactoryApiClient api, WizardSession session,
        IScaleSetConfigurationClient configuration, FactoryNetworkSession network, FactoryCatalogSession? catalog = null)
    {
        _api = api;
        _session = session;
        _configuration = configuration;
        _network = network;
        _catalog = catalog;
        if (catalog is not null) catalog.Changed += (_, _) => ApplySnapshots();
        _network.Changed += (_, _) => ApplySnapshots();
        _session.StateChanged += (_, _) => UpdateSelection();
        RefreshCommand = new AsyncCommand(RefreshAsync);
        LoadScaleSetCommand = new Command<SavedConfigurationItemViewModel>(async item => await LoadScaleSetAsync(item));
        ApplySnapshots();
    }

    public ObservableCollection<SavedConfigurationItemViewModel> ScaleSets { get; } = [];
    public AsyncCommand RefreshCommand { get; }
    public Command<SavedConfigurationItemViewModel> LoadScaleSetCommand { get; }
    public bool HasScaleSets => ScaleSets.Count > 0;

    public Task RefreshAsync() => ExecuteOperationAsync(async () =>
    {
        if (_catalog is not null)
        {
            await _catalog.RefreshAsync();
            if (!_catalog.IsLegacy) { ApplySnapshots(); return; }
        }
        await _session.InitializeAsync();
        await _network.EnsureLoadedAsync(_session.GetString("_save_folder"));
        ApplySnapshots();
    }, "Loading saved scale sets from known factories...");

    private void ApplySnapshots()
    {
        ScaleSets.Clear();
        if (_catalog is not null && !_catalog.IsLegacy)
        {
            OnPropertyChanged(nameof(HasScaleSets));
            StatusMessage = "Catalog scale sets require exact factory, environment and subscription selection. Open Manage factories; this legacy scene is not a catalog scope.";
            return;
        }
        foreach (var item in _network.Snapshots.OrderBy(snapshot => snapshot.Folder, StringComparer.OrdinalIgnoreCase)
                     .SelectMany(snapshot => snapshot.ScaleSets))
        {
            ScaleSets.Add(item);
        }
        UpdateSelection();
        OnPropertyChanged(nameof(HasScaleSets));
        Warning = _network.Warning;
        StatusMessage = $"{ScaleSets.Count} saved scale set(s) across {_network.Snapshots.Count} known factories. " +
            "Refresh Azure checks all folders and common resource group access; blue lights mean verified access.";
    }

    private void UpdateSelection()
    {
        foreach (var item in ScaleSets)
        {
            item.UpdateSelection(_session.Identity);
        }
    }

    public Task DeleteConfigurationAsync(SavedConfigurationItemViewModel item) =>
        ExecuteOperationAsync(async () =>
        {
            if (item.ScaleSet is null || !ScaleSets.Contains(item) || _network.IsRefreshing)
            {
                throw new InvalidOperationException("Wait for Refresh Azure to finish and select a current saved scale set.");
            }
            var result = await _network.DeleteConfigurationAsync(item, () =>
                _configuration.DeleteScaleSetConfigurationAsync(item.Folder, item.ScaleSet.ScaleSetId, item.Path));
            StatusMessage = $"{result.Message} Azure resources and the current editor are unchanged.";
        }, "Deleting the saved scale-set configuration only...");

    public Task LoadScaleSetAsync(SavedConfigurationItemViewModel? item) =>
        ExecuteOperationAsync(async () =>
        {
            if (item?.ScaleSet is not { } scale || !ScaleSets.Contains(item))
            {
                throw new InvalidOperationException("Select a saved scale set from the current list.");
            }
            var editedState = _session.State.ToJsonString();
            var result = await _api.LoadScaleSetAsync(item.Folder, scale.ScaleSetId);
            if (!FactoryNetworkSession.SameFolder(item.Path, result.Path))
            {
                throw new InvalidOperationException("The saved configuration path changed. Reload the list before loading.");
            }
            if (_session.State.ToJsonString() != editedState)
            {
                throw new InvalidOperationException("The editor changed while loading. Its changes were preserved; load again when ready.");
            }
            result.State["_save_folder"] = item.Folder;
            _session.ReplaceState(result.State);
            StatusMessage = $"Loaded scale set {scale.ScaleSetId} from {item.Folder}.";
            await AppShell.NavigateToWorkspaceAsync(AppShell.WizardPageKey);
        }, "Loading the selected saved scale set...");
}

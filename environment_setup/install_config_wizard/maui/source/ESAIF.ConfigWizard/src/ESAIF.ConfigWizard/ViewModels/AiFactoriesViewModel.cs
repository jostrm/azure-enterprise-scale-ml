using System.Collections.ObjectModel;
using ESAIF.BaseLayer.Application;
using ESAIF.ConfigWizard.Services;
using ESAIF.ConfigWizard.Pages;
using ESAIF.DomainLayer.Operations;
using ESAIF.DomainLayer.Configuration;

namespace ESAIF.ConfigWizard.ViewModels;

public sealed class AiFactoriesViewModel : OperationViewModel
{
    private readonly OperationsSession _operations;
    private readonly FactoryNetworkSession _network;
    private readonly IConfigurationFileService _files;
    private readonly IRegionFindingsClient _findingsClient;
    private readonly FactoryCatalogSession _catalog;
    private readonly FactoryCatalogViewModel _catalogViewModel;
    private AzureRegionInfo? _selectedRegion;
    private FactorySummary _factory = new();
    private string _sourceLabel = "Local";
    private string _missingFolderMessage = string.Empty;

    public AiFactoriesViewModel(OperationsSession operations, IConfigurationFileService files, IRegionFindingsClient findingsClient,
        FactoryNetworkSession network, FactoryCatalogSession catalog, FactoryCatalogViewModel catalogViewModel)
    {
        _operations = operations;
        _network = network;
        _catalog = catalog;
        _catalogViewModel = catalogViewModel;
        _catalog.Changed += (_, _) => ApplyOverview(_operations.Current);
        _network.Changed += (_, _) => ApplyOverview(_operations.Current);
        _files = files;
        _findingsClient = findingsClient;
        _operations.OverviewChanged += OnOverviewChanged;
        OpenWizardCommand = new AsyncCommand(
            () => AppShell.NavigateToWorkspaceAsync(AppShell.WizardPageKey));
        SelectRegionCommand = new Command<AzureRegionInfo>(region => SelectedRegion = region);
        AddFactoryCommand = new AsyncCommand(() => OpenConfigurationAsync("factory"));
        AddScaleSetCommand = new AsyncCommand(() => OpenConfigurationAsync("scale-set"));
        CloneFactoryCommand = new AsyncCommand(() => OpenConfigurationAsync("clone"));
        DeleteFactoryCommand = new AsyncCommand(() => OpenConfigurationAsync("delete"));
        ManageFactoriesCommand = new AsyncCommand(() => AppShell.NavigateToWorkspaceAsync(AppShell.FactoryCatalogPageKey));
        CloseDetailsCommand = new Command(() => SelectedRegion = null);
        ImportPipelineReportCommand = new AsyncCommand(ImportPipelineReportAsync);
        ApplyOverview(_operations.Current);
    }

    public ObservableCollection<AzureRegionInfo> Regions { get; } = [];

    public AsyncCommand OpenWizardCommand { get; }
    public AsyncCommand ImportPipelineReportCommand { get; }

    public Command<AzureRegionInfo> SelectRegionCommand { get; }

    public AsyncCommand AddFactoryCommand { get; }

    public AsyncCommand AddScaleSetCommand { get; }

    public AsyncCommand CloneFactoryCommand { get; }
    public AsyncCommand DeleteFactoryCommand { get; }
    public AsyncCommand ManageFactoriesCommand { get; }

    public Command CloseDetailsCommand { get; }

    public AzureRegionInfo? SelectedRegion
    {
        get => _selectedRegion;
        set
        {
            if (SetProperty(ref _selectedRegion, value))
            {
                OnPropertyChanged(nameof(IsRegionSelected));
                OnPropertyChanged(nameof(CanConfigureSelected));
                OnPropertyChanged(nameof(CanAddScaleSet));
                OnPropertyChanged(nameof(CanCloneSelected));
                OnPropertyChanged(nameof(CanOpenFactory));
                OnPropertyChanged(nameof(HasPipelineFindings));
                OnPropertyChanged(nameof(PipelineFindingDetails));
            }
        }
    }

    public bool IsRegionSelected => SelectedRegion is not null;
    public bool HasPipelineFindings => RegionPipelinePresentation.HasFailure(SelectedRegion);
    public string PipelineFindingDetails => RegionPipelinePresentation.Details(SelectedRegion);

    public bool CanConfigureSelected => SelectedRegion is { } region && RegionMapPresentation.IsGeographicRegion(region);

    public bool CanAddScaleSet => CanConfigureSelected;
    public bool CanOpenFactory => _catalog.IsLegacy && SelectedRegion is { HasFactory: true } region &&
        Factory.MonitoringRegions.Contains(region.Name, StringComparer.OrdinalIgnoreCase) &&
        AzureDashboardLink.Parse(Factory.DashboardUrl) is not null;
    public string DashboardHint => string.IsNullOrWhiteSpace(Factory.DashboardUrl)
        ? "Set aifactory-dash-01 to the Azure Portal dashboard URL in the current factory variables."
        : AzureDashboardLink.Parse(Factory.DashboardUrl) is null
            ? "aifactory-dash-01 must contain an HTTPS portal.azure.com dashboard link."
            : "Open the current AI Factory's existing Azure Portal dashboard in your browser.";

    public bool CanCloneSelected =>
        CanConfigureSelected;

    public FactorySummary Factory
    {
        get => _factory;
        private set => SetProperty(ref _factory, value);
    }

    public string SourceLabel
    {
        get => _sourceLabel;
        private set => SetProperty(ref _sourceLabel, value);
    }

    public string MissingFolderMessage
    {
        get => _missingFolderMessage;
        private set
        {
            if (SetProperty(ref _missingFolderMessage, value))
            {
                OnPropertyChanged(nameof(IsMissingFolder));
            }
        }
    }

    public bool IsMissingFolder => !string.IsNullOrWhiteSpace(MissingFolderMessage);

    public bool HasOverview => _catalog.IsLegacy && (_operations.HasOverview || _network.Snapshots.Count > 0);
    public string CatalogScopeNotice => _catalog.IsCatalog
        ? "This root contains a factory catalog. Use Manage factories for exact factory, scale-set and subscription selection. This legacy map does not show catalog Azure inventory."
        : "Legacy map / independently verified recent folders. Catalog operations use exact identities in Manage factories; a region is only a destination filter.";
    public string MonitoringScope => Factory.MonitoringRegions.Count == 0
        ? "Monitoring scope: current factory configuration"
        : $"Monitoring scope: {string.Join(", ", Factory.MonitoringRegions)}";

    public string Subscriptions => Factory.Subscriptions.Count > 0
        ? string.Join(
            Environment.NewLine,
            Factory.Subscriptions.Select(item => $"{item.Key}: {item.Value}"))
        : Factory.SubscriptionIds.Count > 0
            ? string.Join(Environment.NewLine, Factory.SubscriptionIds.Select((id, index) => $"Subscription {index + 1}: {id}"))
            : "Not reported";

    public Task LoadAsync(bool forceRefresh = false) =>
        ExecuteOperationAsync(async () =>
        {
            await _catalog.RefreshAsync();
            if (!_catalog.IsLegacy)
            {
                ApplyOverview(null);
                StatusMessage = CatalogScopeNotice;
                return;
            }
            var overview = await _operations.LoadAsync(
                forceRefresh,
                includeAzure: true);
            ApplyOverview(overview);
            StatusMessage = overview is null
                ? MissingFolderMessage
                : $"{Regions.Count} Azure regions loaded." +
                  (HasWarning ? " Use ! in the footer for data source details." : string.Empty);
        }, forceRefresh
            ? "Refreshing Azure regions..."
            : "Loading AI Factory regions...");

    public async Task OpenConfigurationAsync(string kind)
    {
        await ExecuteOperationAsync(async () =>
        {
            _catalogViewModel.SetIntent(kind switch
            {
                "factory" => "create-factory",
                "scale-set" => "create-scale-set",
                "clone" => "clone",
                "delete" => "delete-factory",
                _ => throw new ArgumentException("Unknown catalog action.", nameof(kind))
            }, SelectedRegion?.Name);
            await AppShell.NavigateToWorkspaceAsync(AppShell.FactoryCatalogPageKey);
        }, "Opening explicit catalog selection and review...");
    }

    private void OnOverviewChanged(object? sender, EventArgs e)
    {
        ApplyOverview(_operations.Current);
        StatusMessage = _operations.Current is null ? MissingFolderMessage : $"{Regions.Count} Azure regions loaded.";
    }

    private void ApplyOverview(OperationsOverview? overview)
    {
        var selectedName = SelectedRegion?.Name;
        Regions.Clear();
        foreach (var region in !_catalog.IsLegacy ? [] :
                     _network.Snapshots.Count > 0 ? _network.Regions : overview?.Regions ?? [])
        {
            Regions.Add(region);
        }

        Factory = _catalog.IsLegacy ? overview?.Factory ?? new FactorySummary() : new FactorySummary();
        SelectedRegion = Regions.FirstOrDefault(region =>
            string.Equals(region.Name, selectedName, StringComparison.OrdinalIgnoreCase));
        SourceLabel = _catalog.IsCatalog ? "Factory catalog · configuration inventory" :
            _network.Snapshots.Count > 0 ? "Legacy factory network · independently scoped" : _operations.SourceLabel;
        Warning = string.Join("\n\n", new[] { _operations.Warning, _network.Warning }.Where(value => value.Length > 0));
        MissingFolderMessage = _network.Snapshots.Count > 0 ? string.Empty : _operations.MissingFolderMessage;
        OnPropertyChanged(nameof(HasOverview));
        OnPropertyChanged(nameof(CatalogScopeNotice));
        OnPropertyChanged(nameof(Subscriptions));
        OnPropertyChanged(nameof(MonitoringScope));
        OnPropertyChanged(nameof(CanCloneSelected));
        OnPropertyChanged(nameof(CanAddScaleSet));
        OnPropertyChanged(nameof(CanOpenFactory));
        OnPropertyChanged(nameof(DashboardHint));
    }

    private Task ImportPipelineReportAsync() =>
        ExecuteOperationAsync(async () =>
        {
            if (!_catalog.IsLegacy)
                throw new InvalidOperationException("Pipeline report import is a legacy operation. Catalog resource ownership cannot be imported through this view.");
            var folder = RequireFolder();
            var file = await _files.PickAsync();
            if (file is null)
            {
                StatusMessage = "Pipeline report import cancelled.";
                return;
            }
            if (file.Format != "json")
            {
                throw new InvalidDataException("Select a pipeline region-report JSON file.");
            }
            var result = await _findingsClient.ImportRegionFindingsAsync(folder, file.Content);
            _operations.Invalidate();
            await _operations.LoadAsync();
            StatusMessage = result.Message;
        }, "Importing recorded pipeline findings...");

    private string RequireFolder()
    {
        var folder = _operations.Folder;
        return string.IsNullOrWhiteSpace(folder)
            ? throw new InvalidOperationException(OperationsPresentation.MissingFolderMessage)
            : folder;
    }
}

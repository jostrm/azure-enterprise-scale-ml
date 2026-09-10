using System.Collections.ObjectModel;
using System.ComponentModel;
using ESAIF.BaseLayer.Application;
using ESAIF.DomainLayer.Configuration;
using ESAIF.ConfigWizard.Services;

namespace ESAIF.ConfigWizard.ViewModels;

public sealed class ProjectsViewModel : OperationViewModel
{
    private readonly IAiFactoryApiClient _api;
    private readonly WizardSession _session;
    private readonly IProjectConfigurationClient _configuration;
    private readonly FactoryNetworkSession _network;
    private readonly FactoryCatalogSession? _catalog;
    private IReadOnlyList<SavedConfigurationItemViewModel> _allProjects = [];
    private string _selectedFactory = "All AI Factories";
    private string _environment = "All";
    private SavedConfigurationItemViewModel? _selectedProject;

    public ProjectsViewModel(IAiFactoryApiClient api, WizardSession session,
        IProjectConfigurationClient configuration, FactoryNetworkSession network, FactoryCatalogSession? catalog = null)
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
        LoadProjectCommand = new Command<SavedConfigurationItemViewModel>(async item => await LoadProjectAsync(item));
        ApplySnapshots();
    }

    public ObservableCollection<SavedConfigurationItemViewModel> Projects { get; } = [];
    public ObservableCollection<string> FactoryChoices { get; } = ["All AI Factories"];
    public SavedConfigurationItemViewModel? SelectedProject
    {
        get => _selectedProject is not null && Projects.Contains(_selectedProject) ? _selectedProject : null;
        set
        {
            if (value is null || !Projects.Contains(value) || ReferenceEquals(value, _selectedProject)) return;
            _selectedProject = value;
            ApplyHighlight();
        }
    }
    public string? SelectedFactory
    {
        get => _selectedFactory;
        set
        {
            if (value is not null && SetProperty(ref _selectedFactory, value))
            {
                ApplyFilters();
            }
        }
    }
    public bool AllEnvironments { get => _environment == "All"; set { if (value) SetEnvironment("All"); } }
    public bool DevEnvironment { get => _environment == "Dev"; set { if (value) SetEnvironment("Dev"); } }
    public bool StageEnvironment { get => _environment == "Stage"; set { if (value) SetEnvironment("Stage"); } }
    public bool ProdEnvironment { get => _environment == "Prod"; set { if (value) SetEnvironment("Prod"); } }
    public AsyncCommand RefreshCommand { get; }
    public Command<SavedConfigurationItemViewModel> LoadProjectCommand { get; }
    public bool HasProjects => Projects.Count > 0;

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
    }, "Loading saved configurations from known factories...");

    private void ApplySnapshots()
    {
        foreach (var item in _allProjects)
        {
            item.PropertyChanged -= OnProjectChanged;
        }
        _allProjects = _catalog is not null && !_catalog.IsLegacy ? [] :
            _network.Snapshots.SelectMany(snapshot => snapshot.Projects).ToArray();
        if (_selectedProject is { } previous)
            _selectedProject = _allProjects.FirstOrDefault(item =>
                FactoryNetworkSession.SameFolder(item.Folder, previous.Folder) &&
                FactoryNetworkSession.SameFolder(item.Path, previous.Path));
        foreach (var item in _allProjects)
        {
            item.PropertyChanged += OnProjectChanged;
        }
        var selected = _selectedFactory;
        FactoryChoices.Clear();
        FactoryChoices.Add("All AI Factories");
        foreach (var factory in _allProjects.Select(project => project.FactoryScaleSet).Distinct().Order(StringComparer.OrdinalIgnoreCase))
        {
            FactoryChoices.Add(factory);
        }
        _selectedFactory = FactoryChoices.Contains(selected) ? selected : "All AI Factories";
        OnPropertyChanged(nameof(SelectedFactory));
        ApplyFilters();
        UpdateSelection();
        Warning = _network.Warning;
    }

    private void OnProjectChanged(object? sender, PropertyChangedEventArgs e)
    {
        if (e.PropertyName is nameof(SavedConfigurationItemViewModel.IsResourceGroupVerified) or
            nameof(SavedConfigurationItemViewModel.DeployedEnvironments))
        {
            ApplyFilters();
        }
    }

    private void SetEnvironment(string environment)
    {
        if (_environment == environment) { return; }
        _environment = environment;
        foreach (var property in new[] { nameof(AllEnvironments), nameof(DevEnvironment), nameof(StageEnvironment), nameof(ProdEnvironment) })
        {
            OnPropertyChanged(property);
        }
        ApplyFilters();
    }

    private void ApplyFilters()
    {
        Projects.Clear();
        foreach (var project in _allProjects.Where(project => (_selectedFactory == "All AI Factories" ||
                     project.FactoryScaleSet == _selectedFactory) && project.MatchesEnvironment(_environment))
                     .OrderByDescending(project => project.IsResourceGroupVerified)
                     .ThenBy(project => project.FactoryScaleSet, StringComparer.OrdinalIgnoreCase)
                     .ThenBy(project => project.Project?.ProjectNumber, StringComparer.OrdinalIgnoreCase)
                     .ThenBy(project => project.Folder, StringComparer.OrdinalIgnoreCase))
        {
            Projects.Add(project);
        }
        OnPropertyChanged(nameof(HasProjects));
        ApplyHighlight();
        StatusMessage = $"{Projects.Count} of {_allProjects.Count} saved projects. Accessible first; status shows every observed deployment environment.";
        if (_catalog is not null && !_catalog.IsLegacy)
            StatusMessage = "Catalog projects require exact factory placements. Open Manage factories; this legacy scene is not a catalog scope.";
    }

    private void UpdateSelection()
    {
        foreach (var item in _allProjects)
        {
            item.UpdateSelection(_session.Identity);
        }
        _selectedProject ??= _allProjects.FirstOrDefault(item => item.IsSelected);
        ApplyHighlight();
    }

    private void ApplyHighlight()
    {
        foreach (var item in _allProjects) item.SetHighlight(ReferenceEquals(item, SelectedProject));
        OnPropertyChanged(nameof(SelectedProject));
    }

    public Task DeleteConfigurationAsync(SavedConfigurationItemViewModel item) =>
        ExecuteOperationAsync(async () =>
        {
            if (item.Project is null || !Projects.Contains(item) || _network.IsRefreshing)
            {
                throw new InvalidOperationException("Wait for Refresh Azure to finish and select a current saved project.");
            }
            var result = await _network.DeleteConfigurationAsync(item, () =>
                _configuration.DeleteProjectConfigurationAsync(item.Folder, item.Project.ProjectNumber, item.Path));
            StatusMessage = $"{result.Message} Azure resources and the current editor are unchanged.";
        }, "Deleting the saved project configuration only...");

    public Task LoadProjectAsync(SavedConfigurationItemViewModel? item) =>
        ExecuteOperationAsync(async () =>
        {
            if (item?.Project is not { } project || !Projects.Contains(item))
            {
                throw new InvalidOperationException("Select a saved project from the current list.");
            }
            var editedState = _session.State.ToJsonString();
            var result = await _api.LoadProjectAsync(item.Folder, project.ProjectNumber);
            if (!FactoryNetworkSession.SameFolder(item.Path, result.Path))
            {
                throw new InvalidOperationException("The saved configuration path changed. Reload the list before loading.");
            }
            if (_session.State.ToJsonString() != editedState)
            {
                throw new InvalidOperationException("The editor changed while loading. Its changes were preserved; load again when ready.");
            }
            result.State["_save_folder"] = item.Folder;
            SelectedProject = item;
            _session.ReplaceState(result.State);
            StatusMessage = $"Loaded project {project.ProjectNumber} from {item.Folder}.";
            await AppShell.NavigateToWorkspaceAsync(AppShell.WizardPageKey);
        }, "Loading the selected saved project...");
}

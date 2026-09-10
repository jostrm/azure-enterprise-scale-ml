using System.Collections.ObjectModel;
using ESAIF.BaseLayer.Application;
using ESAIF.DomainLayer.Configuration;
using ESAIF.ConfigWizard.Services;

namespace ESAIF.ConfigWizard.ViewModels;

public sealed class WizardViewModel : OperationViewModel
{
    private readonly IAiFactoryApiClient _apiClient;
    private readonly IAiFactoryFolderPickerService _folderPickerService;
    private readonly IConfigurationFileService _fileService;
    private readonly IRecentProjectLoader _recentProjectLoader;
    private readonly WizardSession _session;
    private readonly INetworkPlacementClient? _networkPlacementClient;
    private WizardStepViewModel? _currentStep;
    private string _searchText = string.Empty;
    private string _selectedExportFormat = "yaml";
    private string _exportDestinationPath = string.Empty;
    private bool _writePipelineVariables = true;
    private string _apiVersion = string.Empty;
    private bool _isDevSkuTab = true;

    public WizardViewModel(
        IAiFactoryApiClient apiClient,
        IAiFactoryFolderPickerService folderPickerService,
        IConfigurationFileService fileService,
        IRecentProjectLoader recentProjectLoader,
        WizardSession session,
        INetworkPlacementClient? networkPlacementClient = null)
    {
        _apiClient = apiClient;
        _folderPickerService = folderPickerService;
        _fileService = fileService;
        _recentProjectLoader = recentProjectLoader;
        _session = session;
        _networkPlacementClient = networkPlacementClient;
        _session.StateChanged += OnSessionStateChanged;
        _session.StateReplaced += (_, _) => MainThread.BeginInvokeOnMainThread(BuildSteps);

        PreviousCommand = new AsyncCommand(PreviousAsync);
        NextCommand = new AsyncCommand(NextAsync);
        ValidateCommand = new AsyncCommand(ValidateAsync);
        ImportCommand = new AsyncCommand(ImportAsync);
        ExportCommand = new AsyncCommand(ExportAsync);
        LoadStartupCommand = new AsyncCommand(LoadStartupAsync);
        SaveProjectCommand = new AsyncCommand(SaveProjectAsync);
        SaveScaleSetCommand = new AsyncCommand(SaveScaleSetAsync);
        ResetCommand = new AsyncCommand(ResetAsync);
        BrowseFolderCommand = new AsyncCommand(BrowseFolderAsync);
        SelectDevSkuCommand = new Command(() => IsDevSkuTab = true);
        SelectStageProdSkuCommand = new Command(() => IsDevSkuTab = false);
        SelectStepCommand = new Command<WizardStepViewModel>(step =>
        {
            if (step is not null)
            {
                CurrentStep = step;
            }
        });
    }

    public ObservableCollection<WizardStepViewModel> Steps { get; } = [];

    public ObservableCollection<ConfigFieldViewModel> VisibleFields { get; } = [];

    public ObservableCollection<ConfigFieldViewModel> VisibleSkuFields { get; } = [];
    public ObservableCollection<WizardFieldMatch> SearchResults { get; } = [];
    public bool IsSearching => !string.IsNullOrWhiteSpace(SearchText);
    public string SearchSummary => $"{SearchResults.Count} matching field(s) across all sections. Edits apply to the current configuration.";

    public ObservableCollection<ValidationIssue> ValidationIssues { get; } = [];

    public IReadOnlyList<string> ExportFormats { get; } = ["yaml", "env", "json"];

    public AsyncCommand PreviousCommand { get; }

    public AsyncCommand NextCommand { get; }

    public AsyncCommand ValidateCommand { get; }

    public AsyncCommand ImportCommand { get; }

    public AsyncCommand ExportCommand { get; }

    public AsyncCommand LoadStartupCommand { get; }

    public AsyncCommand SaveProjectCommand { get; }

    public AsyncCommand SaveScaleSetCommand { get; }

    public AsyncCommand ResetCommand { get; }

    public AsyncCommand BrowseFolderCommand { get; }

    public Command SelectDevSkuCommand { get; }

    public Command SelectStageProdSkuCommand { get; }

    public Command<WizardStepViewModel> SelectStepCommand { get; }

    public WizardStepViewModel? CurrentStep
    {
        get => _currentStep;
        set
        {
            // Native pickers emit null or stale items while a recreated page binds its items.
            if (value is null || !Steps.Contains(value) || !SetProperty(ref _currentStep, value))
            {
                return;
            }

            foreach (var step in Steps)
            {
                step.IsSelected = ReferenceEquals(step, value);
            }

            RefreshVisibleFields();
            NotifyStepProperties();
        }
    }

    public string SearchText
    {
        get => _searchText;
        set
        {
            if (SetProperty(ref _searchText, value))
            {
                RefreshVisibleFields();
            }
        }
    }

    public string SelectedExportFormat
    {
        get => _selectedExportFormat;
        set => SetProperty(ref _selectedExportFormat, value);
    }

    public string ExportDestinationPath
    {
        get => _exportDestinationPath;
        set => SetProperty(ref _exportDestinationPath, value);
    }

    public bool WritePipelineVariables
    {
        get => _writePipelineVariables;
        set => SetProperty(ref _writePipelineVariables, value);
    }

    public string ApiVersion
    {
        get => _apiVersion;
        private set => SetProperty(ref _apiVersion, value);
    }

    public ApiConnectionState Connection => _session.Connection;

    public WizardIdentity Identity => _session.Identity;

    public string AiFactoryFolder
    {
        get => _session.GetString("_save_folder");
        set
        {
            var normalized = value ?? string.Empty;
            if (string.Equals(
                    _session.GetString("_save_folder"),
                    normalized,
                    StringComparison.Ordinal))
            {
                return;
            }

            _session.SetValue("_save_folder", normalized);
            OnPropertyChanged();
        }
    }

    public bool IsReady => Steps.Count > 0;

    public bool IsReviewStep => !IsSearching && CurrentStep?.IsReview == true;

    public bool HasFields =>
        !IsSearching && CurrentStep is { IsReview: false, IsSkuStep: false };

    public bool IsSkuStep => !IsSearching && CurrentStep?.IsSkuStep == true;

    public bool IsDevSkuTab
    {
        get => _isDevSkuTab;
        set
        {
            if (SetProperty(ref _isDevSkuTab, value))
            {
                OnPropertyChanged(nameof(IsStageProdSkuTab));
                RefreshVisibleFields();
            }
        }
    }

    public bool IsStageProdSkuTab => !IsDevSkuTab;

    public bool HasValidationIssues => ValidationIssues.Count > 0;

    public bool CanGoBack => CurrentStep is not null && Steps.IndexOf(CurrentStep) > 0;

    public bool CanGoNext =>
        CurrentStep is not null &&
        Steps.IndexOf(CurrentStep) >= 0 &&
        Steps.IndexOf(CurrentStep) < Steps.Count - 1;

    public double Progress =>
        CurrentStep is null || Steps.Count == 0
            ? 0
            : (double) CurrentStep.Number / Steps.Count;

    public string CurrentTitle => CurrentStep?.Title ?? "Connect to begin";

    public string CurrentDescription =>
        CurrentStep?.Description ??
        "Open Connection in the navigation menu and enter the API key.";

    public async Task InitializeAsync()
    {
        await ExecuteOperationAsync(async () =>
        {
            var health = await _apiClient.GetHealthAsync();
            ApiVersion = health.Version;
            await _session.InitializeAsync();
            if (Steps.Count == 0 || CurrentStep is null || !Steps.Contains(CurrentStep))
            {
                BuildSteps();
            }

            StatusMessage =
                $"Connected to AIFactory Config API {health.Version}. " +
                $"{_session.Schema?.Defaults.Count ?? 0} settings loaded.";
        }, "Connecting to the local Python API...");
    }

    private Task PreviousAsync()
    {
        MoveBy(-1);
        return Task.CompletedTask;
    }

    private Task NextAsync()
    {
        MoveBy(1);
        return Task.CompletedTask;
    }

    private async Task ValidateAsync()
    {
        await ExecuteOperationAsync(async () =>
        {
            var result = await ValidateCoreAsync();
            StatusMessage = result.Valid
                ? "Configuration is valid. No unresolved values were found."
                : $"{result.Issues.Count} configuration issue(s) require attention.";
        }, "Validating with the Python API...");
    }

    private async Task ImportAsync()
    {
        await ExecuteOperationAsync(async () =>
        {
            EnsureReady();
            var file = await _fileService.PickAsync();
            if (file is null)
            {
                StatusMessage = "Import cancelled.";
                return;
            }

            var result = await _apiClient.ImportAsync(
                file.Format,
                file.Content,
                _session.State);
            _session.ReplaceState(result.State);
            StatusMessage =
                $"Imported {result.FieldsLoaded} fields from {file.Name}.";
        }, "Selecting a configuration file...");
    }

    private async Task ExportAsync()
    {
        await ExecuteOperationAsync(async () =>
        {
            EnsureReady();
            ConfigurationStateEditing.ValidateTopology(_session.State, _session.Schema);
            var serverPath = string.IsNullOrWhiteSpace(ExportDestinationPath)
                ? null
                : ExportDestinationPath.Trim();
            var result = await _apiClient.ExportAsync(
                SelectedExportFormat,
                _session.State,
                serverPath);
            var destination = result.Path ??
                              await _fileService.SaveExportAsync(
                                  SelectedExportFormat,
                                  result.Content);
            StatusMessage = $"Exported {SelectedExportFormat.ToUpperInvariant()} to {destination}.";
        }, "Rendering configuration with the Python API...");
    }

    public async Task QuickExportAsync(string format)
    {
        SelectedExportFormat = format;
        ExportDestinationPath = string.Empty;
        await ExportAsync();
    }

    public async Task<IReadOnlyList<RecentProjectChoice>> GetRecentProjectsAsync(
        string orchestrator)
    {
        var choices = new List<RecentProjectChoice>();
        await ExecuteOperationAsync(async () =>
        {
            EnsureReady();
            var result = await _apiClient.GetRecentProjectsAsync();
            choices.AddRange(
                result.RecentProjects
                    .Where(project => project.Orchestrator.Equals(
                        orchestrator,
                        StringComparison.OrdinalIgnoreCase))
                    .Select((project, index) =>
                        RecentProjectChoice.Create(index + 1, project)));
            StatusMessage = choices.Count == 0
                ? $"No recent {orchestrator.ToUpperInvariant()} projects were found."
                : $"{choices.Count} recent {orchestrator.ToUpperInvariant()} project(s) found.";
        }, $"Loading recent {orchestrator.ToUpperInvariant()} projects...");
        return choices;
    }

    public async Task LoadRecentProjectAsync(RecentProjectChoice choice)
    {
        ArgumentNullException.ThrowIfNull(choice);
        await ExecuteOperationAsync(async () =>
        {
            var result = await _recentProjectLoader.LoadAsync(choice.Project);
            _session.ReplaceState(result.State);
            StatusMessage = result.LoadedSnapshot
                ? $"Loaded project {choice.Project.Project} using its snapshot and matching current variables."
                : result.SourcePath is not null
                    ? $"Loaded project {choice.Project.Project}: imported {result.FieldsLoaded} fields from {result.SourcePath}."
                    : $"Loaded defaults for project {choice.Project.Project}; no snapshot or variable file was found.";
        }, $"Loading project {choice.Project.Project}...");
    }

    private async Task BrowseFolderAsync()
    {
        await ExecuteOperationAsync(async () =>
        {
            var folder = await _folderPickerService.PickFolderAsync(AiFactoryFolder);
            if (string.IsNullOrWhiteSpace(folder))
            {
                StatusMessage = "Folder selection cancelled.";
                return;
            }

            AiFactoryFolder = folder;
            StatusMessage = $"AI Factory folder set to {folder}.";
        }, "Opening the folder browser...");
    }

    private async Task LoadStartupAsync()
    {
        await ExecuteOperationAsync(async () =>
        {
            EnsureReady();
            var folder = RequireState("_save_folder", "AI Factory folder");
            var projectNumber = _session.GetString("project_number_000");
            if (string.IsNullOrWhiteSpace(projectNumber))
            {
                projectNumber = "001";
            }

            var result = await _apiClient.LoadStartupAsync(folder, projectNumber);
            _session.ReplaceState(result.State);
            StatusMessage = result.SourcePath is null
                ? $"No variable file was found. {result.Orchestrator.ToUpperInvariant()} defaults are loaded."
                : $"Loaded {result.FieldsLoaded} fields from {result.SourcePath}.";
        }, "Loading the AI Factory startup folder...");
    }

    private async Task SaveProjectAsync()
    {
        await ExecuteOperationAsync(async () =>
        {
            EnsureReady();
            var validation = await ValidateCoreAsync();
            if (!validation.Valid)
            {
                StatusMessage =
                    $"Project was not saved. Resolve {validation.Issues.Count} validation issue(s).";
                return;
            }

            var folder = RequireState("_save_folder", "AI Factory folder");
            var projectNumber = RequireState("project_number_000", "Project number");
            if (!projectNumber.All(char.IsAsciiDigit))
            {
                throw new InvalidOperationException(
                    "Project number must contain digits only.");
            }

            var result = await _apiClient.SaveProjectAsync(
                _session.State,
                WritePipelineVariables);
            await _apiClient.RecordRecentProjectAsync(
                folder,
                projectNumber,
                _session.GetString("orchestrator"),
                _session.GetString("admin_aifactoryPrefixRG"),
                _session.GetString("admin_aifactorySuffixRG"));
            StatusMessage = result.VariablesPath is null
                ? $"Project snapshot saved to {result.SnapshotPath}."
                : $"Project and pipeline variables saved to {result.VariablesPath}.";
        }, "Validating and saving the project...");
    }

    private async Task SaveScaleSetAsync()
    {
        await ExecuteOperationAsync(async () =>
        {
            EnsureReady();
            RequireState("_save_folder", "AI Factory folder");
            RequireState("admin_aifactorySuffixRG", "Scale-set resource group suffix");
            ConfigurationStateEditing.ValidateTopology(_session.State, _session.Schema);
            var result = await _apiClient.SaveScaleSetAsync(_session.State);
            StatusMessage = $"Scale set saved to {result.Path}.";
        }, "Saving the scale set...");
    }

    private async Task ResetAsync()
    {
        await ExecuteOperationAsync(async () =>
        {
            await _session.InitializeAsync(force: true);
            StatusMessage = "Configuration reset to the Python API defaults.";
        }, "Reloading defaults...");
    }

    private async Task<ValidationResult> ValidateCoreAsync()
    {
        ConfigurationStateEditing.ValidateTopology(_session.State, _session.Schema);
        foreach (var field in Steps.SelectMany(step => step.Fields))
        {
            field.IssueMessage = string.Empty;
        }

        ValidationIssues.Clear();
        OnPropertyChanged(nameof(HasValidationIssues));
        var result = await _apiClient.ValidateAsync(_session.State);
        var fields = Steps
            .SelectMany(step => step.Fields)
            .ToDictionary(field => field.Key, StringComparer.Ordinal);
        foreach (var issue in result.Issues)
        {
            ValidationIssues.Add(issue);
            if (fields.TryGetValue(issue.Field, out var field))
            {
                field.IssueMessage = issue.Message;
            }
        }

        OnPropertyChanged(nameof(HasValidationIssues));
        return result;
    }

    private void MoveBy(int offset)
    {
        if (CurrentStep is null)
        {
            return;
        }

        var target = Steps.IndexOf(CurrentStep) + offset;
        if (target >= 0 && target < Steps.Count)
        {
            CurrentStep = Steps[target];
        }
    }

    private void BuildSteps()
    {
        if (_session.Schema is null)
        {
            return;
        }

        var selectedNumber = CurrentStep?.Number ?? 1;
        foreach (var field in Steps.SelectMany(step => step.Fields)) field.ScalingMode?.Dispose();
        Steps.Clear();
        foreach (var step in WizardFieldCatalog.Build(
                     _session.Schema,
                     _session.State,
                     _session.SetValue,
                     _session.ApplyScalingNetworkDefaults, _networkPlacementClient, _session.ApplyNetworkOptimization))
        {
            Steps.Add(step);
        }

        CurrentStep = Steps.FirstOrDefault(step => step.Number == selectedNumber) ??
                      Steps.FirstOrDefault();
        OnPropertyChanged(nameof(AiFactoryFolder));
        OnPropertyChanged(nameof(IsReady));
    }

    private void RefreshVisibleFields()
    {
        VisibleFields.Clear();
        VisibleSkuFields.Clear();
        SearchResults.Clear();
        foreach (var match in WizardFieldSearch.Find(Steps, SearchText))
        {
            SearchResults.Add(match);
        }
        OnPropertyChanged(nameof(IsSearching));
        OnPropertyChanged(nameof(SearchSummary));
        NotifyStepProperties();
        if (CurrentStep is null)
        {
            return;
        }

        foreach (var field in WizardFieldSearch.EditableCards(CurrentStep.Fields))
        {
            VisibleFields.Add(field);
        }

        if (!CurrentStep.IsSkuStep)
        {
            return;
        }

        var skuFields = IsDevSkuTab
            ? CurrentStep.DevSkuFields
            : CurrentStep.StageProdSkuFields;
        foreach (var field in skuFields)
        {
            VisibleSkuFields.Add(field);
        }
    }

    private void NotifyStepProperties()
    {
        OnPropertyChanged(nameof(IsReviewStep));
        OnPropertyChanged(nameof(HasFields));
        OnPropertyChanged(nameof(IsSkuStep));
        OnPropertyChanged(nameof(CanGoBack));
        OnPropertyChanged(nameof(CanGoNext));
        OnPropertyChanged(nameof(Progress));
        OnPropertyChanged(nameof(CurrentTitle));
        OnPropertyChanged(nameof(CurrentDescription));
    }

    private void EnsureReady()
    {
        if (!_session.IsInitialized)
        {
            throw new InvalidOperationException(
                "Connect to the Python API before using configuration operations.");
        }
    }

    private string RequireState(string key, string label)
    {
        var value = _session.GetString(key).Trim();
        return string.IsNullOrWhiteSpace(value)
            ? throw new InvalidOperationException($"{label} is required.")
            : value;
    }

    private void OnSessionStateChanged(object? sender, EventArgs e)
    {
        MainThread.BeginInvokeOnMainThread(() =>
        {
            OnPropertyChanged(nameof(Identity));
            OnPropertyChanged(nameof(AiFactoryFolder));
            foreach (var field in Steps.SelectMany(step => step.Fields))
            {
                field.SynchronizeValue(_session.State[field.Key]);
                field.NetworkMode?.Synchronize(_session.State);
                field.HubTopology?.Synchronize(_session.State);
                field.RunnerConfiguration?.Synchronize(_session.State);
                field.ScalingMode?.Synchronize(_session.State);
            }
        });
    }

    protected override void OnOperationFailed(Exception exception)
    {
        if (exception is HttpRequestException or TaskCanceledException or System.Text.Json.JsonException)
        {
            Connection.MarkFailed(exception);
        }
    }
}

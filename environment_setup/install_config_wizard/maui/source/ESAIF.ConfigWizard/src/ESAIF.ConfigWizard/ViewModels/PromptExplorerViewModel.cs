using System.Collections.ObjectModel;
using ESAIF.BaseLayer.Application;
using ESAIF.BaseLayer.Monitoring;
using ESAIF.ConfigWizard.Services;
using ESAIF.DomainLayer.Configuration;
using ESAIF.DomainLayer.Operations;

namespace ESAIF.ConfigWizard.ViewModels;

public sealed class PromptExplorerViewModel : OperationViewModel
{
    private readonly IAiFactoryApiClient _apiClient;
    private readonly WizardSession _wizardSession;
    private string _searchText = string.Empty;
    private string _selectedProject = OperationsPresentation.AllFilter;
    private string _selectedEnvironment = OperationsPresentation.AllFilter;
    private string _selectedModel = OperationsPresentation.AllFilter;
    private string _selectedCategory = OperationsPresentation.AllFilter;
    private string _selectedSuccess = OperationsPresentation.AllFilter;
    private PromptTelemetryRecord? _selectedPrompt;
    private string _sourceLabel = "Local";
    private string _missingFolderMessage = string.Empty;
    private string _requests = "0";
    private string _inputTokens = "0";
    private string _cachedTokens = "0";
    private string _outputTokens = "0";
    private string _successRate = "0%";

    public PromptExplorerViewModel(
        IAiFactoryApiClient apiClient,
        WizardSession wizardSession)
    {
        _apiClient = apiClient;
        _wizardSession = wizardSession;
        SearchCommand = new AsyncCommand(SearchAsync);
        ClearCommand = new AsyncCommand(ClearAsync);
        OpenWizardCommand = new AsyncCommand(
            () => AppShell.NavigateToWorkspaceAsync(AppShell.WizardPageKey));
        InitializeOptions();
    }

    public ObservableCollection<PromptTelemetryRecord> Rows { get; } = [];
    public ObservableCollection<string> Projects { get; } = [];
    public ObservableCollection<string> Environments { get; } = [];
    public ObservableCollection<string> Models { get; } = [];
    public ObservableCollection<string> Categories { get; } = [];
    public ObservableCollection<string> SuccessOptions { get; } = [];

    public AsyncCommand SearchCommand { get; }

    public AsyncCommand ClearCommand { get; }

    public AsyncCommand OpenWizardCommand { get; }

    public string SearchText
    {
        get => _searchText;
        set => SetProperty(ref _searchText, value);
    }

    public string SelectedProject
    {
        get => _selectedProject;
        set => SetProperty(ref _selectedProject, value);
    }

    public string SelectedEnvironment
    {
        get => _selectedEnvironment;
        set => SetProperty(ref _selectedEnvironment, value);
    }

    public string SelectedModel
    {
        get => _selectedModel;
        set => SetProperty(ref _selectedModel, value);
    }

    public string SelectedCategory
    {
        get => _selectedCategory;
        set => SetProperty(ref _selectedCategory, value);
    }

    public string SelectedSuccess
    {
        get => _selectedSuccess;
        set => SetProperty(ref _selectedSuccess, value);
    }

    public PromptTelemetryRecord? SelectedPrompt
    {
        get => _selectedPrompt;
        set
        {
            if (SetProperty(ref _selectedPrompt, value))
            {
                OnPropertyChanged(nameof(HasSelection));
                OnPropertyChanged(nameof(HasNoSelection));
            }
        }
    }

    public bool HasSelection => SelectedPrompt is not null;

    public bool HasNoSelection => SelectedPrompt is null;

    public bool HasRows => Rows.Count > 0;

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

    public string Requests
    {
        get => _requests;
        private set => SetProperty(ref _requests, value);
    }

    public string InputTokens
    {
        get => _inputTokens;
        private set => SetProperty(ref _inputTokens, value);
    }

    public string CachedTokens
    {
        get => _cachedTokens;
        private set => SetProperty(ref _cachedTokens, value);
    }

    public string OutputTokens
    {
        get => _outputTokens;
        private set => SetProperty(ref _outputTokens, value);
    }

    public string SuccessRate
    {
        get => _successRate;
        private set => SetProperty(ref _successRate, value);
    }

    public Task SearchAsync()
    {
        return ExecuteOperationAsync(async () =>
        {
            await _wizardSession.InitializeAsync();
            var folder = _wizardSession.GetString("_save_folder").Trim();
            MissingFolderMessage = string.IsNullOrWhiteSpace(folder)
                ? OperationsPresentation.MissingFolderMessage
                : string.Empty;
            if (IsMissingFolder)
            {
                ClearResults();
                StatusMessage = MissingFolderMessage;
                return;
            }

            var result = await _apiClient.SearchPromptsAsync(
                folder,
                OperationsPresentation.NormalizeOptionalFilter(SelectedProject),
                OperationsPresentation.NormalizeOptionalFilter(SelectedEnvironment),
                OperationsPresentation.NormalizeOptionalFilter(SelectedModel),
                OperationsPresentation.NormalizeOptionalFilter(SelectedCategory),
                OperationsPresentation.NormalizeOptionalFilter(SearchText),
                OperationsPresentation.ParseSuccessFilter(SelectedSuccess));
            ApplyResult(result);
        }, "Searching local prompt telemetry...");
    }

    private async Task ClearAsync()
    {
        SearchText = string.Empty;
        SelectedProject = OperationsPresentation.AllFilter;
        SelectedEnvironment = OperationsPresentation.AllFilter;
        SelectedModel = OperationsPresentation.AllFilter;
        SelectedCategory = OperationsPresentation.AllFilter;
        SelectedSuccess = OperationsPresentation.AllFilter;
        await SearchAsync();
    }

    private void ApplyResult(OperationsPromptSearchResult result)
    {
        Rows.Clear();
        foreach (var row in result.Rows)
        {
            Rows.Add(row);
        }

        SelectedPrompt = Rows.FirstOrDefault();
        ReplaceOptions(Projects, result.Filters.ProjectNumbers, SelectedProject);
        ReplaceOptions(Environments, result.Filters.Environments, SelectedEnvironment);
        ReplaceOptions(Models, result.Filters.Models, SelectedModel);
        ReplaceOptions(Categories, result.Filters.Categories, SelectedCategory);

        SourceLabel = OperationsPresentation.GetSourceLabel(result.Source);
        Warning = result.Warning?.Trim() ?? string.Empty;
        ApplySummary(result.Summary);
        OnPropertyChanged(nameof(HasRows));
        StatusMessage = result.Total == 0
            ? "No prompt records match the current filters."
            : $"Showing {Rows.Count:N0} of {result.Total:N0} prompt record(s).";
    }

    private void ApplySummary(PromptSummary summary)
    {
        Requests = summary.RecordCount.ToString("N0");
        InputTokens = Math.Max(0, summary.InputTokens).ToString("N0");
        CachedTokens = Math.Max(0, summary.CachedInputTokens).ToString("N0");
        OutputTokens = Math.Max(0, summary.OutputTokens).ToString("N0");
        SuccessRate = $"{OperationsPresentation.GetSuccessRate(summary):0.#}%";
    }

    private void ClearResults()
    {
        Rows.Clear();
        SelectedPrompt = null;
        Warning = string.Empty;
        ApplySummary(new PromptSummary());
        OnPropertyChanged(nameof(HasRows));
    }

    private void InitializeOptions()
    {
        ReplaceOptions(Projects, [], OperationsPresentation.AllFilter);
        ReplaceOptions(Environments, [], OperationsPresentation.AllFilter);
        ReplaceOptions(Models, [], OperationsPresentation.AllFilter);
        ReplaceOptions(Categories, [], OperationsPresentation.AllFilter);
        SuccessOptions.Add(OperationsPresentation.AllFilter);
        SuccessOptions.Add("Success");
        SuccessOptions.Add("Errors");
    }

    private static void ReplaceOptions(
        ObservableCollection<string> target,
        IEnumerable<string> values,
        string selectedValue)
    {
        target.Clear();
        target.Add(OperationsPresentation.AllFilter);
        foreach (var value in values
                     .Where(value => !string.IsNullOrWhiteSpace(value))
                     .Distinct(StringComparer.OrdinalIgnoreCase)
                     .OrderBy(value => value, StringComparer.OrdinalIgnoreCase))
        {
            target.Add(value);
        }

        if (!target.Contains(selectedValue, StringComparer.OrdinalIgnoreCase))
        {
            target.Add(selectedValue);
        }
    }
}

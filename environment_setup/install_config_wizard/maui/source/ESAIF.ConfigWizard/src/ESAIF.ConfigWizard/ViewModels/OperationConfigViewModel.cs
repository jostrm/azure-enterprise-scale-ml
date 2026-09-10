using System.Collections.ObjectModel;
using ESAIF.BaseLayer.Application;
using ESAIF.ConfigWizard.Services;
using ESAIF.DomainLayer.Configuration;

namespace ESAIF.ConfigWizard.ViewModels;

public sealed class OperationConfigViewModel : OperationViewModel, IQueryAttributable
{
    private readonly IAiFactoryApiClient _apiClient;
    private readonly WizardSession _wizard;
    private OperationConfigForm? _form;
    private string _projectNumber = string.Empty;
    private string _environment = string.Empty;
    private string _kind = string.Empty;
    private string _title = "Operation configuration";
    private string _subtitle = string.Empty;
    private string _sourceLabel = "API";
    private string _savedStatus = string.Empty;
    private bool _queryChanged;

    public OperationConfigViewModel(
        IAiFactoryApiClient apiClient,
        WizardSession wizard)
    {
        _apiClient = apiClient;
        _wizard = wizard;
        SaveCommand = new AsyncCommand(SaveAsync);
        BackCommand = new AsyncCommand(AppShell.GoBackAsync);
    }

    public ObservableCollection<OperationConfigFieldViewModel> Fields { get; } = [];

    public ObservableCollection<OperationGuidanceCard> Guidance { get; } = [];

    public AsyncCommand SaveCommand { get; }

    public AsyncCommand BackCommand { get; }

    public string ProjectNumber
    {
        get => _projectNumber;
        private set => SetProperty(ref _projectNumber, value);
    }

    public string Environment
    {
        get => _environment;
        private set => SetProperty(ref _environment, value);
    }

    public string Kind
    {
        get => _kind;
        private set => SetProperty(ref _kind, value);
    }

    public string Title
    {
        get => _title;
        private set => SetProperty(ref _title, value);
    }

    public string Subtitle
    {
        get => _subtitle;
        private set => SetProperty(ref _subtitle, value);
    }

    public string SourceLabel
    {
        get => _sourceLabel;
        private set => SetProperty(ref _sourceLabel, value);
    }

    public string SavedStatus
    {
        get => _savedStatus;
        private set => SetProperty(ref _savedStatus, value);
    }

    public bool HasGuidance => Guidance.Count > 0;

    public void ApplyQueryAttributes(IDictionary<string, object> query)
    {
        ProjectNumber = ReadQuery(query, "projectNumber");
        Environment = ReadQuery(query, "environment").ToLowerInvariant();
        Kind = OperationConfigFormFactory.NormalizeKind(ReadQuery(query, "kind"));
        Title = OperationConfigFormFactory.GetTitle(Kind);
        Subtitle = $"Project {ProjectNumber} / {Capitalize(Environment)}";
        _queryChanged = true;
    }

    public async Task LoadAsync()
    {
        if (!_queryChanged && _form is not null)
        {
            return;
        }

        await ExecuteOperationAsync(async () =>
        {
            ValidateRoute();
            await _wizard.InitializeAsync();
            var result = await _apiClient.LoadOperationsConfigAsync(
                RequireFolder(),
                ProjectNumber,
                Environment,
                Kind);
            _form = OperationConfigFormFactory.Create(Kind, result.Config);
            Replace(Fields, _form.Fields);
            Replace(Guidance, _form.Guidance);
            SourceLabel = result.IsSaved ? "Saved configuration" : "API defaults";
            SavedStatus = result.IsSaved
                ? $"Saved {FormatTimestamp(result.UpdatedAt)}"
                : "Not saved";
            StatusMessage = "Configuration loaded from the API.";
            _queryChanged = false;
            OnPropertyChanged(nameof(HasGuidance));
        }, "Loading operation configuration...");
    }

    public async Task SaveAsync()
    {
        if (_form is null)
        {
            StatusMessage = "Load the operation configuration before saving.";
            return;
        }

        if (!_form.TryBuildConfig(out var config, out var validationMessage))
        {
            StatusMessage = validationMessage;
            return;
        }

        await ExecuteOperationAsync(async () =>
        {
            var result = await _apiClient.SaveOperationsConfigAsync(
                RequireFolder(),
                ProjectNumber,
                Environment,
                Kind,
                config);
            SourceLabel = "Saved configuration";
            SavedStatus = $"Saved {FormatTimestamp(result.UpdatedAt)}";
            StatusMessage = "Configuration saved through the API.";
        }, "Saving operation configuration...");
    }

    private void ValidateRoute()
    {
        if (string.IsNullOrWhiteSpace(ProjectNumber) ||
            string.IsNullOrWhiteSpace(Environment) ||
            string.IsNullOrWhiteSpace(Kind))
        {
            throw new InvalidOperationException(
                "Project number, environment, and operation kind are required.");
        }
    }

    private string RequireFolder()
    {
        var folder = _wizard.GetString("_save_folder").Trim();
        return string.IsNullOrWhiteSpace(folder)
            ? throw new InvalidOperationException(OperationsPresentation.MissingFolderMessage)
            : folder;
    }

    private static string ReadQuery(
        IDictionary<string, object> query,
        string key) =>
        query.TryGetValue(key, out var value)
            ? value?.ToString() ?? string.Empty
            : string.Empty;

    private static string Capitalize(string value) =>
        string.IsNullOrWhiteSpace(value)
            ? string.Empty
            : char.ToUpperInvariant(value[0]) + value[1..];

    private static string FormatTimestamp(string? timestamp) =>
        DateTimeOffset.TryParse(timestamp, out var value)
            ? value.ToLocalTime().ToString("g")
            : timestamp ?? "now";

    private static void Replace<T>(
        ObservableCollection<T> target,
        IEnumerable<T> source)
    {
        target.Clear();
        foreach (var item in source)
        {
            target.Add(item);
        }
    }
}

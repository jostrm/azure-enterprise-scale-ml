using ESAIF.DomainLayer.Configuration;
using ESAIF.ConfigWizard.Services;

namespace ESAIF.ConfigWizard.ViewModels;

public sealed class ConnectionViewModel : OperationViewModel
{
    private readonly IAiFactoryApiClient _apiClient;
    private readonly IConnectionSettingsService _settingsService;
    private readonly WizardSession _session;
    private readonly IRecentProjectLoader _recentProjectLoader;
    private readonly IBundledApiHost? _bundledApiHost;
    private bool _verified;
    private string _baseAddress = AiFactoryConnection.LocalDefault.BaseAddress;
    private string _apiKey = string.Empty;

    public ConnectionViewModel(
        IAiFactoryApiClient apiClient,
        IConnectionSettingsService settingsService,
        WizardSession session,
        IRecentProjectLoader recentProjectLoader,
        IBundledApiHost? bundledApiHost = null)
    {
        _apiClient = apiClient;
        _settingsService = settingsService;
        _session = session;
        _recentProjectLoader = recentProjectLoader;
        _bundledApiHost = bundledApiHost;
        _session.Connection.PropertyChanged += (_, e) =>
        {
            if (e.PropertyName == nameof(ApiConnectionState.IsConnected))
            {
                OnPropertyChanged(nameof(IsConnected));
            }
        };
    }

    public string BaseAddress
    {
        get => _baseAddress;
        set => SetProperty(ref _baseAddress, value);
    }

    public string ApiKey
    {
        get => _apiKey;
        set => SetProperty(ref _apiKey, value);
    }

    public bool IsConnected => _session.Connection.IsConnected;
    public bool UsesBundledApi => _bundledApiHost?.IsAvailable == true;
    public bool NeedsManualConnection => !UsesBundledApi;
    public string ConnectionModeDescription => UsesBundledApi
        ? "The bundled API starts automatically and is available only to this Windows device."
        : "Enter an authenticated HTTPS companion API. A phone cannot use the Windows localhost address.";

    public Uri GetDocumentationUri()
    {
        return new AiFactoryConnection(BaseAddress.Trim(), ApiKey).DocumentationUri;
    }

    public async Task LoadAsync()
    {
        await ExecuteOperationAsync(async () =>
        {
            var connection = await _settingsService.GetConnectionAsync();
            BaseAddress = connection.BaseAddress;
            ApiKey = connection.ApiKey;
            StatusMessage = UsesBundledApi
                ? "Bundled API settings loaded. Connect to open the wizard."
                : string.IsNullOrWhiteSpace(ApiKey)
                ? "Enter the API key, then connect to open the wizard."
                : "A saved API key is available. Connect to verify it and open the wizard.";
        }, "Loading connection settings...");
    }

    public async Task<bool> ConnectAsync()
    {
        if (IsBusy)
        {
            return false;
        }

        await ExecuteOperationAsync(async () =>
        {
            _verified = false;
            _session.Connection.BeginVerification();
            if (UsesBundledApi)
            {
                await _bundledApiHost!.StartAsync();
                var connection = await _settingsService.GetConnectionAsync();
                BaseAddress = connection.BaseAddress;
                ApiKey = connection.ApiKey;
            }
            else
            {
                await SaveCoreAsync();
            }
            var health = await _apiClient.GetHealthAsync();
            await _session.RefreshSchemaAsync();
            _verified = true;
            Warning = string.Empty;
            var restored = await RestoreRecentProjectAsync();
            StatusMessage =
                $"Connected to API {health.Version}. " +
                $"{_session.Schema?.Defaults.Count ?? 0} settings are ready." + restored;
        }, "Saving credentials and connecting to the Python API...");
        return IsConnected;
    }

    private async Task<string> RestoreRecentProjectAsync()
    {
        if (!string.IsNullOrWhiteSpace(_session.GetString("_save_folder")))
        {
            return " Current factory and edits preserved.";
        }
        var before = _session.State.DeepClone();
        try
        {
            var recent = (await _apiClient.GetRecentProjectsAsync()).RecentProjects.FirstOrDefault();
            if (recent is null)
            {
                return " No recent project is available; choose an AI Factory folder.";
            }
            if (string.IsNullOrWhiteSpace(recent.Folder) ||
                string.IsNullOrWhiteSpace(recent.Project) || !recent.Project.All(char.IsAsciiDigit) ||
                recent.Orchestrator is not ("ado" or "gha"))
            {
                throw new InvalidDataException("The most recent project has an invalid folder, project number, or orchestrator.");
            }
            if (!System.Text.Json.Nodes.JsonNode.DeepEquals(before, _session.State))
            {
                return " Current edits preserved.";
            }
            var loaded = await _recentProjectLoader.LoadAsync(recent);
            if (!System.Text.Json.Nodes.JsonNode.DeepEquals(before, _session.State))
            {
                return " Current edits preserved.";
            }
            var state = (System.Text.Json.Nodes.JsonObject)loaded.State.DeepClone();
            state["_save_folder"] = recent.Folder.Trim();
            _session.ReplaceState(state);
            return $" Loaded most recent project {recent.Project} and its AI Factory folder.";
        }
        catch (Exception exception) when (exception is HttpRequestException or IOException or
            InvalidOperationException or ArgumentException or System.Text.Json.JsonException or OperationCanceledException)
        {
            Warning = $"Connected to the API, but the most recent project could not be restored: {exception.Message}";
            return " Select a recent project or folder to continue.";
        }
    }

    protected override void OnOperationFailed(Exception exception)
    {
        if (!_verified)
        {
            _session.Connection.MarkFailed(exception);
        }
    }

    private Task SaveCoreAsync()
    {
        return _settingsService.SaveConnectionAsync(
            new AiFactoryConnection(BaseAddress.Trim(), ApiKey));
    }
}

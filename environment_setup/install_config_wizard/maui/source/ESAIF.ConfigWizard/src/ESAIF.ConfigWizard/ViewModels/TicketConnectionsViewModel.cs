using ESAIF.BaseLayer.Application;
using ESAIF.ConfigWizard.Services;
using ESAIF.DomainLayer.Configuration;

namespace ESAIF.ConfigWizard.ViewModels;

public sealed class TicketConnectionsViewModel : OperationViewModel
{
    private readonly ITicketClient _client;
    private TicketConnection? _selectedConnection;
    private string _name = string.Empty;
    private string _provider = "Jira";
    private string _baseUrl = string.Empty;
    private string _projectKey = string.Empty;
    private string _username = string.Empty;
    private string _credentialEnv = string.Empty;
    private long _identityVersion;

    public TicketConnectionsViewModel(ITicketClient client, AzureAuthenticationMonitor? authentication = null)
    {
        _client = client;
        if (authentication is not null)
        {
            var identity = (authentication.IsLoggedIn, authentication.Status.AccountName, authentication.Status.TenantId);
            authentication.PropertyChanged += (_, e) =>
            {
                if (e.PropertyName != nameof(AzureAuthenticationMonitor.Status)) return;
                var current = (authentication.IsLoggedIn, authentication.Status.AccountName, authentication.Status.TenantId);
                if (identity == current) return;
                identity = current;
                ++_identityVersion;
                NewProfile();
                Connections = [];
                NotifyConnections();
                ConnectionsChanged?.Invoke(this, EventArgs.Empty);
                StatusMessage = "Azure identity changed. Reload your own profiles before continuing.";
            };
        }
        ReloadCommand = new AsyncCommand(LoadAsync);
        SaveCommand = new AsyncCommand(SaveAsync);
        NewCommand = new AsyncCommand(() => { NewProfile(); return Task.CompletedTask; });
        OpenTicketsCommand = new AsyncCommand(() => AppShell.NavigateToWorkspaceAsync(AppShell.TicketsPageKey));
    }

    public AsyncCommand ReloadCommand { get; }
    public AsyncCommand SaveCommand { get; }
    public AsyncCommand NewCommand { get; }
    public AsyncCommand OpenTicketsCommand { get; }
    public event EventHandler? ConnectionsChanged;
    public IReadOnlyList<string> Providers => TicketChoices.Providers;
    public IReadOnlyList<TicketConnection> Connections { get; private set; } = [];
    public bool IsEmpty => Connections.Count == 0;
    public string Name { get => _name; set => SetProperty(ref _name, value); }
    public string Provider { get => _provider; set => SetProperty(ref _provider, value); }
    public string BaseUrl { get => _baseUrl; set => SetProperty(ref _baseUrl, value); }
    public string ProjectKey { get => _projectKey; set => SetProperty(ref _projectKey, value); }
    public string Username { get => _username; set => SetProperty(ref _username, value); }
    public string CredentialEnv { get => _credentialEnv; set => SetProperty(ref _credentialEnv, value); }
    public TicketConnection? SelectedConnection
    {
        get => _selectedConnection;
        set
        {
            if (!SetProperty(ref _selectedConnection, value)) return;
            Populate(value);
        }
    }

    public Task LoadAsync() => ExecuteOperationAsync(async () =>
    {
        NewProfile();
        Connections = [];
        NotifyConnections();
        var version = _identityVersion;
        var result = await _client.ListTicketConnectionsAsync();
        if (version != _identityVersion) return;
        Connections = result.Connections;
        NotifyConnections();
        ConnectionsChanged?.Invoke(this, EventArgs.Empty);
        StatusMessage = "Loaded your connector profiles. Not tested; no external communication performed.";
    }, "Loading your profiles (Azure sign-in required)...");

    public Task SaveAsync() => ExecuteOperationAsync(async () =>
    {
        Warning = string.Empty;
        if (string.IsNullOrWhiteSpace(Name) || string.IsNullOrWhiteSpace(BaseUrl) || string.IsNullOrWhiteSpace(CredentialEnv))
            throw new InvalidOperationException("Enter a profile name, HTTPS base URL, and Python-host environment variable name.");
        if (!System.Text.RegularExpressions.Regex.IsMatch(CredentialEnv.Trim(), "^[A-Za-z_][A-Za-z0-9_]*$"))
            throw new InvalidOperationException("Credential environment must be a variable name (for example JIRA_API_TOKEN), not a secret value.");
        if (Provider == "Jira" && string.IsNullOrWhiteSpace(ProjectKey))
            throw new InvalidOperationException("Enter the Jira project key.");
        var version = _identityVersion;
        var saved = await _client.SaveTicketConnectionAsync(new TicketConnection
        {
            Id = SelectedConnection?.Id,
            Name = Name.Trim(),
            Provider = Provider,
            BaseUrl = BaseUrl.Trim(),
            ProjectKey = Optional(ProjectKey),
            Username = Optional(Username),
            CredentialEnv = CredentialEnv.Trim()
        });
        if (version != _identityVersion) return;
        Connections = new[] { saved }.Concat(Connections.Where(item => item.Id != saved.Id)).ToArray();
        NotifyConnections();
        SelectedConnection = saved;
        ConnectionsChanged?.Invoke(this, EventArgs.Empty);
        StatusMessage = "Profile saved, NOT tested. Configure its credential environment variable on the Python API host. No external send occurred.";
    }, "Saving your profile in the AI Factory API...");

    protected override void OnOperationFailed(Exception exception) =>
        Warning = "Sign in to Azure using the menu and check Connection. Saving a profile does not verify the endpoint or credential. Never paste the secret value here.";

    private void NewProfile()
    {
        SelectedConnection = null;
        Populate(null);
        Warning = string.Empty;
    }
    private void Populate(TicketConnection? value)
    {
        Name = value?.Name ?? string.Empty;
        Provider = value?.Provider ?? "Jira";
        BaseUrl = value?.BaseUrl ?? string.Empty;
        ProjectKey = value?.ProjectKey ?? string.Empty;
        Username = value?.Username ?? string.Empty;
        CredentialEnv = value?.CredentialEnv ?? string.Empty;
    }
    private void NotifyConnections()
    {
        OnPropertyChanged(nameof(Connections));
        OnPropertyChanged(nameof(IsEmpty));
    }
    private static string? Optional(string value) => string.IsNullOrWhiteSpace(value) ? null : value.Trim();
}

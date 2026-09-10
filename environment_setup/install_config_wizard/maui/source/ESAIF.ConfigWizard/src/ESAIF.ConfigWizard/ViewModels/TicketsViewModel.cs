using System.Text.Json;
using ESAIF.BaseLayer.Application;
using ESAIF.ConfigWizard.Services;
using ESAIF.DomainLayer.Configuration;

namespace ESAIF.ConfigWizard.ViewModels;

public sealed class TicketsViewModel : OperationViewModel
{
    private readonly ITicketClient _client;
    private readonly WizardSession _wizard;
    private string _folder;
    private long _contextVersion;
    private FactoryTicket? _selectedTicket;
    private TicketConnection? _selectedConnection;
    private TicketSyncPreview? _preview;
    private string _selectedStatus = "New";
    private string _ticketType = TicketChoices.Types[0];
    private string _title = string.Empty;
    private string _description = string.Empty;
    private string _resourceGroup = string.Empty;
    private TicketResourceIdentity? _resourceIdentity;
    private long _resourceVersion;
    private string _severity = "minor";
    private string _selectedSeverity = "minor";
    private string _costCenter = string.Empty;
    private string _departmentName = string.Empty;
    private string _requestedService = string.Empty;
    private bool _hasFullList;
    private long _draftRevision;
    private string _prefilledResourceGroup = string.Empty;
    private string _selectedProjectNumber = string.Empty;
    private bool _extractingResourceGroup;

    public TicketsViewModel(ITicketClient client, WizardSession wizard, AzureAuthenticationMonitor? authentication = null)
    {
        _client = client;
        _wizard = wizard;
        _folder = CurrentFolder;
        PropertyChanged += (_, e) =>
        {
            if (e.PropertyName is nameof(Title) or nameof(Description) or nameof(ResourceGroup) or
                nameof(TicketType) or nameof(Severity) or nameof(CostCenter) or nameof(DepartmentName) or
                nameof(RequestedService))
                ++_draftRevision;
        };
        _wizard.StateChanged += OnWizardChanged;
        if (authentication is not null)
        {
            var identity = (authentication.IsLoggedIn, authentication.Status.AccountName, authentication.Status.TenantId);
            authentication.PropertyChanged += (_, e) =>
            {
                if (e.PropertyName != nameof(AzureAuthenticationMonitor.Status)) return;
                var current = (authentication.IsLoggedIn, authentication.Status.AccountName, authentication.Status.TenantId);
                if (identity == current) return;
                identity = current;
                ++_contextVersion;
                ClearData();
                ResetDraft();
                StatusMessage = "Azure identity changed. Reload your tickets and profiles before continuing.";
            };
        }
        ReloadCommand = new AsyncCommand(LoadAsync);
        CreateCommand = new AsyncCommand(CreateAsync);
        ExtractResourceGroupCommand = new AsyncCommand(ExtractResourceGroupAsync);
        SaveStatusCommand = new AsyncCommand(SaveStatusAsync);
        PreviewSyncCommand = new AsyncCommand(PreviewSyncAsync);
        ConfirmSyncCommand = new AsyncCommand(ConfirmSyncAsync);
        CancelPreviewCommand = new AsyncCommand(() => { ClearPreview(); return Task.CompletedTask; });
        SelectTicketCommand = new Command<FactoryTicket>(ticket => SelectedTicket = ticket);
        ManageConnectionsCommand = new AsyncCommand(() => AppShell.NavigateToWorkspaceAsync(AppShell.TicketConnectionsPageKey));
        OpenWizardCommand = new AsyncCommand(() => AppShell.NavigateToWorkspaceAsync(AppShell.WizardPageKey));
    }

    public AsyncCommand ReloadCommand { get; }
    public AsyncCommand CreateCommand { get; }
    public AsyncCommand ExtractResourceGroupCommand { get; }
    public AsyncCommand SaveStatusCommand { get; }
    public AsyncCommand PreviewSyncCommand { get; }
    public AsyncCommand ConfirmSyncCommand { get; }
    public AsyncCommand CancelPreviewCommand { get; }
    public Command<FactoryTicket> SelectTicketCommand { get; }
    public AsyncCommand ManageConnectionsCommand { get; }
    public AsyncCommand OpenWizardCommand { get; }
    public IReadOnlyList<string> Types => TicketChoices.Types;
    public IReadOnlyList<string> Statuses => TicketChoices.Statuses;
    public IReadOnlyList<string> Severities => TicketChoices.Severities;
    public IReadOnlyList<FactoryTicket> Tickets { get; private set; } = [];
    public IReadOnlyList<TicketConnection> Connections { get; private set; } = [];
    public string Owner { get; private set; } = "Unknown — reload after Azure sign-in";
    public string CurrentFolder => _wizard.GetString("_save_folder").Trim();
    public string CountsLabel { get; private set; } = "New: Unknown · Active: Unknown · Solved: Unknown";
    public bool IsEmpty => Tickets.Count == 0;
    public bool HasSelection => SelectedTicket is not null;
    public bool HasPreview => _preview is not null;
    public long DraftRevision => _draftRevision;
    public bool HasDraftContent => !string.IsNullOrWhiteSpace(Title) || !string.IsNullOrWhiteSpace(Description) ||
        !string.IsNullOrWhiteSpace(RequestedService) || !string.IsNullOrWhiteSpace(CostCenter) ||
        !string.IsNullOrWhiteSpace(DepartmentName) || Severity != "minor" || TicketType != TicketChoices.Types[0] ||
        !string.Equals(ResourceGroup.Trim(), _prefilledResourceGroup, StringComparison.OrdinalIgnoreCase);
    public string SelectedProjectNumber => _selectedProjectNumber;
    public string DraftContextHint => _selectedProjectNumber.Length == 0 ? string.Empty :
        $"Selected project: {_selectedProjectNumber} · unsaved draft. " +
        (string.IsNullOrWhiteSpace(ResourceGroup)
            ? "Missing observed RG; paste a project resource group to derive details. No resource-group name was guessed."
            : "Nothing has been created or sent.");
    public string PreviewRecipient => _preview?.Recipient ?? string.Empty;
    public string PreviewContent => _preview?.Content ?? string.Empty;
    public string TicketType { get => _ticketType; set => SetProperty(ref _ticketType, value); }
    public string Title { get => _title; set => SetProperty(ref _title, value); }
    public string Description { get => _description; set => SetProperty(ref _description, value); }
    public string ResourceGroup
    {
        get => _resourceGroup;
        set
        {
            if (!SetProperty(ref _resourceGroup, value)) return;
            ++_resourceVersion;
            _resourceIdentity = null;
            _selectedProjectNumber = string.Empty;
            NotifyResourceIdentity();
            NotifyDraftContext();
        }
    }
    public string ProjectNumber => _resourceIdentity?.ProjectNumber ?? string.Empty;
    public string Environment => _resourceIdentity?.Environment ?? string.Empty;
    public string Region => _resourceIdentity?.Region ?? string.Empty;
    public string AiFactoryPrefix => _resourceIdentity?.AiFactoryPrefix ?? string.Empty;
    public string AiFactorySuffix => _resourceIdentity?.AiFactorySuffix ?? string.Empty;
    public bool HasResourceIdentity => _resourceIdentity is not null;
    public string Severity { get => _severity; set { if (value is not null) SetProperty(ref _severity, value); } }
    public string CostCenter { get => _costCenter; set => SetProperty(ref _costCenter, value); }
    public string DepartmentName { get => _departmentName; set => SetProperty(ref _departmentName, value); }
    public string SelectedSeverity
    {
        get => _selectedSeverity;
        set { if (value is not null && SetProperty(ref _selectedSeverity, value)) ClearPreview(); }
    }
    public string RequestedService { get => _requestedService; set => SetProperty(ref _requestedService, value); }
    public string SelectedStatus
    {
        get => _selectedStatus;
        set { if (SetProperty(ref _selectedStatus, value)) ClearPreview(); }
    }
    public FactoryTicket? SelectedTicket
    {
        get => _selectedTicket;
        set
        {
            if (!SetProperty(ref _selectedTicket, value)) return;
            SelectedStatus = value?.Status ?? "New";
            SelectedSeverity = value?.Severity ?? "minor";
            ClearPreview();
            OnPropertyChanged(nameof(HasSelection));
        }
    }
    public TicketConnection? SelectedConnection
    {
        get => _selectedConnection;
        set { if (SetProperty(ref _selectedConnection, value)) ClearPreview(); }
    }

    public Task LoadAsync() => ExecuteOperationAsync(async () =>
    {
        ClearData();
        Warning = string.Empty;
        await _wizard.InitializeAsync();
        var version = _contextVersion;
        var result = await _client.ListTicketsAsync();
        if (version != _contextVersion) return;
        ApplyList(result);
        StatusMessage = "Loaded your tickets across factories. Connector profiles are not tested and sync is manual.";
        // Keep the ticket list usable even if connector-profile retrieval fails.
        try
        {
            var connections = await _client.ListTicketConnectionsAsync();
            if (version != _contextVersion) return;
            ApplyConnections(connections.Connections);
        }
        catch (Exception error) when (error is HttpRequestException or IOException or JsonException or
            InvalidOperationException or ArgumentException or NotSupportedException or
            OperationCanceledException or UnauthorizedAccessException)
        {
            if (version == _contextVersion)
                Warning = $"{Warning} Connector profiles unavailable: {error.Message} Open Ticket connections or Reload.".Trim();
        }
    }, "Loading your tickets. Azure sign-in is required...");

    internal void ApplyConnections(IReadOnlyList<TicketConnection> connections)
    {
        if (Connections.SequenceEqual(connections)) return;
        var selected = SelectedConnection;
        Connections = connections;
        OnPropertyChanged(nameof(Connections));
        SelectedConnection = selected is null ? null : connections.FirstOrDefault(item => item.Id == selected.Id);
    }

    public async Task<bool> BeginDraftFromResourceGroupAsync(
        string? resourceGroup, string projectNumber, Func<Task<bool>> confirmReplace,
        Func<Task<bool>>? prepare = null, Func<Task>? navigate = null)
    {
        var revision = _draftRevision;
        var context = _contextVersion;
        if (HasDraftContent && !await confirmReplace()) return false;
        if (revision != _draftRevision || context != _contextVersion) return false;
        if (prepare is not null && !await prepare()) return false;
        if (revision != _draftRevision || context != _contextVersion || IsBusy) return false;

        ResetDraft();
        SelectedTicket = null;
        ClearPreview();
        ResourceGroup = resourceGroup?.Trim() ?? string.Empty;
        _prefilledResourceGroup = ResourceGroup;
        _selectedProjectNumber = projectNumber.Trim();
        NotifyDraftContext();
        Warning = string.Empty;
        revision = _draftRevision;
        if (ResourceGroup.Length > 0)
            await ExtractResourceGroupAsync();
        else
            await ExecuteOperationAsync(() =>
            {
                Warning = "Missing observed RG; paste a project resource group to derive details.";
                StatusMessage = "Opened an unsaved project ticket draft. Nothing was created or sent.";
                return Task.CompletedTask;
            }, "Opening ticket draft...");
        if (revision != _draftRevision || context != _contextVersion) return false;
        if (navigate is not null) await navigate();
        return true;
    }

    public async Task ExtractResourceGroupAsync()
    {
        _extractingResourceGroup = true;
        try
        {
            await ExecuteOperationAsync(async () =>
            {
                Warning = string.Empty;
                if (await ParseResourceIdentityAsync())
                    StatusMessage = "Factory and project fields extracted from the name. This does not verify deployment or Azure access.";
            }, "Extracting resource-group identity...");
        }
        finally { _extractingResourceGroup = false; }
    }

    private async Task<bool> ParseResourceIdentityAsync()
    {
        if (string.IsNullOrWhiteSpace(ResourceGroup))
            throw new InvalidOperationException("Paste a project resource-group name to identify the ticket's factory and environment.");
        var version = _contextVersion;
        var resourceVersion = _resourceVersion;
        var group = ResourceGroup.Trim();
        _resourceIdentity = null;
        NotifyResourceIdentity();
        var result = await _client.ParseTicketResourceGroupAsync(group);
        if (version != _contextVersion || resourceVersion != _resourceVersion)
        {
            StatusMessage = "Ticket context changed. Extract the resource group again before creating a ticket.";
            return false;
        }
        if (!string.Equals(result.ResourceGroup, group, StringComparison.OrdinalIgnoreCase) ||
            string.IsNullOrWhiteSpace(result.ProjectNumber) || result.Environment is not ("dev" or "stage" or "prod") ||
            string.IsNullOrWhiteSpace(result.Region) || string.IsNullOrWhiteSpace(result.AiFactoryPrefix) ||
            string.IsNullOrWhiteSpace(result.AiFactorySuffix))
            throw new InvalidDataException("The API did not return a complete resource-group identity. Nothing was created.");
        if (_selectedProjectNumber.Length > 0 &&
            !_selectedProjectNumber.TrimStart('0').Equals(result.ProjectNumber.TrimStart('0'), StringComparison.OrdinalIgnoreCase))
            throw new InvalidDataException("The observed resource group does not identify the selected project. Paste the correct resource group. Nothing was created.");
        _resourceIdentity = result;
        NotifyResourceIdentity();
        return true;
    }

    public Task CreateAsync() => ExecuteOperationAsync(async () =>
    {
        Warning = string.Empty;
        ClearPreview();
        if (string.IsNullOrWhiteSpace(Title) || string.IsNullOrWhiteSpace(Description))
            throw new InvalidOperationException("Enter a title and description before creating a ticket.");
        if (TicketType == "Request Azure service" && string.IsNullOrWhiteSpace(RequestedService))
            throw new InvalidOperationException("Enter the requested Azure service for a Request Azure service ticket.");
        if (!Severities.Contains(Severity))
            throw new InvalidOperationException("Choose minor, major, or blocker for severity.");
        if (!HasResourceIdentity && !await ParseResourceIdentityAsync()) return;
        var version = _contextVersion;
        var ticket = await _client.CreateTicketAsync(new CreateTicketRequest
        {
            ResourceGroup = ResourceGroup.Trim(),
            Severity = Severity,
            CostCenter = Optional(CostCenter),
            DepartmentName = Optional(DepartmentName),
            Type = TicketType,
            Title = Title.Trim(),
            Description = Description.Trim(),
            RequestedService = Optional(RequestedService)
        });
        if (version != _contextVersion) return;
        Upsert(ticket);
        Owner = ticket.Owner;
        OnPropertyChanged(nameof(Owner));
        Title = Description = RequestedService = string.Empty;
        StatusMessage = "Ticket created for the pasted resource group, independently of the wizard folder. Nothing sent to Jira or ServiceNow.";
    }, "Creating your ticket...");

    public Task SaveStatusAsync() => ExecuteOperationAsync(async () =>
    {
        Warning = string.Empty;
        var ticket = SelectedTicket ?? throw new InvalidOperationException("Select one of your tickets first.");
        var version = _contextVersion;
        ClearPreview();
        var updated = await _client.UpdateTicketAsync(ticket.Id, SelectedStatus, SelectedSeverity);
        if (version != _contextVersion) return;
        Upsert(updated);
        StatusMessage = "Status and severity saved in the AI Factory API. Use a fresh preview for any external sync.";
    }, "Saving ticket status and severity...");

    public Task PreviewSyncAsync() => ExecuteOperationAsync(async () =>
    {
        Warning = string.Empty;
        ClearPreview();
        var ticket = SelectedTicket ?? throw new InvalidOperationException("Select one of your tickets first.");
        var connection = SelectedConnection ?? throw new InvalidOperationException("Choose a connector profile. Add one in Ticket connections if needed.");
        if (SelectedStatus != ticket.Status || SelectedSeverity != ticket.Severity)
            throw new InvalidOperationException("Save the changed status and severity before previewing external content.");
        var version = _contextVersion;
        var preview = await _client.PreviewTicketSyncAsync(ticket.Id, connection.Id ?? string.Empty);
        if (version != _contextVersion || SelectedTicket != ticket || SelectedConnection != connection ||
            SelectedStatus != ticket.Status || SelectedSeverity != ticket.Severity) return;
        if (string.IsNullOrWhiteSpace(preview.ConfirmationId) || string.IsNullOrWhiteSpace(preview.Recipient) ||
            string.IsNullOrWhiteSpace(preview.Content))
            throw new InvalidDataException("The API did not return a complete recipient/content preview. Reload and try again; nothing was sent.");
        _preview = preview;
        NotifyPreview();
        StatusMessage = "Preview only — nothing sent. Review WHO and the exact CONTENT, then explicitly confirm if appropriate.";
    }, "Preparing a private-data disclosure preview (no external send)...");

    public Task ConfirmSyncAsync() => ExecuteOperationAsync(async () =>
    {
        Warning = string.Empty;
        var preview = _preview ?? throw new InvalidOperationException("Generate and review a fresh preview before confirming.");
        var version = _contextVersion;
        // A confirmation can only be submitted once by this view; errors require a new preview.
        ClearPreview();
        var ticket = await _client.ConfirmTicketSyncAsync(preview.ConfirmationId);
        if (version != _contextVersion) return;
        Upsert(ticket);
        StatusMessage = $"Manual sync completed. State: {ticket.SyncState ?? "Unknown"}. No live background synchronization.";
    }, "Sending only the confirmed preview to the displayed recipient...");

    protected override void OnOperationFailed(Exception exception)
    {
        ClearPreview();
        Warning = _extractingResourceGroup
            ? "Resource-group details could not be extracted. Check the name and API connection, then choose Extract details. Nothing was created or sent."
            : "Check the API connection and Azure sign-in (menu). Reload to verify saved state before retrying. Sync failures may have reached the external service; inspect its result before submitting again.";
    }

    private void OnWizardChanged(object? sender, EventArgs e)
    {
        if (FactoryNetworkSession.SameFolder(_folder, CurrentFolder))
            return;
        _folder = CurrentFolder;
        ++_contextVersion;
        ClearData();
        ResetDraft();
        OnPropertyChanged(nameof(CurrentFolder));
        StatusMessage = "Factory changed. Reload your tickets and connector profiles before continuing.";
    }

    private void ResetDraft()
    {
        ++_draftRevision;
        ++_resourceVersion;
        _resourceIdentity = null;
        _prefilledResourceGroup = _selectedProjectNumber = string.Empty;
        Title = Description = RequestedService = CostCenter = DepartmentName = ResourceGroup = string.Empty;
        Severity = "minor";
        TicketType = TicketChoices.Types[0];
        NotifyResourceIdentity();
        NotifyDraftContext();
    }

    private void NotifyDraftContext()
    {
        OnPropertyChanged(nameof(SelectedProjectNumber));
        OnPropertyChanged(nameof(DraftContextHint));
    }

    private void NotifyResourceIdentity()
    {
        foreach (var property in new[] { nameof(ProjectNumber), nameof(Environment), nameof(Region),
            nameof(AiFactoryPrefix), nameof(AiFactorySuffix), nameof(HasResourceIdentity) })
            OnPropertyChanged(property);
    }

    private void ApplyList(TicketListResult result)
    {
        Owner = result.Owner;
        _hasFullList = true;
        Tickets = result.Tickets;
        CountsLabel = $"New: {result.Counts.New:N0} · Active: {result.Counts.Active:N0} · Solved: {result.Counts.Solved:N0}";
        Warning = result.Warning ?? string.Empty;
        NotifyList();
    }

    private void Upsert(FactoryTicket ticket)
    {
        Tickets = new[] { ticket }.Concat(Tickets.Where(item => item.Id != ticket.Id)).ToArray();
        CountsLabel = _hasFullList
            ? $"New: {Tickets.Count(item => item.Status == "New"):N0} · Active: {Tickets.Count(item => item.Status == "Active"):N0} · Solved: {Tickets.Count(item => item.Status == "Solved"):N0}"
            : "New: Unknown · Active: Unknown · Solved: Unknown — reload the full list";
        SelectedTicket = ticket;
        NotifyList();
    }

    private void ClearData()
    {
        ClearPreview();
        SelectedTicket = null;
        SelectedConnection = null;
        Tickets = [];
        _hasFullList = false;
        Connections = [];
        Owner = "Unknown — reload after Azure sign-in";
        CountsLabel = "New: Unknown · Active: Unknown · Solved: Unknown";
        NotifyList();
        OnPropertyChanged(nameof(Connections));
    }

    private void ClearPreview() { _preview = null; NotifyPreview(); }
    private void NotifyPreview()
    {
        OnPropertyChanged(nameof(HasPreview));
        OnPropertyChanged(nameof(PreviewRecipient));
        OnPropertyChanged(nameof(PreviewContent));
    }
    private void NotifyList()
    {
        OnPropertyChanged(nameof(Tickets));
        OnPropertyChanged(nameof(Owner));
        OnPropertyChanged(nameof(CountsLabel));
        OnPropertyChanged(nameof(IsEmpty));
    }
    private static string? Optional(string value) => string.IsNullOrWhiteSpace(value) ? null : value.Trim();
}

using System.Text.Json;
using ESAIF.BaseLayer.Application;
using ESAIF.ConfigWizard.Services;
using ESAIF.DomainLayer.Configuration;
using ESAIF.DomainLayer.Operations;

namespace ESAIF.ConfigWizard.ViewModels;

public sealed class CurrentFactoryAnalyticsViewModel : ObservableObject
{
    private readonly IFactoryAnalyticsClient _analytics;
    private readonly ITicketClient _tickets;
    private readonly OperationsSession _operations;
    private OperationsOverview? _requestedOverview;
    private string? _requestedFolder;
    private Task _refresh = Task.CompletedTask;
    private long _version;
    private bool _isBusy;

    public CurrentFactoryAnalyticsViewModel(
        IFactoryAnalyticsClient analytics, ITicketClient tickets, OperationsSession operations,
        AzureAuthenticationMonitor? authentication = null)
    {
        _analytics = analytics;
        _tickets = tickets;
        _operations = operations;
        _operations.OverviewChanged += OnOverviewChanged;
        if (authentication is not null)
        {
            var identity = (authentication.IsLoggedIn, authentication.Status.AccountName, authentication.Status.TenantId);
            authentication.PropertyChanged += (_, e) =>
            {
                if (e.PropertyName != nameof(AzureAuthenticationMonitor.Status)) return;
                var current = (authentication.IsLoggedIn, authentication.Status.AccountName, authentication.Status.TenantId);
                if (identity == current) return;
                identity = current;
                ++_version;
                _requestedFolder = null;
                ClearSnapshot();
                IsBusy = false;
                TicketError = "Azure identity changed. Reload analytics and counts after signing in.";
                OnPropertyChanged(nameof(TicketError));
            };
        }
        ReloadCommand = new AsyncCommand(() => RefreshAsync(true));
        OpenWizardCommand = new AsyncCommand(() => AppShell.NavigateToWorkspaceAsync(AppShell.WizardPageKey));
        OpenTicketsCommand = new AsyncCommand(() => AppShell.NavigateToWorkspaceAsync(AppShell.TicketsPageKey));
    }

    public AsyncCommand ReloadCommand { get; }
    public AsyncCommand OpenWizardCommand { get; }
    public AsyncCommand OpenTicketsCommand { get; }
    public string Folder => _operations.Folder;
    public bool IsMissingFolder => string.IsNullOrWhiteSpace(Folder);
    public string Title { get; private set; } = "Current AI Factory";
    public string Source { get; private set; } = "Unknown";
    public string GeneratedAt { get; private set; } = "Unknown";
    public string Warning { get; private set; } = string.Empty;
    public string ErrorMessage { get; private set; } = string.Empty;
    public string TicketError { get; private set; } = string.Empty;
    public string TicketWarning { get; private set; } = string.Empty;
    public string TicketOwner { get; private set; } = "Unknown — Azure sign-in required";
    public string NewTickets { get; private set; } = "Unknown";
    public string ActiveTickets { get; private set; } = "Unknown";
    public string SolvedTickets { get; private set; } = "Unknown";
    public string TicketSource { get; private set; } = "Unknown";
    public IReadOnlyList<AnalyticsSectionViewModel> Sections { get; private set; } = [];
    public bool IsEmpty => !IsBusy && Sections.Count == 0 && !IsMissingFolder;
    public bool IsBusy
    {
        get => _isBusy;
        private set
        {
            if (SetProperty(ref _isBusy, value))
            {
                OnPropertyChanged(nameof(IsNotBusy));
                OnPropertyChanged(nameof(IsEmpty));
            }
        }
    }
    public bool IsNotBusy => !IsBusy;

    // A published snapshot, rather than a render/tab change, is the refresh identity.
    public Task RefreshAsync(bool force = false)
    {
        var folder = Folder;
        var sameRequest = _requestedFolder is not null &&
            FactoryNetworkSession.SameFolder(_requestedFolder, folder) &&
            ReferenceEquals(_requestedOverview, _operations.Current);
        if (sameRequest && (!force || !_refresh.IsCompleted))
            return _refresh;

        _requestedFolder = folder;
        _requestedOverview = _operations.Current;
        var version = ++_version;
        ClearSnapshot();
        if (string.IsNullOrWhiteSpace(folder))
        {
            IsBusy = false;
            _refresh = Task.CompletedTask;
            return _refresh;
        }

        IsBusy = true;
        _refresh = RefreshCoreAsync(folder, version);
        return _refresh;
    }

    private async void OnOverviewChanged(object? sender, EventArgs e) => await RefreshAsync();

    private async Task RefreshCoreAsync(string folder, long version)
    {
        await Task.Yield();
        try
        {
            await Task.WhenAll(LoadAnalyticsAsync(folder, version), LoadTicketCountsAsync(folder, version));
        }
        finally
        {
            if (IsCurrent(folder, version))
            {
                IsBusy = false;
                NotifySnapshot();
            }
        }
    }

    private async Task LoadAnalyticsAsync(string folder, long version)
    {
        try
        {
            var result = await _analytics.GetCurrentFactoryAnalyticsAsync(folder);
            if (!IsCurrent(folder, version)) return;
            Title = Known(result.Title);
            Source = Known(result.Source);
            GeneratedAt = Known(result.GeneratedAt);
            Warning = result.Warning ?? string.Empty;
            Sections = result.Sections.Select(section => new AnalyticsSectionViewModel(section)).ToArray();
        }
        catch (Exception error) when (error is HttpRequestException or IOException or JsonException or
            InvalidOperationException or ArgumentException or NotSupportedException or
            OperationCanceledException or UnauthorizedAccessException)
        {
            if (!IsCurrent(folder, version)) return;
            ErrorMessage = $"Analytics could not be loaded: {error.Message} Check the API connection and factory folder, then Reload.";
        }
        if (IsCurrent(folder, version)) NotifySnapshot();
    }

    private async Task LoadTicketCountsAsync(string folder, long version)
    {
        try
        {
            var result = await _tickets.ListTicketsAsync(folder);
            if (!IsCurrent(folder, version)) return;
            TicketOwner = Known(result.Owner);
            TicketSource = "Signed-in user's tickets · current factory · manual snapshot";
            TicketWarning = result.Warning ?? string.Empty;
            NewTickets = result.Counts.New.ToString("N0");
            ActiveTickets = result.Counts.Active.ToString("N0");
            SolvedTickets = result.Counts.Solved.ToString("N0");
        }
        catch (Exception error) when (error is HttpRequestException or IOException or JsonException or
            InvalidOperationException or ArgumentException or NotSupportedException or
            OperationCanceledException or UnauthorizedAccessException)
        {
            if (!IsCurrent(folder, version)) return;
            TicketError = $"Ticket counts unavailable: {error.Message} Sign in to Azure from the menu, check Connection, then Reload.";
        }
        if (IsCurrent(folder, version)) NotifySnapshot();
    }

    private bool IsCurrent(string folder, long version) =>
        version == _version && FactoryNetworkSession.SameFolder(Folder, folder);

    private void ClearSnapshot()
    {
        Title = "Current AI Factory";
        Source = GeneratedAt = NewTickets = ActiveTickets = SolvedTickets = TicketSource = "Unknown";
        TicketOwner = "Unknown — Azure sign-in required";
        Warning = ErrorMessage = TicketError = TicketWarning = string.Empty;
        Sections = [];
        NotifySnapshot();
    }

    private void NotifySnapshot()
    {
        foreach (var property in new[]
        {
            nameof(Folder), nameof(IsMissingFolder), nameof(Title), nameof(Source), nameof(GeneratedAt),
            nameof(Warning), nameof(ErrorMessage), nameof(Sections), nameof(IsEmpty), nameof(TicketError),
            nameof(TicketWarning), nameof(TicketOwner), nameof(TicketSource),
            nameof(NewTickets), nameof(ActiveTickets), nameof(SolvedTickets)
        })
            OnPropertyChanged(property);
    }

    internal static string Known(string? value) => string.IsNullOrWhiteSpace(value) ? "Unknown" : value;
}

public sealed class AnalyticsSectionViewModel(FactoryAnalyticsSection section)
{
    public string Title { get; } = CurrentFactoryAnalyticsViewModel.Known(section.Title);
    public string Description { get; } = section.Description;
    public string Source { get; } = CurrentFactoryAnalyticsViewModel.Known(section.Source);
    public IReadOnlyList<AnalyticsRowViewModel> Rows { get; } = section.Rows
        .Select(row => new AnalyticsRowViewModel(Enumerable.Range(0, Math.Max(section.Columns.Count, row.Count))
            .Select(index => new AnalyticsCell(
                index < section.Columns.Count ? CurrentFactoryAnalyticsViewModel.Known(section.Columns[index]) : $"Column {index + 1}",
                index < row.Count ? CurrentFactoryAnalyticsViewModel.Known(row[index]) : "Unknown")).ToArray()))
        .ToArray();
    public bool IsEmpty => Rows.Count == 0;
}

public sealed record AnalyticsRowViewModel(IReadOnlyList<AnalyticsCell> Cells);
public sealed record AnalyticsCell(string Column, string Value);

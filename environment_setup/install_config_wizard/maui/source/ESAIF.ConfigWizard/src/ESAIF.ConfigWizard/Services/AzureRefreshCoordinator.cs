using System.Diagnostics;
using System.Text.Json;
using ESAIF.BaseLayer.Application;
using ESAIF.DomainLayer.Operations;

namespace ESAIF.ConfigWizard.Services;

public enum AzureRefreshState { Ready, Running, Succeeded, Partial, Failed, Superseded }

public sealed class AzureRefreshCoordinator : ObservableObject
{
    private readonly OperationsSession _operations;
    private readonly WizardSession _wizard;
    private Task? _runningTask;
    private string _observedFolder;
    private long _contextVersion;
    private readonly FactoryNetworkSession? _network;
    private readonly AzureAuthenticationMonitor? _authentication;
    private long _refreshedAuthenticationVersion = -1;

    public AzureRefreshCoordinator(OperationsSession operations, WizardSession wizard, FactoryNetworkSession? network = null,
        AzureAuthenticationMonitor? authentication = null)
    {
        _operations = operations;
        _wizard = wizard;
        _network = network;
        _authentication = authentication;
        if (_authentication is not null)
        {
            _authentication.PropertyChanged += (_, _) => NotifyState();
            _authentication.FirstAuthenticated += (_, _) => _ = RefreshAsync(manual: false);
        }
        _observedFolder = operations.Folder;
        Details = operations.Warning;
        RefreshCommand = new AsyncCommand(() => RefreshAsync(), () => CanRefresh);
        _wizard.StateChanged += OnConfigurationChanged;
        _operations.OverviewChanged += (_, _) =>
        {
            if (_network is not null)
            {
                return;
            }
            if (_operations.Current is null && !IsRunning)
            {
                State = AzureRefreshState.Ready;
                CompletedAt = null;
                Details = string.Empty;
                Message = "Configuration changed. Refresh Azure to update all three views.";
                NotifyState();
            }
            else if (_operations.Current is not null && State == AzureRefreshState.Ready)
            {
                Details = _operations.Warning;
                NotifyState();
            }
        };
    }

    public AsyncCommand RefreshCommand { get; }
    public event EventHandler? LoginRequired;
    public AzureRefreshState State { get; private set; }
    public bool IsRunning => State == AzureRefreshState.Running;
    public bool CanRefresh => !IsRunning && (_authentication?.IsLoggedIn ?? true) &&
        (_network is not null || !string.IsNullOrWhiteSpace(_operations.Folder));
    public bool NeedsLogin => _authentication is not null && !_authentication.IsLoggedIn;
    public string Message { get; private set; } = "Refresh all known ADO/GitHub factories, the map, and project access.";
    public string Details { get; private set; } = string.Empty;
    public bool HasDetails => !string.IsNullOrWhiteSpace(Details);
    public DateTimeOffset? CompletedAt { get; private set; }
    public string CompletedLabel => CompletedAt is { } completed ? $"Completed {completed.ToLocalTime():HH:mm:ss}" : string.Empty;
    public string Folder => _operations.Folder;
    public string LightColor => State switch
    {
        AzureRefreshState.Succeeded => "#22C9A7",
        AzureRefreshState.Failed => "#E45664",
        AzureRefreshState.Running => "#22BBD0",
        AzureRefreshState.Partial or AzureRefreshState.Superseded => "#D79B32",
        _ => "#8292A6"
    };
    public string StatusLabel => State switch
    {
        AzureRefreshState.Running => "Refreshing Azure",
        AzureRefreshState.Succeeded => "Refresh complete",
        AzureRefreshState.Partial => "Complete with warnings",
        AzureRefreshState.Failed => "Refresh failed",
        AzureRefreshState.Superseded => "Refresh needed",
        _ => NeedsLogin ? "Azure sign-in required" : "Azure refresh ready"
    };

    public Task RefreshAsync(bool manual = true)
    {
        if (_runningTask is { IsCompleted: false })
        {
            return _runningTask;
        }

        // The application owns this task; page navigation never cancels it.
        _runningTask = RefreshCoreAsync(manual);
        return _runningTask;
    }

    public Task RefreshAfterLoginAsync() =>
        _authentication is { IsLoggedIn: true } authentication &&
        authentication.AuthenticationVersion == _refreshedAuthenticationVersion && _runningTask is not null
            ? _runningTask : RefreshAsync(manual: false);

    private async Task RefreshCoreAsync(bool manual)
    {
        State = AzureRefreshState.Running;
        Message = "Refreshing all views in the background. You can keep working.";
        Details = string.Empty;
        CompletedAt = null;
        NotifyState();
        var timer = Stopwatch.StartNew();
        await Task.Yield();
        var version = _contextVersion;
        var folder = Folder;
        try
        {
            if (_authentication is not null)
            {
                await _authentication.CheckAsync();
                if (!_authentication.IsLoggedIn)
                {
                    State = AzureRefreshState.Ready;
                    Message = "Login to Azure is required before refreshing all known factories.";
                    Details = _authentication.Status.Message;
                    if (manual && _authentication.Status.State != "unavailable")
                    {
                        LoginRequired?.Invoke(this, EventArgs.Empty);
                    }
                    return;
                }
                _refreshedAuthenticationVersion = _authentication.AuthenticationVersion;
            }
            if (_network is not null)
            {
                await _network.RefreshAsync(folder, progress =>
                {
                    Message = progress;
                    NotifyState();
                });
                foreach (var snapshot in _network.Snapshots)
                {
                    if (snapshot.Overview is not null && snapshot.Error.Length == 0)
                    {
                        _operations.ApplyRefreshedOverview(snapshot.Folder, snapshot.Overview);
                    }
                }
                var messages = _network.Snapshots.Select(snapshot =>
                {
                    var verificationWarnings = snapshot.Projects.Concat(snapshot.ScaleSets)
                        .Where(item => !item.IsVerificationComplete)
                        .Select(item => $"{item.Label}: {item.VerificationDetails}");
                    return $"{snapshot.Folder}\n" + string.Join("\n", new[]
                        { snapshot.Error, snapshot.Overview?.Warning ?? "" }.Concat(verificationWarnings)
                        .Where(message => !string.IsNullOrWhiteSpace(message)));
                });
                Details = string.Join("\n\n", messages.Prepend(_network.DiscoveryError).Where(message => message.Length > 0));
                var partial = _network.DiscoveryError.Length > 0 || _network.Snapshots.Any(snapshot =>
                    snapshot.Error.Length > 0 || snapshot.Overview is null || HasIncompleteData(snapshot.Overview) ||
                    snapshot.Projects.Concat(snapshot.ScaleSets).Any(item => !item.IsVerificationComplete));
                if (_authentication is not null)
                {
                    await _authentication.CheckAsync();
                    if (!_authentication.IsLoggedIn)
                    {
                        partial = true;
                        Details += $"\n\nAzure sign-in needs attention: {_authentication.Status.Message}";
                        if (manual && _authentication.Status.State != "unavailable")
                        {
                            LoginRequired?.Invoke(this, EventArgs.Empty);
                        }
                    }
                }
                var addedFolders = _network.KnownFolders.Except(_network.LastRefreshFolders, StringComparer.OrdinalIgnoreCase).ToArray();
                if (addedFolders.Length > 0)
                {
                    partial = true;
                    Details += "\n\nAdditional factories were discovered during collection. Refresh again to check:\n" +
                        string.Join("\n", addedFolders);
                }
                State = _network.Snapshots.All(snapshot => snapshot.Error.Length > 0) ? AzureRefreshState.Failed :
                    partial ? AzureRefreshState.Partial : AzureRefreshState.Succeeded;
                CompletedAt = DateTimeOffset.Now;
                Message = State == AzureRefreshState.Failed
                    ? "All factory refreshes failed; see details. No access verification is claimed."
                    : $"{_network.Snapshots.Count} known factories checked; map and saved configuration access updated in {timer.Elapsed.TotalSeconds:0}s." +
                      (partial ? " Some results are incomplete; see details." : "");
                return;
            }
            // FastAPI runs collection on its worker thread; awaited HTTP never blocks the UI.
            var overview = await _operations.LoadAsync(forceRefresh: true, includeAzure: true);
            if (version != _contextVersion || !string.Equals(folder, Folder, StringComparison.OrdinalIgnoreCase))
            {
                SetSuperseded();
            }
            else if (overview is null)
            {
                State = AzureRefreshState.Superseded;
                Message = string.IsNullOrWhiteSpace(Folder)
                    ? OperationsPresentation.MissingFolderMessage
                    : "Configuration changed during collection. Refresh the active factory again.";
            }
            else
            {
                State = HasIncompleteData(overview) ? AzureRefreshState.Partial : AzureRefreshState.Succeeded;
                CompletedAt = DateTimeOffset.Now;
                Details = overview.Warning?.Trim() ?? string.Empty;
                if (State == AzureRefreshState.Partial && Details.Length == 0)
                {
                    Details = "Some data is cached, local, seeded or unavailable. See Monitoring for each metric's source.";
                }
                Message = State == AzureRefreshState.Succeeded
                    ? $"All three views updated in {timer.Elapsed.TotalSeconds:0}s."
                    : $"All three views updated in {timer.Elapsed.TotalSeconds:0}s; some data has warnings.";
            }
        }
        catch (Exception exception) when (exception is HttpRequestException or IOException or
            JsonException or InvalidOperationException or ArgumentException or OperationCanceledException)
        {
            if (version != _contextVersion)
            {
                SetSuperseded();
            }
            else
            {
                State = AzureRefreshState.Failed;
                Message = "Azure refresh failed. Existing data remains available; see details.";
                Details = exception is OperationCanceledException
                    ? "Azure collection exceeded the request timeout. Confirm the Python API is running and try again."
                    : exception.Message;
            }
        }
        finally
        {
            NotifyState();
        }
    }

    private static bool HasIncompleteData(OperationsOverview overview) =>
        !string.IsNullOrWhiteSpace(overview.Warning) ||
        StatusPresentation.ForOverview(overview).IsRealCollection is false;

    private void OnConfigurationChanged(object? sender, EventArgs e)
    {
        if (_network is not null)
        {
            _network.RememberFolder(Folder);
            NotifyState();
            return;
        }
        if (!string.Equals(_observedFolder, Folder, StringComparison.OrdinalIgnoreCase))
        {
            _observedFolder = Folder;
            _contextVersion++;
            CompletedAt = null;
            Details = string.Empty;
            if (IsRunning)
            {
                Message = "Factory changed. Finishing the earlier refresh without applying it to this factory.";
            }
            else
            {
                State = AzureRefreshState.Ready;
                Message = "Factory changed. Refresh Azure to update all three views.";
            }
        }
        NotifyState();
    }

    private void SetSuperseded()
    {
        State = AzureRefreshState.Superseded;
        CompletedAt = null;
        Details = string.Empty;
        Message = "The earlier refresh finished. Refresh Azure for the newly selected factory.";
    }

    private void NotifyState()
    {
        foreach (var property in new[]
        {
            nameof(State), nameof(IsRunning), nameof(CanRefresh), nameof(Message), nameof(Details),
            nameof(HasDetails), nameof(CompletedAt), nameof(CompletedLabel), nameof(Folder),
            nameof(LightColor), nameof(StatusLabel), nameof(NeedsLogin)
        })
        {
            OnPropertyChanged(property);
        }
        RefreshCommand.NotifyCanExecuteChanged();
    }
}

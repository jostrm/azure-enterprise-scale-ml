using System.Text.Json;
using ESAIF.BaseLayer.Application;
using ESAIF.BaseLayer.Networking;
using ESAIF.DomainLayer.Configuration;
using ESAIF.ConfigWizard.Services;

namespace ESAIF.ConfigWizard.ViewModels;

public sealed class AzureAuthenticationViewModel : ObservableObject
{
    private readonly IAzureAuthenticationClient client;
    private readonly IPostAzureLoginRefresh? postLoginRefresh;
    private readonly AzureAuthenticationMonitor? _monitor;
    public AzureAuthenticationViewModel(IAzureAuthenticationClient client,
        IPostAzureLoginRefresh? postLoginRefresh = null, AzureAuthenticationMonitor? monitor = null)
    {
        this.client = client;
        this.postLoginRefresh = postLoginRefresh;
        _monitor = monitor;
        if (_monitor is not null)
        {
            _status = _monitor.Status;
            _monitor.PropertyChanged += (_, args) =>
            {
                if (args.PropertyName == nameof(AzureAuthenticationMonitor.Status) && !_busy)
                {
                    Apply(_monitor.Status);
                }
            };
        }
    }
    private readonly SemaphoreSlim _operationLock = new(1, 1);
    private AzureAuthenticationStatus _status = new();
    private bool _busy;
    private string _message = "Azure sign-in has not been checked.";
    private string? _operationId;
    private string? _refreshedOperationId;

    public bool IsLoggedIn => _status.IsLoggedIn;
    public bool IsWorking => _busy || _status.State is "signing_in" or "signing_out";
    public bool CanAuthenticate => !IsWorking;
    public string ButtonText => IsLoggedIn ? "Logout" : "Login to Azure";
    public string AccountName => string.IsNullOrWhiteSpace(_status.AccountName)
        ? "Azure CLI shared session" : _status.AccountName;
    public string Message => _message;
    public string LightColor => IsLoggedIn ? "#61F3B1" : "#FFD48A";
    public IReadOnlyList<AzureAuthenticationTenant> LoginTenants =>
        _status.Tenants.Where(tenant => tenant.NeedsLogin).ToArray();
    public string? SuggestedTenantId => LoginTenants.FirstOrDefault()?.TenantId ??
        (string.IsNullOrWhiteSpace(_status.TenantId) ? null : _status.TenantId);

    public Task RefreshAsync(string? folder, CancellationToken cancellationToken = default) =>
        ExecuteAsync(async () =>
        {
            if (_operationId is not null)
            {
                Apply(await client.GetAzureAuthenticationOperationAsync(_operationId, cancellationToken));
                await WaitForOperationAsync(cancellationToken);
            }
            Apply(await client.GetAzureAuthenticationStatusAsync(folder, cancellationToken));
            while (_status.State is "signing_in" or "signing_out")
            {
                await WaitForOperationAsync(cancellationToken);
                // The shared CLI job may have originated in another factory context.
                Apply(await client.GetAzureAuthenticationStatusAsync(folder, cancellationToken));
            }
            if (_monitor is not null)
            {
                await _monitor.CheckAsync(cancellationToken);
                Apply(_monitor.Status);
            }
        }, "Checking Azure sign-in...", cancellationToken);

    public Task LoginAsync(string? folder, string? tenantId, CancellationToken cancellationToken = default) =>
        ExecuteAsync(async () =>
        {
            _monitor?.Invalidate("Signing in to Azure...");
            Apply(await client.LoginToAzureAsync(folder, tenantId, cancellationToken));
            if (IsLoggedIn)
            {
                _operationId ??= Guid.NewGuid().ToString();
            }
            await WaitForOperationAsync(cancellationToken);
            if (_monitor is not null)
            {
                await _monitor.CheckAsync(cancellationToken);
                Apply(_monitor.Status);
            }
        }, "Opening Microsoft sign-in in your browser...", cancellationToken);

    public Task LogoutAsync(string? folder, CancellationToken cancellationToken = default) =>
        ExecuteAsync(async () =>
        {
            _monitor?.Invalidate("Signing out of the shared Azure CLI session...");
            Apply(await client.LogoutFromAzureAsync(folder, cancellationToken));
            await WaitForOperationAsync(cancellationToken);
        }, "Signing out of the shared Azure CLI session...", cancellationToken);

    private async Task WaitForOperationAsync(CancellationToken cancellationToken)
    {
        while (_status.State is "signing_in" or "signing_out")
        {
            var operation = _operationId ?? throw new InvalidDataException("The API did not return a sign-in operation ID.");
            await Task.Delay(TimeSpan.FromSeconds(2), cancellationToken);
            Apply(await client.GetAzureAuthenticationOperationAsync(operation, cancellationToken));
        }
        if (_operationId is not null)
        {
            var completedOperation = _operationId;
            _operationId = null;
            if (IsLoggedIn && completedOperation != _refreshedOperationId)
            {
                _refreshedOperationId = completedOperation;
                _message = "Azure sign-in verified. Checking all known factories...";
                NotifyState();
                try
                {
                    // Once sign-in succeeds, closing the menu must not cancel the shared refresh.
                    _message = postLoginRefresh is null
                        ? "Azure sign-in verified."
                        : await postLoginRefresh.RefreshAsync();
                }
                catch (Exception exception) when (exception is HttpRequestException or IOException or
                    JsonException or InvalidOperationException or ArgumentException or OperationCanceledException)
                {
                    _message = $"Azure sign-in succeeded, but refreshing factories failed: {exception.Message}. Use Refresh Azure to retry.";
                }
                NotifyState();
            }
        }
    }

    private void Apply(AzureAuthenticationStatus status)
    {
        _status = status;
        _operationId = status.OperationId;
        _message = status.Message;
        NotifyState();
    }

    private async Task ExecuteAsync(Func<Task> action, string progress, CancellationToken cancellationToken)
    {
        try
        {
            await _operationLock.WaitAsync(cancellationToken);
        }
        catch (OperationCanceledException) when (cancellationToken.IsCancellationRequested)
        {
            return;
        }
        _busy = true;
        _message = progress;
        NotifyState();
        try
        {
            await action();
        }
        catch (OperationCanceledException) when (cancellationToken.IsCancellationRequested)
        {
            // Closing the drawer cancels its polling, not the browser sign-in owned by Python.
        }
        catch (Exception exception) when (exception is HttpRequestException or ApiRequestException or
            IOException or JsonException or ArgumentException or InvalidOperationException or OperationCanceledException)
        {
            _status = new AzureAuthenticationStatus { State = "unavailable" };
            if (exception is HttpRequestException { StatusCode: System.Net.HttpStatusCode.NotFound })
            {
                _operationId = null;
            }
            _message = exception is OperationCanceledException
                ? "The Python API did not respond in time. Reopen the menu to check Azure sign-in."
                : $"Azure authentication failed: {exception.Message}";
        }
        finally
        {
            _busy = false;
            NotifyState();
            _operationLock.Release();
        }
    }

    private void NotifyState()
    {
        foreach (var property in new[]
        {
            nameof(IsLoggedIn), nameof(IsWorking), nameof(CanAuthenticate), nameof(ButtonText),
            nameof(AccountName), nameof(Message), nameof(LightColor), nameof(LoginTenants), nameof(SuggestedTenantId)
        })
        {
            OnPropertyChanged(property);
        }
    }
}

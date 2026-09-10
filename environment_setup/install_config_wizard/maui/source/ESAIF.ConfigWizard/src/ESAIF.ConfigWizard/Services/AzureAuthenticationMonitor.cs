using System.Text.Json;
using ESAIF.BaseLayer.Application;
using ESAIF.DomainLayer.Configuration;

namespace ESAIF.ConfigWizard.Services;

public sealed class AzureAuthenticationMonitor(
    IAzureAuthenticationClient client, WizardSession wizard, FactoryNetworkSession network) : ObservableObject
{
    private Task? _checking;
    private CancellationToken _checkingCancellation;
    private bool _hasAuthenticated;
    private long _version;
    private readonly Dictionary<string, string?> _tenantFolders = new(StringComparer.OrdinalIgnoreCase);
    public event EventHandler? FirstAuthenticated;
    public AzureAuthenticationStatus Status { get; private set; } = new();
    public bool IsLoggedIn => Status.IsLoggedIn;
    public bool IsChecking => _checking is { IsCompleted: false };
    public DateTimeOffset? CheckedAt { get; private set; }
    public long AuthenticationVersion { get; private set; }
    public string? LoginFolder { get; private set; }
    public string? GetLoginFolder(string? tenantId) =>
        tenantId is not null && _tenantFolders.TryGetValue(tenantId, out var folder) ? folder : LoginFolder;

    public Task CheckAsync(CancellationToken cancellationToken = default)
    {
        if (_checking is { IsCompleted: false })
        {
            return _checkingCancellation.IsCancellationRequested && !cancellationToken.IsCancellationRequested
                ? RecheckAfterAsync(_checking, cancellationToken) : _checking;
        }
        _checkingCancellation = cancellationToken;
        _checking = CheckCoreAsync(cancellationToken);
        return _checking;
    }

    private async Task RecheckAfterAsync(Task previous, CancellationToken cancellationToken)
    {
        await previous;
        if (!cancellationToken.IsCancellationRequested)
        {
            await CheckAsync(cancellationToken);
        }
    }

    public void Invalidate(string message)
    {
        _version++;
        Status = new() { State = "unavailable", Message = message };
        OnPropertyChanged(nameof(Status));
        OnPropertyChanged(nameof(IsLoggedIn));
    }

    private async Task CheckCoreAsync(CancellationToken cancellationToken)
    {
        await Task.Yield();
        var version = _version;
        try
        {
            await wizard.InitializeAsync(cancellationToken: cancellationToken);
            var current = wizard.GetString("_save_folder");
            var folders = await network.DiscoverFoldersAsync(current, cancellationToken);
            var statuses = new List<(string? Folder, AzureAuthenticationStatus Status)>();
            foreach (var folder in folders.Count > 0 ? folders : new string[] { current })
            {
                cancellationToken.ThrowIfCancellationRequested();
                var scope = string.IsNullOrWhiteSpace(folder) ? null : folder;
                statuses.Add((scope, await client.GetAzureAuthenticationStatusAsync(scope, cancellationToken)));
            }
            if (version != _version) { return; }
            _tenantFolders.Clear();
            foreach (var item in statuses)
            {
                foreach (var tenant in item.Status.Tenants.Where(tenant => tenant.NeedsLogin))
                {
                    _tenantFolders.TryAdd(tenant.TenantId, item.Folder);
                }
            }
            var required = statuses.FirstOrDefault(item => !item.Status.IsLoggedIn);
            var primary = required.Status ?? statuses[0].Status;
            LoginFolder = required.Status is null ? current : required.Folder;
            var wasLoggedIn = IsLoggedIn;
            Status = primary with
            {
                IsLoggedIn = statuses.All(item => item.Status.IsLoggedIn),
                Tenants = statuses.SelectMany(item => item.Status.Tenants)
                    .GroupBy(tenant => tenant.TenantId, StringComparer.OrdinalIgnoreCase)
                    .Select(group => group.FirstOrDefault(tenant => tenant.NeedsLogin) ?? group.First()).ToArray()
            };
            if (!wasLoggedIn && IsLoggedIn)
            {
                AuthenticationVersion++;
            }
            CheckedAt = DateTimeOffset.Now;
            NotifyState();
            if (IsLoggedIn && !_hasAuthenticated)
            {
                _hasAuthenticated = true;
                FirstAuthenticated?.Invoke(this, EventArgs.Empty);
            }
        }
        catch (OperationCanceledException) when (cancellationToken.IsCancellationRequested)
        {
            // A backgrounded or closed window stops its check, never the API-owned login.
            if (version == _version)
            {
                Invalidate("Azure sign-in check was paused. It will resume when the app is active.");
            }
        }
        catch (Exception error) when (error is HttpRequestException or IOException or JsonException or
            InvalidOperationException or ArgumentException or OperationCanceledException)
        {
            if (version == _version)
            {
                Invalidate($"Azure sign-in could not be verified: {error.Message}");
            }
        }
    }

    private void NotifyState()
    {
        OnPropertyChanged(nameof(Status));
        OnPropertyChanged(nameof(IsLoggedIn));
        OnPropertyChanged(nameof(CheckedAt));
        OnPropertyChanged(nameof(LoginFolder));
    }
}

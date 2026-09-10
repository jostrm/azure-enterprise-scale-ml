using ESAIF.DomainLayer.Configuration;

namespace ESAIF.ConfigWizard.Services;

/// <summary>Catalog selection is separate from the unsaved configuration editor.</summary>
public sealed class FactoryCatalogSession
{
    private readonly IFactoryCatalogClient _client;
    private readonly WizardSession _wizard;
    private readonly IAiFactoryConnectionProvider _connections;
    private readonly Dictionary<string, (string? Factory, string? ScaleSet, string? Project)> _selection = new(StringComparer.Ordinal);
    private AiFactoryConnection? _connection;
    private string _folder;
    private long _generation;
    private long _reload;

    public FactoryCatalogSession(IFactoryCatalogClient client, WizardSession wizard,
        IAiFactoryConnectionProvider connections, AzureAuthenticationMonitor? authentication = null)
    {
        _client = client;
        _wizard = wizard;
        _connections = connections;
        _folder = wizard.GetString("_save_folder");
        wizard.StateChanged += OnWizardChanged;
        wizard.Connection.PropertyChanged += (_, e) =>
        {
            if (e.PropertyName == nameof(ApiConnectionState.Status) &&
                wizard.Connection.Status is ApiConnectionStatus.Verifying or ApiConnectionStatus.Disconnected)
                InvalidateContext();
        };
        if (authentication is not null)
        {
            var previous = authentication.Status;
            var previousVersion = authentication.AuthenticationVersion;
            authentication.PropertyChanged += (_, e) =>
            {
                if (e.PropertyName != nameof(AzureAuthenticationMonitor.Status)) return;
                var current = authentication.Status;
                if (previousVersion == authentication.AuthenticationVersion && SameAuthentication(previous, current)) return;
                previous = current;
                previousVersion = authentication.AuthenticationVersion;
                InvalidateConsent();
            };
        }
    }

    public event EventHandler? Changed;
    public event EventHandler? ConsentInvalidated;
    public string Folder => _folder;
    public long Generation => _generation;
    public FactoryCatalog? Catalog { get; private set; }
    public bool IsCatalog => Catalog?.Mode == "catalog";
    public bool IsLegacy => Catalog?.Mode == "legacy";
    public bool AllowsLegacyFolder(string folder) => IsLegacy &&
        !string.IsNullOrWhiteSpace(folder) && FactoryNetworkSession.SameFolder(folder, Folder);
    public string? SelectedFactoryId { get; private set; }
    public string? SelectedScaleSetId { get; private set; }
    public string? SelectedProjectId { get; private set; }
    public CatalogFactory? SelectedFactory => Catalog?.Factories.SingleOrDefault(x => x.Id == SelectedFactoryId);
    public CatalogScaleSet? SelectedScaleSet => SelectedFactory?.ScaleSets.SingleOrDefault(x => x.Id == SelectedScaleSetId);
    public CatalogProject? SelectedProject => SelectedFactory?.Projects.SingleOrDefault(x => x.Id == SelectedProjectId);

    public async Task<bool> VerifyContextAsync(CancellationToken cancellationToken = default)
    {
        OnWizardChanged(this, EventArgs.Empty);
        var connection = await _connections.GetConnectionAsync(cancellationToken);
        var unchanged = _connection is null || _connection == connection;
        if (!unchanged) InvalidateContext();
        _connection = connection;
        return unchanged;
    }

    public async Task RefreshAsync(CancellationToken cancellationToken = default)
    {
        await VerifyContextAsync(cancellationToken);
        if (string.IsNullOrWhiteSpace(Folder))
            throw new InvalidOperationException("Select an AI Factory root in the configuration wizard first.");
        InvalidateConsent();
        var generation = Generation;
        var reload = ++_reload;
        var folder = Folder;
        FactoryCatalog catalog;
        try
        {
            catalog = await _client.GetFactoryCatalogAsync(folder, cancellationToken);
        }
        catch (Exception error) when (folder != Folder &&
            error is HttpRequestException or IOException or InvalidOperationException or ArgumentException or
                System.Text.Json.JsonException or OperationCanceledException)
        {
            return;
        }
        if (!await VerifyContextAsync(cancellationToken) || generation != Generation || reload != _reload ||
            folder != Folder) return;
        Apply(catalog);
    }

    public void Apply(FactoryCatalog catalog)
    {
        ArgumentNullException.ThrowIfNull(catalog);
        if (catalog.ContractVersion != 1 || catalog.Mode is not ("catalog" or "legacy"))
            throw new InvalidDataException("This catalog contract is not supported. No catalog action is enabled.");
        if (catalog.Factories.Select(x => x.Id).Distinct(StringComparer.Ordinal).Count() != catalog.Factories.Count)
            throw new InvalidDataException("The catalog contains duplicate factory identities.");
        foreach (var factory in catalog.Factories)
        {
            if (factory.ScaleSets.Select(x => x.Id).Distinct(StringComparer.Ordinal).Count() != factory.ScaleSets.Count)
                throw new InvalidDataException("The catalog contains duplicate scale-set identities.");
            if (factory.Projects.Select(x => x.Id).Distinct(StringComparer.Ordinal).Count() != factory.Projects.Count)
                throw new InvalidDataException("The catalog contains duplicate project identities.");
        }
        Catalog = catalog;
        var saved = _selection.GetValueOrDefault(Folder);
        SelectedFactoryId = catalog.Factories.Any(x => x.Id == saved.Factory) ? saved.Factory : null;
        SelectedScaleSetId = SelectedFactory?.ScaleSets.Any(x => x.Id == saved.ScaleSet) == true ? saved.ScaleSet : null;
        SelectedProjectId = SelectedFactory?.Projects.Any(x => x.Id == saved.Project) == true ? saved.Project : null;
        SaveSelection();
        InvalidateConsent();
        Changed?.Invoke(this, EventArgs.Empty);
    }

    public void SelectFactory(string? id)
    {
        if (id is not null && Catalog?.Factories.Any(x => x.Id == id) != true)
            throw new InvalidOperationException("Select an exact factory from the current catalog.");
        if (id == SelectedFactoryId) return;
        SelectedFactoryId = id;
        SelectedScaleSetId = null;
        SelectedProjectId = null;
        SaveSelection();
        InvalidateConsent();
        Changed?.Invoke(this, EventArgs.Empty);
    }

    public void SelectScaleSet(string? id)
    {
        if (id is not null && SelectedFactory?.ScaleSets.Any(x => x.Id == id) != true)
            throw new InvalidOperationException("Select a scale set belonging to the selected factory.");
        if (id == SelectedScaleSetId) return;
        SelectedScaleSetId = id;
        SaveSelection();
        InvalidateConsent();
        Changed?.Invoke(this, EventArgs.Empty);
    }

    public void InvalidateConsent()
    {
        _generation++;
        ConsentInvalidated?.Invoke(this, EventArgs.Empty);
    }

    public void SelectProject(string? id)
    {
        if (id is not null && SelectedFactory?.Projects.Any(x => x.Id == id) != true)
            throw new InvalidOperationException("Select an exact project belonging to the selected factory.");
        if (id == SelectedProjectId) return;
        SelectedProjectId = id;
        SaveSelection();
        InvalidateConsent();
        Changed?.Invoke(this, EventArgs.Empty);
    }

    public void InvalidateContext()
    {
        Catalog = null;
        SelectedFactoryId = SelectedScaleSetId = SelectedProjectId = null;
        InvalidateConsent();
        Changed?.Invoke(this, EventArgs.Empty);
    }

    private void OnWizardChanged(object? sender, EventArgs e)
    {
        var folder = _wizard.GetString("_save_folder");
        if (folder == Folder) return;
        SaveSelection();
        _folder = folder;
        InvalidateContext();
    }

    private void SaveSelection() => _selection[Folder] = (SelectedFactoryId, SelectedScaleSetId, SelectedProjectId);

    private static bool SameAuthentication(AzureAuthenticationStatus left, AzureAuthenticationStatus right) =>
        left.State == right.State && left.IsLoggedIn == right.IsLoggedIn && left.AccountName == right.AccountName &&
        left.TenantId == right.TenantId && left.OperationId == right.OperationId &&
        left.Tenants.OrderBy(x => x.TenantId, StringComparer.Ordinal).Select(x => (x.TenantId, x.AccountName, x.NeedsLogin))
            .SequenceEqual(right.Tenants.OrderBy(x => x.TenantId, StringComparer.Ordinal)
                .Select(x => (x.TenantId, x.AccountName, x.NeedsLogin)));
}

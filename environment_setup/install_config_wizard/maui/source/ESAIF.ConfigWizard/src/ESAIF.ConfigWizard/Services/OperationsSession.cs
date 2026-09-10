using ESAIF.DomainLayer.Configuration;
using ESAIF.DomainLayer.Operations;

namespace ESAIF.ConfigWizard.Services;

public sealed class OperationsSession
{
    private readonly IAiFactoryApiClient _apiClient;
    private readonly WizardSession _wizardSession;
    private readonly SemaphoreSlim _loadLock = new(1, 1);
    private string _overviewFolder = string.Empty;
    private string _observedFolder;
    private long _loadVersion;
    private long _invalidationVersion;
    private bool _overviewIncludesAzure;
    private bool _overviewWasForced;

    public OperationsSession(
        IAiFactoryApiClient apiClient,
        WizardSession wizardSession)
    {
        _apiClient = apiClient;
        _wizardSession = wizardSession;
        _observedFolder = Folder;
        _wizardSession.StateChanged += OnWizardStateChanged;
    }

    public event EventHandler? OverviewChanged;

    public OperationsOverview? Current { get; private set; }

    public string Folder => _wizardSession.GetString("_save_folder").Trim();

    public bool HasOverview => Current is not null;

    public string MissingFolderMessage =>
        string.IsNullOrWhiteSpace(Folder)
            ? OperationsPresentation.MissingFolderMessage
            : string.Empty;

    public string SourceLabel =>
        OperationsPresentation.GetSourceLabel(Current?.Source);

    public string Warning => Current?.Warning?.Trim() ?? string.Empty;

    public async Task<OperationsOverview?> LoadAsync(
        bool forceRefresh = false,
        bool includeAzure = true,
        CancellationToken cancellationToken = default)
    {
        await _wizardSession.InitializeAsync(cancellationToken: cancellationToken);
        var folder = Folder;
        if (string.IsNullOrWhiteSpace(folder))
        {
            Invalidate();
            return null;
        }

        var observedVersion = Interlocked.Read(ref _loadVersion);
        if (!forceRefresh &&
            Current is not null &&
            _overviewIncludesAzure == includeAzure &&
            FactoryNetworkSession.SameFolder(_overviewFolder, folder))
        {
            return Current;
        }

        await _loadLock.WaitAsync(cancellationToken);
        try
        {
            folder = Folder;
            if (string.IsNullOrWhiteSpace(folder))
            {
                Invalidate();
                return null;
            }

            var sameFolder = Current is not null &&
                _overviewIncludesAzure == includeAzure &&
                FactoryNetworkSession.SameFolder(_overviewFolder, folder);
            if (sameFolder &&
                (!forceRefresh || (_overviewWasForced &&
                    Interlocked.Read(ref _loadVersion) != observedVersion)))
            {
                return Current;
            }

            var invalidationVersion = Interlocked.Read(ref _invalidationVersion);
            var overview = await _apiClient.GetOperationsOverviewAsync(
                folder,
                includeAzure,
                forceRefresh,
                cancellationToken);
            if (Interlocked.Read(ref _invalidationVersion) != invalidationVersion ||
                !FactoryNetworkSession.SameFolder(Folder, folder))
            {
                return null;
            }

            Current = overview;
            _overviewFolder = folder;
            _observedFolder = folder;
            _overviewIncludesAzure = includeAzure;
            _overviewWasForced = forceRefresh;
            Interlocked.Increment(ref _loadVersion);
            OverviewChanged?.Invoke(this, EventArgs.Empty);
            return overview;
        }
        finally
        {
            _loadLock.Release();
        }
    }

    private void OnWizardStateChanged(object? sender, EventArgs e)
    {
        var folder = Folder;
        if (FactoryNetworkSession.SameFolder(_observedFolder, folder))
        {
            return;
        }

        _observedFolder = folder;
        Invalidate();
    }

    public void Invalidate()
    {
        Interlocked.Increment(ref _invalidationVersion);
        Current = null;
        _overviewFolder = string.Empty;

        OverviewChanged?.Invoke(this, EventArgs.Empty);
    }

    public void ApplyRefreshedOverview(string folder, OperationsOverview overview)
    {
        if (!FactoryNetworkSession.SameFolder(folder, Folder))
        {
            return;
        }
        Interlocked.Increment(ref _invalidationVersion);
        Current = overview;
        _overviewFolder = Folder;
        _observedFolder = Folder;
        _overviewIncludesAzure = true;
        _overviewWasForced = true;
        Interlocked.Increment(ref _loadVersion);
        OverviewChanged?.Invoke(this, EventArgs.Empty);
    }
}

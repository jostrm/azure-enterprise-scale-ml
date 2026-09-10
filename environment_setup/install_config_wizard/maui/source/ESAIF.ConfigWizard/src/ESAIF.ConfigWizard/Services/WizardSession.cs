using System.Text.Json.Nodes;
using ESAIF.DomainLayer.Configuration;

namespace ESAIF.ConfigWizard.Services;

public sealed class WizardSession
{
    private const string FolderEnvironmentVariable = "ESAIF_AIFACTORY_FOLDER";
    private readonly IAiFactoryApiClient _apiClient;
    private readonly SemaphoreSlim _initializationLock = new(1, 1);
    private readonly string? _startupFolder;

    public WizardSession(IAiFactoryApiClient apiClient, ApiConnectionState? connection = null, string? startupFolder = null)
    {
        _apiClient = apiClient;
        Connection = connection ?? new ApiConnectionState();
        _startupFolder = startupFolder ?? Environment.GetEnvironmentVariable(FolderEnvironmentVariable);
    }

    public event EventHandler? StateChanged;

    public FactorySchema? Schema { get; private set; }

    public JsonObject State { get; private set; } = [];

    public ApiConnectionState Connection { get; }

    public WizardIdentity Identity => WizardIdentity.FromState(State, GetString("_save_folder"));

    public event EventHandler? StateReplaced;

    public bool IsInitialized => Schema is not null;

    public async Task InitializeAsync(
        bool force = false,
        CancellationToken cancellationToken = default)
    {
        if (IsInitialized && Connection.IsConnected && !force)
        {
            return;
        }

        await _initializationLock.WaitAsync(cancellationToken);
        try
        {
            if (IsInitialized && Connection.IsConnected && !force)
            {
                return;
            }

            Connection.BeginVerification();
            var schema = await _apiClient.GetSchemaAsync(cancellationToken);
            var firstInitialization = !IsInitialized;
            var replaceState = !IsInitialized || force;
            Schema = schema;
            Connection.MarkVerified();
            if (replaceState)
            {
                State = (JsonObject) schema.Defaults.DeepClone();
                if (firstInitialization && !string.IsNullOrWhiteSpace(_startupFolder))
                {
                    State["_save_folder"] = _startupFolder.Trim();
                }
                StateReplaced?.Invoke(this, EventArgs.Empty);
            }

            StateChanged?.Invoke(this, EventArgs.Empty);
        }
        catch (Exception exception) when (
            exception is HttpRequestException or System.Text.Json.JsonException or InvalidDataException
                or InvalidOperationException or ArgumentException ||
            exception is OperationCanceledException && !cancellationToken.IsCancellationRequested)
        {
            Connection.MarkFailed(exception);
            throw;
        }
        finally
        {
            _initializationLock.Release();
        }
    }

    public async Task RefreshSchemaAsync(CancellationToken cancellationToken = default)
    {
        if (!IsInitialized)
        {
            await InitializeAsync(cancellationToken: cancellationToken);
            return;
        }
        await _initializationLock.WaitAsync(cancellationToken);
        try
        {
            Schema = await _apiClient.GetSchemaAsync(cancellationToken);
            Connection.MarkVerified();
            // Refresh schema-driven controls without resetting user edits to defaults.
            StateReplaced?.Invoke(this, EventArgs.Empty);
            StateChanged?.Invoke(this, EventArgs.Empty);
        }
        finally
        {
            _initializationLock.Release();
        }
    }

    public void ReplaceState(JsonObject state)
    {
        ArgumentNullException.ThrowIfNull(state);
        State = (JsonObject) state.DeepClone();
        StateReplaced?.Invoke(this, EventArgs.Empty);
        StateChanged?.Invoke(this, EventArgs.Empty);
    }

    public string GetString(string key)
    {
        if (key.Equals("_save_folder", StringComparison.Ordinal) && !IsInitialized && State.Count == 0)
        {
            if (!string.IsNullOrWhiteSpace(_startupFolder))
            {
                return _startupFolder.Trim();
            }
        }

        return State[key]?.ToString() ?? string.Empty;
    }

    public void SetValue(string key, JsonNode? value)
    {
        ConfigurationStateEditing.SetValue(State, Schema, key, value);
        StateChanged?.Invoke(this, EventArgs.Empty);
    }

    public void ApplyScalingNetworkDefaults()
    {
        ScalingModeConfiguration.ApplyDefaults(State, Schema);
        StateChanged?.Invoke(this, EventArgs.Empty);
    }

    public void ApplyNetworkOptimization(JsonObject expected, JsonObject changes)
    {
        ScalingModeConfiguration.ApplyOptimization(State, expected, changes);
        StateChanged?.Invoke(this, EventArgs.Empty);
    }
}

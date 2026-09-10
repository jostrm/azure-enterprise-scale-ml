using ESAIF.DomainLayer.Configuration;

namespace ESAIF.ConfigWizard.Services;

public sealed class ConnectionSettingsService : IConnectionSettingsService
{
    private const string BaseAddressKey = "api.base-address";
    private const string ApiKeyKey = "api.key";
    private const string BaseAddressEnvironmentVariable = "ESAIF_API_BASE_ADDRESS";
    private const string ApiKeyEnvironmentVariable = "ESAIF_API_KEY";

    public async Task<AiFactoryConnection> GetConnectionAsync(
        CancellationToken cancellationToken = default)
    {
        cancellationToken.ThrowIfCancellationRequested();
        var storedBaseAddress = Preferences.Default.Get(
            BaseAddressKey,
            AiFactoryConnection.LocalDefault.BaseAddress);
        var storedApiKey = await SecureStorage.Default.GetAsync(ApiKeyKey) ?? string.Empty;
        var baseAddress = EnvironmentValueOrFallback(
            BaseAddressEnvironmentVariable,
            storedBaseAddress);
        var apiKey = EnvironmentValueOrFallback(
            ApiKeyEnvironmentVariable,
            storedApiKey);
        return new AiFactoryConnection(baseAddress, apiKey);
    }

    public async Task SaveConnectionAsync(
        AiFactoryConnection connection,
        CancellationToken cancellationToken = default)
    {
        ArgumentNullException.ThrowIfNull(connection);
        cancellationToken.ThrowIfCancellationRequested();

        Preferences.Default.Set(BaseAddressKey, connection.BaseAddress.Trim());
        if (string.IsNullOrWhiteSpace(connection.ApiKey))
        {
            SecureStorage.Default.Remove(ApiKeyKey);
            return;
        }

        await SecureStorage.Default.SetAsync(ApiKeyKey, connection.ApiKey);
    }

    internal static string EnvironmentValueOrFallback(
        string variable,
        string fallback)
    {
        var value = Environment.GetEnvironmentVariable(variable);
        return string.IsNullOrWhiteSpace(value) ? fallback : value.Trim();
    }
}

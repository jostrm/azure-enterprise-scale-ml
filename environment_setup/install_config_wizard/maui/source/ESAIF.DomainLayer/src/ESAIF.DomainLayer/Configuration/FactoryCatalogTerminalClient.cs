using System.Text.Json;

namespace ESAIF.DomainLayer.Configuration;

public interface IFactoryCatalogTerminalClient
{
    Task<ProjectTerminalOutput> ReadFactoryCatalogTerminalAsync(AiFactoryConnection connection, string folder,
        string jobId, long cursor, CancellationToken cancellationToken = default);
    Task WriteFactoryCatalogTerminalAsync(AiFactoryConnection connection, string folder,
        string jobId, string data, CancellationToken cancellationToken = default);
    Task ResizeFactoryCatalogTerminalAsync(AiFactoryConnection connection, string folder,
        string jobId, int columns, int rows, CancellationToken cancellationToken = default);
}

public sealed partial class AiFactoryApiClient : IFactoryCatalogTerminalClient
{
    private const string CatalogTerminalPath = "api/v1/factory-catalog";

    public async Task<ProjectTerminalOutput> ReadFactoryCatalogTerminalAsync(AiFactoryConnection connection,
        string folder, string jobId, long cursor, CancellationToken cancellationToken = default)
    {
        ValidateTerminalScope(folder, jobId);
        ArgumentOutOfRangeException.ThrowIfNegative(cursor);
        var result = await SendTerminalAsync<ProjectTerminalOutput>(connection, HttpMethod.Get,
            $"{CatalogTerminalPath}/terminal?folder={Uri.EscapeDataString(folder)}&job_id={Uri.EscapeDataString(jobId)}&cursor={cursor}",
            null, cancellationToken);
        ValidateTerminalOutput(result, jobId, cursor);
        return result;
    }

    public async Task WriteFactoryCatalogTerminalAsync(AiFactoryConnection connection, string folder,
        string jobId, string data, CancellationToken cancellationToken = default)
    {
        ValidateTerminalScope(folder, jobId);
        ArgumentNullException.ThrowIfNull(data);
        if (data.Length is < 1 or > 8_192) throw new ArgumentOutOfRangeException(nameof(data));
        await SendTerminalAsync<JsonElement>(connection, HttpMethod.Post,
            $"{CatalogTerminalPath}/terminal/input", new { folder, job_id = jobId, data }, cancellationToken);
    }

    public async Task ResizeFactoryCatalogTerminalAsync(AiFactoryConnection connection, string folder,
        string jobId, int columns, int rows, CancellationToken cancellationToken = default)
    {
        ValidateTerminalScope(folder, jobId);
        if (columns is < 20 or > 500 || rows is < 5 or > 200)
            throw new ArgumentOutOfRangeException(nameof(columns));
        await SendTerminalAsync<JsonElement>(connection, HttpMethod.Post,
            $"{CatalogTerminalPath}/terminal/resize", new { folder, job_id = jobId, columns, rows }, cancellationToken);
    }
}

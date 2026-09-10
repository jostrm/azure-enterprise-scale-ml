using System.Net.Http.Json;
using System.Text.Json.Serialization;

namespace ESAIF.DomainLayer.Configuration;

public sealed class ProjectTerminalConnectionException(string message) : InvalidOperationException(message);

public interface IProjectTerminalClient
{
    Task<ProjectTerminalOutput> ReadProjectTerminalAsync(AiFactoryConnection connection, string folder,
        string jobId, long cursor, CancellationToken cancellationToken = default);
    Task WriteProjectTerminalAsync(AiFactoryConnection connection, string folder,
        string jobId, string data, CancellationToken cancellationToken = default);
    Task ResizeProjectTerminalAsync(AiFactoryConnection connection, string folder,
        string jobId, int columns, int rows, CancellationToken cancellationToken = default);
}

public sealed record ProjectTerminalOutput
{
    [JsonPropertyName("job_id")]
    public string JobId { get; init; } = string.Empty;
    public string Output { get; init; } = string.Empty;
    [JsonPropertyName("next_cursor")]
    public long NextCursor { get; init; }
    public bool Reset { get; init; }
    public string Status { get; init; } = string.Empty;
}

public sealed partial class AiFactoryApiClient : IProjectTerminalClient
{
    private const string TerminalPath = "api/v1/operations/project-deployments/terminal";

    public async Task<ProjectTerminalOutput> ReadProjectTerminalAsync(AiFactoryConnection connection,
        string folder, string jobId, long cursor, CancellationToken cancellationToken = default)
    {
        ValidateTerminalScope(folder, jobId);
        ArgumentOutOfRangeException.ThrowIfNegative(cursor);
        var result = await SendTerminalAsync<ProjectTerminalOutput>(connection, HttpMethod.Get,
            $"{TerminalPath}?folder={Uri.EscapeDataString(folder)}&job_id={Uri.EscapeDataString(jobId)}&cursor={cursor}",
            null, cancellationToken);
        ValidateTerminalOutput(result, jobId, cursor);
        return result;
    }

    public async Task WriteProjectTerminalAsync(AiFactoryConnection connection, string folder,
        string jobId, string data, CancellationToken cancellationToken = default)
    {
        ValidateTerminalScope(folder, jobId);
        ArgumentNullException.ThrowIfNull(data);
        if (data.Length is < 1 or > 8_192)
            throw new ArgumentOutOfRangeException(nameof(data));
        await SendTerminalAsync<System.Text.Json.JsonElement>(connection, HttpMethod.Post,
            $"{TerminalPath}/input", new { folder, job_id = jobId, data }, cancellationToken);
    }

    public async Task ResizeProjectTerminalAsync(AiFactoryConnection connection, string folder,
        string jobId, int columns, int rows, CancellationToken cancellationToken = default)
    {
        ValidateTerminalScope(folder, jobId);
        if (columns is < 20 or > 500 || rows is < 5 or > 200)
            throw new ArgumentOutOfRangeException(nameof(columns));
        await SendTerminalAsync<System.Text.Json.JsonElement>(connection, HttpMethod.Post,
            $"{TerminalPath}/resize", new { folder, job_id = jobId, columns, rows }, cancellationToken);
    }

    private async Task<T> SendTerminalAsync<T>(AiFactoryConnection connection, HttpMethod method,
        string path, object? body, CancellationToken cancellationToken)
    {
        ArgumentNullException.ThrowIfNull(connection);
        // Bind every request to the connection captured when the job was opened, never to new settings.
        if (await _connectionProvider.GetConnectionAsync(cancellationToken) != connection)
            throw new ProjectTerminalConnectionException("The API connection changed. Restore it before reconnecting this terminal.");
        if (string.IsNullOrWhiteSpace(connection.ApiKey))
            throw new ProjectTerminalConnectionException("The API key is required for the terminal.");
        Uri address;
        try { address = new Uri(connection.BaseUri, path); }
        catch (InvalidOperationException) { throw new ProjectTerminalConnectionException("The API address is invalid."); }
        using var request = new HttpRequestMessage(method, address);
        request.Headers.Add(ApiKeyHeader, connection.ApiKey);
        request.Headers.CacheControl = new() { NoStore = true };
        if (body is not null) request.Content = JsonContent.Create(body, options: SerializerOptions);
        return await _transport.SendAsync<T>(request, cancellationToken);
    }

    private static void ValidateTerminalScope(string folder, string jobId)
    {
        ArgumentException.ThrowIfNullOrWhiteSpace(folder);
        ArgumentException.ThrowIfNullOrWhiteSpace(jobId);
        if (folder.Length > 4096 || jobId.Length > 128)
            throw new ArgumentOutOfRangeException(nameof(jobId));
    }

    private static void ValidateTerminalOutput(ProjectTerminalOutput result, string jobId, long cursor)
    {
        if (result.JobId != jobId || result.NextCursor < 0 ||
            (!result.Reset && result.NextCursor < cursor) || result.Output.Length > 262_144)
            throw new InvalidDataException("The terminal returned an invalid output scope or cursor.");
    }
}

using System.Net;
using System.Text.Json;
using ESAIF.BaseLayer.Networking;

namespace ESAIF.ConfigWizard.Services;

public sealed class ProjectTerminalTransport : IJsonApiTransport, IDisposable
{
    private readonly HttpClient _http = new(new HttpClientHandler
    {
        AllowAutoRedirect = false,
        UseCookies = false,
        AutomaticDecompression = DecompressionMethods.None
    }) { Timeout = TimeSpan.FromSeconds(10) };

    public async Task<TResponse> SendAsync<TResponse>(HttpRequestMessage request,
        CancellationToken cancellationToken = default)
    {
        using var response = await _http.SendAsync(request, HttpCompletionOption.ResponseHeadersRead, cancellationToken);
        if (!response.IsSuccessStatusCode)
            throw new ApiRequestException(response.StatusCode, "The terminal request failed.", string.Empty);
        const int limit = 2_097_152;
        if (response.Content.Headers.ContentLength > limit) throw new InvalidDataException("Terminal response limit exceeded.");
        await using var stream = await response.Content.ReadAsStreamAsync(cancellationToken);
        using var memory = new MemoryStream();
        var buffer = new byte[16_384];
        int read;
        while ((read = await stream.ReadAsync(buffer, cancellationToken)) > 0)
        {
            if (memory.Length + read > limit) throw new InvalidDataException("Terminal response limit exceeded.");
            memory.Write(buffer, 0, read);
        }
        memory.Position = 0;
        return await JsonSerializer.DeserializeAsync<TResponse>(memory,
            new JsonSerializerOptions(JsonSerializerDefaults.Web), cancellationToken)
            ?? throw new InvalidDataException("The terminal response was empty.");
    }

    public void Dispose() => _http.Dispose();
}

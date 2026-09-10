using System.Net.Http.Json;
using System.Text.Json;
using System.Text.Json.Nodes;

namespace ESAIF.BaseLayer.Networking;

public sealed class HttpJsonApiTransport : IJsonApiTransport
{
    private static readonly JsonSerializerOptions SerializerOptions = new(JsonSerializerDefaults.Web);
    private readonly HttpClient _httpClient;

    public HttpJsonApiTransport(HttpClient httpClient)
    {
        ArgumentNullException.ThrowIfNull(httpClient);
        _httpClient = httpClient;
    }

    public async Task<TResponse> SendAsync<TResponse>(
        HttpRequestMessage request,
        CancellationToken cancellationToken = default)
    {
        ArgumentNullException.ThrowIfNull(request);

        using var response = await _httpClient.SendAsync(
            request,
            HttpCompletionOption.ResponseHeadersRead,
            cancellationToken);

        if (!response.IsSuccessStatusCode)
        {
            var responseBody = await response.Content.ReadAsStringAsync(cancellationToken);
            throw new ApiRequestException(
                response.StatusCode,
                ExtractErrorMessage(responseBody, response.ReasonPhrase),
                responseBody);
        }

        var result = await response.Content.ReadFromJsonAsync<TResponse>(
            SerializerOptions,
            cancellationToken);

        return result
            ?? throw new InvalidDataException(
                $"The API returned an empty {typeof(TResponse).Name} response.");
    }

    private static string ExtractErrorMessage(string responseBody, string? reasonPhrase)
    {
        if (!string.IsNullOrWhiteSpace(responseBody))
        {
            try
            {
                var detail = JsonNode.Parse(responseBody)?["detail"];
                if (detail is JsonValue value &&
                    value.TryGetValue<string>(out var text) &&
                    !string.IsNullOrWhiteSpace(text))
                {
                    return text;
                }

                if (detail is JsonArray errors)
                {
                    var messages = errors
                        .Select(item => item?["msg"]?.GetValue<string>())
                        .Where(message => !string.IsNullOrWhiteSpace(message))
                        .ToArray();

                    if (messages.Length > 0)
                    {
                        return string.Join(Environment.NewLine, messages!);
                    }
                }
            }
            catch (JsonException)
            {
                // The raw response remains available on ApiRequestException.
            }
        }

        return string.IsNullOrWhiteSpace(reasonPhrase)
            ? "The API request failed."
            : reasonPhrase;
    }
}

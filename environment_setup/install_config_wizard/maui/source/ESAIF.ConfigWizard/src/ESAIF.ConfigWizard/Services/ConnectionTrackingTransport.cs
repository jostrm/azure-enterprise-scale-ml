using System.Text.Json;
using ESAIF.BaseLayer.Networking;

namespace ESAIF.ConfigWizard.Services;

// Observes existing requests only; it never polls, signs in, or changes request content.
public sealed class ConnectionTrackingTransport(
    IJsonApiTransport inner,
    ApiConnectionState connection) : IJsonApiTransport
{
    public async Task<TResponse> SendAsync<TResponse>(
        HttpRequestMessage request,
        CancellationToken cancellationToken = default)
    {
        try
        {
            var response = await inner.SendAsync<TResponse>(request, cancellationToken);
            if (request.Headers.Contains("X-API-Key"))
            {
                connection.MarkVerified();
            }

            return response;
        }
        catch (Exception exception) when (
            exception is HttpRequestException httpException &&
                (httpException.StatusCode is null or System.Net.HttpStatusCode.Unauthorized or System.Net.HttpStatusCode.Forbidden ||
                 (int)httpException.StatusCode.Value >= 500) ||
            exception is JsonException or IOException or InvalidDataException ||
            exception is OperationCanceledException && !cancellationToken.IsCancellationRequested)
        {
            connection.MarkFailed(exception);
            throw;
        }
    }
}

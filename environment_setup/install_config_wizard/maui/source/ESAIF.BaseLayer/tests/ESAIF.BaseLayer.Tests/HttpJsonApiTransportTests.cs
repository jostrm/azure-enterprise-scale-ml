using System.Net;
using System.Text;
using ESAIF.BaseLayer.Networking;

namespace ESAIF.BaseLayer.Tests;

public sealed class HttpJsonApiTransportTests
{
    [Fact]
    public async Task SendAsync_DeserializesSuccessfulResponse()
    {
        using var client = new HttpClient(new StubHandler(
            new HttpResponseMessage(HttpStatusCode.OK)
            {
                Content = new StringContent(
                    """{"status":"ok","version":"1.0.0"}""",
                    Encoding.UTF8,
                    "application/json")
            }));
        var transport = new HttpJsonApiTransport(client);
        using var request = new HttpRequestMessage(HttpMethod.Get, "http://localhost/health");

        var result = await transport.SendAsync<HealthResult>(request);

        Assert.Equal("ok", result.Status);
        Assert.Equal("1.0.0", result.Version);
    }

    [Fact]
    public async Task SendAsync_ThrowsApiErrorWithFastApiDetail()
    {
        using var client = new HttpClient(new StubHandler(
            new HttpResponseMessage(HttpStatusCode.Unauthorized)
            {
                Content = new StringContent(
                    """{"detail":"Invalid API key"}""",
                    Encoding.UTF8,
                    "application/json")
            }));
        var transport = new HttpJsonApiTransport(client);
        using var request = new HttpRequestMessage(HttpMethod.Get, "http://localhost/api");

        var exception = await Assert.ThrowsAsync<ApiRequestException>(
            () => transport.SendAsync<HealthResult>(request));

        Assert.Equal(HttpStatusCode.Unauthorized, exception.StatusCode);
        Assert.Equal("Invalid API key", exception.Message);
    }

    private sealed record HealthResult(string Status, string Version);

    private sealed class StubHandler(HttpResponseMessage response) : HttpMessageHandler
    {
        protected override Task<HttpResponseMessage> SendAsync(
            HttpRequestMessage request,
            CancellationToken cancellationToken)
        {
            return Task.FromResult(response);
        }
    }
}

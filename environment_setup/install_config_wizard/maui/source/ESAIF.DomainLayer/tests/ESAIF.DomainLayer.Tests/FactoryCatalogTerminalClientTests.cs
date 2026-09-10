using System.Text.Json;
using ESAIF.BaseLayer.Networking;
using ESAIF.DomainLayer.Configuration;

namespace ESAIF.DomainLayer.Tests;

public sealed class FactoryCatalogTerminalClientTests
{
    [Fact]
    public async Task CatalogReadUsesFixedRouteAndCapturedConnectionWithoutCaching()
    {
        var transport = new Transport();
        var connection = new Connection();
        var result = await new AiFactoryApiClient(transport, connection).ReadFactoryCatalogTerminalAsync(
            connection.Current, @"C:\factory & one\aifactory", "catalog-job", 0);
        Assert.Equal("/api/v1/factory-catalog/terminal", transport.Uri!.AbsolutePath);
        Assert.Equal("?folder=C%3A%5Cfactory%20%26%20one%5Caifactory&job_id=catalog-job&cursor=0", transport.Uri.Query);
        Assert.Equal("catalog-job", result.JobId);
        Assert.Equal("test-key", transport.Key);
        Assert.True(transport.NoStore);
    }

    [Fact]
    public async Task CatalogInputAndResizeNeverUseTheProjectEndpoint()
    {
        var transport = new Transport { Response = "{}" };
        var connection = new Connection();
        var client = new AiFactoryApiClient(transport, connection);
        await client.WriteFactoryCatalogTerminalAsync(connection.Current, "folder", "catalog-job", "yes\r");
        Assert.Equal("/api/v1/factory-catalog/terminal/input", transport.Uri!.AbsolutePath);
        Assert.Equal("""{"folder":"folder","job_id":"catalog-job","data":"yes\r"}""", transport.Body);
        await client.ResizeFactoryCatalogTerminalAsync(connection.Current, "folder", "catalog-job", 80, 24);
        Assert.Equal("/api/v1/factory-catalog/terminal/resize", transport.Uri!.AbsolutePath);
        Assert.Equal("""{"folder":"folder","job_id":"catalog-job","columns":80,"rows":24}""", transport.Body);
    }

    [Fact]
    public async Task ChangedApiConnectionBlocksBeforeAnyCatalogInput()
    {
        var connection = new Connection();
        var captured = connection.Current;
        connection.Current = new("http://127.0.0.1:9999", "other-key");
        var transport = new Transport();
        await Assert.ThrowsAsync<ProjectTerminalConnectionException>(() =>
            new AiFactoryApiClient(transport, connection).WriteFactoryCatalogTerminalAsync(captured, "folder", "catalog-job", "yes"));
        Assert.Equal(0, transport.Calls);
    }

    [Theory]
    [InlineData("""{"job_id":"other","output":"","next_cursor":0,"status":"running"}""")]
    [InlineData("""{"job_id":"catalog-job","output":"","next_cursor":-1,"status":"running"}""")]
    [InlineData("""{"job_id":"catalog-job","output":"","next_cursor":1,"status":"running"}""")]
    public async Task MismatchedScopeOrCursorIsRejected(string response)
    {
        var transport = new Transport { Response = response };
        var connection = new Connection();
        await Assert.ThrowsAsync<InvalidDataException>(() =>
            new AiFactoryApiClient(transport, connection).ReadFactoryCatalogTerminalAsync(connection.Current, "folder", "catalog-job", 10));
    }

    private sealed class Connection : IAiFactoryConnectionProvider
    {
        public AiFactoryConnection Current { get; set; } = new("http://127.0.0.1:8765", "test-key");
        public Task<AiFactoryConnection> GetConnectionAsync(CancellationToken cancellationToken = default) => Task.FromResult(Current);
    }
    private sealed class Transport : IJsonApiTransport
    {
        public string Response = """{"job_id":"catalog-job","output":"prompt>","next_cursor":7,"status":"running"}""";
        public int Calls;
        public Uri? Uri;
        public string? Key;
        public bool NoStore;
        public string Body = string.Empty;
        public async Task<TResponse> SendAsync<TResponse>(HttpRequestMessage request, CancellationToken cancellationToken = default)
        {
            Calls++;
            Uri = request.RequestUri;
            Key = request.Headers.TryGetValues("X-API-Key", out var values) ? values.Single() : null;
            NoStore = request.Headers.CacheControl?.NoStore == true;
            Body = request.Content is null ? string.Empty : await request.Content.ReadAsStringAsync(cancellationToken);
            return JsonSerializer.Deserialize<TResponse>(Response, new JsonSerializerOptions(JsonSerializerDefaults.Web))!;
        }
    }
}

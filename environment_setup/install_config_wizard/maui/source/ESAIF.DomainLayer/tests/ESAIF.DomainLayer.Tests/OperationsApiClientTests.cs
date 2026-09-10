using System.Text.Json.Nodes;
using ESAIF.BaseLayer.Networking;
using ESAIF.DomainLayer.Configuration;
using ESAIF.DomainLayer.Operations;

namespace ESAIF.DomainLayer.Tests;

public sealed class OperationsApiClientTests
{
    [Fact]
    public async Task GetOperationsOverviewAsync_UsesRouteHeaderAndSnakeCaseBody()
    {
        var transport = new RecordingTransport(new OperationsOverview());
        var client = CreateClient(transport);

        await client.GetOperationsOverviewAsync(@"C:\factory", false, true);

        AssertRequest(transport, HttpMethod.Post, "/api/v1/operations/overview");
        Assert.Contains(@"""aifactory_folder"":""C:\\factory""", transport.RequestBody);
        Assert.Contains(@"""include_azure"":false", transport.RequestBody);
        Assert.Contains(@"""force_refresh"":true", transport.RequestBody);
    }

    [Fact]
    public async Task GetOperationsRegionsAsync_UsesGetWithoutBody()
    {
        var transport = new RecordingTransport(new OperationsRegionsResult());
        var client = CreateClient(transport);

        await client.GetOperationsRegionsAsync();

        AssertRequest(transport, HttpMethod.Get, "/api/v1/operations/regions");
        Assert.Empty(transport.RequestBody);
    }

    [Fact]
    public async Task LoadOperationsConfigAsync_UsesExpectedPayload()
    {
        var transport = new RecordingTransport(new OperationConfigResult());
        var client = CreateClient(transport);

        await client.LoadOperationsConfigAsync(@"C:\factory", "001", "dev", "rag");

        AssertRequest(transport, HttpMethod.Post, "/api/v1/operations/config/load");
        Assert.Contains(@"""project_number"":""001""", transport.RequestBody);
        Assert.Contains(@"""environment"":""dev""", transport.RequestBody);
        Assert.Contains(@"""kind"":""rag""", transport.RequestBody);
    }

    [Fact]
    public async Task SaveOperationsConfigAsync_SerializesExtensibleConfig()
    {
        var transport = new RecordingTransport(new OperationConfigResult());
        var client = CreateClient(transport);

        await client.SaveOperationsConfigAsync(
            @"C:\factory",
            "001",
            "stage",
            "mlops",
            new JsonObject
            {
                ["threshold"] = 0.85,
                ["retrain_on_drift"] = true
            });

        AssertRequest(transport, HttpMethod.Post, "/api/v1/operations/config/save");
        Assert.Contains(@"""config"":{", transport.RequestBody);
        Assert.Contains(@"""threshold"":0.85", transport.RequestBody);
        Assert.Contains(@"""retrain_on_drift"":true", transport.RequestBody);
    }

    [Fact]
    public async Task CreateFactoryActionAsync_OmitsNullSourceRegion()
    {
        var transport = new RecordingTransport(new DraftFactoryAction());
        var client = CreateClient(transport);

        await client.CreateFactoryActionAsync(@"C:\factory", "create", "swedencentral");

        AssertRequest(transport, HttpMethod.Post, "/api/v1/operations/factory-actions");
        Assert.Contains(@"""target_region"":""swedencentral""", transport.RequestBody);
        Assert.DoesNotContain("source_region", transport.RequestBody);
    }

    [Fact]
    public async Task CreateFactoryActionAsync_IncludesCloneSourceRegion()
    {
        var transport = new RecordingTransport(new DraftFactoryAction());
        var client = CreateClient(transport);

        await client.CreateFactoryActionAsync(
            @"C:\factory",
            "clone",
            "westeurope",
            "swedencentral");

        Assert.Contains(@"""action"":""clone""", transport.RequestBody);
        Assert.Contains(@"""source_region"":""swedencentral""", transport.RequestBody);
    }

    [Fact]
    public async Task CreateProjectActionAsync_UsesExpectedRouteAndPayload()
    {
        var transport = new RecordingTransport(new DraftProjectAction());
        var client = CreateClient(transport);

        await client.CreateProjectActionAsync(
            @"C:\factory",
            "123",
            "dev",
            "stage",
            "promote");

        AssertRequest(transport, HttpMethod.Post, "/api/v1/operations/project-actions");
        Assert.Contains(@"""project_number"":""123""", transport.RequestBody);
        Assert.Contains(@"""source_environment"":""dev""", transport.RequestBody);
        Assert.Contains(@"""target_environment"":""stage""", transport.RequestBody);
        Assert.Contains(@"""action"":""promote""", transport.RequestBody);
    }

    [Fact]
    public async Task SearchPromptsAsync_SerializesFiltersAndPaging()
    {
        var transport = new RecordingTransport(new OperationsPromptSearchResult());
        var client = CreateClient(transport);

        await client.SearchPromptsAsync(
            @"C:\factory",
            "001",
            "prod",
            "gpt-4o",
            "Coding",
            "refactor",
            false,
            25,
            50);

        AssertRequest(transport, HttpMethod.Post, "/api/v1/operations/prompts/search");
        Assert.Contains(@"""project_number"":""001""", transport.RequestBody);
        Assert.Contains(@"""environment"":""prod""", transport.RequestBody);
        Assert.Contains(@"""model"":""gpt-4o""", transport.RequestBody);
        Assert.Contains(@"""category"":""Coding""", transport.RequestBody);
        Assert.Contains(@"""search"":""refactor""", transport.RequestBody);
        Assert.Contains(@"""success"":false", transport.RequestBody);
        Assert.Contains(@"""limit"":25", transport.RequestBody);
        Assert.Contains(@"""offset"":50", transport.RequestBody);
    }

    [Fact]
    public async Task SearchPromptsAsync_OmitsNullOptionalFilters()
    {
        var transport = new RecordingTransport(new OperationsPromptSearchResult());
        var client = CreateClient(transport);

        await client.SearchPromptsAsync(@"C:\factory");

        Assert.DoesNotContain("project_number", transport.RequestBody);
        Assert.DoesNotContain(@"""environment""", transport.RequestBody);
        Assert.DoesNotContain(@"""model""", transport.RequestBody);
        Assert.DoesNotContain(@"""category""", transport.RequestBody);
        Assert.DoesNotContain(@"""search""", transport.RequestBody);
        Assert.DoesNotContain(@"""success""", transport.RequestBody);
        Assert.Contains(@"""limit"":100", transport.RequestBody);
        Assert.Contains(@"""offset"":0", transport.RequestBody);
    }

    [Fact]
    public async Task OperationsMethods_PropagateCancellationToken()
    {
        var transport = new RecordingTransport(new OperationsOverview());
        var client = CreateClient(transport);
        using var source = new CancellationTokenSource();

        await client.GetOperationsOverviewAsync(
            @"C:\factory",
            cancellationToken: source.Token);

        Assert.Equal(source.Token, transport.CancellationToken);
    }

    [Fact]
    public async Task OperationsMethods_ValidateInputsBeforeTransport()
    {
        var transport = new RecordingTransport(new OperationsOverview());
        var client = CreateClient(transport);

        await Assert.ThrowsAsync<ArgumentException>(
            () => client.GetOperationsOverviewAsync(" "));
        await Assert.ThrowsAsync<ArgumentException>(
            () => client.LoadOperationsConfigAsync(@"C:\factory", "1234567", "dev", "rag"));
        await Assert.ThrowsAsync<ArgumentOutOfRangeException>(
            () => client.LoadOperationsConfigAsync(@"C:\factory", "001", "qa", "rag"));
        await Assert.ThrowsAsync<ArgumentOutOfRangeException>(
            () => client.LoadOperationsConfigAsync(@"C:\factory", "001", "dev", "unknown"));
        await Assert.ThrowsAsync<ArgumentException>(
            () => client.CreateFactoryActionAsync(
                @"C:\factory",
                "clone",
                "swedencentral"));
        await Assert.ThrowsAsync<ArgumentOutOfRangeException>(
            () => client.CreateFactoryActionAsync(
                @"C:\factory",
                "destroy",
                "swedencentral"));
        await Assert.ThrowsAsync<ArgumentException>(
            () => client.CreateProjectActionAsync(
                @"C:\factory",
                "001",
                "dev",
                "dev",
                "deploy"));
        await Assert.ThrowsAsync<ArgumentOutOfRangeException>(
            () => client.CreateProjectActionAsync(
                @"C:\factory",
                "001",
                "dev",
                "stage",
                "destroy"));
        await Assert.ThrowsAsync<ArgumentNullException>(
            () => client.SaveOperationsConfigAsync(
                @"C:\factory",
                "001",
                "dev",
                "rag",
                null!));
        await Assert.ThrowsAsync<ArgumentOutOfRangeException>(
            () => client.SearchPromptsAsync(@"C:\factory", limit: 0));

        Assert.Null(transport.RequestUri);
    }

    private static void AssertRequest(
        RecordingTransport transport,
        HttpMethod method,
        string path)
    {
        Assert.Equal($"http://127.0.0.1:8765{path}", transport.RequestUri?.AbsoluteUri);
        Assert.Equal(method, transport.Method);
        Assert.Equal("secret", transport.ApiKey);
    }

    private static AiFactoryApiClient CreateClient(RecordingTransport transport)
    {
        return new AiFactoryApiClient(
            transport,
            new StaticConnectionProvider(
                new AiFactoryConnection("http://127.0.0.1:8765", "secret")));
    }

    private sealed class StaticConnectionProvider(AiFactoryConnection connection)
        : IAiFactoryConnectionProvider
    {
        public Task<AiFactoryConnection> GetConnectionAsync(
            CancellationToken cancellationToken = default)
        {
            return Task.FromResult(connection);
        }
    }

    private sealed class RecordingTransport(object response) : IJsonApiTransport
    {
        public Uri? RequestUri { get; private set; }

        public HttpMethod? Method { get; private set; }

        public string? ApiKey { get; private set; }

        public string RequestBody { get; private set; } = string.Empty;

        public CancellationToken CancellationToken { get; private set; }

        public async Task<TResponse> SendAsync<TResponse>(
            HttpRequestMessage request,
            CancellationToken cancellationToken = default)
        {
            RequestUri = request.RequestUri;
            Method = request.Method;
            ApiKey = request.Headers.TryGetValues("X-API-Key", out var values)
                ? values.Single()
                : null;
            RequestBody = request.Content is null
                ? string.Empty
                : await request.Content.ReadAsStringAsync(cancellationToken);
            CancellationToken = cancellationToken;
            return (TResponse)response;
        }
    }
}

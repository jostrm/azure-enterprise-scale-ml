using System.Text.Json;
using ESAIF.BaseLayer.Networking;
using ESAIF.DomainLayer.Configuration;

namespace ESAIF.DomainLayer.Tests;

public sealed class ProjectTerminalClientTests
{
    private static readonly AiFactoryConnection Connection = new("http://127.0.0.1:8765", "fixture-key");

    [Fact]
    public async Task Read_BindsConnectionFolderJobAndOpaqueCursor()
    {
        var transport = new Transport(new ProjectTerminalOutput { JobId = "job-1", NextCursor = 12, Output = "\x1b[31mPrompt> " });
        var client = new AiFactoryApiClient(transport, new Provider(Connection));
        var result = await client.ReadProjectTerminalAsync(Connection, @"C:\factory & one", "job-1", 10);
        Assert.Equal("\x1b[31mPrompt> ", result.Output);
        Assert.Contains("folder=C%3A%5Cfactory%20%26%20one&job_id=job-1&cursor=10", transport.Uri!.OriginalString);
        Assert.Equal("fixture-key", transport.Key);
        Assert.Equal(HttpMethod.Get, transport.Method);
    }

    [Theory]
    [InlineData("other-job", 12, false)]
    [InlineData("job-1", -1, true)]
    [InlineData("job-1", 5, false)]
    public async Task Read_RejectsMismatchedScopeOrInvalidCursor(string job, long cursor, bool reset)
    {
        var transport = new Transport(new ProjectTerminalOutput { JobId = job, NextCursor = cursor, Reset = reset });
        var client = new AiFactoryApiClient(transport, new Provider(Connection));
        await Assert.ThrowsAsync<InvalidDataException>(() => client.ReadProjectTerminalAsync(Connection, "factory", "job-1", 10));
    }

    [Fact]
    public async Task Read_AllowsExplicitCursorReset()
    {
        var transport = new Transport(new ProjectTerminalOutput { JobId = "job-1", NextCursor = 5, Reset = true });
        var client = new AiFactoryApiClient(transport, new Provider(Connection));
        Assert.True((await client.ReadProjectTerminalAsync(Connection, "factory", "job-1", 10)).Reset);
    }

    [Fact]
    public async Task ChangedConnection_RejectsBeforeSendingInput()
    {
        var transport = new Transport(JsonSerializer.SerializeToElement(new { }));
        var client = new AiFactoryApiClient(transport, new Provider(new("https://different.invalid", "different")));
        await Assert.ThrowsAsync<ProjectTerminalConnectionException>(() =>
            client.WriteProjectTerminalAsync(Connection, "factory", "job-1", "yes\r"));
        Assert.Equal(0, transport.Calls);
    }

    [Fact]
    public async Task Input_IsAnExactScopedPayload_NotAShellCommandEndpoint()
    {
        var transport = new Transport(JsonSerializer.SerializeToElement(new { }));
        var client = new AiFactoryApiClient(transport, new Provider(Connection));
        await client.WriteProjectTerminalAsync(Connection, "factory", "job-1", "\x03");
        using var body = JsonDocument.Parse(transport.Body!);
        Assert.EndsWith("/terminal/input", transport.Uri!.AbsolutePath);
        Assert.Equal("\x03", body.RootElement.GetProperty("data").GetString());
        Assert.Equal("job-1", body.RootElement.GetProperty("job_id").GetString());
        Assert.Equal("factory", body.RootElement.GetProperty("folder").GetString());
        Assert.Equal(1, transport.Calls);
    }

    [Fact]
    public async Task InputFailure_IsNotRetried()
    {
        var transport = new Transport(null) { Failure = new HttpRequestException("fixture failure") };
        var client = new AiFactoryApiClient(transport, new Provider(Connection));
        await Assert.ThrowsAsync<HttpRequestException>(() =>
            client.WriteProjectTerminalAsync(Connection, "factory", "job-1", "yes\r"));
        Assert.Equal(1, transport.Calls);
    }

    [Fact]
    public async Task Limits_RejectOversizedInputAndInvalidDimensions()
    {
        var transport = new Transport(JsonSerializer.SerializeToElement(new { }));
        var client = new AiFactoryApiClient(transport, new Provider(Connection));
        await Assert.ThrowsAsync<ArgumentOutOfRangeException>(() =>
            client.WriteProjectTerminalAsync(Connection, "factory", "job-1", new string('a', 8193)));
        await Assert.ThrowsAsync<ArgumentOutOfRangeException>(() =>
            client.ResizeProjectTerminalAsync(Connection, "factory", "job-1", 501, 10));
        await Assert.ThrowsAsync<ArgumentOutOfRangeException>(() =>
            client.ResizeProjectTerminalAsync(Connection, "factory", "job-1", 80, 4));
        Assert.Equal(0, transport.Calls);
    }

    private sealed class Provider(AiFactoryConnection connection) : IAiFactoryConnectionProvider
    {
        public Task<AiFactoryConnection> GetConnectionAsync(CancellationToken cancellationToken = default) => Task.FromResult(connection);
    }

    private sealed class Transport(object? response) : IJsonApiTransport
    {
        public Uri? Uri { get; private set; }
        public string? Body { get; private set; }
        public string? Key { get; private set; }
        public HttpMethod? Method { get; private set; }
        public int Calls { get; private set; }
        public Exception? Failure { get; init; }
        public async Task<T> SendAsync<T>(HttpRequestMessage request, CancellationToken cancellationToken = default)
        {
            Calls++;
            Uri = request.RequestUri;
            Method = request.Method;
            Key = request.Headers.GetValues("X-API-Key").Single();
            Body = request.Content is null ? null : await request.Content.ReadAsStringAsync(cancellationToken);
            if (Failure is not null) throw Failure;
            return (T)response!;
        }
    }
}

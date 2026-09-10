using ESAIF.BaseLayer.Networking;
using ESAIF.ConfigWizard.Services;

namespace ESAIF.ConfigWizard.Tests;

public sealed class ConnectionTrackingTransportTests
{
    [Fact]
    public async Task FailureSuccessFailure_TracksOnlyAuthenticatedSuccessAndClearsStaleErrors()
    {
        var state = new ApiConnectionState();
        var inner = new StubTransport();
        var transport = new ConnectionTrackingTransport(inner, state);
        using var request = new HttpRequestMessage(HttpMethod.Get, "http://localhost/api/v1/schema");
        request.Headers.Add("X-API-Key", "test-key");

        inner.Error = new HttpRequestException("Connection refused");
        await Assert.ThrowsAsync<HttpRequestException>(() => transport.SendAsync<string>(request));
        Assert.False(state.IsConnected);
        Assert.Equal("API disconnected", state.Label);
        Assert.Null(state.LastVerifiedAt);
        Assert.Equal("Connection refused", state.LastError);

        inner.Error = null;
        await transport.SendAsync<string>(request);
        Assert.True(state.IsConnected);
        Assert.NotNull(state.LastVerifiedAt);
        Assert.Empty(state.LastError);

        var verified = state.LastVerifiedAt;
        inner.Error = new HttpRequestException("Unauthorized", null, System.Net.HttpStatusCode.Unauthorized);
        await Assert.ThrowsAsync<HttpRequestException>(() => transport.SendAsync<string>(request));
        Assert.False(state.IsConnected);
        Assert.Equal(verified, state.LastVerifiedAt);
        Assert.Equal("Unauthorized", state.LastError);
    }

    [Fact]
    public async Task SuccessfulPublicHealth_DoesNotEstablishOrRestoreAuthenticatedConnection()
    {
        var state = new ApiConnectionState();
        var transport = new ConnectionTrackingTransport(new StubTransport(), state);
        using var request = new HttpRequestMessage(HttpMethod.Get, "http://localhost/health");
        await transport.SendAsync<string>(request);
        Assert.False(state.IsConnected);
        state.MarkFailed(new HttpRequestException("Invalid API key"));
        await transport.SendAsync<string>(request);
        Assert.False(state.IsConnected);
        Assert.Equal("Invalid API key", state.LastError);
    }

    [Fact]
    public async Task UserCancellation_DoesNotPretendAnObservedNetworkFailure()
    {
        var state = new ApiConnectionState();
        state.MarkVerified();
        var transport = new ConnectionTrackingTransport(
            new StubTransport { Error = new TaskCanceledException() }, state);
        using var request = new HttpRequestMessage(HttpMethod.Get, "http://localhost/api/v1/schema");
        using var cancellation = new CancellationTokenSource();
        cancellation.Cancel();
        await Assert.ThrowsAsync<TaskCanceledException>(() =>
            transport.SendAsync<string>(request, cancellation.Token));
        Assert.True(state.IsConnected);
    }

    [Theory]
    [InlineData(System.Net.HttpStatusCode.BadRequest)]
    [InlineData(System.Net.HttpStatusCode.NotFound)]
    [InlineData(System.Net.HttpStatusCode.Conflict)]
    [InlineData(System.Net.HttpStatusCode.UnprocessableEntity)]
    public async Task DomainValidationFailure_DoesNotMisreportDisconnection(System.Net.HttpStatusCode statusCode)
    {
        var state = new ApiConnectionState();
        state.MarkVerified();
        var transport = new ConnectionTrackingTransport(
            new StubTransport { Error = new HttpRequestException("Invalid operation", null, statusCode) }, state);
        using var request = new HttpRequestMessage(HttpMethod.Post, "http://localhost/api/v1/operations/config/save");
        request.Headers.Add("X-API-Key", "test-key");
        await Assert.ThrowsAsync<HttpRequestException>(() => transport.SendAsync<string>(request));
        Assert.True(state.IsConnected);
        Assert.Empty(state.LastError);
    }

    private sealed class StubTransport : IJsonApiTransport
    {
        public Exception? Error { get; set; }
        public Task<TResponse> SendAsync<TResponse>(HttpRequestMessage request, CancellationToken cancellationToken = default) =>
            Error is null ? Task.FromResult((TResponse)(object)"ok") : Task.FromException<TResponse>(Error);
    }
}

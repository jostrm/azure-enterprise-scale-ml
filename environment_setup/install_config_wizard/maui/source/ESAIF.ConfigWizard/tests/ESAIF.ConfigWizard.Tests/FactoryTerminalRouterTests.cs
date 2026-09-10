using ESAIF.ConfigWizard.Services;
using ESAIF.DomainLayer.Configuration;

namespace ESAIF.ConfigWizard.Tests;

public sealed class FactoryTerminalRouterTests
{
    [Fact]
    public async Task OnlyRegisteredKindRootJobAndConnectionCanRouteTerminalTraffic()
    {
        var client = new TerminalClient();
        var router = new FactoryTerminalRouter(client, client);
        var connection = client.Connection;
        await Assert.ThrowsAsync<ProjectTerminalConnectionException>(async () =>
            await router.ReadProjectTerminalAsync(connection, @"C:\catalog", "job", 0));
        router.Register(connection, @"C:\catalog", "job", FactoryTerminalJobKind.FactoryCatalog);
        await router.ReadProjectTerminalAsync(connection, @"C:\catalog", "job", 7);
        await router.WriteProjectTerminalAsync(connection, @"C:\catalog", "job", "yes\r");
        await router.ResizeProjectTerminalAsync(connection, @"C:\catalog", "job", 120, 40);
        Assert.Equal(new[] { "catalog:read:7", "catalog:write:yes\r", "catalog:resize:120:40" }, client.Calls);
        await Assert.ThrowsAsync<ProjectTerminalConnectionException>(async () =>
            await router.WriteProjectTerminalAsync(connection, @"C:\other", "job", "wrong"));
        await Assert.ThrowsAsync<ProjectTerminalConnectionException>(async () =>
            await router.WriteProjectTerminalAsync(connection, @"C:\catalog", "another-job", "wrong"));
        await Assert.ThrowsAsync<ProjectTerminalConnectionException>(async () =>
            await router.WriteProjectTerminalAsync(connection with { ApiKey = "changed" }, @"C:\catalog", "job", "wrong"));
        Assert.Equal(3, client.Calls.Count);
    }

    [Fact]
    public async Task ExistingProjectRouteUsesOnlyProjectEndpoints()
    {
        var client = new TerminalClient();
        var router = new FactoryTerminalRouter(client, client);
        router.Register(client.Connection, @"C:\legacy", "project-job", FactoryTerminalJobKind.ProjectDeployment);
        await router.ReadProjectTerminalAsync(client.Connection, @"C:\legacy", "project-job", 0);
        await router.WriteProjectTerminalAsync(client.Connection, @"C:\legacy", "project-job", "text");
        await router.ResizeProjectTerminalAsync(client.Connection, @"C:\legacy", "project-job", 80, 24);
        Assert.All(client.Calls, call => Assert.StartsWith("project:", call));
    }

    [Fact]
    public async Task SharedSessionSupportsCatalogInputResizeAndStopsReadingWhenHidden()
    {
        var client = new TerminalClient { Running = true };
        var router = new FactoryTerminalRouter(client, client);
        var session = new DeploymentTerminalSession(router, client);
        await session.OpenCatalogAsync(@"C:\catalog", new()
        {
            Id = "catalog-job", FactoryId = "factory-a", ScaleSetId = "scale-a",
            Action = "deploy", Status = "running", TerminalAvailable = true
        });
        Assert.True(session.HasJob);
        Assert.Null(session.Draft);
        Assert.Contains("Catalog:", session.Title);
        Assert.Contains("factory-a", session.Title);
        var owner = new object();
        var reading = session.AttachAsync(owner, (_, _) => Task.CompletedTask);
        await client.ReadStarted.Task.WaitAsync(TimeSpan.FromSeconds(3));
        Assert.True(session.CanType);
        await session.SendInputAsync("yes\r");
        await session.ResizeAsync(100, 30);
        session.Detach(owner);
        await reading.WaitAsync(TimeSpan.FromSeconds(3));
        Assert.False(session.CanType);
        Assert.Contains("catalog:write:yes\r", client.Calls);
        Assert.Contains("catalog:resize:100:30", client.Calls);
        Assert.All(client.Calls, call => Assert.StartsWith("catalog:", call));
    }

    [Fact]
    public async Task UncertainCatalogInputIsNeverAutomaticallyResent()
    {
        var client = new TerminalClient { Running = true, FailInput = true };
        var session = new DeploymentTerminalSession(new FactoryTerminalRouter(client, client), client);
        await session.OpenCatalogAsync(@"C:\catalog", new()
        {
            Id = "catalog-job", FactoryId = "factory-a", Status = "running", TerminalAvailable = true
        });
        var owner = new object();
        var reading = session.AttachAsync(owner, (_, _) => Task.CompletedTask);
        await client.ReadStarted.Task.WaitAsync(TimeSpan.FromSeconds(3));
        await session.SendInputAsync("yes\r");
        await session.SendInputAsync("yes\r");
        Assert.Single(client.Calls, call => call.StartsWith("catalog:write:", StringComparison.Ordinal));
        Assert.False(session.CanType);
        Assert.Contains("never automatically retried", session.Notice);
        await reading.WaitAsync(TimeSpan.FromSeconds(3));
    }

    [Fact]
    public async Task OpeningDifferentJobKindCannotReusePreviousInputScope()
    {
        var client = new TerminalClient();
        var session = new DeploymentTerminalSession(new FactoryTerminalRouter(client, client), client);
        await session.OpenAsync(@"C:\root", new() { JobId = "same-id", Status = "succeeded" });
        var projectInputScope = session.InputScope;
        await session.AttachAsync(new object(), (_, _) => Task.CompletedTask);
        await session.OpenCatalogAsync(@"C:\root", new()
        {
            Id = "same-id", FactoryId = "factory-a", Status = "succeeded", TerminalAvailable = true
        });
        Assert.NotEqual(projectInputScope, session.InputScope);
        await session.AttachAsync(new object(), (_, _) => Task.CompletedTask);
        Assert.Equal(new[] { "project:read:0", "catalog:read:0" }, client.Calls);
    }

    private sealed class TerminalClient : IProjectTerminalClient, IFactoryCatalogTerminalClient, IAiFactoryConnectionProvider
    {
        public AiFactoryConnection Connection { get; } = new("http://localhost:8765", "offline-test");
        public List<string> Calls { get; } = [];
        public bool Running { get; init; }
        public bool FailInput { get; init; }
        public TaskCompletionSource ReadStarted { get; } = new(TaskCreationOptions.RunContinuationsAsynchronously);
        public Task<AiFactoryConnection> GetConnectionAsync(CancellationToken cancellationToken = default) => Task.FromResult(Connection);
        public Task<ProjectTerminalOutput> ReadProjectTerminalAsync(AiFactoryConnection connection, string folder,
            string jobId, long cursor, CancellationToken cancellationToken = default) => Read("project", jobId, cursor);
        public Task<ProjectTerminalOutput> ReadFactoryCatalogTerminalAsync(AiFactoryConnection connection, string folder,
            string jobId, long cursor, CancellationToken cancellationToken = default) => Read("catalog", jobId, cursor);
        private Task<ProjectTerminalOutput> Read(string kind, string jobId, long cursor)
        {
            Calls.Add($"{kind}:read:{cursor}");
            ReadStarted.TrySetResult();
            return Task.FromResult(new ProjectTerminalOutput
                { JobId = jobId, NextCursor = cursor, Output = string.Empty, Status = Running ? "running" : "succeeded" });
        }
        public Task WriteProjectTerminalAsync(AiFactoryConnection connection, string folder, string jobId, string data,
            CancellationToken cancellationToken = default) => Write("project", data);
        public Task WriteFactoryCatalogTerminalAsync(AiFactoryConnection connection, string folder, string jobId, string data,
            CancellationToken cancellationToken = default) => Write("catalog", data);
        private Task Write(string kind, string data)
        {
            Calls.Add($"{kind}:write:{data}");
            return FailInput ? Task.FromException(new HttpRequestException("Transport failed")) : Task.CompletedTask;
        }
        public Task ResizeProjectTerminalAsync(AiFactoryConnection connection, string folder, string jobId, int columns,
            int rows, CancellationToken cancellationToken = default) => Resize("project", columns, rows);
        public Task ResizeFactoryCatalogTerminalAsync(AiFactoryConnection connection, string folder, string jobId, int columns,
            int rows, CancellationToken cancellationToken = default) => Resize("catalog", columns, rows);
        private Task Resize(string kind, int columns, int rows)
        {
            Calls.Add($"{kind}:resize:{columns}:{rows}");
            return Task.CompletedTask;
        }
    }
}

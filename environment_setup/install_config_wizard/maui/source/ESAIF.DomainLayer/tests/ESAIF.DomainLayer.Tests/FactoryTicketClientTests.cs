using System.Text.Json;
using System.Text.Json.Nodes;
using ESAIF.BaseLayer.Networking;
using ESAIF.DomainLayer.Configuration;

namespace ESAIF.DomainLayer.Tests;

public sealed class FactoryTicketClientTests
{
    [Fact]
    public async Task Analytics_PostsSecuredFolderAndReadsGenericSections()
    {
        var transport = new Transport("""
            {"title":"Current factory","source":"configuration","generated_at":"2026-09-09",
             "warning":"Deployment history unknown",
             "sections":[{"title":"Agents","description":"Configured evidence","source":"config",
             "columns":["Project","Agents"],"rows":[["017","Unknown"]]}]}
            """);
        var result = await CreateClient(transport).GetCurrentFactoryAnalyticsAsync(@"C:\factory");
        AssertEndpoint(transport, "/api/v1/analytics/current-factory");
        Assert.Equal(@"C:\factory", transport.Body!["aifactory_folder"]!.GetValue<string>());
        Assert.Equal("2026-09-09", result.GeneratedAt);
        Assert.Equal("Unknown", result.Sections.Single().Rows.Single()[1]);
        Assert.Equal("config", result.Sections.Single().Source);
    }

    [Fact]
    public async Task Tickets_ListUsesServerOwnerAndStatusCounts()
    {
        var transport = new Transport("""
            {"owner":"user@example.test","tickets":[{"id":"t1","title":"Service request","description":"details",
            "type":"Request Azure service","status":"New","owner":"user@example.test","project_number":"017",
            "aifactory_folder":"C:\\factory","requested_service":"AI Search","created_at":"created","updated_at":"updated",
            "external_url":null,"sync_state":"not_synced"}],"counts":{"new":1,"active":2,"solved":3}}
            """);
        var result = await CreateClient(transport).ListTicketsAsync(@"C:\factory");
        AssertEndpoint(transport, "/api/v1/tickets/list");
        Assert.Equal(1, result.Counts.New);
        Assert.Equal(2, result.Counts.Active);
        Assert.Equal(3, result.Counts.Solved);
        Assert.Equal("user@example.test", result.Owner);
        Assert.Equal("017", result.Tickets[0].ProjectNumber);
        Assert.Equal("AI Search", result.Tickets[0].RequestedService);
        Assert.Equal("not_synced", result.Tickets[0].SyncState);
    }

    [Fact]
    public async Task Tickets_CreateHasNoCallerControlledOwnerAndUpdateOnlySendsStatus()
    {
        var transport = new Transport("""{"id":"t1","owner":"server-owner","status":"New"}""");
        var client = CreateClient(transport);
        var result = await client.CreateTicketAsync(new CreateTicketRequest
        {
            AiFactoryFolder = @"C:\factory", ProjectNumber = "017", Type = "Blocker",
            Title = "Blocked deployment", Description = "Details", RequestedService = "AI Search"
        });
        AssertEndpoint(transport, "/api/v1/tickets/create");
        Assert.Equal("server-owner", result.Owner);
        Assert.False(transport.Body!.ContainsKey("owner"));
        Assert.Equal("017", transport.Body["project_number"]!.GetValue<string>());
        Assert.Equal("AI Search", transport.Body["requested_service"]!.GetValue<string>());
        await client.UpdateTicketAsync("t1", "Solved");
        AssertEndpoint(transport, "/api/v1/tickets/update");
        Assert.Equal(2, transport.Body!.Count);
        Assert.Equal("Solved", transport.Body["status"]!.GetValue<string>());
    }

    [Theory]
    [InlineData("Open")]
    [InlineData("Closed")]
    public async Task Tickets_RejectUnsupportedStatusBeforeSending(string status)
    {
        var transport = new Transport("{}");
        await Assert.ThrowsAsync<ArgumentException>(() => CreateClient(transport).UpdateTicketAsync("t1", status));
        Assert.Equal(0, transport.Calls);
    }

    [Fact]
    public async Task Connections_SaveSendsOnlyProfileAndCredentialEnvironmentReference()
    {
        var transport = new Transport("""{"id":"c1","name":"Jira","provider":"Jira","base_url":"https://example.test","credential_env":"JIRA_TOKEN"}""");
        var client = CreateClient(transport);
        var result = await client.SaveTicketConnectionAsync(new TicketConnection
        {
            Name = "Jira", BaseUrl = "https://example.test", CredentialEnv = "JIRA_TOKEN",
            ProjectKey = "OPS", Username = "user@example.test"
        });
        AssertEndpoint(transport, "/api/v1/tickets/connections/save");
        Assert.Equal("JIRA_TOKEN", result.CredentialEnv);
        Assert.Equal("JIRA_TOKEN", transport.Body!["credential_env"]!.GetValue<string>());
        Assert.False(transport.Body.ContainsKey("credential"));
        Assert.False(transport.Body.ContainsKey("password"));
        Assert.False(transport.Body.ContainsKey("token"));
        Assert.False(transport.Body.ContainsKey("id"));
        Assert.Equal(1, transport.Calls);
    }

    [Theory]
    [InlineData("http://example.test")]
    [InlineData("https://user:password@example.test")]
    [InlineData("https://example.test?token=secret")]
    public async Task Connections_RejectUnsecuredOrCredentialBearingUrls(string url)
    {
        var transport = new Transport("{}");
        await Assert.ThrowsAsync<ArgumentException>(() => CreateClient(transport).SaveTicketConnectionAsync(
            new TicketConnection { Name = "Profile", BaseUrl = url, CredentialEnv = "TOKEN" }));
        Assert.Equal(0, transport.Calls);
    }

    [Fact]
    public async Task Connections_ListIsSecuredAndDoesNotTestOrSync()
    {
        var transport = new Transport("""{"connections":[{"id":"c1","name":"Service desk","provider":"ServiceNow","base_url":"https://example.test","credential_env":"SN_TOKEN"}]}""");
        var result = await CreateClient(transport).ListTicketConnectionsAsync();
        AssertEndpoint(transport, "/api/v1/tickets/connections/list");
        Assert.Empty(transport.Body!);
        Assert.Equal("ServiceNow", result.Connections[0].Provider);
        Assert.Equal(1, transport.Calls);
    }

    [Fact]
    public async Task Sync_PreviewPreservesExactRecipientContentAndConfirmOnlySendsId()
    {
        var transport = new Transport("""
            {"confirmation_id":"confirm-1","recipient":"Jira https://example.test OPS",
            "content":"{\n  \"summary\": \"Private details\"\n}"}
            """);
        var client = CreateClient(transport);
        var preview = await client.PreviewTicketSyncAsync("t1", "c1");
        AssertEndpoint(transport, "/api/v1/tickets/sync/preview");
        Assert.Equal("t1", transport.Body!["ticket_id"]!.GetValue<string>());
        Assert.Equal("c1", transport.Body["connection_id"]!.GetValue<string>());
        Assert.Equal("{\n  \"summary\": \"Private details\"\n}", preview.Content);
        Assert.Equal(1, transport.Calls);
        transport.Response = """{"id":"t1","sync_state":"synced"}""";
        await client.ConfirmTicketSyncAsync(preview.ConfirmationId);
        AssertEndpoint(transport, "/api/v1/tickets/sync");
        Assert.Single(transport.Body!);
        Assert.Equal("confirm-1", transport.Body!["confirmation_id"]!.GetValue<string>());
    }

    [Fact]
    public async Task FeatureEndpoints_RejectMissingApiKeyWithoutTransportCall()
    {
        var transport = new Transport("{}");
        var client = new AiFactoryApiClient(transport, new Provider(""));
        await Assert.ThrowsAsync<InvalidOperationException>(() => client.GetCurrentFactoryAnalyticsAsync("folder"));
        await Assert.ThrowsAsync<InvalidOperationException>(() => client.ListTicketsAsync());
        await Assert.ThrowsAsync<InvalidOperationException>(() => client.ListTicketConnectionsAsync());
        await Assert.ThrowsAsync<InvalidOperationException>(() => client.ConfirmTicketSyncAsync("confirmation"));
        Assert.Equal(0, transport.Calls);
    }

    [Fact]
    public async Task Tickets_ParsesResourceGroupUsingAuthoritativeApiAndPreservesIdentityCharacters()
    {
        var transport = new Transport("""
            {"resource_group":"mrvel-1-project011-sdc-test-007","project_number":"011","environment":"stage",
             "region":"sdc","ai_factory_prefix":"mrvel-1-","ai_factory_suffix":"-007"}
            """);
        var result = await CreateClient(transport).ParseTicketResourceGroupAsync(" mrvel-1-project011-sdc-test-007 ");
        AssertEndpoint(transport, "/api/v1/tickets/resource-group/parse");
        Assert.Single(transport.Body!);
        Assert.Equal("mrvel-1-project011-sdc-test-007", transport.Body!["resource_group"]!.GetValue<string>());
        Assert.Equal("011", result.ProjectNumber);
        Assert.Equal("stage", result.Environment);
        Assert.Equal("sdc", result.Region);
        Assert.Equal("mrvel-1-", result.AiFactoryPrefix);
        Assert.Equal("-007", result.AiFactorySuffix);
    }

    [Fact]
    public async Task Tickets_ResourceGroupCreateNeedsNoFolderAndSendsSeverityNotDerivedIdentity()
    {
        var transport = new Transport("""
            {"id":"t1","resource_group":"mrvel-1-project011-sdc-dev-007","severity":"major",
             "project_number":"011","environment":"dev","region":"sdc","ai_factory_prefix":"mrvel-1-",
             "ai_factory_suffix":"-007","cost_center":"12345","department_name":"hr"}
            """);
        var result = await CreateClient(transport).CreateTicketAsync(new CreateTicketRequest
        {
            ResourceGroup = "mrvel-1-project011-sdc-dev-007", Severity = "major", Type = "Bug report",
            Title = "Title", Description = "Details", CostCenter = "12345", DepartmentName = "hr"
        });
        AssertEndpoint(transport, "/api/v1/tickets/create");
        Assert.Null(transport.Body!["aifactory_folder"]);
        Assert.Null(transport.Body["project_number"]);
        foreach (var field in new[] { "environment", "region", "ai_factory_prefix", "ai_factory_suffix", "owner" })
            Assert.False(transport.Body.ContainsKey(field));
        Assert.Equal("major", result.Severity);
        Assert.Equal("011", result.ProjectNumber);
        Assert.Equal("mrvel-1-", result.AiFactoryPrefix);
        Assert.Equal("-007", result.AiFactorySuffix);
        Assert.Equal("12345", result.CostCenter);
        Assert.Equal("hr", result.DepartmentName);
    }

    [Theory]
    [InlineData("minor")]
    [InlineData("major")]
    [InlineData("blocker")]
    public async Task Tickets_UpdateSendsSeveritySeparatelyFromStatus(string severity)
    {
        var transport = new Transport("{}");
        await CreateClient(transport).UpdateTicketAsync("t1", "Active", severity);
        Assert.Equal(3, transport.Body!.Count);
        Assert.Equal("Active", transport.Body["status"]!.GetValue<string>());
        Assert.Equal(severity, transport.Body["severity"]!.GetValue<string>());
    }

    [Fact]
    public async Task Tickets_UnsupportedSeverityRejectedBeforeSending()
    {
        var transport = new Transport("{}");
        var client = CreateClient(transport);
        await Assert.ThrowsAsync<ArgumentException>(() => client.UpdateTicketAsync("t1", "Active", "critical"));
        Assert.Equal(0, transport.Calls);
    }

    [Fact]
    public void Tickets_LegacyBlockerDefaultsSeverityWithoutOverridingExplicitValue()
    {
        Assert.Equal("blocker", new FactoryTicket { Type = "Blocker" }.Severity);
        Assert.Equal("minor", new FactoryTicket { Type = "Blocker", Severity = "minor" }.Severity);
    }

    [Fact]
    public async Task NetworkPlacement_SendsOnlyActualNetworkFieldsWithoutInjectingDefaults()
    {
        var transport = new Transport("""
            {"guidance":"Loaded ranges 61/62/63","is_peerable":false,"can_optimize":false,
             "optimization_changes":{"dev_cidr_range":"0","test_cidr_range":"0","prod_cidr_range":"0"},
             "optimization_description":"Draft only"}
            """);
        var result = await CreateClient(transport).PreviewNetworkPlacementAsync(new JsonObject
        {
            ["common_vnet_cidr"] = "172.16.0.0/16", ["dev_cidr_range"] = "61",
            ["test_cidr_range"] = "62", ["prod_cidr_range"] = "63", ["password"] = "not-sent"
        });
        AssertEndpoint(transport, "/api/v1/network/placement/preview");
        var input = transport.Body!["state"]!.AsObject();
        Assert.Equal(4, input.Count);
        Assert.False(input.ContainsKey("password"));
        Assert.Equal("62", input["test_cidr_range"]!.ToString());
        Assert.Equal("Loaded ranges 61/62/63", result.Guidance);
        Assert.False(result.IsPeerable);
        Assert.False(result.CanOptimize);
        Assert.Equal("0", result.OptimizationChanges["dev_cidr_range"]!.ToString());
    }

    private static AiFactoryApiClient CreateClient(Transport transport) => new(transport, new Provider("test-key"));
    private static void AssertEndpoint(Transport transport, string endpoint)
    {
        Assert.Equal("http://localhost:8765" + endpoint, transport.Uri!.AbsoluteUri);
        Assert.Equal(HttpMethod.Post, transport.Method);
        Assert.Equal("test-key", transport.ApiKey);
    }
    private sealed class Provider(string apiKey) : IAiFactoryConnectionProvider
    {
        public Task<AiFactoryConnection> GetConnectionAsync(CancellationToken cancellationToken = default) =>
            Task.FromResult(new AiFactoryConnection("http://localhost:8765", apiKey));
    }
    private sealed class Transport(string response) : IJsonApiTransport
    {
        public string Response { get; set; } = response;
        public int Calls { get; private set; }
        public Uri? Uri { get; private set; }
        public HttpMethod? Method { get; private set; }
        public string? ApiKey { get; private set; }
        public JsonObject? Body { get; private set; }
        public async Task<TResponse> SendAsync<TResponse>(HttpRequestMessage request, CancellationToken cancellationToken = default)
        {
            ++Calls;
            Uri = request.RequestUri;
            Method = request.Method;
            ApiKey = request.Headers.TryGetValues("X-API-Key", out var values) ? values.Single() : null;
            Body = JsonNode.Parse(await request.Content!.ReadAsStringAsync(cancellationToken))!.AsObject();
            return JsonSerializer.Deserialize<TResponse>(Response, new JsonSerializerOptions(JsonSerializerDefaults.Web))!;
        }
    }
}

using System.Net;
using System.Text.Json;
using System.Text.Json.Nodes;
using ESAIF.BaseLayer.Networking;
using ESAIF.DomainLayer.Configuration;

namespace ESAIF.DomainLayer.Tests;

public sealed class SimpleFactoryClientTests
{
    [Fact]
    public async Task Options_UsesAuthenticatedGetAndReadsDefaults()
    {
        var transport = new Transport("""
            {"defaults":{"subscription_id":"sub","tenant_id":"tenant","location":"swedencentral",
            "factory_prefix":"aif-","aifactory_version":"125","github_repository":"user/factory","team_member_email":"user@example.com",
            "team_group_name":"factory-team","cost_center":"123456","repo_root":"C:\\factories\\new"},
            "azure_accounts":[{"subscription_id":"sub","subscription_name":"Dev","tenant_id":"tenant","account_name":"user@example.com"}],
            "github_account":"user","regions":["swedencentral"],"requirements":["Owner access"],
            "warnings":["Costs apply"],"script_path":"fixed-purple.sh"}
            """);
        var options = await Client(transport).GetSimpleFactoryOptionsAsync();
        Assert.Equal(HttpMethod.Get, transport.Method);
        Assert.Equal("/api/v1/simple-mode/options", transport.Uri!.AbsolutePath);
        Assert.Equal("test-key", transport.ApiKey);
        Assert.Equal(string.Empty, transport.Body);
        Assert.Equal("123456", options.Defaults.CostCenter);
        Assert.Equal("125", options.Defaults.FactoryVersion);
        Assert.Equal("tenant", options.AzureAccounts.Single().TenantId);
        Assert.Equal("Dev · sub", options.AzureAccounts.Single().DisplayName);
        Assert.Equal("user", options.GithubAccount);
        Assert.Equal(@"C:\factories\new", options.Defaults.RepoRoot);
    }

    [Fact]
    public async Task Prepare_ContainsOnlyAllowedFieldsAndCannotInjectIdentityOrCredentials()
    {
        var transport = new Transport("""
            {"confirmation_id":"plan","can_execute":false,"summary":"Review","script_path":"fixed-purple.sh",
            "command":"bash fixed-purple.sh","environment":{"COST_CENTER":"123456"},"effects":["New private repository"],
            "requirements":["Permissions"],"warnings":["Costs"],"blockers":["Unpublished source"],"expires_at":"not-a-date"}
            """);
        var plan = await Client(transport).PrepareSimpleFactoryAsync(new()
        {
            SubscriptionId = "sub", TenantId = "tenant", GithubRepository = "user/new",
            TeamMemberEmail = "user@example.com", TeamGroupName = "new-team", RepoRoot = @"C:\new"
        });
        Assert.Equal(HttpMethod.Post, transport.Method);
        Assert.Equal("/api/v1/simple-mode/prepare", transport.Uri!.AbsolutePath);
        Assert.Equal("test-key", transport.ApiKey);
        var body = JsonNode.Parse(transport.Body)!.AsObject();
        Assert.Equal(new[] { "app_gateway_backend_fqdn", "app_gateway_certificate_secret_id", "app_gateway_hostname",
            "cost_center", "factory_prefix", "github_repository", "github_visibility", "location", "project_resources", "repo_root",
            "subscription_id", "team_group_name", "team_member_email", "tenant_id" }, body.Select(item => item.Key).Order());
        Assert.Equal("private", body["github_visibility"]!.GetValue<string>());
        Assert.Empty(body["project_resources"]!.AsArray());
        foreach (var key in new[] { "owner", "token", "password", "pat", "script_path", "command", "environment", "can_execute" })
            Assert.False(body.ContainsKey(key));
        Assert.True(typeof(SimpleFactoryDraft).IsSealed);
        Assert.False(plan.CanExecute);
        Assert.Equal("Unpublished source", plan.Blockers.Single());
        Assert.Equal("123456", plan.Environment["COST_CENTER"]);
        Assert.Equal("not-a-date", plan.ExpiresAt);
        Assert.Equal(1, transport.Calls);
    }

    [Fact]
    public async Task PrepareSupportsVisibilityOptionalResourceIdsAndGatewayReferencesWithoutCredentialFields()
    {
        var transport = new Transport("{}");
        await Client(transport).PrepareSimpleFactoryAsync(new()
        {
            GithubVisibility = "public", ProjectResources = ["foundry", "ai-search"],
            AppGatewayHostname = "app.example.com", AppGatewayBackendFqdn = "backend.example.com",
            AppGatewayCertificateSecretId = "https://factory.vault.azure.net/secrets/certificate"
        });
        var body = JsonNode.Parse(transport.Body)!.AsObject();
        Assert.Equal(14, body.Count);
        Assert.Equal("public", body["github_visibility"]!.GetValue<string>());
        Assert.Equal(new[] { "foundry", "ai-search" }, body["project_resources"]!.AsArray().Select(value => value!.GetValue<string>()));
        Assert.Equal("app.example.com", body["app_gateway_hostname"]!.GetValue<string>());
        Assert.Equal("backend.example.com", body["app_gateway_backend_fqdn"]!.GetValue<string>());
        Assert.Equal("https://factory.vault.azure.net/secrets/certificate", body["app_gateway_certificate_secret_id"]!.GetValue<string>());
        Assert.DoesNotContain(body, entry => entry.Key is "password" or "token" or "certificate_value" or "private_key");
    }

    [Fact]
    public async Task CatalogIsTypedForBothOptionsAndPlanWithoutInventingMissingMetadata()
    {
        const string response = """
            {"resource_catalog":{"hub":[{"id":"application-gateway","label":"HTTPS Application Gateway","description":"Backend-defined gateway",
            "required":true,"default_selected":true,"dependencies":[]}],"common":[],
            "project":[{"id":"foundry","label":"Foundry","description":"Account and project","required":false,
            "default_selected":true,"dependencies":["storage"]}]}}
            """;
        var options = await Client(new Transport(response)).GetSimpleFactoryOptionsAsync();
        var plan = await Client(new Transport(response)).PrepareSimpleFactoryAsync(new());
        Assert.True(options.ResourceCatalog!.Hub.Single().Required);
        Assert.Equal("HTTPS Application Gateway", plan.ResourceCatalog!.Hub.Single().Label);
        Assert.True(plan.ResourceCatalog.Project.Single().DefaultSelected);
        Assert.Equal("storage", plan.ResourceCatalog.Project.Single().Dependencies.Single());
        Assert.Null((await Client(new Transport("{}")).GetSimpleFactoryOptionsAsync()).ResourceCatalog);
    }

    [Fact]
    public async Task ExplicitVersionRequiresAcknowledgementButOmittedVersionKeepsLegacyCompatibility()
    {
        var legacy = new Transport("""{"can_execute":true,"confirmation_id":"old"}""");
        await Client(legacy).PrepareSimpleFactoryAsync(new());
        Assert.False(JsonNode.Parse(legacy.Body)!.AsObject().ContainsKey("aifactory_version"));
        await Assert.ThrowsAsync<InvalidOperationException>(() =>
            Client(legacy).PrepareSimpleFactoryAsync(new() { FactoryVersion = "125" }));
        Assert.Equal("125", JsonNode.Parse(legacy.Body)!["aifactory_version"]!.GetValue<string>());
        Assert.Equal(2, legacy.Calls);
        Assert.EndsWith("/prepare", legacy.Uri!.AbsolutePath);
    }

    [Theory]
    [InlineData("124", "124", "release/v1.24")]
    [InlineData("1.25", "125", "release/v1.25")]
    [InlineData("12.345", "12.345", "release/v12.345")]
    [InlineData("main", "main", "main")]
    public async Task ExplicitVersionUsesBackendResolutionWithoutClientParser(string requested, string version, string branch)
    {
        var transport = new Transport(JsonSerializer.Serialize(new
        {
            can_execute = true, confirmation_id = "review",
            aifactory_version = requested, requested_version = version, branch, resolved_ref = new string('a', 40)
        }));
        var plan = await Client(transport).PrepareSimpleFactoryAsync(new() { FactoryVersion = requested });
        Assert.Equal(requested, JsonNode.Parse(transport.Body)!["aifactory_version"]!.GetValue<string>());
        Assert.Equal(version, plan.RequestedVersion);
        Assert.Equal(branch, plan.Branch);
        Assert.Equal(new string('a', 40), plan.ResolvedRef);
        Assert.Equal(1, transport.Calls);
    }

    [Theory]
    [InlineData("missing")]
    [InlineData("wrong-request")]
    [InlineData("missing-version")]
    [InlineData("missing-branch")]
    [InlineData("missing-ref")]
    [InlineData("invalid-ref")]
    public async Task IgnoredOrIncompleteExplicitVersionFailsClosedWithoutRetry(string mismatch)
    {
        var response = JsonNode.Parse("""
            {"can_execute":true,"confirmation_id":"review",
             "aifactory_version":"125","requested_version":"125","branch":"release/v1.25","resolved_ref":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"}
            """)!;
        var selection = response.AsObject();
        switch (mismatch)
        {
            case "missing": selection.Remove("aifactory_version"); break;
            case "wrong-request": selection["aifactory_version"] = "124"; break;
            case "missing-version": selection.Remove("requested_version"); break;
            case "missing-branch": selection.Remove("branch"); break;
            case "missing-ref": selection.Remove("resolved_ref"); break;
            case "invalid-ref": selection["resolved_ref"] = "main"; break;
        }
        var transport = new Transport(response.ToJsonString());
        var error = await Assert.ThrowsAsync<InvalidOperationException>(() =>
            Client(transport).PrepareSimpleFactoryAsync(new() { FactoryVersion = "125" }));
        Assert.Contains("selected factory version", error.Message);
        Assert.Equal(1, transport.Calls);
    }

    [Fact]
    public async Task BlockedExplicitVersionPreservesUnpublishedSourceBlockersWithoutRequiringARef()
    {
        var transport = new Transport("""
            {"can_execute":false,"aifactory_version":"125","requested_version":"125","branch":"release/v1.25",
             "resolved_ref":"","blockers":["Publish or fetch the selected release with required capabilities."]}
            """);
        var plan = await Client(transport).PrepareSimpleFactoryAsync(new() { FactoryVersion = "125" });
        Assert.False(plan.CanExecute);
        Assert.Contains("Publish or fetch", Assert.Single(plan.Blockers));
        Assert.Empty(plan.ResolvedRef);
    }

    [Fact]
    public async Task Start_IsSeparatePostWithOnlyServerConfirmationId()
    {
        var transport = new Transport("""{"id":"job","status":"queued","exit_code":null}""");
        var job = await Client(transport).StartSimpleFactoryAsync("owner-bound-plan");
        Assert.Equal(HttpMethod.Post, transport.Method);
        Assert.Equal("/api/v1/simple-mode/start", transport.Uri!.AbsolutePath);
        Assert.Equal("test-key", transport.ApiKey);
        Assert.Equal("""{"confirmation_id":"owner-bound-plan"}""", transport.Body);
        Assert.Equal("job", job.Id);
        Assert.Null(job.ExitCode);
        Assert.False(job.IsTerminal);
        Assert.Equal(1, transport.Calls);
    }

    [Theory]
    [InlineData("queued", false)]
    [InlineData("running", false)]
    [InlineData("succeeded", true)]
    [InlineData("failed", true)]
    [InlineData("interrupted", true)]
    [InlineData("future-status", false)]
    public async Task Jobs_EscapeIdsAndPreserveServerStatusAndFailureDetails(string status, bool terminal)
    {
        var transport = new Transport($$"""
            {"id":"job/a?b#c","status":"{{status}}","stage":"deploy","message":"detail","exit_code":17,
            "repository_url":"https://github.com/user/new","repo_root":"C:\\new",
            "created_at":"2026-09-09T12:00:00Z","updated_at":"2026-09-09T12:01:00Z","events":["one","two"]}
            """);
        var job = await Client(transport).GetSimpleFactoryJobAsync("job/a?b#c");
        Assert.Equal(HttpMethod.Get, transport.Method);
        Assert.EndsWith("/api/v1/simple-mode/jobs/job%2Fa%3Fb%23c", transport.Uri!.AbsoluteUri);
        Assert.Equal("test-key", transport.ApiKey);
        Assert.Empty(transport.Body);
        Assert.Equal(status, job.Status);
        Assert.Equal(terminal, job.IsTerminal);
        Assert.Equal(17, job.ExitCode);
        Assert.Equal("deploy", job.Stage);
        Assert.Equal(2, job.Events.Count);
        Assert.Equal("https://github.com/user/new", job.RepositoryUrl);
    }

    [Fact]
    public async Task OwnerDenialIsPropagatedWithoutRetryOrReplacementPlan()
    {
        var transport = new Transport("{}") { Error = new ApiRequestException(HttpStatusCode.Forbidden, "Wrong owner", "{}") };
        var error = await Assert.ThrowsAsync<ApiRequestException>(() => Client(transport).StartSimpleFactoryAsync("plan"));
        Assert.Equal(HttpStatusCode.Forbidden, error.StatusCode);
        Assert.Equal(1, transport.Calls);
    }

    [Fact]
    public async Task CancellationIsForwardedAndMissingApiKeyNeverUsesTransport()
    {
        var transport = new Transport("{}");
        using var cancellation = new CancellationTokenSource();
        await Client(transport).GetSimpleFactoryOptionsAsync(cancellation.Token);
        Assert.Equal(cancellation.Token, transport.Token);
        await Assert.ThrowsAsync<InvalidOperationException>(() =>
            new AiFactoryApiClient(transport, new Connection("")).GetSimpleFactoryOptionsAsync());
        Assert.Equal(1, transport.Calls);
    }

    [Theory]
    [InlineData("")]
    [InlineData(" ")]
    [InlineData(".")]
    [InlineData("..")]
    public async Task InvalidJobIdsNeverReachTransport(string id)
    {
        var transport = new Transport("{}");
        await Assert.ThrowsAnyAsync<ArgumentException>(() => Client(transport).GetSimpleFactoryJobAsync(id));
        Assert.Equal(0, transport.Calls);
    }

    private static AiFactoryApiClient Client(Transport transport) => new(transport, new Connection("test-key"));
    private sealed class Connection(string key) : IAiFactoryConnectionProvider
    {
        public Task<AiFactoryConnection> GetConnectionAsync(CancellationToken cancellationToken = default) =>
            Task.FromResult(new AiFactoryConnection("http://127.0.0.1:8765", key));
    }
    private sealed class Transport(string response) : IJsonApiTransport
    {
        public HttpMethod? Method { get; private set; }
        public Uri? Uri { get; private set; }
        public string? ApiKey { get; private set; }
        public string Body { get; private set; } = string.Empty;
        public int Calls { get; private set; }
        public CancellationToken Token { get; private set; }
        public Exception? Error { get; init; }
        public async Task<TResponse> SendAsync<TResponse>(HttpRequestMessage request, CancellationToken cancellationToken = default)
        {
            Calls++;
            Method = request.Method;
            Uri = request.RequestUri;
            ApiKey = request.Headers.TryGetValues("X-API-Key", out var values) ? values.Single() : null;
            Body = request.Content is null ? string.Empty : await request.Content.ReadAsStringAsync(cancellationToken);
            Token = cancellationToken;
            if (Error is not null) throw Error;
            return JsonSerializer.Deserialize<TResponse>(response, new JsonSerializerOptions(JsonSerializerDefaults.Web))!;
        }
    }
}

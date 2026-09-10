using System.Text.Json;
using System.Text.Json.Nodes;
using ESAIF.BaseLayer.Networking;
using ESAIF.DomainLayer.Configuration;

namespace ESAIF.DomainLayer.Tests;

public sealed class FactoryCatalogClientTests
{
    private const string CatalogJson = """
        {"contract_version":1,"mode":"catalog","revision":"revision-1","requires_selection":true,
        "factories":[{"id":"factory-1","key":"mrvel-1-sdc","prefix":"mrvel-1-","region":"swedencentral",
        "default_orchestrator":"ado","status":"draft","scale_sets":[
        {"id":"dev-1","environment":"dev","suffix":"001","subscription_id":"dev-sub","tenant_id":"tenant",
        "orchestrator":"ado","network":{"vnet_cidr":"10.1.0.0/18","max_projects":8},"status":"draft"},
        {"id":"stage-1","environment":"stage","suffix":"001","subscription_id":"stage-sub","tenant_id":"tenant",
        "orchestrator":"gha","network":{"vnet_cidr":"10.2.0.0/18","max_projects":4},"status":"draft"}],
        "projects":[{"id":"p-17","key":"project-017","number":"017","display_name":"Project 017","status":"draft",
        "placements":[{"environment":"dev","scale_set_id":"dev-1"},{"environment":"stage","scale_set_id":"stage-1"}]}]}]}
        """;
    private const string PreviewJson = """
        {"contract_version":1,"confirmation_id":"review","can_execute":true,"source_revision":"revision-1",
        "operation_mode":"configuration","summary":"Clone as dc- in northeurope","effects":["Save an independent draft"],
        "warnings":[],"blockers":[],"expires_at":"2099-01-01T00:00:00Z","target":null,"inventory":[]}
        """;
    private const string JobJson = """
        {"id":"job-1","action":"delete-scale-set","status":"failed","message":"Review retained partial outcome",
        "factory_id":"factory-1","scale_set_id":"dev-1","exit_code":1,"terminal_available":true}
        """;

    [Fact]
    public async Task RootDiscoveryKeepsSeparateEnvironmentSubscriptionsAndRoutes()
    {
        var transport = new Transport(CatalogJson);
        var catalog = await Client(transport).GetFactoryCatalogAsync(@"C:\customer & demo\aifactory");
        Assert.Equal(HttpMethod.Get, transport.Method);
        Assert.Equal("/api/v1/factory-catalog", transport.Uri!.AbsolutePath);
        Assert.Equal("?folder=C%3A%5Ccustomer%20%26%20demo%5Caifactory", transport.Uri.Query);
        Assert.Equal("test-key", transport.Key);
        Assert.True(catalog.RequiresSelection);
        Assert.Equal("revision-1", catalog.Revision);
        var factory = Assert.Single(catalog.Factories);
        Assert.Equal(["dev-sub", "stage-sub"], factory.ScaleSets.Select(scale => scale.SubscriptionId));
        Assert.Equal(["ado", "gha"], factory.ScaleSets.Select(scale => scale.Orchestrator));
        Assert.Equal(["dev-1", "stage-1"], Assert.Single(factory.Projects).Placements.Select(placement => placement.ScaleSetId));
    }

    [Theory]
    [InlineData("none")]
    [InlineData("all")]
    public async Task CloneCarriesExactSourceAndCopyChoiceWithoutResourceAuthority(string includeProjects)
    {
        var transport = new Transport(PreviewJson);
        var preview = await Client(transport).PrepareFactoryCatalogAsync(new()
        {
            Folder = @"C:\factory\aifactory", Action = "clone", FactoryId = "factory-1",
            TargetPrefix = "dc-", TargetRegion = "northeurope", IncludeProjects = includeProjects, VersionRef = "125"
        });
        Assert.Equal(HttpMethod.Post, transport.Method);
        Assert.EndsWith("/factory-catalog/prepare", transport.Uri!.AbsolutePath);
        var body = JsonNode.Parse(transport.Body)!.AsObject();
        Assert.Equal("factory-1", body["factory_id"]!.GetValue<string>());
        Assert.Equal("dc-", body["target_prefix"]!.GetValue<string>());
        Assert.Equal("northeurope", body["target_region"]!.GetValue<string>());
        Assert.Equal(includeProjects, body["include_projects"]!.GetValue<string>());
        Assert.Equal("125", body["version_ref"]!.GetValue<string>());
        Assert.False(body.ContainsKey("resource_allowlist"));
        Assert.False(body.ContainsKey("destination_folder"));
        Assert.False(body.ContainsKey("project_id"));
        Assert.True(preview.CanExecute);
        Assert.Equal(1, transport.Calls);
    }

    [Fact]
    public async Task ScaleSetCreationDoesNotInventOtherEnvironments()
    {
        var transport = new Transport(PreviewJson);
        await Client(transport).PrepareFactoryCatalogAsync(new()
        {
            Folder = "folder", Action = "create-scale-set", FactoryId = "factory-1",
            ScaleSets = [new()
            {
                Environment = "dev", Suffix = "003", SubscriptionId = "new-dev-sub", TenantId = "tenant",
                Orchestrator = "gha", Network = new() { VnetCidr = "10.3.0.0/18", MaxProjects = 8 }
            }]
        });
        var scale = Assert.Single(JsonNode.Parse(transport.Body)!["scale_sets"]!.AsArray())!;
        Assert.Equal("dev", scale["environment"]!.GetValue<string>());
        Assert.Equal("003", scale["suffix"]!.GetValue<string>());
        Assert.Equal("new-dev-sub", scale["subscription_id"]!.GetValue<string>());
        Assert.Equal(8, scale["network"]!["max_projects"]!.GetValue<int>());
    }

    [Theory]
    [InlineData("delete-scale-set", null, null)]
    [InlineData("delete-scale-set", "factory-1", null)]
    [InlineData("delete-factory", null, null)]
    [InlineData("arbitrary-shell", "factory-1", "dev-1")]
    public async Task MissingExactDeletionScopeOrUnknownActionNeverReachesApi(string action, string? factoryId, string? scaleSetId)
    {
        var transport = new Transport(PreviewJson);
        await Assert.ThrowsAnyAsync<ArgumentException>(() => Client(transport).PrepareFactoryCatalogAsync(new()
        {
            Folder = "folder", Action = action, FactoryId = factoryId, ScaleSetId = scaleSetId
        }));
        Assert.Equal(0, transport.Calls);
    }

    [Fact]
    public async Task ConfirmationOnlySendsConsentReceiptNotMutableSettings()
    {
        var transport = new Transport($"{{\"contract_version\":1,\"catalog\":{CatalogJson},\"job\":null}}");
        var result = await Client(transport).ConfirmFactoryCatalogAsync("folder", "review");
        Assert.NotNull(result.Catalog);
        Assert.Null(result.Job);
        Assert.Equal("""{"folder":"folder","contract_version":1,"confirmation_id":"review"}""", transport.Body);
        Assert.EndsWith("/factory-catalog/confirm", transport.Uri!.AbsolutePath);
    }

    [Fact]
    public async Task RuntimeConfirmationRetainsFailureEvidenceAndDoesNotRetry()
    {
        var transport = new Transport($"{{\"contract_version\":1,\"catalog\":null,\"job\":{JobJson}}}");
        var result = await Client(transport).ConfirmFactoryCatalogAsync("folder", "review");
        Assert.Equal("failed", result.Job!.Status);
        Assert.False(result.Job.IsRunning);
        Assert.True(result.Job.TerminalAvailable);
        Assert.Equal(1, result.Job.ExitCode);
        Assert.Equal(1, transport.Calls);
    }

    [Theory]
    [InlineData("{}")]
    [InlineData("""{"contract_version":2,"mode":"catalog","revision":"r"}""")]
    [InlineData("""{"contract_version":1,"mode":"catalog"}""")]
    [InlineData("""{"contract_version":1,"mode":"legacy","revision":"r","factories":[{"id":""}]}""")]
    [InlineData("""{"contract_version":1,"mode":"catalog","revision":"r","factories":[{"id":"same"},{"id":"same"}]}""")]
    public async Task MissingContractOrAmbiguousIdentityNeverFallsBackToLegacy(string response)
    {
        var transport = new Transport(response);
        await Assert.ThrowsAsync<InvalidDataException>(() => Client(transport).GetFactoryCatalogAsync("folder"));
        Assert.Equal(1, transport.Calls);
    }

    [Fact]
    public async Task LegacyDiscoveryIsReadOnlyAndExplicit()
    {
        var transport = new Transport("""{"contract_version":1,"mode":"legacy","revision":"legacy-revision","factories":[]}""");
        var result = await Client(transport).GetFactoryCatalogAsync("folder");
        Assert.Equal("legacy", result.Mode);
        Assert.Equal(HttpMethod.Get, transport.Method);
        Assert.Equal(1, transport.Calls);
    }

    [Fact]
    public async Task LostConfirmationResponseIsSurfacedWithoutAutomaticResubmission()
    {
        var transport = new Transport("{}") { Error = new HttpRequestException("Response lost") };
        await Assert.ThrowsAsync<HttpRequestException>(() => Client(transport).ConfirmFactoryCatalogAsync("folder", "review"));
        Assert.Equal(1, transport.Calls);
    }

    [Fact]
    public async Task IncompleteConfirmationMakesUncertainOutcomeExplicit()
    {
        var transport = new Transport("""{"contract_version":1}""");
        var error = await Assert.ThrowsAsync<InvalidDataException>(() => Client(transport).ConfirmFactoryCatalogAsync("folder", "review"));
        Assert.Contains("do not submit again", error.Message);
        Assert.Equal(1, transport.Calls);
    }

    [Fact]
    public async Task JobReadsKeepOwnerBoundFolderAndExactJobId()
    {
        var transport = new Transport(JobJson);
        var job = await Client(transport).GetFactoryCatalogJobAsync(@"C:\factory & one", "job-1");
        Assert.Equal("job-1", job.Id);
        Assert.Equal("/api/v1/factory-catalog/jobs/job-1", transport.Uri!.AbsolutePath);
        Assert.Equal("?folder=C%3A%5Cfactory%20%26%20one", transport.Uri.Query);
        transport.Response = JobJson.Replace("job-1", "another-job");
        await Assert.ThrowsAsync<InvalidDataException>(() => Client(transport).GetFactoryCatalogJobAsync("folder", "job-1"));
    }

    [Fact]
    public async Task ExecutableRuntimePreviewRequiresPinnedSourceButBlockedPreviewRetainsItsReasons()
    {
        var response = JsonNode.Parse(PreviewJson)!.AsObject();
        response["operation_mode"] = "runtime";
        var transport = new Transport(response.ToJsonString());
        var request = new FactoryCatalogRequest { Folder = "folder", Action = "deploy", FactoryId = "f", ScaleSetId = "s" };
        await Assert.ThrowsAsync<InvalidDataException>(() => Client(transport).PrepareFactoryCatalogAsync(request));
        response["can_execute"] = false;
        response["blockers"] = new JsonArray("Selected release is not published");
        transport.Response = response.ToJsonString();
        var blocked = await Client(transport).PrepareFactoryCatalogAsync(request);
        Assert.Contains("Selected release is not published", blocked.Blockers);
        response["can_execute"] = true;
        response["blockers"] = new JsonArray();
        response["source_version"] = new JsonObject
        {
            ["requested_version"] = "125", ["branch"] = "release/v1.25", ["resolved_ref"] = new string('a', 40)
        };
        transport.Response = response.ToJsonString();
        Assert.Equal(new string('a', 40), (await Client(transport).PrepareFactoryCatalogAsync(request)).SourceVersion!.ResolvedRef);
        var explicitRequest = request with { VersionRef = "1.25" };
        await Assert.ThrowsAsync<InvalidDataException>(() => Client(transport).PrepareFactoryCatalogAsync(explicitRequest));
        response["source_version"]!["aifactory_version"] = "1.25";
        transport.Response = response.ToJsonString();
        var explicitPreview = await Client(transport).PrepareFactoryCatalogAsync(explicitRequest);
        Assert.Equal("1.25", explicitPreview.SourceVersion!.FactoryVersion);
        Assert.Equal("125", explicitPreview.SourceVersion.RequestedVersion);
    }

    [Fact]
    public async Task NewFactoryUsesExpectedRevisionAndExplicitInitialScaleSet()
    {
        var transport = new Transport(PreviewJson);
        await Client(transport).PrepareFactoryCatalogAsync(new()
        {
            Folder = "folder", Action = "create-factory", SourceRevision = new string('b', 64),
            TargetPrefix = "dc-", TargetRegion = "northeurope", FactoryVersion = "125", ScaleSets = [new()
            {
                Environment = "dev", Suffix = "001", SubscriptionId = "sub", TenantId = "tenant",
                Orchestrator = "gha", Network = new() { VnetCidr = "10.1.0.0/20", MaxProjects = 1 }
            }]
        });
        var body = JsonNode.Parse(transport.Body)!.AsObject();
        Assert.Equal(new string('b', 64), body["expected_revision"]!.GetValue<string>());
        Assert.False(body.ContainsKey("source_revision"));
        Assert.False(body.ContainsKey("factory_id"));
        Assert.Single(body["scale_sets"]!.AsArray());
        Assert.Equal("125", body["aifactory_version"]!.GetValue<string>());
        Assert.False(body.ContainsKey("version_ref"));
    }

    [Fact]
    public async Task BindingSetupIsTypedAndCannotSmuggleCredentialsOrACommand()
    {
        var transport = new Transport(PreviewJson);
        await Client(transport).PrepareFactoryCatalogAsync(new()
        {
            Folder = "folder", Action = "configure-binding", FactoryId = "f",
            Binding = new()
            {
                Orchestrator = "gha", WriterId = "writer", Repository = "https://github.com/customer/factory",
                AuthNamespace = "factory-dev", DeploymentObjectId = "principal",
                Locks = new()
                {
                    AccountUrl = "https://factorylocks.blob.core.windows.net", Container = "locks",
                    CoordinationBlob = "enrollment.json", CoordinationHash = new string('c', 64), Revision = 1
                },
                Targets = [new() { ScaleSetId = "dev-1", ResourceGroupIds = ["/subscriptions/sub/resourceGroups/owned"] }]
            }
        });
        var body = JsonNode.Parse(transport.Body)!.AsObject();
        var binding = body["binding"]!.AsObject();
        Assert.Equal("factory-dev", binding["auth_namespace"]!.GetValue<string>());
        Assert.Equal("refs/heads/main", binding["ref"]!.GetValue<string>());
        Assert.Equal(["auth_namespace", "contract_version", "deployment_object_id", "locks", "orchestrator", "ref", "repository",
            "shared_remote", "targets", "writer_id"], binding.Select(item => item.Key).Order());
        Assert.False(body.ContainsKey("command"));
    }

    [Theory]
    [InlineData("gha", "hosted")]
    [InlineData("ado", "hosted")]
    [InlineData("gha", "self-hosted")]
    [InlineData("ado", "self-hosted")]
    public async Task RunnerBindingSendsOnlyItsProviderSpecificFields(string route, string kind)
    {
        var runner = kind == "hosted" ? new CatalogRunnerSelection { Kind = kind, Image = "ubuntu-24.04" }
            : route == "gha" ? new CatalogRunnerSelection { Kind = kind, Labels = ["self-hosted", "linux", "factory"] }
            : new CatalogRunnerSelection { Kind = kind, Pool = "factory-pool", AgentName = "agent-1" };
        var transport = new Transport(PreviewJson);
        var request = RunnerRequest(route, runner);
        await Client(transport).PrepareFactoryCatalogAsync(request);
        var sent = JsonNode.Parse(transport.Body)!["binding"]!["runner"]!.AsObject();
        Assert.Equal(kind, sent["kind"]!.GetValue<string>());
        Assert.Equal("linux", sent["os"]!.GetValue<string>());
        Assert.Equal(kind == "hosted", sent.ContainsKey("image"));
        Assert.Equal(kind == "self-hosted" && route == "gha", sent.ContainsKey("labels"));
        Assert.Equal(kind == "self-hosted" && route == "ado", sent.ContainsKey("pool"));
        var wrong = request with { Binding = request.Binding! with { Runner = runner with { Os = "windows" } } };
        await Assert.ThrowsAnyAsync<ArgumentException>(() => Client(transport).PrepareFactoryCatalogAsync(wrong));
        Assert.Equal(1, transport.Calls);
    }

    private static FactoryCatalogRequest RunnerRequest(string route, CatalogRunnerSelection runner) => new()
    {
        Folder = "folder", Action = "configure-binding", FactoryId = "f", Binding = new()
        {
            Orchestrator = route, WriterId = "writer", Repository = "https://example.test",
            AuthNamespace = "namespace", DeploymentObjectId = "principal", Runner = runner,
            Locks = new() { AccountUrl = "https://locks.blob.core.windows.net", CoordinationHash = new string('c', 64) },
            Targets = [new() { ScaleSetId = "s", ResourceGroupIds = ["resource-id"] }]
        }
    };

    [Fact]
    public async Task NewProjectCarriesExplicitPlacementsWithoutInventingMatchingScaleSets()
    {
        var transport = new Transport(PreviewJson);
        await Client(transport).PrepareFactoryCatalogAsync(new()
        {
            Folder = "folder", Action = "add-project", FactoryId = "f", Project = new()
            {
                Number = "017", DisplayName = "Factory search", Placements =
                [
                    new() { Environment = "dev", ScaleSetId = "dev-003" },
                    new() { Environment = "stage", ScaleSetId = "stage-001" }
                ]
            }
        });
        var body = JsonNode.Parse(transport.Body)!;
        Assert.Equal("017", body["project"]!["number"]!.GetValue<string>());
        Assert.Equal("stage-001", body["project"]!["placements"]![1]!["scale_set_id"]!.GetValue<string>());
        Assert.Null(body["placements"]);
        Assert.Null(body["project_id"]);
    }

    [Fact]
    public async Task AdditionalPlacementUsesExistingLogicalProjectIdAndOnlyTheNewEnvironment()
    {
        var transport = new Transport(PreviewJson);
        var request = new FactoryCatalogRequest
        {
            Folder = "folder", Action = "add-project-placements", FactoryId = "f", ProjectId = "project-guid",
            Placements = [new() { Environment = "prod", ScaleSetId = "prod-001" }]
        };
        await Client(transport).PrepareFactoryCatalogAsync(request);
        var body = JsonNode.Parse(transport.Body)!;
        Assert.Equal("project-guid", body["project_id"]!.GetValue<string>());
        Assert.Single(body["placements"]!.AsArray());
        Assert.Null(body["project"]);
        await Assert.ThrowsAnyAsync<ArgumentException>(() => Client(transport).PrepareFactoryCatalogAsync(request with
        {
            Placements = [new() { Environment = "dev", ScaleSetId = "one" }, new() { Environment = "dev", ScaleSetId = "two" }]
        }));
        Assert.Equal(1, transport.Calls);
    }

    [Fact]
    public async Task PerTargetExecutionIsPreservedOnlyForNamespacedSharedRemote()
    {
        var transport = new Transport(PreviewJson);
        var request = RunnerRequest("ado", new() { Kind = "hosted", Image = "ubuntu-latest" });
        var binding = request.Binding! with
        {
            SharedRemote = true, Targets = [new()
            {
                ScaleSetId = "dev-002", ResourceGroupIds = ["scope"], Execution = new()
                {
                    WriterId = "second-writer", AuthNamespace = "second-connection", DeploymentObjectId = "second-principal",
                    Runner = new() { Kind = "self-hosted", Pool = "private-pool", AgentName = "agent-2" }
                }
            }]
        };
        await Client(transport).PrepareFactoryCatalogAsync(request with { Binding = binding });
        var sent = JsonNode.Parse(transport.Body)!["binding"]!["targets"]![0]!["execution"]!;
        Assert.Equal("second-principal", sent["deployment_object_id"]!.GetValue<string>());
        Assert.Equal("private-pool", sent["runner"]!["pool"]!.GetValue<string>());
        await Assert.ThrowsAnyAsync<ArgumentException>(() =>
            Client(transport).PrepareFactoryCatalogAsync(request with { Binding = binding with { SharedRemote = false } }));
        Assert.Equal(1, transport.Calls);
    }

    [Fact]
    public void CommonSubnetSettingsRoundTripWithoutDroppingExplicitAddresses()
    {
        var network = new CatalogNetwork
        {
            VnetCidr = "10.1.0.0/18", MaxProjects = 4, CommonSubnets = new()
            {
                Common = "10.1.0.0/26", Scoring = "10.1.0.64/26", Powerbi = "10.1.0.128/26", Bastion = "10.1.0.192/26"
            }
        };
        var options = new JsonSerializerOptions(JsonSerializerDefaults.Web);
        var json = JsonSerializer.Serialize(network, options);
        Assert.Equal("10.1.0.128/26", JsonNode.Parse(json)!["common_subnets"]!["powerbi"]!.GetValue<string>());
        Assert.Equal(network, JsonSerializer.Deserialize<CatalogNetwork>(json, options));
    }

    [Fact]
    public async Task ScopedSettingsReadAndDeltaWriteNeverChangeTheRootEditor()
    {
        var transport = new Transport("""
            {"contract_version":1,"revision":"revision-1","factory_id":"f","scale_set_id":"s","project_id":"p",
            "state":{"technical_admins_ad_object_id":"original"},"field_keys":["technical_admins_ad_object_id"],
            "message":"Non-secret scoped settings"}
            """);
        var client = Client(transport);
        var settings = await client.GetFactoryCatalogSettingsAsync(@"C:\factory & one", "f", "s", "p");
        Assert.Equal("?folder=C%3A%5Cfactory%20%26%20one&factory_id=f&scale_set_id=s&project_id=p", transport.Uri!.Query);
        Assert.Equal("original", settings.State["technical_admins_ad_object_id"]!.GetValue<string>());
        transport.Response = PreviewJson;
        await client.PrepareFactoryCatalogAsync(new()
        {
            Folder = "folder", Action = "configure-settings", FactoryId = "f", ScaleSetId = "s", ProjectId = "p",
            SourceRevision = settings.Revision, Settings = new() { ["technical_admins_ad_object_id"] = "updated" }
        });
        var sent = JsonNode.Parse(transport.Body)!;
        Assert.Single(sent["settings"]!.AsObject());
        Assert.Equal("updated", sent["settings"]!["technical_admins_ad_object_id"]!.GetValue<string>());
        Assert.Equal("original", settings.State["technical_admins_ad_object_id"]!.GetValue<string>());
        Assert.Equal("revision-1", sent["expected_revision"]!.GetValue<string>());
    }

    [Fact]
    public async Task WrongSettingsScopeIsRejected()
    {
        var transport = new Transport("""{"contract_version":1,"revision":"r","factory_id":"other","state":{},"field_keys":[]}""");
        await Assert.ThrowsAsync<InvalidDataException>(() => Client(transport).GetFactoryCatalogSettingsAsync("folder", "f"));
        Assert.Equal(1, transport.Calls);
    }

    private static AiFactoryApiClient Client(Transport transport) => new(transport, new Connection());
    private sealed class Connection : IAiFactoryConnectionProvider
    {
        public Task<AiFactoryConnection> GetConnectionAsync(CancellationToken cancellationToken = default) =>
            Task.FromResult(new AiFactoryConnection("http://127.0.0.1:8765", "test-key"));
    }
    private sealed class Transport(string response) : IJsonApiTransport
    {
        public string Response = response;
        public Exception? Error;
        public int Calls;
        public Uri? Uri;
        public HttpMethod? Method;
        public string? Key;
        public string Body = string.Empty;

        public async Task<TResponse> SendAsync<TResponse>(HttpRequestMessage request,
            CancellationToken cancellationToken = default)
        {
            Calls++;
            Uri = request.RequestUri;
            Method = request.Method;
            Key = request.Headers.TryGetValues("X-API-Key", out var values) ? values.Single() : null;
            Body = request.Content is null ? string.Empty : await request.Content.ReadAsStringAsync(cancellationToken);
            if (Error is not null) throw Error;
            return JsonSerializer.Deserialize<TResponse>(Response, new JsonSerializerOptions(JsonSerializerDefaults.Web))!;
        }
    }
}

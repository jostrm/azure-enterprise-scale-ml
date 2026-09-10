using System.Text.Json;
using System.Text.Json.Nodes;
using ESAIF.BaseLayer.Networking;
using ESAIF.DomainLayer.Configuration;

namespace ESAIF.DomainLayer.Tests;

public sealed class ProjectDeploymentClientTests
{
    [Fact]
    public async Task ListAcceptsApiFlatInheritedVersionWithoutDefaultingExistingFactories()
    {
        var transport = new Transport("""
            {"drafts":[],"requested_version":"125","branch":"release/v1.25",
            "resolved_ref":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"}
            """);
        var result = await new AiFactoryApiClient(transport, new Connection()).GetProjectDeploymentsAsync("folder");
        Assert.Equal("125", result.VersionSelection!.RequestedVersion);
        Assert.Equal("release/v1.25", result.VersionSelection.Branch);
        Assert.Equal(new string('a', 40), result.VersionSelection.ResolvedRef);
        transport.Response = """{"drafts":[],"requested_version":"","branch":"","resolved_ref":""}""";
        Assert.Null((await new AiFactoryApiClient(transport, new Connection()).GetProjectDeploymentsAsync("folder")).VersionSelection);
    }

    [Fact]
    public void ConflictingVersionAliasesCannotSilentlyChooseAnotherRelease()
    {
        var list = new ProjectDeploymentList
        {
            RequestedVersion = "125", Branch = "release/v1.25", ResolvedRef = new string('a', 40),
            VersionSelection = new() { RequestedVersion = "124", Branch = "release/v1.24", ResolvedRef = new string('b', 40) }
        };
        Assert.Throws<InvalidDataException>(() => list.VersionSelection);
    }

    [Fact]
    public async Task ListEscapesFactoryAndReadsPersistentDraftMetadata()
    {
        var transport = new Transport("""{"drafts":[{"id":"d","project_number":"001","source_environment":"dev","target_environment":"stage","status":"running","job_id":"j","route":"ado","script_path":"root.sh"}]}""");
        var result = await new AiFactoryApiClient(transport, new Connection()).GetProjectDeploymentsAsync(@"C:\a b\&factory");
        Assert.Equal("test", transport.Key);
        Assert.Equal(HttpMethod.Get, transport.Method);
        Assert.Equal("?folder=C%3A%5Ca%20b%5C%26factory", transport.Uri!.Query);
        var draft = Assert.Single(result.Drafts);
        Assert.Equal("stage", draft.TargetEnvironment);
        Assert.True(draft.IsRunning);
        Assert.Equal("ado", draft.Route);
        Assert.Equal("j", draft.JobId);
    }

    [Fact]
    public async Task PlanSendsOnlyScopeAndForwardEnvironmentPair()
    {
        var transport = new Transport(DraftResponse(project: "001"));
        await new AiFactoryApiClient(transport, new Connection()).PlanProjectDeploymentAsync(@"C:\factory", "001", "dev", "stage");
        Assert.EndsWith("/project-deployments/plan", transport.Uri!.AbsolutePath);
        var body = JsonNode.Parse(transport.Body)!.AsObject();
        Assert.Equal(["folder", "operation", "patch", "project_number", "source_environment", "target_environment"], body.Select(item => item.Key).Order());
        Assert.Equal("stage", body["target_environment"]!.GetValue<string>());
        Assert.Equal("001", body["project_number"]!.GetValue<string>());
        Assert.Equal("deploy", body["operation"]!.GetValue<string>());
        Assert.False(body["patch"]!.GetValue<bool>());
    }

    [Theory]
    [InlineData("dev", "dev")]
    [InlineData("stage", "dev")]
    [InlineData("bad", "stage")]
    public async Task InvalidPairNeverCallsTransport(string source, string target)
    {
        var transport = new Transport("{}");
        await Assert.ThrowsAsync<ArgumentException>(() =>
            new AiFactoryApiClient(transport, new Connection()).PlanProjectDeploymentAsync("folder", "001", source, target));
        Assert.Equal(0, transport.Calls);
    }

    [Fact]
    public async Task PrepareReadsServerCommandButStartCannotSubmitAnArbitraryCommand()
    {
        var transport = new Transport("""{"confirmation_id":"consent","can_execute":true,"command":"bash exact.sh","working_directory":"root","effects":["dispatch pipeline"],"warnings":["cost"],"blockers":[],"expires_at":"2099-01-01T00:00:00Z","deployment_contract":{"version":2,"draft_id":"draft","operation":"deploy","patch":false}}""");
        var client = new AiFactoryApiClient(transport, new Connection());
        var plan = await client.PrepareProjectDeploymentAsync("folder", "draft");
        Assert.Equal("root", plan.WorkingDirectory);
        Assert.Equal("bash exact.sh", plan.Command);
        Assert.Equal("""{"folder":"folder","draft_id":"draft","patch":false}""", transport.Body);
        await client.StartProjectDeploymentAsync("folder", plan.ConfirmationId);
        Assert.Equal("""{"folder":"folder","confirmation_id":"consent"}""", transport.Body);
        Assert.EndsWith("/project-deployments/start", transport.Uri!.AbsolutePath);
        Assert.Equal(2, transport.Calls);
    }

    [Theory]
    [InlineData("dev", false)]
    [InlineData("stage", true)]
    [InlineData("prod", false)]
    public async Task UpdateKeepsSameEnvironmentAndExplicitPatchChoice(string environment, bool patch)
    {
        var transport = new Transport(DraftResponse(environment, environment, patch: patch, operation: "update"));
        var client = new AiFactoryApiClient(transport, new Connection());
        await client.PlanProjectDeploymentAsync("folder", "017", environment, environment, patch, "update");
        var body = JsonNode.Parse(transport.Body)!;
        Assert.Equal("update", body["operation"]!.GetValue<string>());
        Assert.Equal(environment, body["source_environment"]!.GetValue<string>());
        Assert.Equal(environment, body["target_environment"]!.GetValue<string>());
        Assert.Equal(patch, body["patch"]!.GetValue<bool>());
        transport.Response = PreviewResponse(patch, "update");
        await client.PrepareProjectDeploymentAsync("folder", "draft", patch);
        Assert.Equal(patch, JsonNode.Parse(transport.Body)!["patch"]!.GetValue<bool>());
    }

    [Theory]
    [InlineData("dev", "stage", "update")]
    [InlineData("prod", "prod", "deploy")]
    [InlineData("unknown", "unknown", "update")]
    [InlineData("dev", "dev", "retry")]
    public async Task InvalidOperationNeverCallsTransport(string source, string target, string operation)
    {
        var transport = new Transport("{}");
        await Assert.ThrowsAsync<ArgumentException>(() => new AiFactoryApiClient(transport, new Connection())
            .PlanProjectDeploymentAsync("folder", "017", source, target, operation: operation));
        Assert.Equal(0, transport.Calls);
    }

    [Fact]
    public async Task ExistingDevToProdDeploymentRemainsSupported()
    {
        var transport = new Transport(DraftResponse(target: "prod"));
        await new AiFactoryApiClient(transport, new Connection()).PlanProjectDeploymentAsync("folder", "017", "dev", "prod");
        Assert.Equal(1, transport.Calls);
    }

    [Fact]
    public async Task ReconciliationUsesSeparatePreviewAndConfirmationEndpoints()
    {
        var transport = new Transport("""{"confirmation_id":"consent","can_execute":true}""");
        var client = new AiFactoryApiClient(transport, new Connection());
        var preview = await client.PrepareProjectReconciliationAsync("folder", "job");
        Assert.EndsWith("/project-deployments/reconcile/prepare", transport.Uri!.AbsolutePath);
        Assert.Equal("""{"folder":"folder","job_id":"job"}""", transport.Body);
        await client.ReconcileProjectDeploymentAsync("folder", preview.ConfirmationId);
        Assert.EndsWith("/project-deployments/reconcile", transport.Uri!.AbsolutePath);
        Assert.Equal("""{"folder":"folder","confirmation_id":"consent"}""", transport.Body);
    }

    [Fact]
    public async Task ExplicitVersionIsSentAndBoundToPlanAndPrepareAcknowledgement()
    {
        var response = JsonNode.Parse(DraftResponse(patch: true))!;
        AddVersion(response, "1.25", "125", "release/v1.25", new string('a', 40));
        var transport = new Transport(response.ToJsonString());
        var client = new AiFactoryApiClient(transport, new Connection());
        var draft = await client.PlanProjectDeploymentAsync("folder", "017", "dev", "stage", patch: true, factoryVersion: "1.25");
        Assert.Equal("1.25", JsonNode.Parse(transport.Body)!["aifactory_version"]!.GetValue<string>());
        Assert.Equal("release/v1.25", draft.Branch);
        response = JsonNode.Parse(PreviewResponse(true, "deploy"))!;
        AddVersion(response, "1.25", "125", "release/v1.25", new string('a', 40));
        transport.Response = response.ToJsonString();
        var preview = await client.PrepareProjectDeploymentAsync("folder", "draft", true, factoryVersion: "1.25");
        Assert.Equal("1.25", JsonNode.Parse(transport.Body)!["aifactory_version"]!.GetValue<string>());
        Assert.Equal(new string('a', 40), preview.ResolvedRef);
        Assert.Equal(2, transport.Calls);
    }

    [Theory]
    [InlineData("old-api")]
    [InlineData("wrong-choice")]
    [InlineData("unbound")]
    [InlineData("missing-top-echo")]
    [InlineData("wrong-top-echo")]
    [InlineData("different-ref")]
    [InlineData("missing-ref")]
    [InlineData("invalid-ref")]
    public async Task ExplicitVersionCannotBeIgnoredByPlanOrPrepare(string mismatch)
    {
        foreach (var prepare in new[] { false, true })
        {
            var response = JsonNode.Parse(prepare ? PreviewResponse(false, "deploy") : DraftResponse())!;
            if (mismatch != "old-api")
            {
                AddVersion(response, "125", "125", "release/v1.25", new string('a', 40));
                if (mismatch == "wrong-choice")
                {
                    response["deployment_contract"]!["aifactory_version"] = "124";
                }
                if (mismatch == "unbound") response["deployment_contract"]!.AsObject().Remove("aifactory_version");
                if (mismatch == "missing-top-echo") response.AsObject().Remove("aifactory_version");
                if (mismatch == "wrong-top-echo") response["aifactory_version"] = "124";
                if (mismatch == "different-ref") response["deployment_contract"]!["resolved_ref"] = "other-ref";
                if (mismatch == "invalid-ref")
                {
                    response["resolved_ref"] = "main";
                    response["deployment_contract"]!["resolved_ref"] = "main";
                }
                if (mismatch == "missing-ref")
                {
                    response.AsObject().Remove("resolved_ref");
                    response["deployment_contract"]!.AsObject().Remove("resolved_ref");
                }
            }
            var transport = new Transport(response.ToJsonString());
            var client = new AiFactoryApiClient(transport, new Connection());
            if (mismatch == "missing-ref" && !prepare)
            {
                var draft = await client.PlanProjectDeploymentAsync("folder", "017", "dev", "stage", factoryVersion: "125");
                Assert.Empty(draft.ResolvedRef);
                Assert.Equal(1, transport.Calls);
                continue;
            }
            var error = prepare
                ? await Assert.ThrowsAsync<InvalidOperationException>(() => client.PrepareProjectDeploymentAsync("folder", "draft", factoryVersion: "125"))
                : await Assert.ThrowsAsync<InvalidOperationException>(() => client.PlanProjectDeploymentAsync("folder", "017", "dev", "stage", factoryVersion: "125"));
            Assert.Contains("selected factory version", error.Message);
            Assert.Equal(1, transport.Calls);
            Assert.Contains("\"aifactory_version\":\"125\"", transport.Body);
        }
    }

    [Fact]
    public async Task BlockedVersionPreviewRetainsSourceBlockersUntilRefCanBeResolved()
    {
        var response = JsonNode.Parse(PreviewResponse(false, "deploy"))!;
        AddVersion(response, "125", "125", "release/v1.25", "");
        response["can_execute"] = false;
        response["blockers"] = new JsonArray("Publish or fetch the required release capability.");
        var transport = new Transport(response.ToJsonString());
        var plan = await new AiFactoryApiClient(transport, new Connection())
            .PrepareProjectDeploymentAsync("folder", "draft", factoryVersion: "125");
        Assert.False(plan.CanExecute);
        Assert.Empty(plan.ResolvedRef);
        Assert.Contains("required release capability", Assert.Single(plan.Blockers));
    }

    [Fact]
    public async Task ListReadsInheritedAndSavedDraftVersionsIndependently()
    {
        var transport = new Transport("""
            {"version_selection":{"requested_version":"2.134","branch":"release/v2.134","resolved_ref":"saved-ref"},
             "version_blockers":["Fetch the published source."],
             "drafts":[{"id":"d","requested_version":"main","branch":"main","resolved_ref":"draft-ref"}]}
            """);
        var result = await new AiFactoryApiClient(transport, new Connection()).GetProjectDeploymentsAsync("folder");
        Assert.Equal("2.134", result.VersionSelection!.RequestedVersion);
        Assert.Equal("Fetch the published source.", Assert.Single(result.VersionBlockers));
        Assert.Equal("main", Assert.Single(result.Drafts).RequestedVersion);
    }

    [Fact]
    public async Task LegacyPatchRejectionNeverRetriesWithoutTheChoice()
    {
        var transport = new Transport("{}") { Error = new HttpRequestException("422: patch is not supported") };
        var client = new AiFactoryApiClient(transport, new Connection());
        await Assert.ThrowsAsync<HttpRequestException>(() => client.PrepareProjectDeploymentAsync("folder", "draft", false));
        Assert.Equal(1, transport.Calls);
        Assert.Equal("""{"folder":"folder","draft_id":"draft","patch":false}""", transport.Body);
    }

    [Theory]
    [InlineData(null)]
    [InlineData("""{}""")]
    [InlineData("""{"version":1,"draft_id":"draft","operation":"deploy","patch":false}""")]
    [InlineData("""{"version":2,"draft_id":"draft","operation":"deploy"}""")]
    [InlineData("""{"version":2,"draft_id":"draft","patch":false}""")]
    [InlineData("""{"version":2,"draft_id":"draft","operation":"deploy","patch":true}""")]
    [InlineData("""{"version":2,"draft_id":"other","operation":"deploy","patch":false}""")]
    [InlineData("""{"version":2,"draft_id":"draft","operation":"retry","patch":false}""")]
    public async Task PrepareFailsClosedWhenAcknowledgementIsMissingOrDifferent(string? acknowledgement)
    {
        var response = new JsonObject
        {
            ["confirmation_id"] = "legacy-consent", ["can_execute"] = true,
            ["command"] = "bash exact.sh --project-only",
            ["deployment_contract"] = acknowledgement is null ? null : JsonNode.Parse(acknowledgement)
        };
        var transport = new Transport(response.ToJsonString());
        await Assert.ThrowsAsync<InvalidOperationException>(() =>
            new AiFactoryApiClient(transport, new Connection()).PrepareProjectDeploymentAsync("folder", "draft", false));
        Assert.Equal(1, transport.Calls);
        Assert.EndsWith("/prepare", transport.Uri!.AbsolutePath);
        Assert.Contains("\"patch\":false", transport.Body);
    }

    [Theory]
    [InlineData("missing-contract")]
    [InlineData("missing-patch")]
    [InlineData("wrong-version")]
    [InlineData("wrong-operation")]
    [InlineData("wrong-target")]
    [InlineData("wrong-project")]
    public async Task SameEnvironmentPlanRequiresExactVersionedAcknowledgement(string mismatch)
    {
        var response = JsonNode.Parse(DraftResponse("prod", "prod", operation: "update"))!.AsObject();
        switch (mismatch)
        {
            case "missing-contract": response.Remove("deployment_contract"); break;
            case "missing-patch": response["deployment_contract"]!.AsObject().Remove("patch"); break;
            case "wrong-version": response["deployment_contract"]!["version"] = 1; break;
            case "wrong-operation": response["deployment_contract"]!["operation"] = "deploy"; break;
            case "wrong-target": response["target_environment"] = "stage"; break;
            case "wrong-project": response["project_number"] = "018"; break;
        }
        var transport = new Transport(response.ToJsonString());
        await Assert.ThrowsAsync<InvalidOperationException>(() => new AiFactoryApiClient(transport, new Connection())
            .PlanProjectDeploymentAsync("folder", "017", "prod", "prod", operation: "update"));
        Assert.Equal(1, transport.Calls);
        Assert.EndsWith("/plan", transport.Uri!.AbsolutePath);
    }

    private static void AddVersion(JsonNode response, string input, string canonical, string branch, string reference)
    {
        foreach (var target in new[] { response, response["deployment_contract"]! })
        {
            target["aifactory_version"] = input;
            target["requested_version"] = canonical;
            target["branch"] = branch;
            target["resolved_ref"] = reference;
        }
    }

    private static string DraftResponse(string source = "dev", string target = "stage", string project = "017",
        bool patch = false, string operation = "deploy") => JsonSerializer.Serialize(new
        {
            id = "draft", project_number = project, source_environment = source, target_environment = target,
            operation, patch,
            deployment_contract = new { version = 2, draft_id = "draft", operation, patch }
        });

    private static string PreviewResponse(bool patch, string operation) => JsonSerializer.Serialize(new
    {
        confirmation_id = "consent", can_execute = true,
        deployment_contract = new { version = 2, draft_id = "draft", operation, patch }
    });

    private sealed class Connection : IAiFactoryConnectionProvider
    {
        public Task<AiFactoryConnection> GetConnectionAsync(CancellationToken cancellationToken = default) =>
            Task.FromResult(new AiFactoryConnection("http://127.0.0.1:8765", "test"));
    }

    private sealed class Transport(string response) : IJsonApiTransport
    {
        public HttpMethod? Method;
        public Uri? Uri;
        public string Body = "", Key = "";
        public int Calls;
        public Exception? Error;
        public string Response = response;
        public async Task<T> SendAsync<T>(HttpRequestMessage request, CancellationToken cancellationToken = default)
        {
            Calls++;
            Method = request.Method;
            Uri = request.RequestUri;
            Key = request.Headers.GetValues("X-API-Key").Single();
            Body = request.Content is null ? "" : await request.Content.ReadAsStringAsync(cancellationToken);
            if (Error is not null) throw Error;
            return JsonSerializer.Deserialize<T>(Response, new JsonSerializerOptions(JsonSerializerDefaults.Web))!;
        }
    }
}

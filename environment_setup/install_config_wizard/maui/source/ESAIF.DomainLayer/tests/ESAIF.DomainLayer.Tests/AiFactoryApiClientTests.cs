using System.Text.Json.Nodes;
using ESAIF.BaseLayer.Networking;
using ESAIF.DomainLayer.Configuration;

namespace ESAIF.DomainLayer.Tests;

public sealed class AiFactoryApiClientTests
{
    [Fact]
    public void Connection_BuildsSwaggerAddressFromApiBaseAddress()
    {
        var connection = new AiFactoryConnection(
            "http://127.0.0.1:8765",
            "secret");

        Assert.Equal(
            "http://127.0.0.1:8765/docs",
            connection.DocumentationUri.AbsoluteUri);
    }

    [Fact]
    public async Task GetSchemaAsync_UsesConfiguredAddressAndApiKey()
    {
        var transport = new RecordingTransport(new FactorySchema());
        var client = CreateClient(transport);

        await client.GetSchemaAsync();

        Assert.Equal(
            "http://127.0.0.1:8765/api/v1/schema",
            transport.RequestUri?.AbsoluteUri);
        Assert.Equal(HttpMethod.Get, transport.Method);
        Assert.Equal("secret", transport.ApiKey);
    }

    [Fact]
    public async Task ImportAsync_NormalizesYamlAndUsesInlineContent()
    {
        var transport = new RecordingTransport(new ImportResult
        {
            Format = "yaml",
            FieldsLoaded = 1,
            State = new JsonObject { ["project_number_000"] = "001" }
        });
        var client = CreateClient(transport);

        var result = await client.ImportAsync(
            ".yml",
            "variables:\n  project_number_000: 001",
            []);

        Assert.Equal(1, result.FieldsLoaded);
        Assert.Contains(@"""format"":""yaml""", transport.RequestBody);
        Assert.Contains(@"""content"":""variables:\n", transport.RequestBody);
        Assert.Contains(@"""path"":null", transport.RequestBody);
    }

    [Fact]
    public async Task GetSchemaAsync_RejectsMissingApiKey()
    {
        var transport = new RecordingTransport(new FactorySchema());
        var provider = new StaticConnectionProvider(
            new AiFactoryConnection("http://127.0.0.1:8765", string.Empty));
        var client = new AiFactoryApiClient(transport, provider);

        var exception = await Assert.ThrowsAsync<InvalidOperationException>(
            () => client.GetSchemaAsync());

        Assert.Contains("API key", exception.Message);
    }

    [Fact]
    public async Task GetHealthAsync_DoesNotSendApiKey()
    {
        var transport = new RecordingTransport(
            new HealthStatus { Status = "ok", Version = "1.0.0" });
        var client = CreateClient(transport);

        var health = await client.GetHealthAsync();

        Assert.Equal("ok", health.Status);
        Assert.Equal("http://127.0.0.1:8765/health", transport.RequestUri?.AbsoluteUri);
        Assert.Null(transport.ApiKey);
    }

    [Fact]
    public async Task SaveProjectAsync_UsesContractPropertyNames()
    {
        var transport = new RecordingTransport(
            new ProjectSaveResult { SnapshotPath = "snapshot.json" });
        var client = CreateClient(transport);

        await client.SaveProjectAsync(
            new JsonObject { ["project_number_000"] = "007" },
            writeVariables: false);

        Assert.Equal(
            "http://127.0.0.1:8765/api/v1/projects/save",
            transport.RequestUri?.AbsoluteUri);
        Assert.Contains(@"""project_number_000"":""007""", transport.RequestBody);
        Assert.Contains(@"""write_variables"":false", transport.RequestBody);
    }

    [Fact]
    public async Task LoadScaleSetAsync_UsesExpectedRouteAndBody()
    {
        var transport = new RecordingTransport(new ScaleSetLoadResult());
        var client = CreateClient(transport);

        await client.LoadScaleSetAsync(@"C:\aifactory", "007");

        Assert.Equal(
            "http://127.0.0.1:8765/api/v1/scale-sets/load",
            transport.RequestUri?.AbsoluteUri);
        Assert.Contains(@"""aifactory_folder"":""C:\\aifactory""", transport.RequestBody);
        Assert.Contains(@"""scale_set_id"":""007""", transport.RequestBody);
    }

    [Fact]
    public async Task ExportAsync_RejectsUnknownFormatBeforeTransport()
    {
        var transport = new RecordingTransport(new ExportResult());
        var client = CreateClient(transport);

        await Assert.ThrowsAsync<ArgumentOutOfRangeException>(
            () => client.ExportAsync("toml", []));

        Assert.Null(transport.RequestUri);
    }

    [Fact]
    public async Task GetHealthAsync_RejectsNonHttpBaseAddress()
    {
        var transport = new RecordingTransport(new HealthStatus());
        var client = new AiFactoryApiClient(
            transport,
            new StaticConnectionProvider(
                new AiFactoryConnection("file:///temporary/api", "secret")));

        var exception = await Assert.ThrowsAsync<InvalidOperationException>(
            () => client.GetHealthAsync());

        Assert.Contains("HTTP or HTTPS", exception.Message);
    }

    private static AiFactoryApiClient CreateClient(RecordingTransport transport)
    {
        return new AiFactoryApiClient(
            transport,
            new StaticConnectionProvider(
                new AiFactoryConnection("http://127.0.0.1:8765", "secret")));
    }

    [Fact]
    public async Task ImportRegionFindings_SendsArtifactToAuthenticatedCurrentFactoryEndpoint()
    {
        var transport = new RecordingTransport(new RegionFindingsImportResult { Recorded = 3 });
        var result = await CreateClient(transport).ImportRegionFindingsAsync(@"C:\factory", "{\"schema_version\":1}");
        Assert.Equal(3, result.Recorded);
        Assert.EndsWith("/api/v1/operations/region-findings/import", transport.RequestUri!.AbsoluteUri);
        Assert.Equal("secret", transport.ApiKey);
        var body = JsonNode.Parse(transport.RequestBody!)!;
        Assert.Equal(@"C:\factory", body["aifactory_folder"]!.GetValue<string>());
        Assert.Equal("{\"schema_version\":1}", body["content"]!.GetValue<string>());
    }

    [Fact]
    public async Task AzureStatus_UsesSecuredMetadataEndpointWithoutStartingLogin()
    {
        var transport = new RecordingTransport(new AzureAuthenticationStatus());
        await CreateClient(transport).GetAzureAuthenticationStatusAsync(@"C:\factory");
        Assert.EndsWith("/api/v1/azure/auth/status", transport.RequestUri!.AbsoluteUri);
        Assert.Equal("secret", transport.ApiKey);
        Assert.Equal(@"C:\factory", JsonNode.Parse(transport.RequestBody!)!["aifactory_folder"]!.GetValue<string>());
    }

    [Fact]
    public async Task AzureStatus_AllowsLoginBeforeAFactoryFolderHasBeenSelected()
    {
        var transport = new RecordingTransport(new AzureAuthenticationStatus());
        await CreateClient(transport).GetAzureAuthenticationStatusAsync("  ");
        Assert.Null(JsonNode.Parse(transport.RequestBody!)!["aifactory_folder"]);
    }

    [Fact]
    public async Task AzureLogin_UsesExplicitTenantAndNeverPassesCredentials()
    {
        var transport = new RecordingTransport(new AzureAuthenticationStatus());
        await CreateClient(transport).LoginToAzureAsync(@"C:\factory", "11111111-1111-1111-1111-111111111111");
        Assert.EndsWith("/api/v1/azure/auth/login", transport.RequestUri!.AbsoluteUri);
        var body = JsonNode.Parse(transport.RequestBody!)!.AsObject();
        Assert.Equal(2, body.Count);
        Assert.Equal("11111111-1111-1111-1111-111111111111", body["tenant_id"]!.GetValue<string>());
    }

    [Fact]
    public async Task AzureLogout_IsSeparateFromPublicHealthAndM365Authentication()
    {
        var transport = new RecordingTransport(new AzureAuthenticationStatus());
        await CreateClient(transport).LogoutFromAzureAsync(null);
        Assert.EndsWith("/api/v1/azure/auth/logout", transport.RequestUri!.AbsoluteUri);
        Assert.Equal(HttpMethod.Post, transport.Method);
        Assert.Equal("secret", transport.ApiKey);
    }

    [Fact]
    public async Task AzureOperationPoll_UsesReadOnlyAuthenticatedGet()
    {
        var transport = new RecordingTransport(new AzureAuthenticationStatus());
        await CreateClient(transport).GetAzureAuthenticationOperationAsync("job-id");
        Assert.EndsWith("/api/v1/azure/auth/operations/job-id", transport.RequestUri!.AbsoluteUri);
        Assert.Equal(HttpMethod.Get, transport.Method);
        Assert.Empty(transport.RequestBody);
        Assert.Equal("secret", transport.ApiKey);
    }

    [Fact]
    public async Task AzureLogin_RejectsInvalidTenantBeforeSendingRequest()
    {
        var transport = new RecordingTransport(new AzureAuthenticationStatus());
        await Assert.ThrowsAsync<ArgumentException>(() => CreateClient(transport).LoginToAzureAsync(null, "--tenant other"));
        Assert.Null(transport.RequestUri);
    }

    [Fact]
    public async Task PrepareFactoryConfiguration_SendsExplicitSourceAndRegionWithAuthentication()
    {
        var transport = new RecordingTransport(new FactoryConfigurationPreparation());
        await CreateClient(transport).PrepareFactoryConfigurationAsync("clone", "norwayeast", @"C:\source");
        Assert.EndsWith("/api/v1/factories/configuration/prepare", transport.RequestUri!.AbsoluteUri);
        var body = JsonNode.Parse(transport.RequestBody!)!;
        Assert.Equal("clone", body["kind"]!.GetValue<string>());
        Assert.Equal("norwayeast", body["target_region"]!.GetValue<string>());
        Assert.Equal(@"C:\source", body["source_folder"]!.GetValue<string>());
        Assert.Equal("secret", transport.ApiKey);
    }

    [Fact]
    public async Task SaveFactoryConfiguration_SendsSeparateDestinationAndStateWithoutDeployment()
    {
        var transport = new RecordingTransport(new FactoryConfigurationSaveResult { Path = "new.json" });
        var state = new JsonObject { ["admin_location"] = "norwayeast" };
        await CreateClient(transport).SaveFactoryConfigurationAsync("clone", "norwayeast", @"C:\source", @"C:\target", state);
        var body = JsonNode.Parse(transport.RequestBody!)!;
        Assert.EndsWith("/api/v1/factories/configuration/save", transport.RequestUri!.AbsoluteUri);
        Assert.Equal(@"C:\target", body["destination_folder"]!.GetValue<string>());
        Assert.Equal(state.ToJsonString(), body["state"]!.ToJsonString());
        Assert.Equal("secret", transport.ApiKey);
    }

    [Theory]
    [InlineData("delete", "norwayeast", "source")]
    [InlineData("clone", "norwayeast", null)]
    [InlineData("factory", "", null)]
    public async Task PrepareFactoryConfiguration_RejectsUnsupportedOperationsOrMissingContext(
        string kind, string region, string? source)
    {
        var transport = new RecordingTransport(new FactoryConfigurationPreparation());
        await Assert.ThrowsAnyAsync<ArgumentException>(() =>
            CreateClient(transport).PrepareFactoryConfigurationAsync(kind, region, source));
        Assert.Null(transport.RequestUri);
    }

    [Fact]
    public async Task DeleteProjectConfig_UsesAuthenticatedEndpointAndExactListedPath()
    {
        var transport = new RecordingTransport(new ProjectConfigurationDeleteResult { DeletedPath = @"C:\factory\project_state.json" });
        var result = await CreateClient(transport).DeleteProjectConfigurationAsync(
            @"C:\factory", "017", @"C:\factory\project_state.json");
        Assert.Equal(HttpMethod.Post, transport.Method);
        Assert.Equal("secret", transport.ApiKey);
        Assert.EndsWith("/api/v1/projects/delete", transport.RequestUri!.AbsoluteUri);
        var body = JsonNode.Parse(transport.RequestBody!)!;
        Assert.Equal(@"C:\factory", body["aifactory_folder"]!.GetValue<string>());
        Assert.Equal("017", body["project_number"]!.GetValue<string>());
        Assert.Equal(result.DeletedPath, body["path"]!.GetValue<string>());
    }

    [Fact]
    public async Task GetProjects_RetainsDeploymentIdentityProvidedByPython()
    {
        var response = new ProjectsResult
        {
            Projects = [new ProjectSummary
            {
                ProjectNumber = "017",
                DeploymentScope = new ProjectDeploymentScope { Region = "swedencentral", SuffixResourceGroup = "-007" }
            }]
        };
        var result = await CreateClient(new RecordingTransport(response)).GetProjectsAsync(@"C:\factory");
        Assert.Equal("swedencentral", Assert.Single(result.Projects).DeploymentScope!.Region);
    }

    [Fact]
    public async Task DeleteScaleSetConfig_UsesExactListedIdentityAndAuthenticatedEndpoint()
    {
        var transport = new RecordingTransport(new ScaleSetConfigurationDeleteResult
        {
            DeletedPath = @"C:\factory\config-wizard\scalesets\scaleset_007.json", Message = "Deleted"
        });
        var result = await CreateClient(transport).DeleteScaleSetConfigurationAsync(
            @"C:\factory", "007", @"C:\factory\config-wizard\scalesets\scaleset_007.json");
        Assert.Equal("secret", transport.ApiKey);
        Assert.Equal(HttpMethod.Post, transport.Method);
        Assert.EndsWith("/api/v1/scale-sets/delete", transport.RequestUri!.AbsoluteUri);
        var body = JsonNode.Parse(transport.RequestBody!)!;
        Assert.Equal("007", body["scale_set_id"]!.GetValue<string>());
        Assert.Equal(result.DeletedPath, body["path"]!.GetValue<string>());
        Assert.Equal(@"C:\factory", body["aifactory_folder"]!.GetValue<string>());
    }

    [Fact]
    public async Task VerifyScaleSetResourceGroups_SendsListedConfigurationNotArbitraryUrl()
    {
        var transport = new RecordingTransport(new ScaleSetResourceGroupVerification { ScaleSetId = "007" });
        await CreateClient(transport).VerifyScaleSetResourceGroupsAsync(@"C:\factory", "007", @"C:\factory\scaleset_007.json");
        Assert.EndsWith("/api/v1/scale-sets/verify-resource-groups", transport.RequestUri!.AbsoluteUri);
        Assert.Equal(HttpMethod.Post, transport.Method);
        Assert.Equal("secret", transport.ApiKey);
        var body = JsonNode.Parse(transport.RequestBody!)!.AsObject();
        Assert.Equal(3, body.Count);
        Assert.Equal("007", body["scale_set_id"]!.GetValue<string>());
        Assert.Equal(@"C:\factory\scaleset_007.json", body["path"]!.GetValue<string>());
        Assert.False(body.ContainsKey("url"));
    }

    [Fact]
    public async Task VerifyProjectResourceGroups_SendsExactProjectSelectionToSecuredEndpoint()
    {
        var transport = new RecordingTransport(new ProjectResourceGroupVerification { ProjectNumber = "017" });
        await CreateClient(transport).VerifyProjectResourceGroupsAsync(@"C:\factory", "017", @"C:\factory\project017.json");
        Assert.EndsWith("/api/v1/projects/verify-resource-groups", transport.RequestUri!.AbsoluteUri);
        Assert.Equal("secret", transport.ApiKey);
        var body = JsonNode.Parse(transport.RequestBody!)!;
        Assert.Equal("017", body["project_number"]!.GetValue<string>());
        Assert.Equal(@"C:\factory\project017.json", body["path"]!.GetValue<string>());
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
            return (TResponse)response;
        }
    }
}

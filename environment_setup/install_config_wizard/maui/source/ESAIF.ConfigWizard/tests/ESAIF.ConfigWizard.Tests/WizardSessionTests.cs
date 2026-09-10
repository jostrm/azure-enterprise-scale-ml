using System.Text.Json.Nodes;
using ESAIF.DomainLayer.Configuration;
using ESAIF.DomainLayer.Operations;
using ESAIF.ConfigWizard.Services;

namespace ESAIF.ConfigWizard.Tests;

public sealed class WizardSessionTests
{
    [Fact]
    public async Task InitializeAsync_LoadsSchemaAndIndependentStateClone()
    {
        var defaults = new JsonObject { ["project_number_000"] = "001" };
        var session = new WizardSession(new StubApiClient(new FactorySchema
        {
            Defaults = defaults
        }));
        var notifications = 0;
        session.StateChanged += (_, _) => notifications++;

        await session.InitializeAsync();
        session.SetValue("project_number_000", "099");

        Assert.True(session.IsInitialized);
        Assert.Equal("099", session.GetString("project_number_000"));
        Assert.Equal("001", defaults["project_number_000"]?.GetValue<string>());
        Assert.Equal(2, notifications);
    }

    [Fact]
    public async Task InitializeAsync_DoesNotReloadUnlessForced()
    {
        var api = new StubApiClient(new FactorySchema
        {
            Defaults = new JsonObject { ["value"] = "one" }
        });
        var session = new WizardSession(api);

        await session.InitializeAsync();
        await session.InitializeAsync();
        await session.InitializeAsync(force: true);

        Assert.Equal(2, api.SchemaRequests);
    }

    [Fact]
    public async Task SetValue_NetworkModeAppliesApiProvidedFlagMapping()
    {
        var session = new WizardSession(new StubApiClient(new FactorySchema
        {
            Defaults = new JsonObject
            {
                ["network_mode"] = "public",
                ["allowPublicAccessWhenBehindVnet"] = "true"
            },
            Options = new JsonObject
            {
                ["network_modes"] = new JsonObject
                {
                    ["private"] = new JsonObject
                    {
                        ["allowPublicAccessWhenBehindVnet"] = "false",
                        ["enablePublicGenAIAccess"] = "false"
                    }
                }
            }
        }));
        await session.InitializeAsync();
        var notifications = 0;
        session.StateChanged += (_, _) => notifications++;

        session.SetValue("network_mode", "private");

        Assert.Equal("private", session.GetString("network_mode"));
        Assert.Equal("false", session.GetString("allowPublicAccessWhenBehindVnet"));
        Assert.Equal("false", session.GetString("enablePublicGenAIAccess"));
        Assert.Equal(1, notifications);
    }

    [Fact]
    public async Task RegionSelectionUpdatesSuffixAtomicallyButLoadingPreservesSavedSuffix()
    {
        var schema = new FactorySchema
        {
            Defaults = new JsonObject { ["admin_location"] = "eastus2", ["admin_locationSuffix"] = "custom",
                ["projectPrefix"] = "", ["projectSuffix"] = "" },
            Options = new JsonObject
            {
                ["azure_regions"] = new JsonArray("westeurope", "swedencentral", "eastus2"),
                ["azure_region_suffixes"] = new JsonObject
                {
                    ["eastus2"] = "eus2", ["swedencentral"] = "sdc", ["westeurope"] = "weu"
                }
            }
        };
        var session = new WizardSession(new StubApiClient(schema));
        await session.InitializeAsync();
        Assert.Equal("custom", session.GetString("admin_locationSuffix"));
        var notifications = 0;
        session.StateChanged += (_, _) => notifications++;
        session.SetValue("admin_location", "swedencentral");
        Assert.Equal("sdc", session.GetString("admin_locationSuffix"));
        Assert.Equal(1, notifications);
        session.SetValue("admin_location", "westeurope");
        Assert.Equal("weu", session.GetString("admin_locationSuffix"));
        session.SetValue("admin_location", "eastus2");
        Assert.Equal("eus2", session.GetString("admin_locationSuffix"));
        session.SetValue("admin_locationSuffix", "custom-again");
        session.SetValue("admin_location", "eastus2");
        Assert.Equal("custom-again", session.GetString("admin_locationSuffix"));
        session.ReplaceState(new JsonObject { ["admin_location"] = "swedencentral", ["admin_locationSuffix"] = "saved" });
        Assert.Equal("saved", session.GetString("admin_locationSuffix"));
        session.SetValue("admin_location", "new-region");
        Assert.Equal("", session.GetString("admin_locationSuffix"));
        Assert.Equal("custom", schema.Defaults["admin_locationSuffix"]!.GetValue<string>());
    }

    [Fact]
    public void ReplaceState_ClonesCallerStateAndNotifies()
    {
        var session = new WizardSession(new StubApiClient(new FactorySchema()));
        var state = new JsonObject { ["value"] = "original" };
        var notifications = 0;
        session.StateChanged += (_, _) => notifications++;

        session.ReplaceState(state);
        state["value"] = "caller changed";

        Assert.Equal("original", session.GetString("value"));
        Assert.Equal(1, notifications);
    }

    [Fact]
    public async Task StateReplacementAndEdits_UpdateIdentityWithoutRebuildingOnEachEdit()
    {
        var session = new WizardSession(new StubApiClient(new FactorySchema
        {
            Defaults = new JsonObject { ["project_number_000"] = "001" }
        }));
        var replacements = 0;
        session.StateReplaced += (_, _) => replacements++;
        await session.InitializeAsync();
        session.SetValue("project_number_000", "008");
        Assert.Equal("008", session.Identity.ProjectNumber);
        Assert.Equal(1, replacements);

        session.ReplaceState(new JsonObject { ["project_number_000"] = "009" });
        Assert.Equal("009", session.Identity.ProjectNumber);
        Assert.Equal(2, replacements);
        await session.InitializeAsync(force: true);
        Assert.Equal("001", session.Identity.ProjectNumber);
        Assert.Equal(3, replacements);
    }

    [Fact]
    public async Task ReverificationAfterFailure_PreservesEditedStateUnlessResetIsRequested()
    {
        var api = new StubApiClient(new FactorySchema
        {
            Defaults = new JsonObject { ["project_number_000"] = "001" }
        });
        var session = new WizardSession(api);
        await session.InitializeAsync();
        session.SetValue("project_number_000", "008");
        session.Connection.MarkFailed(new HttpRequestException("Disconnected"));
        await session.InitializeAsync();
        Assert.Equal(2, api.SchemaRequests);
        Assert.Equal("008", session.Identity.ProjectNumber);
        Assert.True(session.Connection.IsConnected);
        Assert.Empty(session.Connection.LastError);
    }

    [Fact]
    public async Task StartupFolder_IsAnInitialValueNotAnOverrideOfSubsequentSelections()
    {
        var session = new WizardSession(new StubApiClient(new FactorySchema
        {
            Defaults = new JsonObject { ["_save_folder"] = "" }
        }), startupFolder: @"C:\original");
        Assert.Equal(@"C:\original", session.GetString("_save_folder"));
        await session.InitializeAsync();
        Assert.Equal(@"C:\original", session.State["_save_folder"]!.GetValue<string>());
        session.ReplaceState(new JsonObject { ["_save_folder"] = @"C:\new-factory" });
        Assert.Equal(@"C:\new-factory", session.GetString("_save_folder"));
        session.SetValue("_save_folder", @"C:\third");
        Assert.Equal(@"C:\third", session.GetString("_save_folder"));
    }

    private sealed class StubApiClient(FactorySchema schema) : IAiFactoryApiClient
    {
        public int SchemaRequests { get; private set; }

        public Task<FactorySchema> GetSchemaAsync(
            CancellationToken cancellationToken = default)
        {
            SchemaRequests++;
            return Task.FromResult(schema);
        }

        public Task<HealthStatus> GetHealthAsync(CancellationToken cancellationToken = default) =>
            throw new NotSupportedException();

        public Task<StateResult> GetDefaultsAsync(JsonObject state, CancellationToken cancellationToken = default) =>
            throw new NotSupportedException();

        public Task<ValidationResult> ValidateAsync(JsonObject state, CancellationToken cancellationToken = default) =>
            throw new NotSupportedException();

        public Task<ImportResult> ImportAsync(string format, string content, JsonObject state, CancellationToken cancellationToken = default) =>
            throw new NotSupportedException();

        public Task<ExportResult> ExportAsync(string format, JsonObject state, string? destinationPath = null, CancellationToken cancellationToken = default) =>
            throw new NotSupportedException();

        public Task<StartupLoadResult> LoadStartupAsync(string aiFactoryFolder, string projectNumber, CancellationToken cancellationToken = default) =>
            throw new NotSupportedException();

        public Task<ProjectsResult> GetProjectsAsync(string aiFactoryFolder, CancellationToken cancellationToken = default) =>
            throw new NotSupportedException();

        public Task<ProjectLoadResult> LoadProjectAsync(string aiFactoryFolder, string projectNumber, CancellationToken cancellationToken = default) =>
            throw new NotSupportedException();

        public Task<ProjectSaveResult> SaveProjectAsync(JsonObject state, bool writeVariables = true, CancellationToken cancellationToken = default) =>
            throw new NotSupportedException();

        public Task<ScaleSetsResult> GetScaleSetsAsync(string aiFactoryFolder, CancellationToken cancellationToken = default) =>
            throw new NotSupportedException();

        public Task<ScaleSetLoadResult> LoadScaleSetAsync(string aiFactoryFolder, string scaleSetId, CancellationToken cancellationToken = default) =>
            throw new NotSupportedException();

        public Task<PathResult> SaveScaleSetAsync(JsonObject state, CancellationToken cancellationToken = default) =>
            throw new NotSupportedException();

        public Task<RecentProjectsResult> GetRecentProjectsAsync(CancellationToken cancellationToken = default) =>
            throw new NotSupportedException();

        public Task<RecentProjectsResult> RecordRecentProjectAsync(
            string aiFactoryFolder,
            string projectNumber,
            string orchestrator,
            string prefixResourceGroup,
            string suffixResourceGroup,
            CancellationToken cancellationToken = default) =>
            throw new NotSupportedException();

        public Task<OperationsOverview> GetOperationsOverviewAsync(string aiFactoryFolder, bool includeAzure = true, bool forceRefresh = false, CancellationToken cancellationToken = default) => throw new NotSupportedException();
        public Task<OperationsRegionsResult> GetOperationsRegionsAsync(CancellationToken cancellationToken = default) => throw new NotSupportedException();
        public Task<OperationConfigResult> LoadOperationsConfigAsync(string aiFactoryFolder, string projectNumber, string environment, string kind, CancellationToken cancellationToken = default) => throw new NotSupportedException();
        public Task<OperationConfigResult> SaveOperationsConfigAsync(string aiFactoryFolder, string projectNumber, string environment, string kind, JsonObject config, CancellationToken cancellationToken = default) => throw new NotSupportedException();
        public Task<DraftFactoryAction> CreateFactoryActionAsync(string aiFactoryFolder, string action, string targetRegion, string? sourceRegion = null, CancellationToken cancellationToken = default) => throw new NotSupportedException();
        public Task<DraftProjectAction> CreateProjectActionAsync(string aiFactoryFolder, string projectNumber, string sourceEnvironment, string targetEnvironment, string action, CancellationToken cancellationToken = default) => throw new NotSupportedException();
        public Task<OperationsPromptSearchResult> SearchPromptsAsync(string aiFactoryFolder, string? projectNumber = null, string? environment = null, string? model = null, string? category = null, string? search = null, bool? success = null, int limit = 100, int offset = 0, CancellationToken cancellationToken = default) => throw new NotSupportedException();
    }
}

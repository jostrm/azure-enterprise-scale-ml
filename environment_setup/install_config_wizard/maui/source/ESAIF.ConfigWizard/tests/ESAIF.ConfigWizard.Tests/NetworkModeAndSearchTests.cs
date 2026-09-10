using System.Text.Json.Nodes;
using ESAIF.ConfigWizard.Services;
using ESAIF.ConfigWizard.ViewModels;
using ESAIF.DomainLayer.Configuration;

namespace ESAIF.ConfigWizard.Tests;

public sealed class NetworkModeAndSearchTests
{
    private static JsonObject Flags(bool behind, bool genai, bool perimeter) => new()
    {
        ["allowPublicAccessWhenBehindVnet"] = behind.ToString().ToLowerInvariant(),
        ["enablePublicGenAIAccess"] = genai.ToString().ToLowerInvariant(),
        ["enablePublicAccessWithPerimeter"] = perimeter.ToString().ToLowerInvariant()
    };

    private static FactorySchema Schema()
    {
        var defaults = Flags(true, true, true);
        defaults["network_mode"] = "public";
        defaults["orchestrator"] = "ado";
        defaults["tenantId"] = "tenant";
        defaults["admin_location"] = "swedencentral";
        defaults["projectPrefix"] = "";
        defaults["projectSuffix"] = "";
        defaults["skuStorageAccountDev"] = "Standard_LRS";
        defaults["skuStorageAccountStageProd"] = "Standard_GRS";
        return new FactorySchema
        {
            Defaults = defaults,
            Sections = new SchemaSections { ScaleSetVariables = ["admin_location"] },
            Options = new JsonObject
            {
                ["network_modes"] = new JsonObject
                {
                    ["private"] = Flags(false, false, false),
                    ["hybrid"] = Flags(true, true, false),
                    ["public"] = Flags(true, true, true)
                },
                ["azure_regions"] = new JsonArray("eastus2", "swedencentral")
            }
        };
    }

    [Theory]
    [InlineData("private", false, false, false)]
    [InlineData("hybrid", true, true, false)]
    [InlineData("public", true, true, true)]
    public void LoadedFlagsSelectTheModeWithoutRewritingValues(string expected, bool behind, bool genai, bool perimeter)
    {
        var schema = Schema();
        var state = Flags(behind, genai, perimeter);
        state["network_mode"] = "stale-mode";
        var writes = 0;
        var vm = new NetworkModeViewModel((JsonObject)schema.Options["network_modes"]!, state, _ => writes++);
        Assert.Equal(expected == "private", vm.IsPrivate);
        Assert.Equal(expected == "hybrid", vm.IsHybrid);
        Assert.Equal(expected == "public", vm.IsPublic);
        Assert.False(vm.HasUnrecognizedFlags);
        Assert.Equal(0, writes);
        Assert.Equal("stale-mode", state["network_mode"]!.GetValue<string>());
    }

    [Fact]
    public void RadioChoiceUpdatesAllFlagsOnceAndFalseEventsNeverApplyAnotherMode()
    {
        var schema = Schema();
        var state = (JsonObject)schema.Defaults.DeepClone();
        var writes = 0;
        var vm = new NetworkModeViewModel((JsonObject)schema.Options["network_modes"]!, state, mode =>
        {
            writes++;
            ConfigurationStateEditing.SetValue(state, schema, "network_mode", JsonValue.Create(mode));
        });
        vm.IsPublic = false;
        Assert.Equal(0, writes);
        vm.IsPrivate = true;
        Assert.Equal(1, writes);
        Assert.All(NetworkModeViewModel.FlagKeys, key => Assert.Equal("false", state[key]!.GetValue<string>()));
        vm.IsPrivate = true;
        Assert.Equal(1, writes);
        vm.IsHybrid = true;
        Assert.Equal(2, writes);
        Assert.Equal("true", vm.AllowPublicAccess);
        Assert.Equal("true", vm.PublicGenAIAccess);
        Assert.Equal("false", vm.PublicPerimeterAccess);
        Assert.Equal("", state["projectPrefix"]!.GetValue<string>());
        Assert.Equal("", state["projectSuffix"]!.GetValue<string>());
    }

    [Fact]
    public void MappingComesFromApiNotHardcodedFrontendLogic()
    {
        var schema = Schema();
        ((JsonObject)schema.Options["network_modes"]!)["hybrid"] = Flags(true, false, true);
        var vm = new NetworkModeViewModel((JsonObject)schema.Options["network_modes"]!, Flags(true, false, true), _ => { });
        Assert.True(vm.IsHybrid);
        Assert.Equal("false", vm.PublicGenAIAccess);
        Assert.Equal("true", vm.PublicPerimeterAccess);
    }

    [Fact]
    public void UnmatchedOrMissingFlagsAreNotSilentlyConverted()
    {
        var schema = Schema();
        foreach (var state in new[] { Flags(false, true, false), new JsonObject() })
        {
            var before = state.ToJsonString();
            var vm = new NetworkModeViewModel((JsonObject)schema.Options["network_modes"]!, state,
                _ => throw new Exception("Must not write loaded state"));
            Assert.True(vm.HasUnrecognizedFlags);
            Assert.False(vm.IsPrivate || vm.IsHybrid || vm.IsPublic);
            Assert.Equal(before, state.ToJsonString());
        }
    }

    [Fact]
    public void SynchronizingAReplacedConfigurationUpdatesRadioAndResultLabelsWithoutWrites()
    {
        var schema = Schema();
        var vm = new NetworkModeViewModel((JsonObject)schema.Options["network_modes"]!, schema.Defaults,
            _ => throw new Exception("Must not write while loading"));
        vm.Synchronize(Flags(false, false, false));
        Assert.True(vm.IsPrivate);
        Assert.Equal("false", vm.PublicPerimeterAccess);
    }

    [Fact]
    public void NetworkModeIsFirstAndIndependentFlagEditorsAreOmitted()
    {
        var schema = Schema();
        var steps = WizardFieldCatalog.Build(schema, schema.Defaults, (_, _) => { });
        var cards = WizardFieldSearch.EditableCards(steps[0].Fields).ToArray();
        Assert.Equal("network_mode", cards[0].Key);
        Assert.True(cards[0].IsNetworkMode);
        Assert.False(cards[0].IsChoice || cards[0].IsText);
        Assert.DoesNotContain(cards, field => field.IsNetworkFlag);
        Assert.Equal(3, steps[0].Fields.Count(field => field.IsNetworkFlag));
    }

    [Theory]
    [InlineData("ADMIN_LOCATION", "Scale set & region", "admin_location")]
    [InlineData("tenant id", "Security & governance", "tenantId")]
    [InlineData("project prefix", "Project", "projectPrefix")]
    [InlineData("enablePublicAccessWithPerimeter", "Start & destination", "network_mode")]
    [InlineData("Enable Public Gen AI Access", "Start & destination", "network_mode")]
    public void GlobalSearchFindsLabelsKeysAndNetworkFlagsAcrossSections(string query, string section, string key)
    {
        var schema = Schema();
        var steps = WizardFieldCatalog.Build(schema, schema.Defaults, (_, _) => { });
        var match = Assert.Single(WizardFieldSearch.Find(steps, query));
        Assert.Equal(section, match.SectionTitle);
        Assert.Equal(key, match.Field.Key);
    }

    [Fact]
    public void GlobalSearchIncludesBothSkuEnvironmentsWithoutDuplicatingSharedFields()
    {
        var schema = Schema();
        var steps = WizardFieldCatalog.Build(schema, schema.Defaults, (_, _) => { });
        var matches = WizardFieldSearch.Find(steps, "Storage");
        Assert.Equal(2, matches.Count);
        Assert.All(matches, match => Assert.Equal("SKUs", match.SectionTitle));
        Assert.Contains(matches, match => match.Field.Key.EndsWith("Dev"));
        Assert.Contains(matches, match => match.Field.Key.EndsWith("StageProd"));
        Assert.Empty(WizardFieldSearch.Find(steps, "   "));
        Assert.Empty(WizardFieldSearch.Find(steps, "not-a-real-field"));
    }

    [Fact]
    public void SearchReusesLiveFieldsSoEditsAppearWhenReturningToTheirSection()
    {
        var schema = Schema();
        var state = (JsonObject)schema.Defaults.DeepClone();
        var steps = WizardFieldCatalog.Build(schema, state,
            (key, value) => ConfigurationStateEditing.SetValue(state, schema, key, value));
        var match = Assert.Single(WizardFieldSearch.Find(steps, "admin_location"));
        match.Field.SelectedOption = "eastus2";
        Assert.Same(match.Field, steps[1].Fields.Single());
        Assert.Equal("eastus2", state["admin_location"]!.GetValue<string>());
    }
}

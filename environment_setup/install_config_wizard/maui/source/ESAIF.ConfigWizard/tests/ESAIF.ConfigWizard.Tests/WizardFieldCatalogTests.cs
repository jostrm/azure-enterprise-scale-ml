using System.Text.Json.Nodes;
using ESAIF.DomainLayer.Configuration;
using ESAIF.ConfigWizard.Services;

namespace ESAIF.ConfigWizard.Tests;

public sealed class WizardFieldCatalogTests
{
    [Theory]
    [InlineData(false)]
    [InlineData(true)]
    public void FoundryAndBastionFieldsUseRequestedSectionsWithoutChangingState(bool schemaPlacesThemInScaleSet)
    {
        var state = new JsonObject
        {
            ["enableAFoundryCaphost"] = "true", ["addAIFoundryHub"] = "false",
            ["enableAIFoundryHub"] = "false", ["addBastionHost"] = "false",
            ["common_bastion_subnet_name"] = "AzureBastionSubnet",
            ["common_bastion_subnet_cidr"] = "10.0.0.0/26", ["dev_sub_id"] = "subscription"
        };
        var before = state.ToJsonString();
        var schema = new FactorySchema
        {
            Defaults = (JsonObject)state.DeepClone(),
            Sections = new SchemaSections
            {
                ScaleSetVariables = schemaPlacesThemInScaleSet ? state.Select(pair => pair.Key).ToArray() : []
            }
        };
        var steps = WizardFieldCatalog.Build(schema, state, (_, _) => throw new Exception("No writes while building UI"));
        var advanced = steps.Single(step => step.Title == "Advanced");
        var capabilityHost = Assert.Single(advanced.Fields, field => field.Key == "enableAFoundryCaphost");
        Assert.Equal("enableAFoundryCaphost", capabilityHost.Key);
        Assert.Equal("Enable AI Foundry Capability host", capabilityHost.Label);
        Assert.True(capabilityHost.IsBoolean);
        Assert.DoesNotContain(steps.SelectMany(step => step.Fields), field => field.Key == "addAIFoundryHub");
        Assert.Empty(WizardFieldSearch.Find(steps, "addAIFoundryHub"));
        Assert.Contains(steps.SelectMany(step => step.Fields), field => field.Key == "enableAIFoundryHub");
        var scale = steps.Single(step => step.Title == "Platform networking");
        var subnet = scale.Fields.Single(field => field.Key == "common_bastion_subnet_name");
        Assert.Equal("addBastionHost", scale.Fields[scale.Fields.IndexOf(subnet) + 1].Key);
        Assert.Equal("Platform networking", Assert.Single(WizardFieldSearch.Find(steps, "addBastionHost")).SectionTitle);
        Assert.Equal(before, state.ToJsonString());
        Assert.Equal("false", state["addAIFoundryHub"]!.GetValue<string>());
    }

    [Theory]
    [InlineData("swedencentral")]
    [InlineData("SwedenCentral")]
    [InlineData("future-region")]
    [InlineData("")]
    public void AdminLocationUsesApiRegionsWithoutChangingLoadedValuesOrNaming(string location)
    {
        var state = new JsonObject
        {
            ["admin_location"] = location, ["admin_locationSuffix"] = "custom",
            ["projectPrefix"] = "", ["projectSuffix"] = ""
        };
        var schema = new FactorySchema
        {
            Defaults = (JsonObject)state.DeepClone(),
            Sections = new SchemaSections { ScaleSetVariables = ["admin_location", "admin_locationSuffix"] },
            Options = new JsonObject { ["azure_regions"] = new JsonArray("eastus2", "swedencentral", "westeurope") }
        };
        var writes = new List<string>();
        var fields = WizardFieldCatalog.Build(schema, state, (key, value) =>
        {
            writes.Add(key);
            state[key] = value;
        }).SelectMany(step => step.Fields).ToDictionary(field => field.Key);
        var region = fields["admin_location"];

        Assert.True(region.IsChoice);
        Assert.False(region.IsText);
        Assert.Contains("eastus2", region.Options);
        Assert.Contains("swedencentral", region.Options);
        Assert.Contains("westeurope", region.Options);
        Assert.Equal(location, region.SelectedOption);
        region.SelectedOption = null;
        Assert.Equal(location, region.Value);
        Assert.Empty(writes);
        Assert.True(fields["admin_locationSuffix"].IsText);

        region.SelectedOption = "eastus2";
        Assert.Equal("eastus2", state["admin_location"]!.GetValue<string>());
        Assert.Equal(["admin_location"], writes);
        Assert.Equal("custom", state["admin_locationSuffix"]!.GetValue<string>());
        Assert.Equal("", state["projectPrefix"]!.GetValue<string>());
        Assert.Equal("", state["projectSuffix"]!.GetValue<string>());
    }

    [Fact]
    public void RegionChoicesAreAlphabeticalIncludingTheLoadedCustomValue()
    {
        var state = new JsonObject { ["admin_location"] = "middle-custom" };
        var schema = new FactorySchema
        {
            Defaults = state,
            Options = new JsonObject { ["azure_regions"] = new JsonArray("westeurope", "eastus2", "swedencentral", "eastus2") }
        };
        var field = Assert.Single(WizardFieldCatalog.Build(schema, state, (_, _) => { }).SelectMany(step => step.Fields));
        Assert.Equal(["eastus2", "middle-custom", "swedencentral", "westeurope"], field.Options);
        field.SynchronizeValue(JsonValue.Create("a-custom"));
        Assert.Equal(["a-custom", "eastus2", "swedencentral", "westeurope"], field.Options);
    }

    [Fact]
    public void OlderApiWithoutRegionOptionsKeepsLocationEditable()
    {
        var state = new JsonObject { ["admin_location"] = "swedencentral" };
        var field = Assert.Single(WizardFieldCatalog.Build(
            new FactorySchema { Defaults = state }, state, (_, _) => { }).SelectMany(step => step.Fields));
        Assert.True(field.IsText);
        Assert.Equal("swedencentral", field.Value);
    }

    [Fact]
    public void FactoryDashboardLink_IsEditableOnTheStartStep()
    {
        var defaults = new JsonObject { ["aifactory-dash-01"] = "" };
        var steps = WizardFieldCatalog.Build(new FactorySchema { Defaults = defaults }, defaults, (_, _) => { });
        var field = Assert.Single(steps[0].Fields);
        Assert.Equal("aifactory-dash-01", field.Key);
        Assert.Equal("AI Factory dashboard URL", field.Label);
    }

    [Fact]
    public void Build_MapsSchemaIntoNineCohesiveStepsWithoutLosingFields()
    {
        var defaults = new JsonObject
        {
            ["orchestrator"] = "ado",
            ["network_mode"] = "public",
            ["_save_folder"] = "",
            ["dev_sub_id"] = "<todo>",
            ["centralDnsZoneByPolicyInHub"] = "false",
            ["cmk"] = "false",
            ["project_number_000"] = "001",
            ["enableAIFoundry"] = "true",
            ["skuStorageAccountDev"] = "Standard_LRS",
            ["skuStorageAccountStageProd"] = "Standard_GRS",
            ["admin_semanticSearchTier"] = "free",
            ["custom_setting"] = "value",
            ["_internal_only"] = "hidden"
        };
        var schema = new FactorySchema
        {
            Defaults = defaults,
            Orchestrators = ["ado", "gha"],
            Sections = new SchemaSections
            {
                ScaleSetVariables = ["dev_sub_id"]
            },
            Options = new JsonObject
            {
                ["network_modes"] = new JsonObject
                {
                    ["private"] = new JsonObject(),
                    ["hybrid"] = new JsonObject(),
                    ["public"] = new JsonObject()
                }
            }
        };

        var steps = WizardFieldCatalog.Build(schema, defaults, (_, _) => { });

        Assert.Equal(9, steps.Count);
        Assert.True(steps[^1].IsReview);
        Assert.Contains(steps[0].Fields, field => field.Key == "orchestrator");
        Assert.Contains(steps[1].Fields, field => field.Key == "dev_sub_id");
        Assert.Contains(steps[0].Fields, field => field.Key == "centralDnsZoneByPolicyInHub");
        Assert.Contains(steps[3].Fields, field => field.Key == "cmk");
        Assert.Contains(steps[4].Fields, field => field.Key == "project_number_000");
        Assert.Equal("project_number_000", steps[4].Fields[0].Key);
        Assert.Contains(steps[5].Fields, field => field.Key == "enableAIFoundry");
        Assert.True(steps[6].IsSkuStep);
        Assert.Contains(steps[6].DevSkuFields, field => field.Key == "skuStorageAccountDev");
        Assert.DoesNotContain(
            steps[6].DevSkuFields,
            field => field.Key == "skuStorageAccountStageProd");
        Assert.Contains(
            steps[6].StageProdSkuFields,
            field => field.Key == "skuStorageAccountStageProd");
        Assert.DoesNotContain(
            steps[6].StageProdSkuFields,
            field => field.Key == "skuStorageAccountDev");
        Assert.Contains(
            steps[6].DevSkuFields,
            field => field.Key == "admin_semanticSearchTier");
        Assert.Contains(
            steps[6].StageProdSkuFields,
            field => field.Key == "admin_semanticSearchTier");
        Assert.Contains(steps[7].Fields, field => field.Key == "custom_setting");
        Assert.DoesNotContain(
            steps.SelectMany(step => step.Fields),
            field => field.Key == "_internal_only");
        Assert.DoesNotContain(
            steps.SelectMany(step => step.Fields),
            field => field.Key == "_save_folder");
        Assert.Equal(
            defaults.Count - 2,
            steps.Sum(step => step.FieldCount));
    }

    [Fact]
    public void Build_UsesSchemaOptionsForOrchestratorAndNetworkMode()
    {
        var defaults = new JsonObject
        {
            ["orchestrator"] = "ado",
            ["network_mode"] = "public"
        };
        var schema = new FactorySchema
        {
            Defaults = defaults,
            Orchestrators = ["ado", "gha"],
            Options = new JsonObject
            {
                ["network_modes"] = new JsonObject
                {
                    ["private"] = new JsonObject(),
                    ["public"] = new JsonObject()
                }
            }
        };

        var fields = WizardFieldCatalog
            .Build(schema, defaults, (_, _) => { })[0]
            .Fields;

        Assert.Equal(
            ["ado", "gha"],
            fields.Single(field => field.Key == "orchestrator").Options);
        Assert.Equal(
            ["private", "public"],
            fields.Single(field => field.Key == "network_mode").Options);
    }

    [Fact]
    public void Build_Project017TierIsVisibleOnBothSkuTabsAndAgentsRemainEditable()
    {
        var state = new JsonObject
        {
            ["admin_aiSearchTier"] = "standard",
            ["adminVMBuildAgentName"] = "vm-test",
            ["adminVMBuildAgentPool"] = "aifactory-build-agent-1",
            ["enableAISearch"] = "true",
            ["customAISearchSetting"] = "custom"
        };
        var schema = new FactorySchema
        {
            Defaults = (JsonObject) state.DeepClone(),
            Options = new JsonObject
            {
                ["ai_search_skus"] = new JsonArray("free", "basic", "standard")
            }
        };

        var steps = WizardFieldCatalog.Build(schema, state, (_, _) => { });
        var skuStep = steps.Single(step => step.IsSkuStep);
        var tier = Assert.Single(skuStep.Fields);

        Assert.Equal("admin_aiSearchTier", tier.Key);
        Assert.Equal("AI Search tier", tier.Label);
        Assert.Contains(tier, skuStep.DevSkuFields);
        Assert.Contains(tier, skuStep.StageProdSkuFields);
        Assert.Equal("standard", tier.SelectedOption);
        Assert.Contains(tier.SelectedOption, tier.Options);
        var fields = steps.SelectMany(step => step.Fields).ToDictionary(field => field.Key);
        Assert.True(fields["adminVMBuildAgentName"].IsText);
        Assert.Equal("vm-test", fields["adminVMBuildAgentName"].Value);
        Assert.Equal("aifactory-build-agent-1", fields["adminVMBuildAgentPool"].Value);
        Assert.True(fields["enableAISearch"].IsBoolean);
        Assert.True(fields["customAISearchSetting"].IsText);
    }

    [Fact]
    public void Build_FieldMutationWritesToSharedState()
    {
        var state = new JsonObject
        {
            ["project_number_000"] = "001"
        };
        var schema = new FactorySchema
        {
            Defaults = (JsonObject) state.DeepClone()
        };
        var fields = WizardFieldCatalog
            .Build(schema, state, (key, value) => state[key] = value)
            .SelectMany(step => step.Fields);

        fields.Single().Value = "042";

        Assert.Equal("042", state["project_number_000"]?.GetValue<string>());
    }
}

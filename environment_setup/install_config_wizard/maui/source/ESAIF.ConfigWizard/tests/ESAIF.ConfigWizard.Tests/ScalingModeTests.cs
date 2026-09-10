using System.Text.Json.Nodes;
using ESAIF.ConfigWizard.Services;
using ESAIF.ConfigWizard.ViewModels;
using ESAIF.DomainLayer.Configuration;

namespace ESAIF.ConfigWizard.Tests;

public sealed class ScalingModeTests
{
    [Fact]
    public void ScalingModeIsFirstStartFieldAndUsesOnlySpecializedRadioEditor()
    {
        var schema = Schema();
        var state = (JsonObject)schema.Defaults.DeepClone();
        var steps = WizardFieldCatalog.Build(schema, state, (_, _) => { });
        var field = steps[0].Fields[0];
        Assert.Equal("scaling-mode", field.Key);
        Assert.True(field.IsScalingMode);
        Assert.False(field.IsBoolean);
        Assert.False(field.IsChoice);
        Assert.False(field.IsText);
        Assert.True(field.ScalingMode!.IsShared);
        Assert.Equal("Scaling mode", field.Label);
        Assert.Equal(field, Assert.Single(WizardFieldSearch.Find(steps, "Own subscriptions")).Field);
    }

    [Fact]
    public void ModeChangeAppliesCompleteApiProfileAtomicallyToUntouchedDefaults()
    {
        var schema = Schema();
        var state = (JsonObject)schema.Defaults.DeepClone();
        ConfigurationStateEditing.SetValue(state, schema, "scaling-mode", JsonValue.Create("own-subscriptions"));
        Assert.Equal("172.16.XX.0/20", state["common_vnet_cidr"]!.ToString());
        Assert.Equal("0", state["dev_cidr_range"]!.ToString());
        Assert.Equal("16", state["test_cidr_range"]!.ToString());
        Assert.Equal("32", state["prod_cidr_range"]!.ToString());
        Assert.True(ScalingModeConfiguration.MatchesProfile(state, schema, ScalingModeConfiguration.Own));
        ConfigurationStateEditing.SetValue(state, schema, "scaling-mode", JsonValue.Create("shared-subscriptions"));
        Assert.True(ScalingModeConfiguration.MatchesProfile(state, schema, ScalingModeConfiguration.Shared));
        Assert.Equal("172.16.XX.0/18", state["common_vnet_cidr"]!.ToString());
        Assert.Equal("untouched", state["unrelated"]!.ToString());
    }

    [Theory]
    [InlineData("common_vnet_cidr", "10.16.0.0/16")]
    [InlineData("test_cidr_range", "55")]
    [InlineData("common_subnet_cidr", "172.16.XX.0/25")]
    [InlineData("common_bastion_subnet_cidr", "")]
    public void CustomOrExplicitEmptyAddressingIsRetainedOnRadioSelection(string key, string value)
    {
        var schema = Schema();
        var state = (JsonObject)schema.Defaults.DeepClone();
        state[key] = value;
        var before = state.ToJsonString();
        ScalingModeConfiguration.SetMode(state, schema, ScalingModeConfiguration.Own);
        state["scaling-mode"] = ScalingModeConfiguration.Shared;
        Assert.Equal(before, state.ToJsonString());
    }

    [Fact]
    public void ExplicitDefaultApplicationReplacesOnlyNetworkFieldsNotSubscriptionsOrScope()
    {
        var schema = Schema();
        var state = (JsonObject)schema.Defaults.DeepClone();
        state["scaling-mode"] = ScalingModeConfiguration.Own;
        state["common_vnet_cidr"] = "10.0.0.0/8";
        state["dev_sub_id"] = "existing-subscription";
        state["admin_aifactorySuffixRG"] = "-007";
        ScalingModeConfiguration.ApplyDefaults(state, schema);
        Assert.True(ScalingModeConfiguration.MatchesProfile(state, schema, ScalingModeConfiguration.Own));
        Assert.Equal("existing-subscription", state["dev_sub_id"]!.ToString());
        Assert.Equal("-007", state["admin_aifactorySuffixRG"]!.ToString());
    }

    [Fact]
    public void ApiDeclaredLegacyProfileCanSwitchButPartialLegacyMatchesCannot()
    {
        var schema = Schema();
        var legacy = (JsonObject)ScalingModeConfiguration.Defaults(schema, ScalingModeConfiguration.Shared).DeepClone();
        legacy["common_vnet_cidr"] = "172.16.0.0/16";
        legacy["dev_cidr_range"] = "61"; legacy["test_cidr_range"] = "62"; legacy["prod_cidr_range"] = "63";
        schema.Options["scaling_network_profiles"] = new JsonArray(
            legacy.DeepClone(),
            ScalingModeConfiguration.Defaults(schema, ScalingModeConfiguration.Own).DeepClone(),
            ScalingModeConfiguration.Defaults(schema, ScalingModeConfiguration.Shared).DeepClone());
        var state = (JsonObject)legacy.DeepClone();
        Assert.True(ScalingModeConfiguration.MatchesKnownProfile(state, schema));
        ScalingModeConfiguration.SetMode(state, schema, ScalingModeConfiguration.Own);
        Assert.True(ScalingModeConfiguration.MatchesProfile(state, schema, ScalingModeConfiguration.Own));
        state = (JsonObject)legacy.DeepClone();
        state["prod_cidr_range"] = "60";
        ScalingModeConfiguration.SetMode(state, schema, ScalingModeConfiguration.Own);
        Assert.Equal("172.16.0.0/16", state["common_vnet_cidr"]!.ToString());
        Assert.Equal("60", state["prod_cidr_range"]!.ToString());
    }

    [Fact]
    public void SameModeAndSynchronizationNeverResetExistingAddressing()
    {
        var schema = Schema();
        var state = (JsonObject)schema.Defaults.DeepClone();
        state.Remove("scaling-mode");
        state["common_vnet_cidr"] = "10.0.0.0/16";
        var before = state.ToJsonString();
        var calls = 0;
        var vm = new ScalingModeViewModel(schema, state, _ => calls++, () => { });
        vm.IsShared = true;
        vm.Synchronize(state);
        Assert.Equal(0, calls);
        Assert.Equal(before, state.ToJsonString());
        Assert.True(vm.IsShared);
        Assert.Contains("retained", vm.PreservationMessage);
    }

    [Fact]
    public void UnsupportedModeAndMissingProfileFailExplicitlyWithoutPartialChanges()
    {
        var schema = Schema();
        var state = (JsonObject)schema.Defaults.DeepClone();
        var before = state.ToJsonString();
        Assert.Throws<ArgumentException>(() => ScalingModeConfiguration.SetMode(state, schema, "invalid"));
        Assert.Equal(before, state.ToJsonString());
        Assert.Throws<InvalidOperationException>(() => ScalingModeConfiguration.ApplyDefaults(state, new FactorySchema()));
        Assert.Equal(before, state.ToJsonString());
    }

    [Fact]
    public void EditorUsesApiGuidanceAndExistingFieldObjectsStaySynchronized()
    {
        var schema = Schema();
        var state = (JsonObject)schema.Defaults.DeepClone();
        IReadOnlyList<WizardStepViewModel> steps = [];
        void Synchronize()
        {
            foreach (var field in steps.SelectMany(step => step.Fields))
            {
                field.SynchronizeValue(state[field.Key]);
                field.ScalingMode?.Synchronize(state);
            }
        }
        steps = WizardFieldCatalog.Build(schema, state,
            (key, value) => { ConfigurationStateEditing.SetValue(state, schema, key, value); Synchronize(); },
            () => { ScalingModeConfiguration.ApplyDefaults(state, schema); Synchronize(); });
        var vm = steps[0].Fields[0].ScalingMode!;
        vm.IsOwn = true;
        Assert.True(vm.IsOwn);
        Assert.False(vm.IsShared);
        Assert.Equal("172.16.XX.0/20", vm.CurrentCidr);
        Assert.Equal("Own sizing from Python", vm.Description);
        Assert.Contains("Capacity unavailable", vm.CapacityDescription);
        Assert.Equal("172.16.XX.0/20", steps.SelectMany(step => step.Fields).Single(field => field.Key == "common_vnet_cidr").Value);
        state["common_vnet_cidr"] = "custom";
        vm.ApplyDefaults();
        Assert.Equal("172.16.XX.0/20", state["common_vnet_cidr"]!.ToString());
        vm.IsShared = true;
        Assert.Contains("Capacity unavailable", vm.CapacityDescription);
    }

    [Fact]
    public void FormatHelpUsesApiExamplesWithoutEditingState()
    {
        var schema = Schema();
        schema.Options["vnet_format_help"] = new JsonObject
        {
            ["examples"] = new JsonArray(
                new JsonObject { ["mode"] = "Shared", ["template"] = "172.16.XX.0/18", ["ranges"] = "0 / 64 / 128" },
                new JsonObject { ["mode"] = "Own", ["template"] = "172.16.XX.0/20", ["ranges"] = "0 / 16 / 32" }),
            ["notes"] = new JsonArray("API-provided support rules", "Second-octet placeholders are not yet supported.")
        };
        var state = (JsonObject)schema.Defaults.DeepClone();
        var before = state.ToJsonString();
        using var vm = new ScalingModeViewModel(schema, state,
            _ => throw new Exception("Help must not edit configuration"),
            () => throw new Exception("Help must not apply defaults"));
        Assert.Equal("Shared", vm.FormatExamples[0].Mode);
        Assert.Equal("172.16.XX.0/18", vm.FormatExamples[0].Template);
        Assert.Equal("0 / 64 / 128", vm.FormatExamples[0].Ranges);
        Assert.Equal("0 / 16 / 32", vm.FormatExamples[1].Ranges);
        Assert.Contains("API-provided support rules", vm.FormatNotes);
        Assert.Equal(before, state.ToJsonString());
    }

    [Fact]
    public void PlatformNetworkingStartsWithHelpAndAddressingFieldsWithoutDuplicates()
    {
        var schema = Schema();
        schema.Defaults["admin_location"] = "swedencentral";
        schema.Defaults["dev_sub_id"] = "subscription";
        schema.Defaults["version_major"] = "1";
        foreach (var key in WizardFieldCatalog.NetworkAddressFields)
            if (!schema.Defaults.ContainsKey(key)) schema.Defaults[key] = "keep";
        schema = new FactorySchema
        {
            Defaults = schema.Defaults, Options = schema.Options,
            Sections = new SchemaSections { ScaleSetVariables = schema.Defaults.Select(pair => pair.Key).ToArray() }
        };
        var state = (JsonObject)schema.Defaults.DeepClone();
        var before = state.ToJsonString();
        var writes = new List<string>();
        var steps = WizardFieldCatalog.Build(schema, state, (key, _) => writes.Add(key));
        var networking = steps[2];
        Assert.Equal("Platform networking", networking.Title);
        Assert.True(networking.HasNetworkFormatHelp);
        Assert.Same(steps[0].Fields.Single(field => field.IsScalingMode).ScalingMode, networking.NetworkFormatHelp);
        Assert.All(steps.Where(step => step != networking), step => Assert.False(step.HasNetworkFormatHelp));
        Assert.Equal(WizardFieldCatalog.NetworkAddressFields,
            networking.Fields.Take(WizardFieldCatalog.NetworkAddressFields.Count).Select(field => field.Key));
        Assert.DoesNotContain(steps[1].Fields, field => WizardFieldCatalog.NetworkAddressFields.Contains(field.Key));
        Assert.Contains(steps[1].Fields, field => field.Key == "admin_location");
        Assert.Contains(steps[1].Fields, field => field.Key == "dev_sub_id");
        var all = steps.SelectMany(step => step.Fields).ToArray();
        Assert.Equal(all.Length, all.Select(field => field.Key).Distinct().Count());
        Assert.Equal(before, state.ToJsonString());
        var match = Assert.Single(WizardFieldSearch.Find(steps, "test_cidr_range"));
        Assert.Equal("Platform networking", match.SectionTitle);
        Assert.Same(networking.Fields[2], match.Field);
        match.Field.Value = "80";
        Assert.Equal(["test_cidr_range"], writes);
    }

    private static FactorySchema Schema()
    {
        var common = new JsonObject
        {
            ["common_vnet_cidr"] = "172.16.XX.0/18",
            ["dev_cidr_range"] = "0", ["test_cidr_range"] = "64", ["prod_cidr_range"] = "128",
            ["common_subnet_cidr"] = "172.16.XX.0/26",
            ["common_subnet_scoring_cidr"] = "172.16.XX.64/26",
            ["common_pbi_subnet_cidr"] = "172.16.XX.128/26",
            ["common_bastion_subnet_cidr"] = "172.16.XX.192/26"
        };
        var own = (JsonObject)common.DeepClone();
        own["common_vnet_cidr"] = "172.16.XX.0/20";
        own["dev_cidr_range"] = "0"; own["test_cidr_range"] = "16"; own["prod_cidr_range"] = "32";
        var defaults = (JsonObject)common.DeepClone();
        defaults["scaling-mode"] = "shared-subscriptions";
        defaults["network_mode"] = "public";
        defaults["orchestrator"] = "ado";
        defaults["unrelated"] = "untouched";
        return new FactorySchema
        {
            Defaults = defaults,
            Options = new JsonObject
            {
                ["scaling_modes"] = new JsonObject
                {
                    [ScalingModeConfiguration.Shared] = new JsonObject
                    {
                        ["network_defaults"] = common, ["description"] = "Shared sizing from Python",
                        ["capacity_description"] = "Shared capacity from Python"
                    },
                    [ScalingModeConfiguration.Own] = new JsonObject
                    {
                        ["network_defaults"] = own, ["description"] = "Own sizing from Python",
                        ["capacity_description"] = "Own capacity from Python"
                    }
                }
            }
        };
    }
}

using System.Text.Json.Nodes;
using ESAIF.ConfigWizard.Services;
using ESAIF.ConfigWizard.ViewModels;
using ESAIF.DomainLayer.Configuration;

namespace ESAIF.ConfigWizard.Tests;

public sealed class HubTopologyTests
{
    private static JsonObject Flags(string value) => new()
    {
        ["allowPublicAccessWhenBehindVnet"] = value, ["enablePublicGenAIAccess"] = value,
        ["enablePublicAccessWithPerimeter"] = value
    };
    private static FactorySchema Schema => new()
    {
        Defaults = new JsonObject
        {
            ["network_mode"] = "public", [HubTopologyViewModel.DnsKey] = "false",
            [HubTopologyViewModel.OwnHubKey] = "false",
            [HubTopologyViewModel.StateKey] = "", ["orchestrator"] = "gha"
        },
        Options = new JsonObject
        {
            ["network_modes"] = new JsonObject { ["private"] = Flags("false"), ["public"] = Flags("true") }
        }
    };

    [Fact]
    public void TopologyImmediatelyFollowsNetworkModeAndReplacesBooleanEditor()
    {
        var schema = Schema;
        var cards = WizardFieldSearch.EditableCards(WizardFieldCatalog.Build(schema, schema.Defaults, (_, _) => { })[0].Fields).ToArray();
        Assert.Equal("network_mode", cards[0].Key);
        Assert.Equal(HubTopologyViewModel.DnsKey, cards[1].Key);
        Assert.True(cards[1].IsHubTopology);
        Assert.False(cards[1].IsBoolean || cards[1].IsText);
        Assert.DoesNotContain(cards, field => field.Key.StartsWith('_'));
        Assert.DoesNotContain(cards, field => field.Key == HubTopologyViewModel.OwnHubKey);
        var match = Assert.Single(WizardFieldSearch.Find(WizardFieldCatalog.Build(schema, schema.Defaults, (_, _) => { }), "Central DNS Zone By Policy In Hub"));
        Assert.Equal(HubTopologyViewModel.DnsKey, match.Field.Key);
        Assert.Equal(HubTopologyViewModel.DnsKey, Assert.Single(WizardFieldSearch.Find(
            WizardFieldCatalog.Build(schema, schema.Defaults, (_, _) => { }), "enableAIFactoryHub")).Field.Key);
    }

    [Fact]
    public void AllChoicesWriteDnsPolicyAndDistinctPersistentMetadata()
    {
        var schema = Schema;
        var state = Flags("true");
        state[HubTopologyViewModel.DnsKey] = "false";
        state[HubTopologyViewModel.OwnHubKey] = "true";
        var network = new NetworkModeViewModel((JsonObject)schema.Options["network_modes"]!, state, _ => { });
        var hub = new HubTopologyViewModel(state, network, choice =>
            ConfigurationStateEditing.SetValue(state, schema, HubTopologyViewModel.StateKey, JsonValue.Create(choice)));
        hub.IsStandalone = true;
        Assert.Equal("standalone", state[HubTopologyViewModel.StateKey]!.GetValue<string>());
        Assert.Equal("false", hub.DnsPolicy);
        Assert.Equal("false", state[HubTopologyViewModel.OwnHubKey]!.ToString());
        hub.IsOwnHub = true;
        Assert.Equal("own-hub", state[HubTopologyViewModel.StateKey]!.GetValue<string>());
        Assert.Equal("false", state[HubTopologyViewModel.DnsKey]!.GetValue<string>());
        Assert.Equal("true", state[HubTopologyViewModel.OwnHubKey]!.ToString());
        Assert.Equal("true", hub.OwnHubEnabled);
        Assert.Contains("VPN Gateway", hub.Guidance);
        Assert.Contains("Bastion", hub.Guidance);
        Assert.Contains("AVD", hub.Guidance);
        hub.IsExternalHub = true;
        Assert.Equal("external-hub", state[HubTopologyViewModel.StateKey]!.GetValue<string>());
        Assert.Equal("true", hub.DnsPolicy);
        Assert.Equal("true", state[HubTopologyViewModel.DnsKey]!.GetValue<string>());
        Assert.Equal("false", state[HubTopologyViewModel.OwnHubKey]!.ToString());
    }

    [Fact]
    public void PrivateModeDisablesStandaloneAndRequiresAnExplicitHubChoice()
    {
        var schema = Schema;
        var state = Flags("true");
        state[HubTopologyViewModel.DnsKey] = "false";
        state[HubTopologyViewModel.StateKey] = "standalone";
        var network = new NetworkModeViewModel((JsonObject)schema.Options["network_modes"]!, state, mode =>
            ConfigurationStateEditing.SetValue(state, schema, "network_mode", JsonValue.Create(mode)));
        var hub = new HubTopologyViewModel(state, network, choice =>
            ConfigurationStateEditing.SetValue(state, schema, HubTopologyViewModel.StateKey, JsonValue.Create(choice)));
        Assert.True(hub.IsStandalone);
        network.IsPrivate = true;
        Assert.False(hub.CanSelectStandalone);
        Assert.True(hub.IsStandalone);
        Assert.Contains("selected by the saved flags", hub.Guidance);
        Assert.True(hub.NeedsChoice);
        Assert.Throws<InvalidOperationException>(() => ConfigurationStateEditing.ValidateTopology(state, schema));
        Assert.Throws<InvalidOperationException>(() => ConfigurationStateEditing.SetValue(state, schema, HubTopologyViewModel.StateKey, JsonValue.Create("standalone")));
        hub.IsOwnHub = true;
        ConfigurationStateEditing.ValidateTopology(state, schema);
        Assert.True(hub.IsOwnHub);
    }

    [Fact]
    public void FalseDnsWithoutLegacyMetadataSelectsStandaloneEvenInPrivateModeWithoutRewritingFlags()
    {
        var schema = Schema;
        var state = Flags("false");
        state[HubTopologyViewModel.DnsKey] = "false";
        var network = new NetworkModeViewModel((JsonObject)schema.Options["network_modes"]!, state, _ => { });
        var hub = new HubTopologyViewModel(state, network, _ => throw new Exception("No writes on load"));
        Assert.True(hub.IsStandalone);
        Assert.True(hub.NeedsChoice);
        Assert.False(hub.IsOwnHub);
        state[HubTopologyViewModel.DnsKey] = "true";
        hub.Synchronize(state);
        Assert.True(hub.IsExternalHub);
    }

    [Fact]
    public void SessionSynchronizationCannotReenterHubSelection()
    {
        var schema = Schema;
        var state = Flags("true");
        state[HubTopologyViewModel.DnsKey] = "false";
        state[HubTopologyViewModel.OwnHubKey] = "true";
        var network = new NetworkModeViewModel((JsonObject)schema.Options["network_modes"]!, state, _ => { });
        HubTopologyViewModel? hub = null;
        var writes = 0;
        hub = new HubTopologyViewModel(state, network, choice =>
        {
            if (++writes > 1)
            {
                throw new InvalidOperationException("Selection reentered from binding notification.");
            }
            ConfigurationStateEditing.SetValue(state, schema, HubTopologyViewModel.StateKey, JsonValue.Create(choice));
            // WizardSession synchronously notifies the network card before the hub card.
            network.Synchronize(state);
            hub!.Synchronize(state);
        });
        hub.PropertyChanged += (_, e) =>
        {
            if (e.PropertyName == nameof(HubTopologyViewModel.IsStandalone))
            {
                hub.IsStandalone = true;
            }
        };
        hub.IsStandalone = true;
        Assert.Equal(1, writes);
        Assert.True(hub.IsStandalone);
    }

    [Fact]
    public void SessionSynchronizationCannotReenterNetworkSelection()
    {
        var schema = Schema;
        var state = Flags("true");
        NetworkModeViewModel? network = null;
        var writes = 0;
        network = new NetworkModeViewModel((JsonObject)schema.Options["network_modes"]!, state, mode =>
        {
            if (++writes > 1)
            {
                throw new InvalidOperationException("Selection reentered from binding notification.");
            }
            ConfigurationStateEditing.SetValue(state, schema, "network_mode", JsonValue.Create(mode));
            network!.Synchronize(state);
        });
        network.PropertyChanged += (_, e) =>
        {
            if (e.PropertyName == nameof(NetworkModeViewModel.IsPublic))
            {
                network.IsPublic = true;
            }
        };
        network.IsPrivate = true;
        Assert.Equal(1, writes);
        Assert.True(network.IsPrivate);
    }

    [Fact]
    public void LoadedOrchestratorUsesFriendlyLabelWithoutChangingApiValue()
    {
        var writes = new List<string>();
        var field = new ConfigFieldViewModel("orchestrator", "CI/CD orchestrator", "", JsonValue.Create("ado"),
            JsonValue.Create("ado"), ["ado", "gha"], (_, value) => writes.Add(value!.ToString()));
        field.SynchronizeValue(JsonValue.Create("gha"));
        Assert.Equal("GitHub", field.SelectedDisplayOption);
        Assert.Equal("gha", field.Value);
        Assert.Empty(writes);
        field.SelectedDisplayOption = null;
        Assert.Equal("GitHub", field.SelectedDisplayOption);
        field.SelectedDisplayOption = "Azure DevOps";
        Assert.Equal("ado", Assert.Single(writes));
        Assert.Equal(["Azure DevOps", "GitHub"], field.DisplayOptions);
    }

    [Theory]
    [InlineData(false, false, "standalone")]
    [InlineData(false, true, "own-hub")]
    [InlineData(true, false, "external-hub")]
    [InlineData(true, true, "external-hub")]
    public void ExplicitFlagsSelectTopologyWithoutChangingLoadedValues(bool dns, bool own, string expected)
    {
        var state = Flags("true");
        state[HubTopologyViewModel.DnsKey] = dns;
        state[HubTopologyViewModel.OwnHubKey] = own;
        state[HubTopologyViewModel.StateKey] = "stale";
        var before = state.ToJsonString();
        var network = new NetworkModeViewModel((JsonObject)Schema.Options["network_modes"]!, state, _ => { });
        var hub = new HubTopologyViewModel(state, network, _ => throw new Exception("No writes on load"));
        Assert.Equal(expected, HubTopologyViewModel.ChoiceFromState(state));
        Assert.Equal(expected == "standalone", hub.IsStandalone);
        Assert.Equal(expected == "own-hub", hub.IsOwnHub);
        Assert.Equal(expected == "external-hub", hub.IsExternalHub);
        Assert.Equal(dns.ToString().ToLowerInvariant(), hub.DnsPolicy);
        Assert.Equal(own.ToString().ToLowerInvariant(), hub.OwnHubEnabled);
        Assert.Equal(before, state.ToJsonString());
    }

    [Fact]
    public void ExplicitOwnFalseOverridesStaleOwnHubMetadataAndMissingFlagRetainsLegacyOwnChoice()
    {
        var state = new JsonObject { [HubTopologyViewModel.DnsKey] = "false", [HubTopologyViewModel.StateKey] = "own-hub" };
        Assert.Equal("own-hub", HubTopologyViewModel.ChoiceFromState(state));
        state[HubTopologyViewModel.OwnHubKey] = "false";
        Assert.Equal("standalone", HubTopologyViewModel.ChoiceFromState(state));
        state[HubTopologyViewModel.StateKey] = "external-hub";
        Assert.Equal("standalone", HubTopologyViewModel.ChoiceFromState(state));
    }

    [Fact]
    public void SelectingTopologyUpdatesBothFlagsAndPreservesBooleanRepresentation()
    {
        var state = Flags("true");
        state[HubTopologyViewModel.DnsKey] = false;
        state[HubTopologyViewModel.OwnHubKey] = false;
        ConfigurationStateEditing.SetValue(state, Schema, HubTopologyViewModel.StateKey, JsonValue.Create("own-hub"));
        Assert.False(state[HubTopologyViewModel.DnsKey]!.GetValue<bool>());
        Assert.True(state[HubTopologyViewModel.OwnHubKey]!.GetValue<bool>());
        ConfigurationStateEditing.SetValue(state, Schema, HubTopologyViewModel.StateKey, JsonValue.Create("external-hub"));
        Assert.True(state[HubTopologyViewModel.DnsKey]!.GetValue<bool>());
        Assert.False(state[HubTopologyViewModel.OwnHubKey]!.GetValue<bool>());
    }

    [Fact]
    public void DirectFlagEditsRefreshDerivedMetadataAndValidationIgnoresStaleMetadata()
    {
        var state = Flags("false");
        state[HubTopologyViewModel.DnsKey] = "false";
        state[HubTopologyViewModel.OwnHubKey] = "false";
        state[HubTopologyViewModel.StateKey] = "own-hub";
        Assert.Throws<InvalidOperationException>(() => ConfigurationStateEditing.ValidateTopology(state, Schema));
        ConfigurationStateEditing.SetValue(state, Schema, HubTopologyViewModel.OwnHubKey, JsonValue.Create("true"));
        Assert.Equal("own-hub", state[HubTopologyViewModel.StateKey]!.ToString());
        ConfigurationStateEditing.ValidateTopology(state, Schema);
        state[HubTopologyViewModel.OwnHubKey] = "";
        Assert.Throws<InvalidOperationException>(() => ConfigurationStateEditing.ValidateTopology(state, Schema));
    }
}

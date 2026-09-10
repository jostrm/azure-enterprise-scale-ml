using System.Text.Json.Nodes;
using ESAIF.ConfigWizard.Services;
using ESAIF.ConfigWizard.ViewModels;
using ESAIF.DomainLayer.Configuration;

namespace ESAIF.ConfigWizard.Tests;

public sealed class RunnerConfigurationTests
{
    private static JsonObject State(string route, string hosted = "true") => new()
    {
        ["orchestrator"] = route, ["useSelfHostedBuildAgent"] = hosted,
        ["selfHostedRunnerLabel"] = "runner-label", ["adminVMBuildAgentName"] = "vm-test",
        ["adminVMBuildAgentPool"] = "custom-pool", ["disable_whitelisting_for_build_agents"] = "true"
    };

    private static IReadOnlyList<WizardStepViewModel> Build(JsonObject state) =>
        WizardFieldCatalog.Build(new FactorySchema { Defaults = (JsonObject)state.DeepClone() },
            state, (key, value) => state[key] = value);

    [Theory]
    [InlineData("ado")]
    [InlineData("gha")]
    public void RunnerCardFollowsOrchestratorAndLoadsRouteSpecificFields(string route)
    {
        var state = State(route);
        var steps = Build(state);
        var cards = WizardFieldSearch.EditableCards(steps[0].Fields).ToArray();
        var orchestratorIndex = Array.FindIndex(cards, field => field.Key == "orchestrator");
        var runner = cards[orchestratorIndex + 1].RunnerConfiguration!;
        Assert.NotNull(runner);
        Assert.True(runner.IsSelfHosted);
        Assert.False(runner.IsHosted);
        Assert.Equal("vm-test", runner.SavedAgentName);
        Assert.Equal("true", runner.FlagValue);
        var expected = route == "gha" ? new[] { "selfHostedRunnerLabel", "disable_whitelisting_for_build_agents" } :
            new[] { "adminVMBuildAgentName", "adminVMBuildAgentPool", "disable_whitelisting_for_build_agents" };
        Assert.Equal(expected, runner.Details.Select(field => field.Key));
        Assert.DoesNotContain(cards, field => field.IsRunnerDetail);
        var search = Assert.Single(WizardFieldSearch.Find(steps, route == "gha" ? "selfHostedRunnerLabel" : "adminVMBuildAgentName"));
        Assert.Same(runner, search.Field.RunnerConfiguration);
    }

    [Fact]
    public void ChangingHostingPreservesNamesAndUncheckingDoesNotWrite()
    {
        var state = State("ado");
        var cards = Build(state);
        var runner = cards[0].Fields.Single(field => field.IsRunnerConfiguration).RunnerConfiguration!;
        var name = runner.Details.Single(field => field.Key == "adminVMBuildAgentName");
        name.Value = "another-agent";
        runner.IsSelfHosted = false;
        Assert.Equal("true", state["useSelfHostedBuildAgent"]!.ToString());
        runner.IsHosted = true;
        Assert.Empty(runner.Details);
        Assert.Equal("false", state["useSelfHostedBuildAgent"]!.ToString());
        Assert.Equal("another-agent", state["adminVMBuildAgentName"]!.ToString());
        runner.IsSelfHosted = true;
        Assert.Contains(name, runner.Details);
        Assert.Equal("another-agent", name.Value);
    }

    [Fact]
    public void LoadedFalseIsHostedEvenWhenAnAgentNameExists()
    {
        var state = State("ado", "false");
        var runner = Build(state)[0].Fields.Single(field => field.IsRunnerConfiguration).RunnerConfiguration!;
        Assert.True(runner.IsHosted);
        Assert.False(runner.IsSelfHosted);
        Assert.Empty(runner.Details);
        Assert.Equal("vm-test", runner.SavedAgentName);
    }

    [Fact]
    public void GitHubDoesNotInventVmNameAndRouteChangesRefreshLabels()
    {
        var state = State("gha");
        state["adminVMBuildAgentName"] = "";
        var runner = Build(state)[0].Fields.Single(field => field.IsRunnerConfiguration).RunnerConfiguration!;
        Assert.Contains("not specified", runner.VmNameReference);
        Assert.Contains("GitHub", runner.HostedLabel);
        state["orchestrator"] = "ado";
        runner.Synchronize(state);
        Assert.Equal("Microsoft-hosted build agent", runner.HostedLabel);
        Assert.False(runner.ShowVmNameReference);
        Assert.Contains(runner.Details, field => field.Key == "adminVMBuildAgentPool");
    }
}

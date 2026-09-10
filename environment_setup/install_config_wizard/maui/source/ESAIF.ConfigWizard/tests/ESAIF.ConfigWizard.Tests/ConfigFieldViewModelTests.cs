using System.Text.Json.Nodes;
using ESAIF.ConfigWizard.ViewModels;

namespace ESAIF.ConfigWizard.Tests;

public sealed class ConfigFieldViewModelTests
{
    [Fact]
    public void BooleanValue_PreservesStringRepresentationUsedByPythonState()
    {
        string? updatedKey = null;
        JsonNode? updatedValue = null;
        var field = new ConfigFieldViewModel(
            "enableAIFoundry",
            "Enable AI Foundry",
            "API field",
            JsonValue.Create("false"),
            JsonValue.Create("false"),
            [],
            (key, value) =>
            {
                updatedKey = key;
                updatedValue = value;
            });

        field.BooleanValue = true;

        Assert.True(field.IsBoolean);
        Assert.False(field.IsText);
        Assert.Equal("true", field.Value);
        Assert.Equal("enableAIFoundry", updatedKey);
        Assert.Equal("true", updatedValue?.GetValue<string>());
        Assert.True(field.IsChanged);
    }

    [Fact]
    public void ChoiceField_UpdatesSelectedValue()
    {
        JsonNode? updatedValue = null;
        var field = new ConfigFieldViewModel(
            "orchestrator",
            "CI/CD orchestrator",
            "API field",
            JsonValue.Create("ado"),
            JsonValue.Create("ado"),
            ["ado", "gha"],
            (_, value) => updatedValue = value);

        field.SelectedOption = "gha";

        Assert.True(field.IsChoice);
        Assert.Equal("gha", updatedValue?.GetValue<string>());
    }

    [Fact]
    public void HiddenPickerDoesNotClearLoadedAgentName()
    {
        var writes = 0;
        var field = new ConfigFieldViewModel(
            "adminVMBuildAgentName", "Agent", "", JsonValue.Create("vm-test"),
            JsonValue.Create(""), [], (_, _) => writes++);

        field.SelectedOption = null;

        Assert.Equal("vm-test", field.Value);
        Assert.Equal(0, writes);
    }

    [Theory]
    [InlineData("standard")]
    [InlineData("Standard")]
    [InlineData("custom-tier")]
    [InlineData("")]
    public void ChoicePreservesExactLoadedValueAndIgnoresTransientNullSelection(string value)
    {
        var writes = 0;
        var field = new ConfigFieldViewModel(
            "admin_aiSearchTier", "AI Search tier", "", JsonValue.Create(value),
            JsonValue.Create("basic"), ["free", "basic", "standard"], (_, _) => writes++);

        field.SelectedOption = null;

        Assert.Equal(value, field.Value);
        Assert.Equal(value, field.SelectedOption);
        Assert.Contains(value, field.Options);
        Assert.Equal(0, writes);
    }

    [Fact]
    public void SynchronizeValueKeepsPickerOptionsInSyncWithoutWritingBack()
    {
        var writes = 0;
        var changed = new List<string?>();
        var field = new ConfigFieldViewModel(
            "admin_aiSearchTier", "AI Search tier", "", JsonValue.Create("basic"),
            JsonValue.Create("basic"), ["basic", "standard"], (_, _) => writes++);
        field.PropertyChanged += (_, args) => changed.Add(args.PropertyName);

        field.SynchronizeValue(JsonValue.Create("Standard"));

        Assert.Contains("Standard", field.Options);
        Assert.Equal("Standard", field.SelectedOption);
        Assert.Contains(nameof(ConfigFieldViewModel.Options), changed);
        Assert.Contains(nameof(ConfigFieldViewModel.SelectedOption), changed);
        Assert.Equal(0, writes);
    }

    [Fact]
    public void IssueMessage_ControlsInvalidState()
    {
        var field = new ConfigFieldViewModel(
            "cmkKeyName",
            "CMK key name",
            "API field",
            JsonValue.Create("<todo>"),
            JsonValue.Create("<todo>"),
            [],
            (_, _) => { });

        field.IssueMessage = "Value contains <todo>";

        Assert.True(field.IsInvalid);
    }
}

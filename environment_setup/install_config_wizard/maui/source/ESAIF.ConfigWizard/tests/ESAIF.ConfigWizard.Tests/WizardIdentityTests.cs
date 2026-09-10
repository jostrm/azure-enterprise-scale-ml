using System.Text.Json.Nodes;
using ESAIF.ConfigWizard.Services;
using ESAIF.ConfigWizard.ViewModels;
using ESAIF.DomainLayer.Configuration;

namespace ESAIF.ConfigWizard.Tests;

public sealed class WizardIdentityTests
{
    [Fact]
    public void Identity_UsesCurrentStateAndLabelsSelectionNotDeployment()
    {
        var state = new JsonObject
        {
            ["project_number_000"] = "007",
            ["admin_aifactoryPrefixRG"] = "factory-",
            ["admin_aifactorySuffixRG"] = "-abc"
        };
        var identity = WizardIdentity.FromState(state, @"C:\factory");
        Assert.Equal("Project 007 · selected", identity.ProjectLabel);
        Assert.Equal("Scale set abc · selected", identity.ScaleSetLabel);
        Assert.True(identity.IsProjectSelected(@"C:\factory\", "007"));
        Assert.True(identity.IsScaleSetSelected(@"c:\FACTORY", "abc"));
        Assert.False(identity.IsScaleSetSelected(@"c:\FACTORY", "factory-abc"));
        Assert.False(identity.IsProjectSelected(@"C:\other", "007"));
        state["project_number_000"] = "009";
        Assert.Equal("009", WizardIdentity.FromState(state, @"C:\factory").ProjectNumber);
    }

    [Theory]
    [InlineData("")]
    [InlineData("  ")]
    [InlineData("<todo>")]
    public void MissingOrPlaceholderIdentity_IsNotSelected(string value)
    {
        var state = new JsonObject
        {
            ["project_number_000"] = value,
            ["admin_aifactorySuffixRG"] = value
        };
        var identity = WizardIdentity.FromState(state, "");
        Assert.False(identity.HasProject);
        Assert.False(identity.HasScaleSet);
    }

    [Fact]
    public void SavedItems_UpdateInPlaceAndDoNotMatchOtherFolders()
    {
        var project = new SavedConfigurationItemViewModel(
            new ProjectSummary { ProjectNumber = "001" }, @"C:\factory");
        var scaleSet = new SavedConfigurationItemViewModel(
            new ScaleSetSummary { ScaleSetId = "factory-abc" }, @"C:\factory");
        var identity = new WizardIdentity(@"C:\factory", "001", "factory-abc");
        project.UpdateSelection(identity);
        scaleSet.UpdateSelection(identity);
        Assert.True(project.IsSelected);
        Assert.True(scaleSet.IsSelected);

        project.UpdateSelection(identity with { ProjectNumber = "002" });
        scaleSet.UpdateSelection(identity with { Folder = @"C:\different" });
        Assert.False(project.IsSelected);
        Assert.False(scaleSet.IsSelected);
    }

    [Fact]
    public void SynchronizingFields_UpdatesValueWithoutWritingBack()
    {
        var writes = 0;
        var field = new ConfigFieldViewModel(
            "flag", "Flag", "", JsonValue.Create("true"), JsonValue.Create("true"),
            [], (_, _) => writes++);
        field.SynchronizeValue(JsonValue.Create("false"));
        Assert.Equal("false", field.Value);
        Assert.False(field.BooleanValue);
        Assert.True(field.IsChanged);
        Assert.Equal(0, writes);
    }
}

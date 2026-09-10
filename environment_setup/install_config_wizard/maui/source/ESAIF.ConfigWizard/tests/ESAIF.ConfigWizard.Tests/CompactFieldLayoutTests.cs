using System.Xml.Linq;

namespace ESAIF.ConfigWizard.Tests;

public sealed class CompactFieldLayoutTests
{
    [Fact]
    public void WizardProjectTicketShortcutImmediatelyFollowsRecentGitHubProjects()
    {
        var page = XDocument.Load(Path.Combine(AppContext.BaseDirectory, "Assets", "MainPage.xaml"));
        var ticket = Assert.Single(page.Descendants(), node =>
            (string?)node.Attribute("AutomationId") == "CreateTicketForCurrentProject");
        Assert.Equal("Create ticket", (string?)ticket.Attribute("Text"));
        Assert.Equal("OnCreateTicketClicked", (string?)ticket.Attribute("Clicked"));
        Assert.Equal("Recent projects / GHA", (string?)ticket.ElementsBeforeSelf().Last().Attribute("Text"));
    }

    [Fact]
    public void NetworkingFormatHelpIsScrollableHeaderBeforeVariablesAndNotInStartEditor()
    {
        var page = XDocument.Load(Path.Combine(AppContext.BaseDirectory, "Assets", "MainPage.xaml"));
        var fields = Assert.Single(page.Descendants(), node =>
            (string?)node.Attribute("BindableLayout.ItemsSource") == "{Binding VisibleFields}");
        var help = Assert.Single(fields.Parent!.Descendants(), node => node.Name.LocalName == "VNetFormatHelpView");
        Assert.Equal("{Binding CurrentStep.NetworkFormatHelp}", (string?)help.Attribute("BindingContext"));
        Assert.Equal("ScrollView", help.Parent!.Parent!.Parent!.Name.LocalName);
        Assert.Equal("{Binding CurrentStep.HasNetworkFormatHelp}", (string?)help.Parent.Attribute("IsVisible"));
        Assert.Same(help.Parent, fields.ElementsBeforeSelf().Single());
        var scaling = XDocument.Load(Path.Combine(AppContext.BaseDirectory, "Assets", "ScalingModeEditor.xaml"));
        Assert.DoesNotContain(scaling.Descendants(), node =>
            (string?)node.Attribute("AutomationId") is "VNetFormatHelp" or "ShowVNetFormatHelp");
    }

    [Theory]
    [InlineData("ConfigFieldCard.xaml")]
    [InlineData("OperationConfigFieldCard.xaml")]
    public void FieldsHaveOneCompactTitleAndApiTagWithNoRepeatedDescriptionOrPickerHeading(string file)
    {
        var document = XDocument.Load(Path.Combine(AppContext.BaseDirectory, "Assets", file));
        var elements = document.Descendants().ToArray();
        var title = Assert.Single(elements, item => item.Name.LocalName == "TechnicalLabel" && (string?)item.Attribute("Value") == "{Binding Label}");
        Assert.Equal("13", (string?)title.Attribute("FontSize"));
        Assert.Equal("{Binding Description}", (string?)title.Attribute("ToolTipProperties.Text"));
        var tag = Assert.Single(elements, item => item.Name.LocalName == "TechnicalLabel" && (string?)item.Attribute("Value") == "{Binding Key}");
        Assert.Equal("Border", tag.Parent!.Name.LocalName);
        Assert.Equal("1", (string?)tag.Parent.Attribute("Grid.Column"));
        Assert.DoesNotContain(elements, item => (string?)item.Attribute("Value") == "{Binding Description}");
        Assert.All(elements.Where(item => item.Name.LocalName == "TechnicalPicker"), picker =>
        {
            Assert.Null(picker.Attribute("Title"));
            Assert.Equal("{Binding Label}", (string?)picker.Attribute("SemanticProperties.Description"));
            Assert.Equal("Start", (string?)picker.Attribute("HorizontalTextAlignment"));
        });
        Assert.Contains(elements, item => (string?)item.Attribute("IsVisible") == "{Binding IsInvalid}");
        if (file == "ConfigFieldCard.xaml")
        {
            var grid = title.Parent!;
            Assert.Equal("Auto,Auto,Auto", (string?)grid.Attribute("RowDefinitions"));
            Assert.All(elements.Where(item => item.Name.LocalName is "TechnicalEntry" or "TechnicalPicker"),
                input => Assert.Equal("1", (string?)input.Parent!.Attribute("Grid.Row")));
        }
    }
}

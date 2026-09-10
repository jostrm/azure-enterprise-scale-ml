using System.Xml.Linq;

namespace ESAIF.ConfigWizard.Tests;

public sealed class TechnicalValueLayoutTests
{
    private static string Asset(string name) => Path.Combine(AppContext.BaseDirectory, "Assets", "Disclosure", name);

    [Fact]
    public void EveryDynamicDisplayUsesAnExplicitRawValueControl()
    {
        var files = Directory.GetFiles(Path.Combine(AppContext.BaseDirectory, "Assets", "Disclosure"), "*.xaml");
        Assert.True(files.Length >= 30);
        foreach (var file in files)
        {
            var document = XDocument.Load(file);
            foreach (var node in document.Descendants())
            {
                var binding = (string?)node.Attribute("Text");
                if (node.Name.LocalName is "Label" or "Button")
                    Assert.False(binding?.StartsWith("{Binding", StringComparison.Ordinal) == true,
                        $"{Path.GetFileName(file)}: {node.Name.LocalName} must bind a raw Value, not Text.");
                if (node.Name.LocalName == "Entry")
                {
                    Assert.Equal("True", (string?)node.Attribute("IsPassword"));
                    Assert.Null(node.Attribute("ToolTipProperties.Text"));
                }
                Assert.NotEqual("Editor", node.Name.LocalName);
                Assert.NotEqual("Picker", node.Name.LocalName);
                if (node.Name.LocalName == "TechnicalLabel")
                    Assert.NotNull(node.Attribute("Value"));
            }
        }
    }

    [Theory]
    [InlineData("AiFactoryPage.xaml", "{Binding DeploymentPlan.Command}")]
    [InlineData("SimpleFactoryPage.xaml", "{Binding Plan.Command}")]
    public void ExactReviewCommandsAreRetainedBehindExplicitDisclosure(string file, string binding)
    {
        var command = Assert.Single(XDocument.Load(Asset(file)).Descendants(),
            node => (string?)node.Attribute("Value") == binding);
        Assert.Equal("TechnicalLabel", command.Name.LocalName);
        Assert.Equal("True", (string?)command.Attribute("Conceal"));
        Assert.Equal("Exact command", (string?)command.Attribute("Caption"));
    }

    [Theory]
    [InlineData("ProjectsPage.xaml")]
    [InlineData("ScaleSetsPage.xaml")]
    public void SavedConfigurationsKeepBothRawPathsWithContextualLabels(string file)
    {
        var nodes = XDocument.Load(Asset(file)).Descendants().ToArray();
        foreach (var path in new[] { "{Binding Folder}", "{Binding Path}" })
        {
            var value = Assert.Single(nodes, node => (string?)node.Attribute("Value") == path);
            Assert.Equal("TechnicalLabel", value.Name.LocalName);
            Assert.Equal("True", (string?)value.Attribute("Conceal"));
            Assert.False(string.IsNullOrWhiteSpace((string?)value.Attribute("Caption")));
        }
    }

    [Theory]
    [InlineData("ConfigFieldCard.xaml")]
    [InlineData("OperationConfigFieldCard.xaml")]
    public void SchemaFieldsRetainTwoWayRawBindingAndSecretContext(string file)
    {
        var entries = XDocument.Load(Asset(file)).Descendants().Where(node => node.Name.LocalName == "TechnicalEntry").ToArray();
        Assert.NotEmpty(entries);
        Assert.All(entries, entry =>
        {
            Assert.Equal("{Binding Value, Mode=TwoWay}", (string?)entry.Attribute("Text"));
            Assert.Equal("{Binding Key}", (string?)entry.Attribute("Context"));
        });
    }

    [Fact]
    public void FactorySubscriptionsKeepEnvironmentLabelsVisible()
    {
        var subscription = Assert.Single(XDocument.Load(Asset("AiFactoriesPage.xaml")).Descendants(),
            node => (string?)node.Attribute("Value") == "{Binding Subscriptions}");
        Assert.Null(subscription.Attribute("Conceal"));
        Assert.Equal("Subscription ids", (string?)subscription.Attribute("Caption"));
    }

    [Fact]
    public void DetailsAndEditorsUseNativeExplicitActionsWithStaleValueGuards()
    {
        var label = File.ReadAllText(Asset("TechnicalLabel.cs"));
        var entry = File.ReadAllText(Asset("TechnicalEntry.cs"));
        var picker = File.ReadAllText(Asset("TechnicalPicker.cs"));
        var details = File.ReadAllText(Asset("MessageDetailsPage.cs"));
        Assert.Contains("ToolTipProperties.SetText", label);
        Assert.Contains("_tap.Tapped", label);
        Assert.Contains("GestureRecognizers.Remove(_tap)", label);
        Assert.Contains("validity: _disclosure.Token", label);
        Assert.Contains("revision == _revision", entry);
        Assert.Contains("BindingMode.TwoWay", entry);
        Assert.Contains("SelectedItem = choice.Item", picker);
        Assert.Contains("SetBinding(ValueProperty, binding)", picker);
        Assert.DoesNotContain("binding is Binding", picker);
        Assert.DoesNotContain("BindableProperty ItemDisplayBindingProperty", picker);
        Assert.DoesNotContain("BindableProperty ItemDetailsBindingProperty", picker);
        Assert.Contains("RemoveBinding(ValueProperty)", picker);
        Assert.Contains("ChoiceLabels", picker);
        Assert.Contains("Copy all", details);
        Assert.Contains("Reveal full details", details);
        Assert.Contains("Save value", details);
        Assert.Contains("page._invalid ? null", details);
        Assert.Contains("page.Invalidate", details);
    }

    [Fact]
    public void RecentProjectsUseCompactNativeOverlayRatherThanFullPagePicker()
    {
        var source = File.ReadAllText(Asset("MainPage.xaml.cs"));
        Assert.Contains("choices.Select(choice => choice.SelectionLabel)", source);
        Assert.Contains("await DisplayActionSheetAsync(", source);
        Assert.DoesNotContain("TechnicalChoicePage.ChooseAsync", source);
        Assert.Contains("Array.IndexOf(labels, selected)", source);
    }

    [Fact]
    public void RegionNamesAndCompactSubscriptionLabelsUseTheSameBindingEngine()
    {
        var region = Assert.Single(XDocument.Load(Asset("WorldMapView.xaml")).Descendants(),
            node => (string?)node.Attribute(XName.Get("Name", "http://schemas.microsoft.com/winfx/2009/xaml")) == "RegionPicker");
        Assert.Equal("{Binding DisplayName}", (string?)region.Attribute("ItemDisplayBinding"));
        var account = Assert.Single(XDocument.Load(Asset("SimpleFactoryPage.xaml")).Descendants(),
            node => (string?)node.Attribute("AutomationId") == "SimpleSubscription");
        Assert.Equal("{Binding ., Converter={StaticResource AccountLabels}}", (string?)account.Attribute("ItemDisplayBinding"));
        Assert.Equal("{Binding ., Converter={StaticResource AccountLabels}, ConverterParameter=details}",
            (string?)account.Attribute("ItemDetailsBinding"));
    }

    [Fact]
    public void TerminalHeaderUsesDisclosureWithoutChangingInteractiveOutput()
    {
        var footer = File.ReadAllText(Asset("DeploymentTerminalFooter.cs"));
        Assert.Contains("TechnicalLabel _title", footer);
        Assert.Contains("_title.Value = _session.Title", footer);
        Assert.Contains("await _terminal.WriteAsync(output, reset)", footer);
        Assert.DoesNotContain("Summary(output", footer);
    }
}

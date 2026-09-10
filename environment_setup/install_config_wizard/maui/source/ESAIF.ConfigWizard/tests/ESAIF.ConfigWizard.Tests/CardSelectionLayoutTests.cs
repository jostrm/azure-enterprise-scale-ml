using System.Xml.Linq;

namespace ESAIF.ConfigWizard.Tests;

public sealed class CardSelectionLayoutTests
{
    [Fact]
    public void ProjectsUseInteractiveSelectionInsteadOfOnlyLoadedProjectForGlow()
    {
        var document = XDocument.Load(Asset("ProjectsPage.xaml"));
        var list = Assert.Single(document.Descendants(), node => node.Name.LocalName == "CollectionView");
        Assert.Equal("Single", (string?)list.Attribute("SelectionMode"));
        Assert.Equal("{Binding SelectedProject, Mode=TwoWay}", (string?)list.Attribute("SelectedItem"));
        var glow = Assert.Single(document.Descendants(), node => node.Name.LocalName == "GlowCard");
        Assert.Equal("{Binding IsHighlighted}", (string?)glow.Attribute("IsSelected"));
    }

    [Fact]
    public void EnvironmentCardsUseSharedGlowAndActivityLightAndHaveAccessibleSelectionAction()
    {
        var document = XDocument.Load(Asset("ProjectEnvironmentCardView.xaml"));
        var glow = Assert.Single(document.Descendants(), node => node.Name.LocalName == "GlowCard");
        Assert.Equal("{Binding IsSelected}", (string?)glow.Attribute("IsSelected"));
        Assert.Equal("{Binding HasCard}", (string?)glow.Attribute("IsVisible"));
        var light = Assert.Single(glow.Descendants(), node => node.Name.LocalName == "StatusLight");
        Assert.Equal("{Binding IsStatusPulsing}", (string?)light.Attribute("IsPulsing"));
        Assert.Equal("{Binding Status}", (string?)light.Attribute("Label"));
        Assert.Contains(glow.Descendants(), node => node.Name.LocalName == "TechnicalButton" &&
            (string?)node.Attribute("AutomationId") == "SelectEnvironmentProject");
    }

    [Fact]
    public void EveryFooterSharesOneApplicationPopupPolicy()
    {
        var shell = File.ReadAllText(Asset("AppShell.cs"));
        Assert.Contains("new WarningToastState(services.GetRequiredService<WarningToastSession>())", shell);
        Assert.DoesNotContain("new WarningToastState();", shell);
    }

    [Fact]
    public void DeploymentCardsExposePatchUpdateAndReviewedAcknowledgement()
    {
        var document = XDocument.Load(Asset("ProjectEnvironmentCardView.xaml"));
        var patch = Assert.Single(document.Descendants(), node =>
            (string?)node.Attribute("AutomationId") == "ProjectPatchCheckbox");
        Assert.Equal("CheckBox", patch.Name.LocalName);
        Assert.Equal("{Binding Patch, Mode=TwoWay}", (string?)patch.Attribute("IsChecked"));
        Assert.Equal("{Binding CanEditPatch}", (string?)patch.Attribute("IsEnabled"));
        var update = Assert.Single(document.Descendants(), node =>
            (string?)node.Attribute("AutomationId") == "UpdateProjectDeployment");
        Assert.Equal("{Binding IsDeployed}", (string?)update.Attribute("IsVisible"));
        Assert.Equal("{Binding Source={x:Reference CardRoot}, Path=UpdateCommand}", (string?)update.Attribute("Command"));
        var review = Assert.Single(document.Descendants(), node =>
            (string?)node.Attribute("AutomationId") == "ReviewProjectDeploymentOutcome");
        Assert.Equal("{Binding CanReviewOutcome}", (string?)review.Attribute("IsVisible"));
        Assert.Equal("{Binding Source={x:Reference CardRoot}, Path=ReviewOutcomeCommand}", (string?)review.Attribute("Command"));
    }

    [Fact]
    public void DeploymentActionsShareOneCompactRowWithPatchToTheRight()
    {
        var document = XDocument.Load(Asset("ProjectEnvironmentCardView.xaml"));
        var row = Assert.Single(document.Descendants(), node =>
            (string?)node.Attribute("AutomationId") == "ProjectDeploymentActions");
        var planning = Assert.Single(row.Elements(), node =>
            (string?)node.Attribute("AutomationId") == "ProjectPlanningOptions");
        var actions = Assert.Single(row.Elements(), node => node.Name.LocalName == "Grid");
        Assert.Equal("1", (string?)actions.Attribute("Grid.Column"));
        var update = Assert.Single(actions.Elements(), node => (string?)node.Attribute("Text") == "Update");
        var deploy = Assert.Single(actions.Elements(), node => (string?)node.Attribute("Text") == "Deploy");
        foreach (var button in new[] { update, deploy })
        {
            Assert.Equal((string?)planning.Attribute("Style"), (string?)button.Attribute("Style"));
            Assert.Equal((string?)planning.Attribute("BackgroundColor"), (string?)button.Attribute("BackgroundColor"));
        }
        Assert.Equal("{Binding IsDraft}", (string?)deploy.Attribute("IsVisible"));
        Assert.Equal("{Binding ShowDeployButton}", (string?)deploy.Attribute("IsEnabled"));
        Assert.Equal("{Binding Source={x:Reference CardRoot}, Path=DeployCommand}", (string?)deploy.Attribute("Command"));
        Assert.Equal("2", (string?)Assert.Single(row.Elements(), node => node.Name.LocalName == "CheckBox").Attribute("Grid.Column"));
        Assert.Equal("3", (string?)Assert.Single(row.Elements(), node => node.Name.LocalName == "Label").Attribute("Grid.Column"));
        var status = Assert.Single(document.Descendants(), node =>
            (string?)node.Attribute("AutomationId") == "PlannedEnvironmentStatus");
        Assert.Equal("TechnicalLabel", status.Name.LocalName);
        Assert.Equal("{Binding Status, StringFormat='Status: {0}'}", (string?)status.Attribute("Value"));
    }

    [Fact]
    public void MenuRetainsCurrentRouteAndReusesProjectSelectionGlow()
    {
        var shell = File.ReadAllText(Asset("AppShell.cs"));
        Assert.Contains("private string _currentWorkspaceKey = WizardPageKey;", shell);
        Assert.Contains("shell._currentWorkspaceKey,", shell);
        Assert.Contains("_currentWorkspaceKey = key;", shell);
        var menu = File.ReadAllText(Asset("NavigationMenuPage.cs"));
        Assert.Contains("string.Equals(item.Key, selectedKey, StringComparison.Ordinal)", menu);
        Assert.Contains("new GlowCard", menu);
        Assert.Contains("IsSelected = selected", menu);
        Assert.Contains("current page", menu);
    }

    [Fact]
    public void BoardWiresEveryEnvironmentToSameScopedActionsAndReview()
    {
        var document = XDocument.Load(Asset("AiFactoryPage.xaml"));
        var cards = document.Descendants().Where(node => node.Name.LocalName == "ProjectEnvironmentCardView").ToArray();
        Assert.Equal(3, cards.Length);
        Assert.All(cards, card => Assert.Equal("{StaticResource ProjectCard}", (string?)card.Attribute("Style")));
        foreach (var action in new[] { "UpdateCommand", "DeployCommand", "OpenTerminalCommand", "ReviewOutcomeCommand" })
            Assert.Contains(document.Descendants(), node => node.Name.LocalName == "Setter" &&
                (string?)node.Attribute("Property") == action &&
                (string?)node.Attribute("Value") ==
                    "{Binding Source={RelativeSource AncestorType={x:Type ContentPage}}, Path=BindingContext." + action + "}");
        var confirm = Assert.Single(document.Descendants(), node =>
            (string?)node.Attribute("AutomationId") == "ConfirmProjectDeployment");
        Assert.Equal("{Binding ConfirmDeploymentText}", (string?)confirm.Attribute("Value"));
        Assert.Equal("{Binding ConfirmDeploymentCommand}", (string?)confirm.Attribute("Command"));
    }

    private static string Asset(string name) => Path.Combine(AppContext.BaseDirectory, "Assets", name);
}

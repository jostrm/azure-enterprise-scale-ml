using System.Text.RegularExpressions;
using System.Xml.Linq;

namespace ESAIF.ConfigWizard.Tests;

public sealed class TicketTabsLayoutTests
{
    [Fact]
    public void TicketsIsLastWorkspaceMenuItemAndLegacyConnectionsRouteSelectsSamePage()
    {
        var shell = File.ReadAllText(Asset("AppShell.cs"));
        var items = Regex.Matches(shell, """new WorkspaceNavigationItem\(([^,]+), "([^"]+)"\)""");
        Assert.Single(items, item => item.Groups[1].Value == "TicketsPageKey");
        Assert.DoesNotContain(items, item => item.Groups[1].Value == "TicketConnectionsPageKey");
        var labels = items.Select(item => item.Groups[2].Value).ToArray();
        Assert.Equal(new[] { "Tickets", "Connection", "Appearance", "About" }, labels[^4..]);
        Assert.DoesNotContain("Create ticket", labels);
        Assert.Contains("var connectionsTab = key == TicketConnectionsPageKey;", shell);
        Assert.Contains("if (connectionsTab) key = TicketsPageKey;", shell);
        Assert.Contains("currentRoot is TicketsPage currentTickets", shell);
        Assert.Contains("await currentTickets.ShowTabAsync(connectionsTab);", shell);
        Assert.DoesNotContain("ResolvePage<TicketConnectionsPage>", shell);
    }

    [Fact]
    public void TabsAreKeyboardButtonsWithSelectedVisualsSemanticsAndExplicitContentModels()
    {
        var document = XDocument.Load(Asset("TicketsPage.xaml"));
        var elements = document.Descendants().ToArray();
        Assert.Equal("Tickets", (string?)document.Root!.Attribute("Title"));
        Assert.Single(elements, item => item.Name.LocalName == "AppHeader");
        Assert.DoesNotContain(elements, item => item.Name.LocalName == "ScrollView");
        foreach (var (id, label, command, selected, model, view) in new[]
        {
            ("TicketsTab", "Tickets", "ShowTicketsCommand", "IsTicketsTab", "Tickets", "TicketsView"),
            ("TicketConnectionsTab", "Ticket Connections", "ShowConnectionsCommand", "IsConnectionsTab", "TicketConnections", "TicketConnectionsView")
        })
        {
            var button = Assert.Single(elements, item => (string?)item.Attribute("AutomationId") == id);
            Assert.Equal("Button", button.Name.LocalName);
            Assert.Equal(label, (string?)button.Attribute("Text"));
            Assert.Equal($"{{Binding {command}}}", (string?)button.Attribute("Command"));
            Assert.NotNull(button.Attribute("SemanticProperties.Description"));
            var trigger = Assert.Single(button.Descendants(), item => item.Name.LocalName == "DataTrigger");
            Assert.Equal($"{{Binding {selected}}}", (string?)trigger.Attribute("Binding"));
            Assert.Contains(trigger.Elements(), item => (string?)item.Attribute("Property") == "FontAttributes" && (string?)item.Attribute("Value") == "Bold");
            var content = Assert.Single(elements, item => item.Name.LocalName == view);
            Assert.Equal($"{{Binding {model}}}", (string?)content.Attribute("BindingContext"));
            Assert.Equal($"{{Binding {selected}}}", (string?)content.Parent!.Attribute("IsVisible"));
        }
    }

    [Fact]
    public void RootReplacementPopsToInsertedRootInsteadOfRemovingDisplayedPage()
    {
        var shell = File.ReadAllText(Asset("AppShell.cs"));
        Assert.Contains("Navigation.InsertPageBefore(page, currentRoot);", shell);
        Assert.DoesNotContain("Navigation.RemovePage(currentRoot)", shell);
        var insert = shell.IndexOf("Navigation.InsertPageBefore(page, currentRoot);", StringComparison.Ordinal);
        Assert.Contains("await PopToRootAsync(false);", shell[insert..]);
    }

    [Fact]
    public void ExtractedViewsKeepOneScrollEachAndAllTicketProfileCommands()
    {
        foreach (var file in new[] { "TicketsView.xaml", "TicketConnectionsView.xaml" })
        {
            var document = XDocument.Load(Asset(file));
            Assert.Equal("ContentView", document.Root!.Name.LocalName);
            Assert.Single(document.Descendants(), item => item.Name.LocalName == "ScrollView");
            Assert.DoesNotContain(document.Descendants(), item => item.Name.LocalName == "AppHeader");
        }
        var tickets = XDocument.Load(Asset("TicketsView.xaml"));
        var commands = tickets.Descendants().Attributes("Command").Select(item => item.Value).ToArray();
        foreach (var command in new[] { "CreateCommand", "SaveStatusCommand", "PreviewSyncCommand", "ConfirmSyncCommand",
            "CancelPreviewCommand", "ManageConnectionsCommand", "ReloadCommand" })
            Assert.Contains($"{{Binding {command}}}", commands);
        Assert.Contains("{Binding Source={x:Reference TicketContent}, Path=BindingContext.SelectTicketCommand}", commands);
        Assert.Equal("TicketContent", (string?)tickets.Root!.Attribute(XName.Get("Name", "http://schemas.microsoft.com/winfx/2009/xaml")));
        var profiles = XDocument.Load(Asset("TicketConnectionsView.xaml"));
        var profileCommands = profiles.Descendants().Attributes("Command").Select(item => item.Value).ToArray();
        foreach (var command in new[] { "SaveCommand", "NewCommand", "ReloadCommand", "OpenTicketsCommand" })
            Assert.Contains($"{{Binding {command}}}", profileCommands);
    }

    private static string Asset(string file) => Path.Combine(AppContext.BaseDirectory, "Assets", file);
}

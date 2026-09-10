using ESAIF.ConfigWizard.Pages;

namespace ESAIF.ConfigWizard.Services;

public static class ProjectResourceGroupNavigator
{
    public static async Task OpenAsync(
        Page page, IReadOnlyList<ProjectResourceGroupLink> links, string unavailableMessage,
        string resourceGroupKind = "project")
    {
        if (links.Count == 0)
        {
            await MessageDetailsPage.ShowAsync(page, "Resource group unavailable", unavailableMessage);
            return;
        }
        var link = links[0];
        if (links.Count > 1)
        {
            var labels = links.Select(item => $"{item.Environment} · {item.Name} ({item.SubscriptionId})").ToArray();
            var index = await TechnicalChoicePage.ChooseAsync(page, $"Select {resourceGroupKind} resource group", labels);
            if (index < 0)
            {
                return;
            }
            link = links[index];
        }
        try
        {
            if (!await Launcher.Default.OpenAsync(link.Url))
            {
                await MessageDetailsPage.ShowAsync(page, "Unable to open Azure Portal", link.Url.AbsoluteUri);
            }
        }
        catch (Exception exception) when (exception is InvalidOperationException or NotSupportedException or
            System.Runtime.InteropServices.COMException)
        {
            await MessageDetailsPage.ShowAsync(page, "Unable to open Azure Portal", exception.Message);
        }
    }
}

using System.Text.Json;
using ESAIF.ConfigWizard.ViewModels;
using ESAIF.ConfigWizard.Pages;

namespace ESAIF.ConfigWizard.Services;

public interface IProjectTicketLauncher
{
    Task OpenForProjectAsync(Page page, SavedConfigurationItemViewModel item);
    Task OpenForCurrentProjectAsync(Page page);
}

public sealed class ProjectTicketLauncher(
    WizardSession wizard, OperationsSession operations, FactoryNetworkSession network,
    TicketTabsViewModel tabs, AzureAuthenticationMonitor? authentication = null) : IProjectTicketLauncher
{
    private bool _opening;

    public Task OpenForProjectAsync(Page page, SavedConfigurationItemViewModel item) =>
        OpenAsync(page, () => ProjectTicketContext.FromProject(item, operations.Current,
            network.Find(item.Folder)?.Overview), () => true);

    public Task OpenForCurrentProjectAsync(Page page)
    {
        var state = wizard.State.ToJsonString();
        return OpenAsync(page, () => ProjectTicketContext.FromState(wizard.State, operations.Current,
            network.Find(wizard.Identity.Folder)?.Overview), () => state == wizard.State.ToJsonString());
    }

    private async Task OpenAsync(Page page, Func<ProjectTicketContext> getContext, Func<bool> isCurrent)
    {
        if (_opening) return;
        _opening = true;
        try
        {
            await wizard.InitializeAsync();
            // Join the startup account check before prefilling; never start an Azure inventory refresh.
            if (authentication is not null && (authentication.CheckedAt is null || authentication.IsChecking))
                await authentication.CheckAsync();
            if (!isCurrent()) return;
            var context = getContext();
            var revision = tabs.Tickets.DraftRevision;
            ProjectResourceGroupLink? group = context.ResourceGroups.FirstOrDefault();
            if (context.ResourceGroups.Count > 1)
            {
                var labels = context.ResourceGroups.Select(link =>
                    $"{link.Environment} · {link.Name} ({link.SubscriptionId})").ToArray();
                var index = await TechnicalChoicePage.ChooseAsync(page, "Select ticket resource group", labels);
                if (index < 0) return;
                group = context.ResourceGroups[index];
            }
            if (!isCurrent() || revision != tabs.Tickets.DraftRevision) return;
            await tabs.Tickets.BeginDraftFromResourceGroupAsync(group?.Name, context.ProjectNumber,
                () => page.DisplayAlertAsync("Replace ticket draft?",
                    "The current unsaved ticket contains edits. Replace its text and context with a new project draft? Nothing will be created or sent.",
                    "Replace draft", "Cancel"),
                async () =>
                {
                    if (!isCurrent()) return false;
                    await tabs.ShowTabAsync(false);
                    return isCurrent() && tabs.IsTicketsTab;
                },
                () => AppShell.NavigateToWorkspaceAsync(AppShell.TicketsPageKey));
        }
        catch (Exception error) when (error is HttpRequestException or IOException or JsonException or
            InvalidOperationException or ArgumentException or NotSupportedException or UnauthorizedAccessException or
            OperationCanceledException)
        {
            await MessageDetailsPage.ShowAsync(page, "Ticket draft unavailable", error.Message, "OK");
        }
        finally { _opening = false; }
    }
}

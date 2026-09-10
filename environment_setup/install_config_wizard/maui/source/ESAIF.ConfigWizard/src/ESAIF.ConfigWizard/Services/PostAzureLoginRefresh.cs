namespace ESAIF.ConfigWizard.Services;

public interface IPostAzureLoginRefresh
{
    Task<string> RefreshAsync();
}

public sealed class PostAzureLoginRefresh(WizardSession wizard, AzureRefreshCoordinator refresh,
    AzureAuthenticationMonitor? monitor = null) : IPostAzureLoginRefresh
{
    public async Task<string> RefreshAsync()
    {
        await wizard.RefreshSchemaAsync();
        if (monitor is not null)
        {
            await monitor.CheckAsync();
        }
        await refresh.RefreshAfterLoginAsync();
        return $"Azure sign-in verified. {refresh.Message} Unsaved editor changes preserved.";
    }
}

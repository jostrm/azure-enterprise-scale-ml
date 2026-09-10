using ESAIF.ConfigWizard.ViewModels;
using ESAIF.ConfigWizard.Pages;

namespace ESAIF.ConfigWizard.Services;

public sealed class AzureLoginCoordinator(
    AzureAuthenticationViewModel authentication, WizardSession wizard, AzureAuthenticationMonitor monitor)
{
    private bool _showing;

    public async Task AuthenticateAsync(Page page, bool allowLogout = true, CancellationToken cancellationToken = default)
    {
        if (_showing || !authentication.CanAuthenticate || cancellationToken.IsCancellationRequested)
        {
            return;
        }
        _showing = true;
        try
        {
            await authentication.RefreshAsync(wizard.GetString("_save_folder"), cancellationToken);
            if (cancellationToken.IsCancellationRequested) { return; }
            if (authentication.IsLoggedIn)
            {
                if (allowLogout && await page.DisplayAlertAsync("Logout from Azure?",
                    "This signs out the shared Azure CLI session on the Python API computer, including other tools using that session. It does not sign out Microsoft 365 or delete saved configurations.",
                    "Logout", "Cancel") && !cancellationToken.IsCancellationRequested)
                {
                    await authentication.LogoutAsync(wizard.GetString("_save_folder"), cancellationToken);
                }
                return;
            }
            var tenantId = authentication.SuggestedTenantId;
            var tenants = authentication.LoginTenants;
            if (tenants.Count > 1)
            {
                var choices = tenants.Select(tenant => string.IsNullOrWhiteSpace(tenant.AccountName)
                    ? tenant.TenantId : $"{tenant.AccountName} | {tenant.TenantId}").ToArray();
                var index = await TechnicalChoicePage.ChooseAsync(page, "Choose the Azure tenant to sign in to", choices);
                if (index < 0 || cancellationToken.IsCancellationRequested) { return; }
                tenantId = tenants[index].TenantId;
            }
            if (await page.DisplayAlertAsync("Login to Azure",
                "Microsoft sign-in will open in the browser on the computer running the Python API. Complete sign-in there; no password is collected by this application.",
                "Open sign-in", "Cancel") && !cancellationToken.IsCancellationRequested)
            {
                await authentication.LoginAsync(monitor.GetLoginFolder(tenantId), tenantId, cancellationToken);
            }
        }
        finally { _showing = false; }
    }
}

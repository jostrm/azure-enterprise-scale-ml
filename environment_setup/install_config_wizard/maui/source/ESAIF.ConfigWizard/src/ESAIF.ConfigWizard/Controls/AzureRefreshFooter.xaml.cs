using ESAIF.ConfigWizard.Services;

namespace ESAIF.ConfigWizard.Controls;

public partial class AzureRefreshFooter : ContentView
{
    private readonly WarningToastState _warnings;

    public AzureRefreshFooter(AzureRefreshCoordinator coordinator, WarningToastState warnings)
    {
        InitializeComponent();
        BindingContext = coordinator;
        _warnings = warnings;
        WarningsButton.BindingContext = warnings;
    }

    private void OnWarningsClicked(object? sender, EventArgs e) => _warnings.Replay();

    private async void OnLoginClicked(object? sender, EventArgs e)
    {
        if (Application.Current?.Windows.FirstOrDefault()?.Page is NavigationPage navigation)
        {
            await AppServices.GetRequiredService<AzureLoginCoordinator>()
                .AuthenticateAsync(navigation.CurrentPage, allowLogout: false);
        }
    }
}

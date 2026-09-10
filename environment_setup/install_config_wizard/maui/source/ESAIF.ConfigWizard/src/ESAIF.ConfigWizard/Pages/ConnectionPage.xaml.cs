using ESAIF.ConfigWizard.ViewModels;
using ESAIF.ConfigWizard.Services;

namespace ESAIF.ConfigWizard.Pages;

public partial class ConnectionPage : ContentPage
{
    private readonly ConnectionViewModel _viewModel;
    private bool _loaded;

    public ConnectionPage()
        : this(AppServices.GetRequiredService<ConnectionViewModel>())
    {
    }

    public ConnectionPage(ConnectionViewModel viewModel)
    {
        InitializeComponent();
        _viewModel = viewModel;
        BindingContext = viewModel;
    }

    protected override async void OnAppearing()
    {
        base.OnAppearing();
        if (!_loaded)
        {
            _loaded = true;
            await _viewModel.LoadAsync();
        }
    }

    private async void OnConnectClicked(object? sender, EventArgs e)
    {
        ConnectButton.IsEnabled = false;
        try
        {
            if (!await _viewModel.ConnectAsync())
            {
                await MessageDetailsPage.ShowAsync(this,
                    "Connection failed",
                    _viewModel.StatusMessage,
                    "OK");
                return;
            }

            await MessageDetailsPage.ShowAsync(this,
                "Connected",
                _viewModel.StatusMessage,
                "Open wizard");
            await AppShell.NavigateToWorkspaceAsync(AppShell.WizardPageKey);
        }
        finally
        {
            ConnectButton.IsEnabled = true;
        }
    }

    private async void OnOpenSwaggerClicked(object? sender, EventArgs e)
    {
        try
        {
            var address = _viewModel.GetDocumentationUri();
            if (!await Launcher.Default.OpenAsync(address))
            {
                await MessageDetailsPage.ShowAsync(this,
                    "Unable to open Swagger",
                    $"Open {address} in your browser.",
                    "OK");
            }
        }
        catch (InvalidOperationException exception)
        {
            await MessageDetailsPage.ShowAsync(this,
                "Invalid API address",
                exception.Message,
                "OK");
        }
    }
}

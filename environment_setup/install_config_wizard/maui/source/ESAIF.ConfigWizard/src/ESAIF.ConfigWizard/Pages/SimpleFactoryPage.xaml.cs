using ESAIF.ConfigWizard.ViewModels;

namespace ESAIF.ConfigWizard.Pages;

public partial class SimpleFactoryPage : ContentPage
{
    private readonly SimpleFactoryViewModel _viewModel;

    public SimpleFactoryPage(SimpleFactoryViewModel viewModel)
    {
        InitializeComponent();
        BindingContext = _viewModel = viewModel;
    }

    protected override async void OnAppearing()
    {
        base.OnAppearing();
        await _viewModel.ActivateAsync();
    }

    protected override void OnDisappearing()
    {
        _viewModel.Deactivate();
        base.OnDisappearing();
    }

    private async void OnAdvancedClicked(object? sender, EventArgs e) =>
        await AppShell.NavigateToWorkspaceAsync(AppShell.WizardPageKey);

    private async void OnOpenRepositoryClicked(object? sender, EventArgs e)
    {
        if (_viewModel.CanOpenRepository)
            await Launcher.Default.OpenAsync(new Uri(_viewModel.Job!.RepositoryUrl));
    }
}

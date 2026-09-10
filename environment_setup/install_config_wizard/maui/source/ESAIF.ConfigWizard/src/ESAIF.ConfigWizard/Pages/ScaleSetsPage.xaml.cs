using ESAIF.ConfigWizard.ViewModels;
using ESAIF.ConfigWizard.Services;

namespace ESAIF.ConfigWizard.Pages;

public partial class ScaleSetsPage : ContentPage
{
    private readonly ScaleSetsViewModel _viewModel;

    public ScaleSetsPage()
        : this(AppServices.GetRequiredService<ScaleSetsViewModel>())
    {
    }

    public ScaleSetsPage(ScaleSetsViewModel viewModel)
    {
        InitializeComponent();
        _viewModel = viewModel;
        BindingContext = viewModel;
    }

    private async void OnOpenResourceGroupClicked(object? sender, EventArgs e)
    {
        if (sender is Button { CommandParameter: SavedConfigurationItemViewModel item })
        {
            await ProjectResourceGroupNavigator.OpenAsync(
                this, item.ResourceGroupLinks, item.ResourceGroupLinkHint, "common");
        }
    }

    private async void OnDeleteConfigurationClicked(object? sender, EventArgs e)
    {
        if (sender is not Button { CommandParameter: SavedConfigurationItemViewModel item } ||
            _viewModel.IsBusy || item.ScaleSet is null)
        {
            return;
        }
        if (await MessageDetailsPage.ConfirmAsync(this, $"Delete config for scale set {item.ScaleSet.ScaleSetId}?",
                $"Only this saved snapshot will be removed:\n{item.Path}\n\nCommon Azure resources, project configurations, exported variables and the current editor remain unchanged.",
                "Delete config", "Cancel"))
        {
            await _viewModel.DeleteConfigurationAsync(item);
        }
    }

    protected override async void OnAppearing()
    {
        base.OnAppearing();
        if (!_viewModel.IsBusy)
        {
            await _viewModel.RefreshAsync();
        }
    }
}

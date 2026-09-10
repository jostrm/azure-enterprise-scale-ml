using System.ComponentModel;
using ESAIF.ConfigWizard.Controls;
using ESAIF.ConfigWizard.Services;
using ESAIF.ConfigWizard.ViewModels;

namespace ESAIF.ConfigWizard.Pages;

public partial class AiFactoriesPage : ContentPage
{
    private readonly AiFactoriesViewModel _viewModel;
    private int _detailsTransition;

    public AiFactoriesPage()
        : this(AppServices.GetRequiredService<AiFactoriesViewModel>())
    {
    }

    public AiFactoriesPage(AiFactoriesViewModel viewModel)
    {
        InitializeComponent();
        _viewModel = viewModel;
        BindingContext = viewModel;
    }

    protected override async void OnAppearing()
    {
        base.OnAppearing();
        WorldMap.SetSceneActive(true);
        _viewModel.PropertyChanged -= OnViewModelPropertyChanged;
        _viewModel.PropertyChanged += OnViewModelPropertyChanged;
        await _viewModel.LoadAsync();
        await UpdateDetailsPaneAsync();
    }

    protected override void OnDisappearing()
    {
        WorldMap.SetSceneActive(false);
        _detailsTransition++;
        DetailsPane.CancelAnimations();
        _viewModel.PropertyChanged -= OnViewModelPropertyChanged;
        base.OnDisappearing();
    }

    private void OnViewModelPropertyChanged(object? sender, PropertyChangedEventArgs e)
    {
        if (e.PropertyName == nameof(AiFactoriesViewModel.SelectedRegion))
        {
            Dispatcher.Dispatch(async () => await UpdateDetailsPaneAsync());
        }
    }

    private async Task UpdateDetailsPaneAsync()
    {
        var transition = ++_detailsTransition;
        DetailsPane.CancelAnimations();
        if (_viewModel.SelectedRegion is not null)
        {
            if (DetailsPane.IsVisible)
            {
                DetailsPane.TranslationX = 0;
                return;
            }
            DetailsPane.TranslationX = DetailsPane.WidthRequest + 20;
            DetailsPane.IsVisible = true;
            await DetailsPane.TranslateToAsync(0, 0, 220, Easing.CubicOut);
            return;
        }

        if (DetailsPane.IsVisible)
        {
            await DetailsPane.TranslateToAsync(DetailsPane.WidthRequest + 20, 0, 170, Easing.CubicIn);
            if (transition == _detailsTransition)
            {
                DetailsPane.IsVisible = false;
            }
        }
    }

    protected override void OnSizeAllocated(double width, double height)
    {
        base.OnSizeAllocated(width, height);
        if (width > 48)
        {
            DetailsPane.WidthRequest = Math.Min(340, width - 48);
        }
    }

    private async void OnOpenFactoryClicked(object? sender, EventArgs e)
    {
        var uri = AzureDashboardLink.Parse(_viewModel.Factory.DashboardUrl);
        if (uri is null || !_viewModel.CanOpenFactory)
        {
            await MessageDetailsPage.ShowAsync(this, "AI Factory dashboard unavailable", _viewModel.DashboardHint);
            return;
        }
        try
        {
            if (!await Launcher.Default.OpenAsync(uri))
            {
                await MessageDetailsPage.ShowAsync(this, "Unable to open AI Factory dashboard",
                    $"Open this configured dashboard link in your browser:\n{uri}");
            }
        }
        catch (Exception exception) when (exception is InvalidOperationException or NotSupportedException or
            System.Runtime.InteropServices.COMException)
        {
            await MessageDetailsPage.ShowAsync(this, "Unable to open AI Factory dashboard", exception.Message);
        }
    }

    private async void OnPipelineFindingsClicked(object? sender, EventArgs e)
    {
        await MessageDetailsPage.ShowAsync(this,
            $"{_viewModel.SelectedRegion?.DisplayName} - last-run findings",
            _viewModel.PipelineFindingDetails);
    }

    private async void OnRegionSecondaryTapped(
        object? sender,
        RegionTappedEventArgs e)
    {
        _viewModel.SelectedRegion = e.Region;
        var actions = new List<string>();
        if (_viewModel.CanConfigureSelected)
        {
            actions.Add("Add AI Factory");
        }
        if (_viewModel.CanAddScaleSet)
        {
            actions.Add("Add AI Factory scale set");
        }
        if (_viewModel.CanCloneSelected)
        {
            actions.Add("Clone AI Factory");
        }
        actions.Add("Manage factories");
        actions.Add("Review factory deletion");

        var selected = await DisplayActionSheetAsync(
            TechnicalValuePresentation.Summary(e.Region.DisplayName),
            "Cancel",
            null,
            actions.ToArray());
        var action = selected switch
        {
            "Add AI Factory" => "factory",
            "Add AI Factory scale set" => "scale-set",
            "Clone AI Factory" => "clone",
            "Review factory deletion" => "delete",
            _ => null
        };
        if (selected == "Manage factories")
        {
            await AppShell.NavigateToWorkspaceAsync(AppShell.FactoryCatalogPageKey);
            return;
        }
        if (action is not null)
        {
            await _viewModel.OpenConfigurationAsync(action);
        }
    }
}

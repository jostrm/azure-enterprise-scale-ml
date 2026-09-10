using ESAIF.ConfigWizard.ViewModels;
using ESAIF.ConfigWizard.Services;
using ESAIF.ConfigWizard.Pages;
using System.ComponentModel;

namespace ESAIF.ConfigWizard;

public partial class MainPage : ContentPage
{
    private readonly WizardViewModel _viewModel;

    public MainPage()
        : this(AppServices.GetRequiredService<WizardViewModel>())
    {
    }

    public MainPage(WizardViewModel viewModel)
    {
        InitializeComponent();
        _viewModel = viewModel;
        BindingContext = viewModel;
        SizeChanged += OnPageSizeChanged;
    }

    protected override async void OnAppearing()
    {
        base.OnAppearing();
        _viewModel.PropertyChanged -= OnViewModelPropertyChanged;
        _viewModel.PropertyChanged += OnViewModelPropertyChanged;
        if (!_viewModel.IsBusy)
        {
            await _viewModel.InitializeAsync();
        }
    }

    protected override void OnDisappearing()
    {
        _viewModel.PropertyChanged -= OnViewModelPropertyChanged;
        base.OnDisappearing();
    }

    private async void OnViewModelPropertyChanged(object? sender, PropertyChangedEventArgs e)
    {
        if (e.PropertyName == nameof(WizardViewModel.CurrentStep))
            await FieldsScroll.ScrollToAsync(0, 0, false);
    }

    private void OnPageSizeChanged(object? sender, EventArgs e)
    {
        var isCompact = Width > 0 && Width < 900;
        WorkspaceGrid.ColumnDefinitions[0].Width =
            isCompact ? new GridLength(0) : new GridLength(250);
        StepsRail.IsVisible = !isCompact;
        CompactStepPicker.IsVisible = isCompact;
    }

    private async void OnQuickExportClicked(object? sender, EventArgs e)
    {
        var format = await DisplayActionSheetAsync(
            "Export variable file",
            "Cancel",
            null,
            "YAML (.yaml)",
            "Environment (.env)",
            "JSON (.json)");
        var apiFormat = format switch
        {
            "YAML (.yaml)" => "yaml",
            "Environment (.env)" => "env",
            "JSON (.json)" => "json",
            _ => null
        };
        if (apiFormat is not null)
        {
            await _viewModel.QuickExportAsync(apiFormat);
        }
    }

    private async void OnRecentAdoClicked(object? sender, EventArgs e)
    {
        await ShowRecentProjectsAsync("ado");
    }

    private async void OnRecentGhaClicked(object? sender, EventArgs e)
    {
        await ShowRecentProjectsAsync("gha");
    }

    private async void OnCreateTicketClicked(object? sender, EventArgs e)
    {
        await AppServices.GetRequiredService<IProjectTicketLauncher>().OpenForCurrentProjectAsync(this);
    }

    private async Task ShowRecentProjectsAsync(string orchestrator)
    {
        var choices = await _viewModel.GetRecentProjectsAsync(orchestrator);
        if (choices.Count == 0)
        {
            await MessageDetailsPage.ShowAsync(this,
                $"Recent {orchestrator.ToUpperInvariant()} projects",
                _viewModel.StatusMessage,
                "OK");
            return;
        }

        var labels = choices.Select(choice => choice.SelectionLabel).ToArray();
        var selected = await DisplayActionSheetAsync(
            $"Recent {orchestrator.ToUpperInvariant()} projects", "Cancel", null, labels);
        var selectedIndex = Array.IndexOf(labels, selected);
        if (selectedIndex >= 0)
        {
            await _viewModel.LoadRecentProjectAsync(choices[selectedIndex]);
        }
    }
}

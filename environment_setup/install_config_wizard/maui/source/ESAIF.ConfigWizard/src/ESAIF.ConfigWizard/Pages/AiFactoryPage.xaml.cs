using ESAIF.ConfigWizard.ViewModels;
using ESAIF.ConfigWizard.Services;
using System.ComponentModel;

namespace ESAIF.ConfigWizard.Pages;

public partial class AiFactoryPage : ContentPage
{
    private readonly AiFactoryViewModel _viewModel;
    private readonly IDispatcherTimer _draftTimer;

    public AiFactoryPage()
        : this(AppServices.GetRequiredService<AiFactoryViewModel>())
    {
    }

    public AiFactoryPage(AiFactoryViewModel viewModel)
    {
        InitializeComponent();
        _viewModel = viewModel;
        BindingContext = viewModel;
        _draftTimer = Dispatcher.CreateTimer();
        _draftTimer.Interval = TimeSpan.FromSeconds(3);
        _draftTimer.Tick += OnDraftTimer;
    }

    protected override async void OnAppearing()
    {
        base.OnAppearing();
        _viewModel.PropertyChanged += OnViewModelChanged;
        _draftTimer.Start();
        await _viewModel.LoadAsync();
    }

    protected override void OnDisappearing()
    {
        _draftTimer.Stop();
        _viewModel.PropertyChanged -= OnViewModelChanged;
        _viewModel.DismissDeployment();
        base.OnDisappearing();
    }

    private async void OnDraftTimer(object? sender, EventArgs e)
    {
        _viewModel.NotifyDeploymentActions();
        if (!_viewModel.IsBusy && _viewModel.CanPollDrafts)
            await _viewModel.RefreshDraftsAsync();
    }

    private async void OnViewModelChanged(object? sender, PropertyChangedEventArgs e)
    {
        if (e.PropertyName == nameof(AiFactoryViewModel.HasDeploymentPlan) && _viewModel.HasDeploymentPlan)
            await BoardScroll.ScrollToAsync(0, 0, false);
    }
}

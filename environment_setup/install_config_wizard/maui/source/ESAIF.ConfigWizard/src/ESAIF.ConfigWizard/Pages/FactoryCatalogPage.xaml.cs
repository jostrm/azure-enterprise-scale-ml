using ESAIF.ConfigWizard.ViewModels;

namespace ESAIF.ConfigWizard.Pages;

public partial class FactoryCatalogPage : ContentPage
{
    private readonly FactoryCatalogViewModel _viewModel;
    private IDispatcherTimer? _expiryTimer;
    private bool _reviewing;

    public FactoryCatalogPage(FactoryCatalogViewModel viewModel)
    {
        InitializeComponent();
        BindingContext = _viewModel = viewModel;
    }

    protected override async void OnAppearing()
    {
        base.OnAppearing();
        if (_reviewing) return;
        _viewModel.SetVisible(true);
        _expiryTimer ??= Dispatcher.CreateTimer();
        _expiryTimer.Interval = TimeSpan.FromSeconds(1);
        _expiryTimer.Tick -= OnExpiryTick;
        _expiryTimer.Tick += OnExpiryTick;
        _expiryTimer.Start();
        await _viewModel.RefreshAsync();
    }

    protected override void OnDisappearing()
    {
        _expiryTimer?.Stop();
        if (!_reviewing) _viewModel.SetVisible(false);
        base.OnDisappearing();
    }

    private void OnExpiryTick(object? sender, EventArgs e) => _viewModel.RefreshConsentExpiry();

    private async void OnReviewClicked(object? sender, EventArgs e)
    {
        var details = _viewModel.ReviewDetails;
        if (string.IsNullOrWhiteSpace(details)) return;
        _reviewing = true;
        try
        {
            await MessageDetailsPage.ShowAsync(this, "Exact server-owned operation review", details,
                reveal: true, validity: _viewModel.DisclosureValidity);
            _viewModel.MarkReviewed(details);
        }
        finally
        {
            _reviewing = false;
            _expiryTimer?.Start();
        }
    }

    private async void OnConfirmClicked(object? sender, EventArgs e)
    {
        if (!_viewModel.CanConfirm) return;
        if (_viewModel.IsDelete && !await DisplayAlertAsync("Confirm destructive operation",
                "Submit the exact reviewed server resource manifest for deletion? No resources outside that manifest are authorized.",
                "Submit deletion", "Cancel")) return;
        await _viewModel.ConfirmAsync();
    }

    private async void OnLegacyClicked(object? sender, EventArgs e) =>
        await AppShell.NavigateToWorkspaceAsync(AppShell.WizardPageKey);

    private async void OnReloadBindingClicked(object? sender, EventArgs e)
    {
        if (_viewModel.BindingEditor.IsDirty && !await DisplayAlertAsync("Replace unsaved binding draft?",
                "Reload the selected binding from the current catalog snapshot? Only this binding form's unsaved edits will be discarded.",
                "Reload binding", "Keep edits")) return;
        _viewModel.ReloadBindingDraft();
    }

    private async void OnLoadSettingsClicked(object? sender, EventArgs e)
    {
        if (_viewModel.SettingsEditor.IsDirty && !await DisplayAlertAsync("Replace unsaved settings draft?",
                "Reload the exact selected settings scope? Its unsaved settings inputs will be discarded; wizard edits are unaffected.",
                "Reload settings", "Keep edits")) return;
        await _viewModel.LoadSettingsAsync();
    }
}

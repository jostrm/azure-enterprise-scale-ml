using ESAIF.ConfigWizard.Services;
using ESAIF.ConfigWizard.ViewModels;

namespace ESAIF.ConfigWizard.Pages;

public partial class FactoryConfigurationPage : ContentPage
{
    private readonly FactoryConfigurationViewModel _viewModel;
    private readonly WizardSession _session;
    private readonly OperationsSession _operations;
    private readonly IAiFactoryFolderPickerService _folderPicker;
    private string _kind = "factory";
    private string _region = string.Empty;
    private string? _source;
    private bool _loaded;

    public FactoryConfigurationPage(FactoryConfigurationViewModel viewModel, WizardSession session,
        OperationsSession operations, IAiFactoryFolderPickerService folderPicker)
    {
        InitializeComponent();
        BindingContext = _viewModel = viewModel;
        _session = session;
        _operations = operations;
        _folderPicker = folderPicker;
    }

    public void Configure(string kind, string region, string? sourceFolder)
    {
        _kind = kind;
        _region = region;
        _source = sourceFolder;
    }

    protected override async void OnAppearing()
    {
        base.OnAppearing();
        if (!_loaded)
        {
            _loaded = true;
            // The map has already initialized the schema; setup never replaces the current editor.
            await _viewModel.PrepareAsync(_kind, _region, _source,
                _session.Schema ?? throw new InvalidOperationException("Load the AI Factories map before opening setup."));
        }
    }

    private async void OnBrowseClicked(object? sender, EventArgs e)
    {
        try
        {
            var folder = await _folderPicker.PickFolderAsync(_viewModel.DestinationFolder);
            if (!string.IsNullOrWhiteSpace(folder))
            {
                _viewModel.DestinationFolder = folder;
            }
        }
        catch (Exception exception) when (exception is IOException or UnauthorizedAccessException or NotSupportedException)
        {
            await MessageDetailsPage.ShowAsync(this, "Folder picker unavailable", exception.Message);
        }
    }

    private async void OnSaveClicked(object? sender, EventArgs e)
    {
        await _viewModel.SaveAsync();
        if (_viewModel.IsSaved && _viewModel.IsScaleSet)
        {
            _operations.Invalidate();
        }
    }

    private async void OnOpenClicked(object? sender, EventArgs e)
    {
        var proceed = await DisplayAlertAsync("Open saved configuration?",
            "This replaces the configuration currently in the editor. Any unsaved editor changes will be discarded.",
            "Open", "Cancel");
        if (!proceed)
        {
            return;
        }
        _session.ReplaceState(_viewModel.GetSavedState());
        await AppShell.NavigateToWorkspaceAsync(AppShell.WizardPageKey);
    }

    private async void OnBackClicked(object? sender, EventArgs e)
    {
        if (_viewModel.IsBusy)
        {
            await DisplayAlertAsync("Operation in progress", "Wait for the API operation to finish before leaving.", "OK");
            return;
        }
        if (!_viewModel.IsSaved && _viewModel.IsPrepared &&
            !await DisplayAlertAsync("Leave setup?", "Unsaved setup changes will be discarded. The existing factory is unchanged.", "Leave", "Stay"))
        {
            return;
        }
        await AppShell.GoBackAsync();
    }
}

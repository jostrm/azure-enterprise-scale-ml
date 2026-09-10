using ESAIF.ConfigWizard.ViewModels;
using ESAIF.ConfigWizard.Services;
using ESAIF.ConfigWizard.Controls;

namespace ESAIF.ConfigWizard.Pages;

public partial class ProjectsPage : ContentPage
{
    private readonly ProjectsViewModel _viewModel;

    public ProjectsPage()
        : this(AppServices.GetRequiredService<ProjectsViewModel>())
    {
    }

    public ProjectsPage(ProjectsViewModel viewModel)
    {
        InitializeComponent();
        _viewModel = viewModel;
        BindingContext = viewModel;
        _ = new RadioChoiceGroup<ProjectsViewModel>(EnvironmentFilterHost,
            (AllRadio, model => model.AllEnvironments, model => model.AllEnvironments = true),
            (DevRadio, model => model.DevEnvironment, model => model.DevEnvironment = true),
            (StageRadio, model => model.StageEnvironment, model => model.StageEnvironment = true),
            (ProdRadio, model => model.ProdEnvironment, model => model.ProdEnvironment = true));
    }

    protected override async void OnAppearing()
    {
        base.OnAppearing();
        if (!_viewModel.IsBusy)
        {
            await _viewModel.RefreshAsync();
        }
    }

    private async void OnOpenResourceGroupClicked(object? sender, EventArgs e)
    {
        if (sender is Button { CommandParameter: SavedConfigurationItemViewModel item })
        {
            await ProjectResourceGroupNavigator.OpenAsync(this, item.ResourceGroupLinks, item.ResourceGroupLinkHint);
        }

    }

    private async void OnCreateTicketClicked(object? sender, EventArgs e)
    {
        if (sender is Button { CommandParameter: SavedConfigurationItemViewModel item })
            await AppServices.GetRequiredService<IProjectTicketLauncher>().OpenForProjectAsync(this, item);
    }

    private async void OnDeleteConfigurationClicked(object? sender, EventArgs e)
    {
        if (sender is not Button { CommandParameter: SavedConfigurationItemViewModel item } ||
            _viewModel.IsBusy || item.Project is null)
        {
            return;
        }
        if (await MessageDetailsPage.ConfirmAsync(this, $"Delete config for Project {item.Project.ProjectNumber}?",
                $"Only this saved snapshot will be removed:\n{item.Path}\n\nAzure resources, exported variable files, and the current editor remain unchanged.",
                "Delete config", "Cancel"))
        {
            await _viewModel.DeleteConfigurationAsync(item);
        }
    }
}

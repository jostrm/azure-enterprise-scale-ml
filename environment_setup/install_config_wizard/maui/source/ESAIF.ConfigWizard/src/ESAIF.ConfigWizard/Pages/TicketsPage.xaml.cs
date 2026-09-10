using ESAIF.ConfigWizard.Services;
using ESAIF.ConfigWizard.ViewModels;

namespace ESAIF.ConfigWizard.Pages;

public partial class TicketsPage : ContentPage
{
    private readonly TicketTabsViewModel _viewModel;
    public TicketsPage() : this(AppServices.GetRequiredService<TicketTabsViewModel>()) { }
    public TicketsPage(TicketTabsViewModel viewModel)
    {
        InitializeComponent();
        BindingContext = _viewModel = viewModel;
    }
    protected override async void OnAppearing()
    {
        base.OnAppearing();
        await _viewModel.LoadSelectedTabAsync();
    }

    public void SelectTab(bool connections) => _viewModel.SelectTab(connections);

    public Task ShowTabAsync(bool connections) => _viewModel.ShowTabAsync(connections);
}

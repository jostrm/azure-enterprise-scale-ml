using ESAIF.ConfigWizard.Services;
using ESAIF.ConfigWizard.ViewModels;

namespace ESAIF.ConfigWizard.Pages;

public partial class TicketConnectionsPage : ContentPage
{
    private readonly TicketConnectionsViewModel _viewModel;
    public TicketConnectionsPage() : this(AppServices.GetRequiredService<TicketConnectionsViewModel>()) { }
    public TicketConnectionsPage(TicketConnectionsViewModel viewModel)
    {
        InitializeComponent();
        BindingContext = _viewModel = viewModel;
    }
    protected override async void OnAppearing()
    {
        base.OnAppearing();
        await _viewModel.LoadAsync();
    }
}

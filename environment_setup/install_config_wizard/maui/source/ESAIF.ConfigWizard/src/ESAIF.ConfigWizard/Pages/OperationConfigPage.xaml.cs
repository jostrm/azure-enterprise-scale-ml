using ESAIF.ConfigWizard.ViewModels;

namespace ESAIF.ConfigWizard.Pages;

public partial class OperationConfigPage : ContentPage, IQueryAttributable
{
    private readonly OperationConfigViewModel _viewModel;

    public OperationConfigPage(OperationConfigViewModel viewModel)
    {
        InitializeComponent();
        _viewModel = viewModel;
        BindingContext = viewModel;
    }

    public void ApplyQueryAttributes(IDictionary<string, object> query) =>
        _viewModel.ApplyQueryAttributes(query);

    protected override async void OnAppearing()
    {
        base.OnAppearing();
        if (!_viewModel.IsBusy)
        {
            await _viewModel.LoadAsync();
        }
    }
}

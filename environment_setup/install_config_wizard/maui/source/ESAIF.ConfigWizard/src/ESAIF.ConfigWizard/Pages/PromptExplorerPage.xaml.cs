using ESAIF.ConfigWizard.ViewModels;

namespace ESAIF.ConfigWizard.Pages;

public partial class PromptExplorerPage : ContentPage
{
    private readonly PromptExplorerViewModel _viewModel;
    private bool _isLoaded;
    private bool _singleColumn;

    public PromptExplorerPage(PromptExplorerViewModel viewModel)
    {
        InitializeComponent();
        _viewModel = viewModel;
        BindingContext = viewModel;
    }

    protected override async void OnAppearing()
    {
        base.OnAppearing();
        if (!_isLoaded)
        {
            _isLoaded = true;
            await _viewModel.SearchAsync();
        }
    }

    protected override void OnSizeAllocated(double width, double height)
    {
        base.OnSizeAllocated(width, height);
        var singleColumn = width < 950;
        if (singleColumn == _singleColumn)
        {
            return;
        }

        _singleColumn = singleColumn;
        PromptLayout.ColumnDefinitions.Clear();
        PromptLayout.RowDefinitions.Clear();
        if (singleColumn)
        {
            PromptLayout.ColumnDefinitions.Add(new ColumnDefinition(GridLength.Star));
            PromptLayout.RowDefinitions.Add(new RowDefinition(GridLength.Auto));
            PromptLayout.RowDefinitions.Add(new RowDefinition(GridLength.Auto));
            Grid.SetRow(ListPane, 0);
            Grid.SetColumn(ListPane, 0);
            Grid.SetRow(DetailPane, 1);
            Grid.SetColumn(DetailPane, 0);
        }
        else
        {
            PromptLayout.ColumnDefinitions.Add(new ColumnDefinition(new GridLength(5, GridUnitType.Star)));
            PromptLayout.ColumnDefinitions.Add(new ColumnDefinition(new GridLength(4, GridUnitType.Star)));
            PromptLayout.RowDefinitions.Add(new RowDefinition(GridLength.Auto));
            Grid.SetRow(ListPane, 0);
            Grid.SetColumn(ListPane, 0);
            Grid.SetRow(DetailPane, 0);
            Grid.SetColumn(DetailPane, 1);
        }
    }
}

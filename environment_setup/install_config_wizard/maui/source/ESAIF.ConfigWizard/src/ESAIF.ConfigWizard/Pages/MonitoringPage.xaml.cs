using ESAIF.ConfigWizard.ViewModels;
using ESAIF.ConfigWizard.Services;

namespace ESAIF.ConfigWizard.Pages;

public partial class MonitoringPage : ContentPage
{
    private readonly MonitoringViewModel _viewModel;
    private bool _isLoaded;
    private bool _singleColumn;
    private readonly IThemeService _themeService;

    public MonitoringPage()
        : this(AppServices.GetRequiredService<MonitoringViewModel>())
    {
    }

    public MonitoringPage(MonitoringViewModel viewModel)
    {
        try
        {
            InitializeComponent();
        }
        catch (Exception exception)
        {
            RuntimeDiagnostics.Write("last-page-error.log", exception);
            throw;
        }

        _viewModel = viewModel;
        _themeService = AppServices.GetRequiredService<IThemeService>();
        BindingContext = viewModel;
    }

    protected override async void OnAppearing()
    {
        base.OnAppearing();
        _themeService.ThemeChanged -= OnThemeChanged;
        _themeService.ThemeChanged += OnThemeChanged;
        _viewModel.RefreshChartTheme();
        if (!_isLoaded)
        {
            _isLoaded = true;
            await _viewModel.LoadAsync();
        }
    }

    protected override void OnDisappearing()
    {
        _themeService.ThemeChanged -= OnThemeChanged;
        base.OnDisappearing();
    }

    private void OnThemeChanged(object? sender, EventArgs e) =>
        MainThread.BeginInvokeOnMainThread(_viewModel.RefreshChartTheme);

    protected override void OnSizeAllocated(double width, double height)
    {
        base.OnSizeAllocated(width, height);
        var singleColumn = width < 900;
        if (singleColumn == _singleColumn)
        {
            return;
        }

        _singleColumn = singleColumn;
        var cards = new[]
        {
            TokensChartCard,
            RequestsChartCard,
            TokenMixChartCard,
            ModelsChartCard,
            SuccessChartCard,
            LatencyChartCard,
            ServicesChartCard,
            EnvironmentsChartCard
        };

        ChartsGrid.ColumnDefinitions.Clear();
        ChartsGrid.RowDefinitions.Clear();
        if (singleColumn)
        {
            ChartsGrid.ColumnDefinitions.Add(new ColumnDefinition(GridLength.Star));
            foreach (var card in cards)
            {
                ChartsGrid.RowDefinitions.Add(new RowDefinition(GridLength.Auto));
            }

            for (var index = 0; index < cards.Length; index++)
            {
                Grid.SetRow(cards[index], index);
                Grid.SetColumn(cards[index], 0);
            }
        }
        else
        {
            ChartsGrid.ColumnDefinitions.Add(new ColumnDefinition(GridLength.Star));
            ChartsGrid.ColumnDefinitions.Add(new ColumnDefinition(GridLength.Star));
            for (var index = 0; index < cards.Length / 2; index++)
            {
                ChartsGrid.RowDefinitions.Add(new RowDefinition(GridLength.Auto));
            }

            for (var index = 0; index < cards.Length; index++)
            {
                Grid.SetRow(cards[index], index / 2);
                Grid.SetColumn(cards[index], index % 2);
            }
        }
    }
}

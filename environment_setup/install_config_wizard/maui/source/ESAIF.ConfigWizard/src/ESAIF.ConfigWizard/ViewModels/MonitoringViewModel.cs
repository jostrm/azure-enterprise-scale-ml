using ESAIF.BaseLayer.Application;
using ESAIF.BaseLayer.Monitoring;
using ESAIF.ConfigWizard.Services;
using ESAIF.DomainLayer.Operations;
using LiveChartsCore;
using LiveChartsCore.SkiaSharpView;
using LiveChartsCore.SkiaSharpView.Painting;

namespace ESAIF.ConfigWizard.ViewModels;

public sealed class MonitoringViewModel : OperationViewModel
{
    private readonly OperationsSession _operations;
    private string _sourceLabel = "Local";
    private string _missingFolderMessage = string.Empty;
    private string _requests = "0";
    private string _inputTokens = "0";
    private string _cachedTokens = "0";
    private string _outputTokens = "0";
    private string _successRate = "0%";
    private string _secondaryKpiLabel = "Resources";
    private string _secondaryKpiValue = "0";
    private bool _refreshFailed;
    private readonly ApiConnectionState _connection;
    private bool _isCurrentFactoryTab = true;

    public MonitoringViewModel(OperationsSession operations, ApiConnectionState connection,
        CurrentFactoryAnalyticsViewModel currentFactory)
    {
        _operations = operations;
        _connection = connection;
        CurrentFactory = currentFactory;
        ShowCurrentFactoryCommand = new AsyncCommand(() => { IsCurrentFactoryTab = true; return Task.CompletedTask; });
        ShowOverviewCommand = new AsyncCommand(() => { IsCurrentFactoryTab = false; return Task.CompletedTask; });
        _operations.OverviewChanged += OnOverviewChanged;
        PropertyChanged += (_, e) =>
        {
            if (e.PropertyName == nameof(IsBusy))
            {
                NotifyPulseState();
            }
        };
        _connection.PropertyChanged += (_, e) =>
        {
            if (e.PropertyName == nameof(ApiConnectionState.IsConnected))
            {
                NotifyPulseState();
            }
        };
        ExplorePromptsCommand = new AsyncCommand(
            () => AppShell.PushPageAsync(
                AppServices.GetRequiredService<Pages.PromptExplorerPage>()));
        OpenWizardCommand = new AsyncCommand(
            () => AppShell.NavigateToWorkspaceAsync(AppShell.WizardPageKey));
        ApplyOverview(_operations.Current);
    }

    public AsyncCommand ExplorePromptsCommand { get; }

    public AsyncCommand OpenWizardCommand { get; }
    public CurrentFactoryAnalyticsViewModel CurrentFactory { get; }
    public AsyncCommand ShowCurrentFactoryCommand { get; }
    public AsyncCommand ShowOverviewCommand { get; }
    public bool IsCurrentFactoryTab
    {
        get => _isCurrentFactoryTab;
        private set
        {
            if (SetProperty(ref _isCurrentFactoryTab, value))
                OnPropertyChanged(nameof(IsOverviewTab));
        }
    }
    public bool IsOverviewTab => !IsCurrentFactoryTab;

    public string SourceLabel
    {
        get => _sourceLabel;
        private set => SetProperty(ref _sourceLabel, value);
    }

    public string MissingFolderMessage
    {
        get => _missingFolderMessage;
        private set
        {
            if (SetProperty(ref _missingFolderMessage, value))
            {
                OnPropertyChanged(nameof(IsMissingFolder));
            }
        }
    }

    public bool IsMissingFolder => !string.IsNullOrWhiteSpace(MissingFolderMessage);

    public bool HasOverview => _operations.HasOverview;
    public bool HasMockData { get; private set; }

    public SourceStatus SourceStatus { get; private set; } = StatusPresentation.FromSource(null);
    public SourceStatus PromptSource { get; private set; } = StatusPresentation.FromSource(null);
    public SourceStatus InventorySource { get; private set; } = StatusPresentation.FromSource(null);
    public SourceStatus SecondaryKpiSource { get; private set; } = StatusPresentation.FromSource(null);
    public SourceStatus TokensSource { get; private set; } = StatusPresentation.FromSource(null);
    public SourceStatus RequestsSource { get; private set; } = StatusPresentation.FromSource(null);
    public SourceStatus ModelsSource { get; private set; } = StatusPresentation.FromSource(null);
    public SourceStatus LatencySource { get; private set; } = StatusPresentation.FromSource(null);
    public SourceStatus ServicesSource { get; private set; } = StatusPresentation.FromSource(null);
    public SourceStatus EnvironmentsSource { get; private set; } = StatusPresentation.FromSource(null);
    public Color SourceLightColor => Color.FromArgb(SourceStatus.ColorHex);
    public bool IsSourcePulsing => IsBusy && !_refreshFailed && _connection.IsConnected && SourceStatus.IsRealCollection;
    public bool IsInventoryPulsing => IsBusy && !_refreshFailed && _connection.IsConnected && InventorySource.IsRealCollection;
    public SolidColorPaint ChartTextPaint { get; private set; } = LiveChartsFactory.CreateTextPaint();

    public string Requests
    {
        get => _requests;
        private set => SetProperty(ref _requests, value);
    }

    public string InputTokens
    {
        get => _inputTokens;
        private set => SetProperty(ref _inputTokens, value);
    }

    public string CachedTokens
    {
        get => _cachedTokens;
        private set => SetProperty(ref _cachedTokens, value);
    }

    public string OutputTokens
    {
        get => _outputTokens;
        private set => SetProperty(ref _outputTokens, value);
    }

    public string SuccessRate
    {
        get => _successRate;
        private set => SetProperty(ref _successRate, value);
    }

    public string SecondaryKpiLabel
    {
        get => _secondaryKpiLabel;
        private set => SetProperty(ref _secondaryKpiLabel, value);
    }

    public string SecondaryKpiValue
    {
        get => _secondaryKpiValue;
        private set => SetProperty(ref _secondaryKpiValue, value);
    }

    public ISeries[] TokensOverTimeSeries { get; private set; } = [];
    public Axis[] TokensOverTimeXAxes { get; private set; } = [];
    public Axis[] TokensOverTimeYAxes { get; private set; } = [];
    public ISeries[] RequestsOverTimeSeries { get; private set; } = [];
    public Axis[] RequestsOverTimeXAxes { get; private set; } = [];
    public Axis[] RequestsOverTimeYAxes { get; private set; } = [];
    public ISeries[] TokenMixSeries { get; private set; } = [];
    public ISeries[] RequestsByModelSeries { get; private set; } = [];
    public Axis[] RequestsByModelXAxes { get; private set; } = [];
    public Axis[] RequestsByModelYAxes { get; private set; } = [];
    public ISeries[] SuccessErrorSeries { get; private set; } = [];
    public ISeries[] LatencySeries { get; private set; } = [];
    public Axis[] LatencyXAxes { get; private set; } = [];
    public Axis[] LatencyYAxes { get; private set; } = [];
    public ISeries[] ResourceServicesSeries { get; private set; } = [];
    public ISeries[] EnvironmentsSeries { get; private set; } = [];
    public Axis[] EnvironmentsXAxes { get; private set; } = [];
    public Axis[] EnvironmentsYAxes { get; private set; } = [];

    public async Task LoadAsync(bool forceRefresh = false)
    {
        var analyticsRefresh = CurrentFactory.RefreshAsync();
        await ExecuteOperationAsync(async () =>
        {
            _refreshFailed = false;
            var overview = await _operations.LoadAsync(forceRefresh, includeAzure: true);
            ApplyOverview(overview);
            StatusMessage = overview is null
                ? MissingFolderMessage
                : $"Snapshot collected {FormatGeneratedAt(overview.GeneratedAt)} · refresh on request.";
        }, forceRefresh
            ? "Collecting an Azure inventory snapshot..."
            : "Loading operations overview...");
        await analyticsRefresh;
        await CurrentFactory.RefreshAsync();
    }

    private void OnOverviewChanged(object? sender, EventArgs e)
    {
        _refreshFailed = false;
        ApplyOverview(_operations.Current);
        StatusMessage = _operations.Current is { } overview
            ? $"Snapshot collected {FormatGeneratedAt(overview.GeneratedAt)}"
            : _operations.MissingFolderMessage;
    }

    private void ApplyOverview(OperationsOverview? overview)
    {
        UpdateSourceStatus(overview);
        Warning = _operations.Warning;
        MissingFolderMessage = _operations.MissingFolderMessage;
        OnPropertyChanged(nameof(HasOverview));

        var summary = overview?.PromptSummary ?? new PromptSummary();
        var telemetryUnavailable = summary.Source == "unavailable";
        Requests = telemetryUnavailable ? "Unavailable" : summary.RecordCount.ToString("N0");
        InputTokens = telemetryUnavailable ? "Unavailable" : Math.Max(0, summary.InputTokens).ToString("N0");
        CachedTokens = telemetryUnavailable ? "Unavailable" : Math.Max(0, summary.CachedInputTokens).ToString("N0");
        OutputTokens = telemetryUnavailable ? "Unavailable" : Math.Max(0, summary.OutputTokens).ToString("N0");
        SuccessRate = telemetryUnavailable ? "Unavailable" : $"{OperationsPresentation.GetSuccessRate(summary):0.#}%";

        var monitoring = overview?.Monitoring ?? new MonitoringChartCollection();
        HasMockData = summary.Source == "mock" || new[]
        {
            monitoring.TokensOverTime, monitoring.RequestsOverTime, monitoring.RequestsByModel,
            monitoring.LatencyTrend, monitoring.ResourcesByServiceType, monitoring.ResourcesByEnvironment
        }.Any(chart => chart.Source == "mock");
        OnPropertyChanged(nameof(HasMockData));
        PromptSource = StatusPresentation.FromSource(overview?.PromptSummary.Source);
        InventorySource = StatusPresentation.FromSource(overview?.ResourceInventory.Source);
        TokensSource = StatusPresentation.ForChart(monitoring.TokensOverTime, summary.Source);
        RequestsSource = StatusPresentation.ForChart(monitoring.RequestsOverTime, summary.Source);
        ModelsSource = StatusPresentation.ForChart(monitoring.RequestsByModel, summary.Source);
        LatencySource = StatusPresentation.ForChart(monitoring.LatencyTrend, summary.Source);
        ServicesSource = StatusPresentation.ForChart(monitoring.ResourcesByServiceType, overview?.ResourceInventory.Source);
        EnvironmentsSource = StatusPresentation.ForChart(monitoring.ResourcesByEnvironment, overview?.ResourceInventory.Source);
        var averageLatency = OperationsPresentation.GetWeightedAverage(
            monitoring.LatencyTrend,
            monitoring.RequestsOverTime);
        SecondaryKpiLabel = averageLatency is null ? "Resources" : "Avg latency";
        SecondaryKpiValue = averageLatency is null
            ? overview?.ResourceInventory.Source == "unavailable"
                ? "Unavailable"
                : (overview?.ResourceInventory.ResourceCount ?? 0).ToString("N0")
            : $"{averageLatency:0} ms";
        SecondaryKpiSource = averageLatency is null ? InventorySource : LatencySource;
        foreach (var property in new[]
        {
            nameof(PromptSource), nameof(InventorySource),
            nameof(SecondaryKpiSource), nameof(TokensSource), nameof(RequestsSource), nameof(ModelsSource),
            nameof(LatencySource), nameof(ServicesSource), nameof(EnvironmentsSource)
        })
        {
            OnPropertyChanged(property);
        }

        NotifyPulseState();
        SetCharts(monitoring, summary);
    }

    public void RefreshChartTheme()
    {
        ChartTextPaint = LiveChartsFactory.CreateTextPaint();
        OnPropertyChanged(nameof(ChartTextPaint));
        foreach (var axis in TokensOverTimeXAxes.Concat(TokensOverTimeYAxes)
                     .Concat(RequestsOverTimeXAxes).Concat(RequestsOverTimeYAxes)
                     .Concat(RequestsByModelXAxes).Concat(RequestsByModelYAxes)
                     .Concat(LatencyXAxes).Concat(LatencyYAxes)
                     .Concat(EnvironmentsXAxes).Concat(EnvironmentsYAxes))
        {
            axis.LabelsPaint = LiveChartsFactory.CreateTextPaint();
            if (axis.SeparatorsPaint is not null)
            {
                axis.SeparatorsPaint = LiveChartsFactory.CreateGridPaint();
            }
        }
    }

    protected override void OnOperationFailed(Exception exception)
    {
        RuntimeDiagnostics.Write("last-monitoring-error.log", exception);
        _refreshFailed = true;
        UpdateSourceStatus(_operations.Current);
        NotifyPulseState();
    }

    private void UpdateSourceStatus(OperationsOverview? overview)
    {
        SourceStatus = _refreshFailed
            ? new SourceStatus(overview is null
                ? "Refresh failed · no snapshot"
                : "Refresh failed · retained snapshot", "#E45664")
            : StatusPresentation.ForOverview(overview);
        SourceLabel = SourceStatus.Label;
        OnPropertyChanged(nameof(SourceStatus));
        OnPropertyChanged(nameof(SourceLightColor));
    }

    private void NotifyPulseState()
    {
        OnPropertyChanged(nameof(IsSourcePulsing));
        OnPropertyChanged(nameof(IsInventoryPulsing));
    }

    private void SetCharts(
        MonitoringChartCollection monitoring,
        PromptSummary summary)
    {
        SetLineChart(
            monitoring.TokensOverTime,
            series => TokensOverTimeSeries = series,
            axes => TokensOverTimeXAxes = axes,
            axes => TokensOverTimeYAxes = axes,
            nameof(TokensOverTimeSeries),
            nameof(TokensOverTimeXAxes),
            nameof(TokensOverTimeYAxes));
        SetLineChart(
            monitoring.RequestsOverTime,
            series => RequestsOverTimeSeries = series,
            axes => RequestsOverTimeXAxes = axes,
            axes => RequestsOverTimeYAxes = axes,
            nameof(RequestsOverTimeSeries),
            nameof(RequestsOverTimeXAxes),
            nameof(RequestsOverTimeYAxes));

        TokenMixSeries = LiveChartsFactory.CreatePieSeries(
            OperationsPresentation.BuildTokenMix(summary));
        OnPropertyChanged(nameof(TokenMixSeries));

        RequestsByModelSeries =
            LiveChartsFactory.CreateColumnSeries(monitoring.RequestsByModel);
        RequestsByModelXAxes =
            LiveChartsFactory.CreateCategoryAxes(monitoring.RequestsByModel);
        RequestsByModelYAxes = LiveChartsFactory.CreateValueAxes();
        OnPropertyChanged(nameof(RequestsByModelSeries));
        OnPropertyChanged(nameof(RequestsByModelXAxes));
        OnPropertyChanged(nameof(RequestsByModelYAxes));

        var successError = OperationsPresentation.BuildSuccessError(summary);
        SuccessErrorSeries = LiveChartsFactory.CreatePieSeries(successError);
        OnPropertyChanged(nameof(SuccessErrorSeries));

        SetLineChart(
            monitoring.LatencyTrend,
            series => LatencySeries = series,
            axes => LatencyXAxes = axes,
            axes => LatencyYAxes = axes,
            nameof(LatencySeries),
            nameof(LatencyXAxes),
            nameof(LatencyYAxes));

        ResourceServicesSeries =
            LiveChartsFactory.CreatePieSeries(monitoring.ResourcesByServiceType);
        OnPropertyChanged(nameof(ResourceServicesSeries));

        EnvironmentsSeries =
            LiveChartsFactory.CreateColumnSeries(monitoring.ResourcesByEnvironment);
        EnvironmentsXAxes =
            LiveChartsFactory.CreateCategoryAxes(monitoring.ResourcesByEnvironment);
        EnvironmentsYAxes = LiveChartsFactory.CreateValueAxes();
        OnPropertyChanged(nameof(EnvironmentsSeries));
        OnPropertyChanged(nameof(EnvironmentsXAxes));
        OnPropertyChanged(nameof(EnvironmentsYAxes));
    }

    private void SetLineChart(
        ChartDataSet chart,
        Action<ISeries[]> setSeries,
        Action<Axis[]> setXAxes,
        Action<Axis[]> setYAxes,
        string seriesProperty,
        string xAxesProperty,
        string yAxesProperty)
    {
        setSeries(LiveChartsFactory.CreateLineSeries(chart));
        setXAxes(LiveChartsFactory.CreateCategoryAxes(chart));
        setYAxes(LiveChartsFactory.CreateValueAxes());
        OnPropertyChanged(seriesProperty);
        OnPropertyChanged(xAxesProperty);
        OnPropertyChanged(yAxesProperty);
    }

    private static string FormatGeneratedAt(string generatedAt)
    {
        return DateTimeOffset.TryParse(generatedAt, out var timestamp)
            ? timestamp.ToLocalTime().ToString("g")
            : generatedAt;
    }
}

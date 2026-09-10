using ESAIF.BaseLayer.Monitoring;
using LiveChartsCore;
using LiveChartsCore.SkiaSharpView;
using LiveChartsCore.SkiaSharpView.Painting;
using SkiaSharp;

namespace ESAIF.ConfigWizard.Services;

public static class LiveChartsFactory
{
    private static readonly SKColor[] Palette =
    [
        new(0x67, 0x50, 0xA4),
        new(0x0F, 0x6C, 0xBD),
        new(0x00, 0x6B, 0x75),
        new(0xD8, 0x3B, 0x01),
        new(0x49, 0x8B, 0xE8),
        new(0x87, 0x68, 0xA8),
        new(0x10, 0x7C, 0x10),
        new(0xC2, 0x39, 0xB3)
    ];

    public static SolidColorPaint CreateTextPaint() =>
        new(ResourceColor("Text", new SKColor(0x68, 0x63, 0x70)));

    public static SolidColorPaint CreateGridPaint() =>
        new(ResourceColor("Border", new SKColor(0xE1, 0xDD, 0xE7)), 1);

    private static SKColor ResourceColor(string key, SKColor fallback)
    {
        if (Application.Current?.Resources.TryGetValue(key, out var value) == true && value is Color color)
        {
            return new SKColor((byte)(color.Red * 255), (byte)(color.Green * 255), (byte)(color.Blue * 255));
        }

        return fallback;
    }

    public static ISeries[] CreateLineSeries(ChartDataSet chart)
    {
        chart = MonitoringDataAdapter.ValidateAndAlign(chart);
        return EnumerateSeries(chart)
            .Select((series, index) =>
            {
                var color = GetSeriesColor(series.Name, index);
                return (ISeries)new LineSeries<double>
                {
                    Name = OperationsPresentation.GetSeriesDisplayName(series.Name),
                    Values = series.Values,
                    Fill = null,
                    Stroke = new SolidColorPaint(color, 3),
                    GeometryFill = new SolidColorPaint(color),
                    GeometryStroke = new SolidColorPaint(color, 2),
                    GeometrySize = 7,
                    LineSmoothness = 0.25
                };
            })
            .ToArray();
    }

    public static ISeries[] CreateColumnSeries(
        ChartDataSet chart,
        bool horizontal = false)
    {
        chart = MonitoringDataAdapter.ValidateAndAlign(chart);
        return EnumerateSeries(chart)
            .Select((series, index) =>
            {
                var color = GetSeriesColor(series.Name, index);
                if (horizontal)
                {
                    return (ISeries)new RowSeries<double>
                    {
                        Name = OperationsPresentation.GetSeriesDisplayName(series.Name),
                        Values = series.Values,
                        Fill = new SolidColorPaint(color),
                        Stroke = null
                    };
                }

                return chart.Stacked
                    ? new StackedColumnSeries<double>
                    {
                        Name = OperationsPresentation.GetSeriesDisplayName(series.Name),
                        Values = series.Values,
                        Fill = new SolidColorPaint(color),
                        Stroke = null
                    }
                    : new ColumnSeries<double>
                    {
                        Name = OperationsPresentation.GetSeriesDisplayName(series.Name),
                        Values = series.Values,
                        Fill = new SolidColorPaint(color),
                        Stroke = null
                    };
            })
            .ToArray();
    }

    public static ISeries[] CreatePieSeries(ChartDataSet chart)
    {
        chart = MonitoringDataAdapter.ValidateAndAlign(chart);
        var values = chart.Values.Count > 0
            ? chart.Values
            : chart.Series.Values.FirstOrDefault() ?? [];

        return chart.Labels
            .Zip(values, (label, value) => (label, value))
            .Select((item, index) => (ISeries)new PieSeries<double>
            {
                Name = item.label,
                Values = [item.value],
                Fill = new SolidColorPaint(Palette[index % Palette.Length]),
                Stroke = null
            })
            .ToArray();
    }

    public static Axis[] CreateCategoryAxes(
        ChartDataSet chart,
        bool horizontal = false)
    {
        chart = MonitoringDataAdapter.ValidateAndAlign(chart);
        return
        [
            new Axis
            {
                Labels = chart.Labels.ToArray(),
                LabelsPaint = CreateTextPaint(),
                SeparatorsPaint = horizontal
                    ? null
                    : CreateGridPaint(),
                TextSize = 11,
                LabelsRotation = chart.Labels.Count > 8 ? 25 : 0
            }
        ];
    }

    public static Axis[] CreateValueAxes(bool horizontal = false)
    {
        return
        [
            new Axis
            {
                LabelsPaint = CreateTextPaint(),
                SeparatorsPaint = horizontal
                    ? CreateGridPaint()
                    : null,
                TextSize = 11,
                MinLimit = 0
            }
        ];
    }

    private static IEnumerable<(string Name, IReadOnlyList<double> Values)> EnumerateSeries(
        ChartDataSet chart)
    {
        if (chart.Series.Count > 0)
        {
            return chart.Series.Select(item => (item.Key, item.Value));
        }

        return [("Value", chart.Values)];
    }

    private static SKColor GetSeriesColor(string name, int index)
    {
        var normalized = name.Replace("-", "_", StringComparison.Ordinal)
            .Replace(" ", "_", StringComparison.Ordinal)
            .ToLowerInvariant();
        return normalized switch
        {
            "input" or "input_tokens" or "non_cached_input" => Palette[1],
            "cached" or "cached_input" or "cached_input_tokens" => Palette[3],
            "output" or "output_tokens" => Palette[2],
            _ => Palette[index % Palette.Length]
        };
    }

}

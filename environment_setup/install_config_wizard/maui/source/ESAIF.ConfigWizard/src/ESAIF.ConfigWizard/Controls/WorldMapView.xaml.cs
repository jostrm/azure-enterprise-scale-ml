using System.Collections;
using System.Collections.Specialized;
using System.Globalization;
using System.Windows.Input;
using ESAIF.ConfigWizard.Services;
using ESAIF.DomainLayer.Operations;
using Microsoft.Maui.Layouts;

namespace ESAIF.ConfigWizard.Controls;

public sealed class RegionTappedEventArgs(AzureRegionInfo region) : EventArgs
{
    public AzureRegionInfo Region { get; } = region;
}

public partial class WorldMapView : ContentView
{
    public static readonly BindableProperty ItemsSourceProperty = BindableProperty.Create(
        nameof(ItemsSource), typeof(IEnumerable), typeof(WorldMapView),
        propertyChanged: (bindable, _, _) => ((WorldMapView)bindable).OnItemsChanged());

    public static readonly BindableProperty SelectedRegionProperty = BindableProperty.Create(
        nameof(SelectedRegion), typeof(AzureRegionInfo), typeof(WorldMapView),
        defaultBindingMode: BindingMode.TwoWay,
        propertyChanged: (bindable, _, _) => ((WorldMapView)bindable).UpdateSelection());

    public static readonly BindableProperty PrimaryCommandProperty = BindableProperty.Create(
        nameof(PrimaryCommand), typeof(ICommand), typeof(WorldMapView));

    public static readonly BindableProperty SecondaryCommandProperty = BindableProperty.Create(
        nameof(SecondaryCommand), typeof(ICommand), typeof(WorldMapView));

    private readonly List<(AzureRegionInfo Region, Border Ring, StatusLight Light)> _markers = [];
    private INotifyCollectionChanged? _observableItems;
    private bool _loaded;
    private bool _sceneActive = true;
    private bool _rebuildQueued;
    private bool _syncingPicker;
    private bool _animateLights = true;

    public WorldMapView()
    {
        InitializeComponent();
        Loaded += OnLoaded;
        Unloaded += OnUnloaded;
    }

    public event EventHandler<RegionTappedEventArgs>? RegionPrimaryTapped;
    public event EventHandler<RegionTappedEventArgs>? RegionSecondaryTapped;

    public IEnumerable? ItemsSource
    {
        get => (IEnumerable?)GetValue(ItemsSourceProperty);
        set => SetValue(ItemsSourceProperty, value);
    }

    public AzureRegionInfo? SelectedRegion
    {
        get => (AzureRegionInfo?)GetValue(SelectedRegionProperty);
        set => SetValue(SelectedRegionProperty, value);
    }

    public ICommand? PrimaryCommand
    {
        get => (ICommand?)GetValue(PrimaryCommandProperty);
        set => SetValue(PrimaryCommandProperty, value);
    }

    public ICommand? SecondaryCommand
    {
        get => (ICommand?)GetValue(SecondaryCommandProperty);
        set => SetValue(SecondaryCommandProperty, value);
    }

    public void SetSceneActive(bool active)
    {
        _sceneActive = active;
        UpdateSelection();
    }

    private void OnLoaded(object? sender, EventArgs e)
    {
        _loaded = true;
        OnItemsChanged();
    }

    private void OnUnloaded(object? sender, EventArgs e)
    {
        _loaded = false;
        DetachItems();
        foreach (var marker in _markers)
        {
            marker.Light.IsActive = false;
        }
    }

    private void DetachItems()
    {
        if (_observableItems is not null)
        {
            _observableItems.CollectionChanged -= OnCollectionChanged;
            _observableItems = null;
        }
    }

    private void OnItemsChanged()
    {
        DetachItems();
        if (_loaded && ItemsSource is INotifyCollectionChanged observable)
        {
            _observableItems = observable;
            observable.CollectionChanged += OnCollectionChanged;
        }

        QueueRebuild();
    }

    private void OnCollectionChanged(object? sender, NotifyCollectionChangedEventArgs e) => QueueRebuild();

    private void QueueRebuild()
    {
        if (!_loaded || _rebuildQueued)
        {
            return;
        }

        _rebuildQueued = true;
        Dispatcher.Dispatch(() =>
        {
            _rebuildQueued = false;
            if (_loaded)
            {
                RebuildMarkers();
            }
        });
    }

    private void OnCanvasSizeChanged(object? sender, EventArgs e) => QueueRebuild();

    private void RebuildMarkers()
    {
        if (MapScene.Width <= 0 || MapScene.Height <= 0 || MapHeader.Height < 0 || MapLegend.Height < 0)
        {
            return; // SizeChanged will retry after the header and legend have been measured.
        }
        var availableHeight = Math.Max(0,
            MapScene.Height - MapHeader.Height - MapLegend.Height - 2 * MapScene.RowSpacing);
        var viewport = RegionMapPresentation.FitViewport(MapScene.Width, availableHeight);
        // Size the map row to the fitted image so its legend follows immediately, not at the panel bottom.
        var mapRow = MapScene.RowDefinitions[1];
        if (!mapRow.Height.IsAbsolute || Math.Abs(mapRow.Height.Value - viewport.Height) > 0.1)
        {
            mapRow.Height = new GridLength(viewport.Height);
        }
        AbsoluteLayout.SetLayoutFlags(MapSurface, AbsoluteLayoutFlags.None);
        AbsoluteLayout.SetLayoutBounds(MapSurface, new Rect(viewport.X, viewport.Y, viewport.Width, viewport.Height));
        var regions = (ItemsSource?.OfType<AzureRegionInfo>() ?? [])
            .OrderBy(region => region.DisplayName, StringComparer.OrdinalIgnoreCase).ToArray();
        foreach (var marker in _markers)
        {
            marker.Light.IsActive = false;
        }

        _markers.Clear();
        MarkerLayer.Children.Clear();
        var positions = RegionMapPresentation.PositionMarkers(regions, viewport.Width, viewport.Height);
        foreach (var position in positions)
        {
            AddMarker(position);
        }

        LeaderLines.Drawable = new LocatorLines(positions);
        LeaderLines.Invalidate();
        _syncingPicker = true;
        RegionPicker.ItemsSource = regions;
        RegionPicker.SelectedItem = regions.FirstOrDefault(region => region.Name == SelectedRegion?.Name);
        _syncingPicker = false;
        var mappedRegions = regions.Where(RegionMapPresentation.IsGeographicRegion).ToArray();
        RegionCountLabel.Text = $"{mappedRegions.Length:00} MAPPED  /  {mappedRegions.Count(region => region.HasFactory):00} CONFIGURED";
        UpdateSelection();
    }

    private void AddMarker(MapMarkerPosition position)
    {
        var region = position.Region;
        var marker = new Grid { WidthRequest = 32, HeightRequest = 32, BackgroundColor = Colors.Transparent };
        var light = new StatusLight { InputTransparent = true, LightColor = MarkerColor(region), IsActive = false };
        marker.Children.Add(light);
        var ring = new Border
        {
            WidthRequest = 30, HeightRequest = 30, StrokeThickness = 1.5,
            Stroke = Color.FromArgb("#FFD48A"),
            StrokeShape = new Microsoft.Maui.Controls.Shapes.RoundRectangle { CornerRadius = 15 },
            HorizontalOptions = LayoutOptions.Center, VerticalOptions = LayoutOptions.Center,
            InputTransparent = true, IsVisible = false
        };
        marker.Children.Add(ring);

        // A real button retains keyboard/automation activation; secondary tap handles the context menu.
        var hitTarget = new Button
        {
            AutomationId = $"Region_{region.Name}", Text = string.Empty, BackgroundColor = Colors.Transparent,
            BorderWidth = 0, Padding = 0, MinimumHeightRequest = 0, MinimumWidthRequest = 0, CornerRadius = 16
        };
        SemanticProperties.SetDescription(hitTarget,
            TechnicalValuePresentation.Summary(RegionPipelinePresentation.HasFailure(region)
                ? RegionPipelinePresentation.Tooltip(region)
                : $"{region.DisplayName}, {region.Status}. {(region.HasFactory ? "AI Factory configured." : "Azure region.")}"));
        ToolTipProperties.SetText(hitTarget, RegionPipelinePresentation.Tooltip(region));
        hitTarget.Clicked += (_, _) => SelectRegion(region);
        var context = new TapGestureRecognizer { Buttons = ButtonsMask.Secondary };
        context.Tapped += (_, _) => OnSecondaryTapped(region);
        hitTarget.GestureRecognizers.Add(context);
        marker.Children.Add(hitTarget);
        AbsoluteLayout.SetLayoutFlags(marker, AbsoluteLayoutFlags.None);
        AbsoluteLayout.SetLayoutBounds(marker, new Rect(position.Center.X - 16, position.Center.Y - 16, 32, 32));
        MarkerLayer.Children.Add(marker);
        _markers.Add((region, ring, light));
    }

    private static Color MarkerColor(AzureRegionInfo region) =>
        Color.FromArgb(RegionPipelinePresentation.LightColor(region, selected: false));

    private void UpdateSelection()
    {
        foreach (var marker in _markers)
        {
            var selected = marker.Region.Name == SelectedRegion?.Name;
            marker.Ring.IsVisible = selected;
            marker.Light.LightColor = Color.FromArgb(RegionPipelinePresentation.LightColor(marker.Region, selected));
            marker.Light.IsActive = _loaded && _sceneActive;
            marker.Light.IsPulsing = _animateLights &&
                (selected || marker.Region.HasFactory || RegionPipelinePresentation.HasFailure(marker.Region));
        }

        if (RegionPicker is null)
        {
            return;
        }

        _syncingPicker = true;
        RegionPicker.SelectedItem = RegionPicker.ItemsSource?.Cast<AzureRegionInfo>()
            .FirstOrDefault(region => region.Name == SelectedRegion?.Name);
        _syncingPicker = false;
        CoordinateLabel.Value = SelectedRegion is not { } region
            ? "Select a light for details. Right-click for region actions."
            : !RegionMapPresentation.IsGeographicRegion(region)
                ? $"{region.DisplayName}  /  Non-regional service scope (not a physical location)"
                : string.Create(CultureInfo.InvariantCulture,
                $"{region.DisplayName}  /  {Math.Abs(region.Latitude):0.00}°{(region.Latitude >= 0 ? "N" : "S")}  {Math.Abs(region.Longitude):0.00}°{(region.Longitude >= 0 ? "E" : "W")}  /  {region.Status}");
    }

    private void OnMapMotionChanged(object? sender, ToggledEventArgs e)
    {
        _animateLights = e.Value;
        UpdateSelection();
    }

    private void OnRegionPickerChanged(object? sender, EventArgs e)
    {
        if (!_syncingPicker && RegionPicker.SelectedItem is AzureRegionInfo region)
        {
            SelectRegion(region);
        }
    }

    private void SelectRegion(AzureRegionInfo region)
    {
        SelectedRegion = region;
        if (PrimaryCommand?.CanExecute(region) == true)
        {
            PrimaryCommand.Execute(region);
        }

        RegionPrimaryTapped?.Invoke(this, new RegionTappedEventArgs(region));
    }

    private void OnSecondaryTapped(AzureRegionInfo region)
    {
        SelectedRegion = region;
        if (SecondaryCommand?.CanExecute(region) == true)
        {
            SecondaryCommand.Execute(region);
        }

        RegionSecondaryTapped?.Invoke(this, new RegionTappedEventArgs(region));
    }

    private sealed class LocatorLines(IReadOnlyList<MapMarkerPosition> positions) : IDrawable
    {
        public void Draw(ICanvas canvas, RectF dirtyRect)
        {
            canvas.StrokeColor = Color.FromArgb("#496B8C");
            canvas.StrokeSize = 0.65f;
            foreach (var position in positions)
            {
                if (Math.Abs(position.Anchor.X - position.Center.X) +
                    Math.Abs(position.Anchor.Y - position.Center.Y) < 5)
                {
                    continue;
                }

                canvas.DrawLine((float)position.Anchor.X, (float)position.Anchor.Y,
                    (float)position.Center.X, (float)position.Center.Y);
            }
        }
    }
}

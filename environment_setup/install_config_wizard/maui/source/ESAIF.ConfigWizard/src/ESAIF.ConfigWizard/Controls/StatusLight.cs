using ESAIF.ConfigWizard.Services;
using Microsoft.Maui.Controls.Shapes;

namespace ESAIF.ConfigWizard.Controls;

public sealed class StatusLight : ContentView
{
    private const string PulseAnimation = "StatusLightPulse";
    public static readonly BindableProperty LightColorProperty = BindableProperty.Create(
        nameof(LightColor), typeof(Color), typeof(StatusLight), Color.FromArgb("#22D3EE"),
        propertyChanged: OnAppearanceChanged);
    public static readonly BindableProperty IsPulsingProperty = BindableProperty.Create(
        nameof(IsPulsing), typeof(bool), typeof(StatusLight), false,
        propertyChanged: OnActivityChanged);
    public static readonly BindableProperty IsActiveProperty = BindableProperty.Create(
        nameof(IsActive), typeof(bool), typeof(StatusLight), true,
        propertyChanged: OnActivityChanged);
    public static readonly BindableProperty LabelProperty = BindableProperty.Create(
        nameof(Label), typeof(string), typeof(StatusLight), string.Empty,
        propertyChanged: OnAppearanceChanged);

    private readonly Ellipse _ring = new()
    {
        WidthRequest = 24, HeightRequest = 24, StrokeThickness = 1.5,
        HorizontalOptions = LayoutOptions.Center, VerticalOptions = LayoutOptions.Center,
        Opacity = 0, InputTransparent = true
    };
    private readonly Ellipse _core = new()
    {
        WidthRequest = 8, HeightRequest = 8,
        HorizontalOptions = LayoutOptions.Center, VerticalOptions = LayoutOptions.Center,
        InputTransparent = true
    };
    private readonly TechnicalLabel _label = new()
    {
        FontSize = 11, VerticalOptions = LayoutOptions.Center,
        LineBreakMode = LineBreakMode.WordWrap
    };
    private Window? _window;
    private Page? _page;
    private bool _loaded;
    private bool _windowActive = true;
    private bool _pageActive = true;
    private bool _animating;

    public StatusLight()
    {
        var indicator = new Grid { WidthRequest = 28, HeightRequest = 28, IsClippedToBounds = true };
        indicator.Children.Add(_ring);
        indicator.Children.Add(_core);
        var layout = new Grid
        {
            ColumnDefinitions = [new(GridLength.Auto), new(GridLength.Star)],
            ColumnSpacing = 3, VerticalOptions = LayoutOptions.Center,
            HorizontalOptions = LayoutOptions.Center
        };
        layout.Children.Add(indicator);
        layout.Children.Add(_label);
        Grid.SetColumn(_label, 1);
        _label.SetDynamicResource(Microsoft.Maui.Controls.Label.TextColorProperty, "Text");
        Content = layout;
        Loaded += OnLoaded;
        Unloaded += OnUnloaded;
        UpdateAppearance();
    }

    public Color LightColor { get => (Color)GetValue(LightColorProperty); set => SetValue(LightColorProperty, value); }
    public bool IsPulsing { get => (bool)GetValue(IsPulsingProperty); set => SetValue(IsPulsingProperty, value); }
    public bool IsActive { get => (bool)GetValue(IsActiveProperty); set => SetValue(IsActiveProperty, value); }
    public string Label { get => (string)GetValue(LabelProperty); set => SetValue(LabelProperty, value); }

    private static void OnAppearanceChanged(BindableObject view, object oldValue, object newValue) =>
        ((StatusLight)view).UpdateAppearance();

    private static void OnActivityChanged(BindableObject view, object oldValue, object newValue) =>
        ((StatusLight)view).UpdateAnimation();

    private void UpdateAppearance()
    {
        _core.Fill = new SolidColorBrush(LightColor);
        _ring.Stroke = new SolidColorBrush(LightColor);
        _label.Value = Label;
        _label.IsVisible = !string.IsNullOrWhiteSpace(Label);
        if (Content is Grid layout)
        {
            layout.ColumnSpacing = _label.IsVisible ? 3 : 0;
        }

        SemanticProperties.SetDescription(this, string.IsNullOrWhiteSpace(Label) ? null : TechnicalValuePresentation.Summary(Label));
        InputTransparent = !TechnicalValuePresentation.HasDetails(Label);
        // Unlabelled markers are decorative; their containing pin supplies the accessible name.
        AutomationProperties.SetIsInAccessibleTree(this, _label.IsVisible);
        AutomationProperties.SetIsInAccessibleTree(_label, false);
        AutomationProperties.SetIsInAccessibleTree(_core, false);
        AutomationProperties.SetIsInAccessibleTree(_ring, false);
    }

    private void OnLoaded(object? sender, EventArgs e)
    {
        if (_loaded)
        {
            return;
        }

        _loaded = true;
        _windowActive = true;
        _pageActive = true;
        MotionPreferences.Current.Changed += OnMotionChanged;
        _window = Window;
        if (_window is not null)
        {
            _window.Activated += OnWindowActivated;
            _window.Deactivated += OnWindowDeactivated;
            _window.Stopped += OnWindowDeactivated;
            _window.Destroying += OnWindowDeactivated;
        }

        for (Element? ancestor = Parent; ancestor is not null; ancestor = ancestor.Parent)
        {
            if (ancestor is Page page)
            {
                _page = page;
                page.Appearing += OnPageAppearing;
                page.Disappearing += OnPageDisappearing;
                break;
            }
        }

        UpdateAnimation();
    }

    private void OnUnloaded(object? sender, EventArgs e)
    {
        _loaded = false;
        MotionPreferences.Current.Changed -= OnMotionChanged;
        if (_window is not null)
        {
            _window.Activated -= OnWindowActivated;
            _window.Deactivated -= OnWindowDeactivated;
            _window.Stopped -= OnWindowDeactivated;
            _window.Destroying -= OnWindowDeactivated;
            _window = null;
        }

        if (_page is not null)
        {
            _page.Appearing -= OnPageAppearing;
            _page.Disappearing -= OnPageDisappearing;
            _page = null;
        }

        StopPulse();
    }

    private void OnMotionChanged(object? sender, EventArgs e) => UpdateAnimation();
    private void OnWindowActivated(object? sender, EventArgs e) { _windowActive = true; UpdateAnimation(); }
    private void OnWindowDeactivated(object? sender, EventArgs e) { _windowActive = false; StopPulse(); }
    private void OnPageAppearing(object? sender, EventArgs e) { _pageActive = true; UpdateAnimation(); }
    private void OnPageDisappearing(object? sender, EventArgs e) { _pageActive = false; StopPulse(); }

    protected override void OnPropertyChanged(string? propertyName = null)
    {
        base.OnPropertyChanged(propertyName);
        if (propertyName == nameof(IsVisible))
        {
            UpdateAnimation();
        }
    }

    private bool ShouldAnimate => StatusLightMotionPolicy.ShouldAnimate(
        _loaded, _windowActive, _pageActive, IsVisible, IsActive, IsPulsing,
        MotionPreferences.Current.AreStatusLightAnimationsEnabled);

    private void UpdateAnimation()
    {
        if (!ShouldAnimate)
        {
            StopPulse();
            return;
        }

        if (_animating)
        {
            return;
        }

        _animating = true;
        new Animation(progress =>
        {
            _ring.Scale = 0.4 + 0.6 * progress;
            _ring.Opacity = 0.38 * Math.Sin(Math.PI * progress);
        }).Commit(this, PulseAnimation, rate: 32,
            length: StatusLightMotionPolicy.CycleMilliseconds, repeat: () => ShouldAnimate);
    }

    private void StopPulse()
    {
        if (_animating)
        {
            this.AbortAnimation(PulseAnimation);
            _animating = false;
        }

        _ring.Opacity = 0;
    }
}

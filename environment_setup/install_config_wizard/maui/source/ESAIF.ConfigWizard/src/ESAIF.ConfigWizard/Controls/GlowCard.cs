using System.Diagnostics;
using ESAIF.ConfigWizard.Services;
using SkiaSharp;
using SkiaSharp.Views.Maui;
using SkiaSharp.Views.Maui.Controls;

namespace ESAIF.ConfigWizard.Controls;

[ContentProperty(nameof(Card))]
public sealed class GlowCard : ContentView
{
    public static readonly BindableProperty CardProperty = BindableProperty.Create(
        nameof(Card), typeof(View), typeof(GlowCard), propertyChanged: (owner, _, value) =>
            ((GlowCard)owner)._slot.Content = (View?)value);
    public static readonly BindableProperty IsSelectedProperty = BindableProperty.Create(
        nameof(IsSelected), typeof(bool), typeof(GlowCard), false,
        propertyChanged: (owner, _, _) => ((GlowCard)owner).UpdateAnimation());
    public static readonly BindableProperty CornerRadiusProperty = BindableProperty.Create(
        nameof(CornerRadius), typeof(double), typeof(GlowCard), 18d,
        propertyChanged: (owner, _, _) => ((GlowCard)owner)._canvas.InvalidateSurface());
    private readonly ContentView _slot = new() { Margin = 8 };
    private readonly SKCanvasView _canvas = new() { InputTransparent = true, IgnorePixelScaling = true, IsVisible = false, ZIndex = 1 };
    private readonly IDispatcherTimer _timer;
    private readonly Stopwatch _clock = new();
    private Window? _window;
    private Page? _page;
    private bool _loaded;
    private bool _active = true;
    private bool _pageActive = true;

    public GlowCard()
    {
        Content = new Grid { Children = { _slot, _canvas } };
        _canvas.PaintSurface += DrawGlow;
        _timer = Dispatcher.CreateTimer();
        _timer.Interval = TimeSpan.FromMilliseconds(50);
        _timer.Tick += (_, _) => _canvas.InvalidateSurface();
        Loaded += OnLoaded;
        Unloaded += OnUnloaded;
        SizeChanged += (_, _) => _canvas.InvalidateSurface();
    }

    public View? Card { get => (View?)GetValue(CardProperty); set => SetValue(CardProperty, value); }
    public bool IsSelected { get => (bool)GetValue(IsSelectedProperty); set => SetValue(IsSelectedProperty, value); }
    public double CornerRadius { get => (double)GetValue(CornerRadiusProperty); set => SetValue(CornerRadiusProperty, value); }

    private void DrawGlow(object? sender, SKPaintSurfaceEventArgs e)
    {
        var canvas = e.Surface.Canvas;
        canvas.Clear(SKColors.Transparent);
        if (!IsSelected || e.Info.Width < 20 || e.Info.Height < 20) { return; }
        var center = new SKPoint(e.Info.Width / 2f, e.Info.Height / 2f);
        using var baseShader = SKShader.CreateSweepGradient(center,
            [SKColor.Parse("#46D9FF"), SKColor.Parse("#8065FF"), SKColor.Parse("#F877D6"),
             SKColor.Parse("#FFC477"), SKColor.Parse("#46D9FF")], [0f, .3f, .55f, .78f, 1f]);
        var phase = MotionPreferences.Current.AreStatusLightAnimationsEnabled
            ? (float)(_clock.Elapsed.TotalSeconds % 9 / 9 * 360) : 0;
        using var shader = baseShader.WithLocalMatrix(SKMatrix.CreateRotationDegrees(phase, center.X, center.Y));
        using var blur = SKMaskFilter.CreateBlur(SKBlurStyle.Normal, 4);
        using var paint = new SKPaint
        {
            IsAntialias = true, Style = SKPaintStyle.Stroke, StrokeWidth = 7,
            Shader = shader, MaskFilter = blur, Color = SKColors.White.WithAlpha(175)
        };
        var bounds = new SKRect(8, 8, e.Info.Width - 8, e.Info.Height - 8);
        canvas.DrawRoundRect(bounds, (float)CornerRadius, (float)CornerRadius, paint);
        paint.MaskFilter = null;
        paint.StrokeWidth = 2.5f;
        paint.Color = SKColors.White;
        canvas.DrawRoundRect(bounds, (float)CornerRadius, (float)CornerRadius, paint);
    }

    private void OnLoaded(object? sender, EventArgs e)
    {
        if (_loaded) { return; }
        _loaded = true;
        _active = _pageActive = true;
        _window = Window;
        if (_window is not null)
        {
            _window.Activated += OnActivated;
            _window.Deactivated += OnDeactivated;
            _window.Stopped += OnDeactivated;
        }
        for (Element? ancestor = Parent; ancestor is not null; ancestor = ancestor.Parent)
        {
            if (ancestor is Page page)
            {
                _page = page;
                page.Appearing += OnAppearing;
                page.Disappearing += OnDisappearing;
                break;
            }
        }
        MotionPreferences.Current.Changed += OnMotionChanged;
        UpdateAnimation();
    }

    private void OnUnloaded(object? sender, EventArgs e)
    {
        _loaded = false;
        if (_window is not null)
        {
            _window.Activated -= OnActivated;
            _window.Deactivated -= OnDeactivated;
            _window.Stopped -= OnDeactivated;
            _window = null;
        }
        if (_page is not null)
        {
            _page.Appearing -= OnAppearing;
            _page.Disappearing -= OnDisappearing;
            _page = null;
        }
        MotionPreferences.Current.Changed -= OnMotionChanged;
        UpdateAnimation();
    }

    private void OnActivated(object? sender, EventArgs e) { _active = true; UpdateAnimation(); }
    private void OnDeactivated(object? sender, EventArgs e) { _active = false; UpdateAnimation(); }
    private void OnAppearing(object? sender, EventArgs e) { _pageActive = true; UpdateAnimation(); }
    private void OnDisappearing(object? sender, EventArgs e) { _pageActive = false; UpdateAnimation(); }
    private void OnMotionChanged(object? sender, EventArgs e) => UpdateAnimation();

    private void UpdateAnimation()
    {
        _canvas.IsVisible = IsSelected;
        if (_loaded && _active && _pageActive && IsVisible && IsSelected && MotionPreferences.Current.AreStatusLightAnimationsEnabled)
        {
            _clock.Start();
            _timer.Start();
        }
        else
        {
            _clock.Stop();
            _timer.Stop();
        }
        _canvas.InvalidateSurface();
    }

    protected override void OnPropertyChanged(string? propertyName = null)
    {
        base.OnPropertyChanged(propertyName);
        if (propertyName == nameof(IsVisible) && _timer is not null)
        {
            UpdateAnimation();
        }
    }
}

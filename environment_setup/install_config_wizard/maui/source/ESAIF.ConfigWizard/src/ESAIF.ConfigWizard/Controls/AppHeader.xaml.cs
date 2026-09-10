namespace ESAIF.ConfigWizard.Controls;

public partial class AppHeader : ContentView
{
    public static readonly BindableProperty TitleProperty = BindableProperty.Create(
        nameof(Title),
        typeof(string),
        typeof(AppHeader),
        string.Empty);

    public static readonly BindableProperty SubtitleProperty = BindableProperty.Create(
        nameof(Subtitle),
        typeof(string),
        typeof(AppHeader),
        string.Empty);

    public static readonly BindableProperty TrailingTextProperty = BindableProperty.Create(
        nameof(TrailingText),
        typeof(string),
        typeof(AppHeader),
        string.Empty,
        propertyChanged: OnTrailingTextChanged);

    public static readonly BindableProperty ShowStatusLightProperty = BindableProperty.Create(
        nameof(ShowStatusLight), typeof(bool), typeof(AppHeader), false);
    public static readonly BindableProperty StatusLightColorProperty = BindableProperty.Create(
        nameof(StatusLightColor), typeof(Color), typeof(AppHeader), Color.FromArgb("#22D3EE"));
    public static readonly BindableProperty IsStatusPulsingProperty = BindableProperty.Create(
        nameof(IsStatusPulsing), typeof(bool), typeof(AppHeader), false);

    public AppHeader()
    {
        InitializeComponent();
        UpdateTrailingBadge();
    }

    public string Title
    {
        get => (string) GetValue(TitleProperty);
        set => SetValue(TitleProperty, value);
    }

    public string Subtitle
    {
        get => (string) GetValue(SubtitleProperty);
        set => SetValue(SubtitleProperty, value);
    }

    public string TrailingText
    {
        get => (string) GetValue(TrailingTextProperty);
        set => SetValue(TrailingTextProperty, value);
    }

    public bool ShowStatusLight { get => (bool)GetValue(ShowStatusLightProperty); set => SetValue(ShowStatusLightProperty, value); }
    public Color StatusLightColor { get => (Color)GetValue(StatusLightColorProperty); set => SetValue(StatusLightColorProperty, value); }
    public bool IsStatusPulsing { get => (bool)GetValue(IsStatusPulsingProperty); set => SetValue(IsStatusPulsingProperty, value); }

    private static void OnTrailingTextChanged(
        BindableObject bindable,
        object oldValue,
        object newValue)
    {
        ((AppHeader) bindable).UpdateTrailingBadge();
    }

    private void UpdateTrailingBadge()
    {
        TrailingBadge.IsVisible = !string.IsNullOrWhiteSpace(TrailingText);
    }

    private void OnMenuClicked(object? sender, EventArgs e)
    {
        AppShell.OpenFlyout();
    }
}

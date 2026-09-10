namespace ESAIF.ConfigWizard.Services;

public sealed class ThemeService : IThemeService
{
    private readonly IThemePreferenceStore _preferenceStore;
    private Application? _application;

    public ThemeService(IThemePreferenceStore preferenceStore)
    {
        _preferenceStore = preferenceStore;
        Preference = preferenceStore.Get();
    }

    public ThemePreference Preference { get; private set; }

    public event EventHandler? ThemeChanged;

    public void Initialize(Application application)
    {
        ArgumentNullException.ThrowIfNull(application);
        if (_application is not null)
        {
            _application.RequestedThemeChanged -= OnRequestedThemeChanged;
        }

        _application = application;
        _application.RequestedThemeChanged += OnRequestedThemeChanged;
        ApplyTheme();
    }

    public void SetTheme(ThemePreference preference)
    {
        Preference = preference;
        _preferenceStore.Set(preference);
        ApplyTheme();
        ThemeChanged?.Invoke(this, EventArgs.Empty);
    }

    private void ApplyTheme()
    {
        if (_application is null)
        {
            return;
        }

        _application.UserAppTheme = Preference switch
        {
            ThemePreference.Light => AppTheme.Light,
            ThemePreference.Dark => AppTheme.Dark,
            _ => AppTheme.Unspecified
        };

        var useDarkPalette = Preference == ThemePreference.Dark ||
                             (Preference == ThemePreference.System &&
                              _application.RequestedTheme == AppTheme.Dark);
        ApplyPalette(useDarkPalette ? ThemePaletteCatalog.Dark : ThemePaletteCatalog.Light);
    }

    private void ApplyPalette(ThemePalette palette)
    {
        if (_application is null)
        {
            return;
        }

        foreach (var token in palette.Colors)
        {
            _application.Resources[token.Key] = Color.FromArgb(token.Value);
        }

        _application.Resources["HeroBrush"] = new LinearGradientBrush(
            new GradientStopCollection
            {
                new(Color.FromArgb(palette.HeroStart), 0),
                new(Color.FromArgb(palette.HeroMiddle), 0.58f),
                new(Color.FromArgb(palette.HeroEnd), 1)
            },
            new Point(0, 0),
            new Point(1, 1));
    }

    private void OnRequestedThemeChanged(object? sender, AppThemeChangedEventArgs e)
    {
        if (Preference != ThemePreference.System)
        {
            return;
        }

        ApplyPalette(
            e.RequestedTheme == AppTheme.Dark
                ? ThemePaletteCatalog.Dark
                : ThemePaletteCatalog.Light);
        ThemeChanged?.Invoke(this, EventArgs.Empty);
    }
}

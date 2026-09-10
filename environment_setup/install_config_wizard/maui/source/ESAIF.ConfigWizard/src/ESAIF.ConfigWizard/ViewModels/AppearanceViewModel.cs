using ESAIF.BaseLayer.Application;
using ESAIF.ConfigWizard.Services;

namespace ESAIF.ConfigWizard.ViewModels;

public sealed class AppearanceViewModel : ObservableObject
{
    private readonly IThemeService _themeService;

    public AppearanceViewModel(IThemeService themeService)
    {
        _themeService = themeService;
        SelectSystemCommand = new Command(() => Select(ThemePreference.System));
        SelectLightCommand = new Command(() => Select(ThemePreference.Light));
        SelectDarkCommand = new Command(() => Select(ThemePreference.Dark));
        _themeService.ThemeChanged += OnThemeChanged;
        MotionPreferences.Current.Changed += OnMotionChanged;
    }

    public Command SelectSystemCommand { get; }

    public Command SelectLightCommand { get; }

    public Command SelectDarkCommand { get; }

    public bool AnimateStatusLights
    {
        get => MotionPreferences.Current.AnimateStatusLights;
        set
        {
            MotionPreferences.Current.SetAnimateStatusLights(value);
        }
    }

    private void OnMotionChanged(object? sender, EventArgs e) =>
        MainThread.BeginInvokeOnMainThread(() => OnPropertyChanged(nameof(AnimateStatusLights)));

    public bool IsSystemSelected => _themeService.Preference == ThemePreference.System;

    public bool IsLightSelected => _themeService.Preference == ThemePreference.Light;

    public bool IsDarkSelected => _themeService.Preference == ThemePreference.Dark;

    public string CurrentThemeLabel => _themeService.Preference switch
    {
        ThemePreference.System => "Following Windows",
        ThemePreference.Light => "Light mode",
        ThemePreference.Dark => "Dark mode",
        _ => string.Empty
    };

    private void Select(ThemePreference preference)
    {
        _themeService.SetTheme(preference);
        NotifySelectionChanged();
    }

    private void OnThemeChanged(object? sender, EventArgs e)
    {
        MainThread.BeginInvokeOnMainThread(NotifySelectionChanged);
    }

    private void NotifySelectionChanged()
    {
        OnPropertyChanged(nameof(IsSystemSelected));
        OnPropertyChanged(nameof(IsLightSelected));
        OnPropertyChanged(nameof(IsDarkSelected));
        OnPropertyChanged(nameof(CurrentThemeLabel));
    }
}

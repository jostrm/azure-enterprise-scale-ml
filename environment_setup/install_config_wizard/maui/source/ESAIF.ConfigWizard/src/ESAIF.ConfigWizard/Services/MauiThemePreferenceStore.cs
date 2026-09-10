namespace ESAIF.ConfigWizard.Services;

public sealed class MauiThemePreferenceStore : IThemePreferenceStore
{
    private const string PreferenceKey = "appearance.theme";

    public ThemePreference Get()
    {
        var value = Preferences.Default.Get(
            PreferenceKey,
            ThemePreference.System.ToString());
        return Enum.TryParse<ThemePreference>(value, ignoreCase: true, out var preference)
            ? preference
            : ThemePreference.System;
    }

    public void Set(ThemePreference preference)
    {
        Preferences.Default.Set(PreferenceKey, preference.ToString());
    }
}

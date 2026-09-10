namespace ESAIF.ConfigWizard.Services;

public interface IThemeService
{
    ThemePreference Preference { get; }

    event EventHandler? ThemeChanged;

    void Initialize(Application application);

    void SetTheme(ThemePreference preference);
}

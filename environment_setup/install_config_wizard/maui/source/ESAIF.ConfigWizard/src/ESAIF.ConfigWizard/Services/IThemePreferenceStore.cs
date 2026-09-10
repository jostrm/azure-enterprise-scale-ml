namespace ESAIF.ConfigWizard.Services;

public interface IThemePreferenceStore
{
    ThemePreference Get();

    void Set(ThemePreference preference);
}

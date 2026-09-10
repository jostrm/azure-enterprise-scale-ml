namespace ESAIF.ConfigWizard.Services;

public sealed class MotionPreferences
{
    private const string PreferenceKey = "animate_status_lights";
    private readonly WeakEventManager _events = new();
#if WINDOWS
    private readonly Windows.UI.ViewManagement.UISettings _systemSettings = new();
#endif

    private MotionPreferences()
    {
        AnimateStatusLights = Preferences.Default.Get(PreferenceKey, true);
#if WINDOWS
        if (OperatingSystem.IsWindowsVersionAtLeast(10, 0, 19041))
        {
            _systemSettings.AnimationsEnabledChanged += (_, _) =>
                MainThread.BeginInvokeOnMainThread(NotifyChanged);
        }
#endif
    }

    public static MotionPreferences Current { get; } = new();

    public bool AnimateStatusLights { get; private set; }

    public bool AreStatusLightAnimationsEnabled =>
        AnimateStatusLights &&
#if WINDOWS
        _systemSettings.AnimationsEnabled;
#else
        true;
#endif

    public event EventHandler Changed
    {
        add => _events.AddEventHandler(value);
        remove => _events.RemoveEventHandler(value);
    }

    public void SetAnimateStatusLights(bool enabled)
    {
        if (AnimateStatusLights == enabled)
        {
            return;
        }

        Preferences.Default.Set(PreferenceKey, enabled);
        AnimateStatusLights = enabled;
        NotifyChanged();
    }

    private void NotifyChanged() => _events.HandleEvent(this, EventArgs.Empty, nameof(Changed));
}

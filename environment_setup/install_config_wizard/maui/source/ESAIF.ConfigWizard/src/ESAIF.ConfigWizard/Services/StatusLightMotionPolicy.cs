namespace ESAIF.ConfigWizard.Services;

public static class StatusLightMotionPolicy
{
    public const uint CycleMilliseconds = 3200;

    public static bool ShouldAnimate(
        bool loaded, bool windowActive, bool pageActive, bool visible,
        bool active, bool pulsing, bool motionEnabled) =>
        loaded && windowActive && pageActive && visible && active && pulsing && motionEnabled;
}

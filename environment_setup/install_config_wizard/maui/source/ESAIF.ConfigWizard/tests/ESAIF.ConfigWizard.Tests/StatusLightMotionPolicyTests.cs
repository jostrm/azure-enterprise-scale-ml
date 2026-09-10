using ESAIF.ConfigWizard.Services;

namespace ESAIF.ConfigWizard.Tests;

public sealed class StatusLightMotionPolicyTests
{
    [Fact]
    public void Pulse_IsSlowAndRequiresAllLifecycleAndPreferenceGates()
    {
        Assert.True(StatusLightMotionPolicy.CycleMilliseconds >= 2500);
        Assert.True(StatusLightMotionPolicy.ShouldAnimate(true, true, true, true, true, true, true));
    }

    [Theory]
    [InlineData(false, true, true, true, true, true, true)]
    [InlineData(true, false, true, true, true, true, true)]
    [InlineData(true, true, false, true, true, true, true)]
    [InlineData(true, true, true, false, true, true, true)]
    [InlineData(true, true, true, true, false, true, true)]
    [InlineData(true, true, true, true, true, false, true)]
    [InlineData(true, true, true, true, true, true, false)]
    public void PausedHiddenUnloadedOrReducedMotion_DoesNotAnimate(
        bool loaded, bool window, bool page, bool visible, bool active, bool pulsing, bool motion)
    {
        Assert.False(StatusLightMotionPolicy.ShouldAnimate(loaded, window, page, visible, active, pulsing, motion));
    }
}

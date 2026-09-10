using ESAIF.ConfigWizard.Services;
using ESAIF.ConfigWizard.ViewModels;

namespace ESAIF.ConfigWizard.Tests;

public sealed class WarningToastTests
{
    [Fact]
    public void InitialWarningFadesThenCollapsesWithoutLosingDetails()
    {
        var state = Warning();
        Assert.True(state.IsVisible);
        state.Advance(WarningToastState.ReadingTime, true);
        Assert.Equal(1, state.Opacity);
        state.Advance(WarningToastState.FadeTime / 2, true);
        Assert.InRange(state.Opacity, 0.49, 0.51);
        state.Advance(WarningToastState.FadeTime / 2, true);
        Assert.False(state.IsVisible);
        Assert.True(state.HasMessages);
        Assert.Equal("Cached Azure inventory", state.Message);
    }

    [Fact]
    public void ReducedMotionHidesWithoutFading()
    {
        var state = Warning();
        state.Advance(WarningToastState.ReadingTime, false);
        Assert.False(state.IsVisible);
        Assert.Equal(1, state.Opacity);
    }

    [Fact]
    public void ReplayRemainsOpenForReadingUntilDismissed()
    {
        var state = Warning();
        state.Advance(TimeSpan.FromMinutes(1), true);
        state.Replay();
        state.Advance(TimeSpan.FromHours(1), true);
        Assert.True(state.IsVisible);
        Assert.True(state.IsPinned);
        Assert.Equal(1, state.Opacity);
        state.Dismiss();
        Assert.False(state.IsVisible);
        Assert.True(state.HasMessages);
    }

    [Fact]
    public void RepeatedUpdatesDoNotReshowDismissedWarning()
    {
        var state = Warning();
        state.Dismiss();
        state.Update("Cached Azure inventory", null, "Cached Azure inventory", null);
        Assert.False(state.IsVisible);
        Assert.Equal("Cached Azure inventory", state.Message);
    }

    [Fact]
    public void UpdatingTheStartupPopupDoesNotRestartItsReadingTime()
    {
        var state = Warning();
        state.Advance(WarningToastState.ReadingTime + WarningToastState.FadeTime / 2, true);
        state.Update("New warning", null, null, null);
        Assert.True(state.IsVisible);
        Assert.InRange(state.Opacity, .49, .51);
        state.Advance(WarningToastState.FadeTime / 2, true);
        Assert.False(state.IsVisible);
        Assert.Equal("New warning", state.Message);
    }

    [Fact]
    public void ResolvingMessagesClearsReplayAndDoesNotReviveOldScope()
    {
        var state = Warning();
        state.Replay();
        state.Update("", "", "", "");
        state.Replay();
        Assert.False(state.IsVisible);
        Assert.False(state.HasMessages);
        state.Update("Other factory warning", null, null, null);
        Assert.DoesNotContain("Cached", state.Message);
        Assert.False(state.IsVisible);
    }

    [Fact]
    public void ErrorsTakePriorityAndWarningsAreNotLost()
    {
        var state = new WarningToastState();
        state.Update("Cache warning", "Save failed", "Cache warning", "Refresh failed");
        Assert.True(state.HasErrors);
        Assert.Equal("Attention required", state.Title);
        Assert.Equal("Save failed\n\nRefresh failed\n\nCache warning", state.Message);
        state.Update("Cache warning", null, "Cache warning", null);
        Assert.False(state.HasErrors);
        Assert.Equal("Data source details", state.Title);
    }

    [Fact]
    public async Task OperationFailureIsReplayableButSuccessClearsIt()
    {
        var vm = new TestOperation();
        await vm.Run(() => throw new IOException("Unable to save"));
        Assert.Equal("Unable to save", vm.ErrorMessage);
        Assert.Equal(vm.StatusMessage, vm.ErrorMessage);
        await vm.Run(() => Task.CompletedTask);
        Assert.Empty(vm.ErrorMessage);
    }

    [Fact]
    public async Task TimeoutIsReportedWithoutRawException()
    {
        var vm = new TestOperation();
        await vm.Run(() => throw new TaskCanceledException("Internal transport details"));
        Assert.Contains("timed out", vm.ErrorMessage);
        Assert.DoesNotContain("Internal", vm.ErrorMessage);
    }

    [Fact]
    public void SharedWarningRetainsHasWarningNotification()
    {
        var vm = new TestOperation();
        var properties = new List<string?>();
        vm.PropertyChanged += (_, e) => properties.Add(e.PropertyName);
        vm.SetWarning("New data source warning");
        Assert.True(vm.HasWarning);
        Assert.Contains(nameof(vm.Warning), properties);
        Assert.Contains(nameof(vm.HasWarning), properties);
    }

    [Fact]
    public void NewPagesAndDifferentMessagesShareOneAutomaticPopupPerApplicationSession()
    {
        var session = new WarningToastSession();
        var first = new WarningToastState(session);
        first.Update(null, "Startup connection error", null, null);
        Assert.True(first.IsVisible);
        first.Dismiss();
        var second = new WarningToastState(session);
        second.Update(null, "Startup connection error", "New view detail", null);
        Assert.False(second.IsVisible);
        second.Update("New warning", "Another error", null, null);
        Assert.False(second.IsVisible);
        Assert.True(second.HasErrors);
        Assert.Contains("Another error", second.Message);
        second.Replay();
        Assert.True(second.IsVisible);
        Assert.True(second.IsPinned);
        second.Dismiss();
        first.Update("Changed", null, null, null);
        Assert.False(first.IsVisible);
        var freshApp = new WarningToastState(new WarningToastSession());
        freshApp.Update(null, "Startup connection error", null, null);
        Assert.True(freshApp.IsVisible);
    }

    [Fact]
    public void InactiveAndEmptyUpdatesDoNotConsumeTheStartupPopup()
    {
        var session = new WarningToastSession();
        var inactive = new WarningToastState(session);
        inactive.Update("Error from hidden page", null, null, null, allowStartupPopup: false);
        Assert.False(inactive.IsVisible);
        var active = new WarningToastState(session);
        active.Update(null, null, null, null);
        Assert.False(active.IsVisible);
        active.Update(null, "Startup error", null, null);
        Assert.True(active.IsVisible);
        inactive.Update("Error from hidden page", null, null, null);
        Assert.False(inactive.IsVisible);
    }

    private static WarningToastState Warning()
    {
        var state = new WarningToastState();
        state.Update("Cached Azure inventory", null, null, null);
        return state;
    }

    private sealed class TestOperation : OperationViewModel
    {
        public Task Run(Func<Task> action) => ExecuteOperationAsync(action, "Working");
        public void SetWarning(string value) => Warning = value;
    }
}

using ESAIF.BaseLayer.Application;

namespace ESAIF.ConfigWizard.Services;

public sealed class WarningToastSession
{
    private int _shown;
    public bool TryShowStartupWarning() => Interlocked.CompareExchange(ref _shown, 1, 0) == 0;
}

public sealed class WarningToastState : ObservableObject
{
    public static readonly TimeSpan ReadingTime = TimeSpan.FromSeconds(10);
    public static readonly TimeSpan FadeTime = TimeSpan.FromMilliseconds(450);
    private TimeSpan _elapsed;
    private readonly WarningToastSession _session;

    public WarningToastState(WarningToastSession? session = null) => _session = session ?? new WarningToastSession();

    public string Message { get; private set; } = string.Empty;
    public bool HasMessages => Message.Length > 0;
    public bool HasErrors { get; private set; }
    public string Title => HasErrors ? "Attention required" : "Data source details";
    public bool IsVisible { get; private set; }
    public bool IsPinned { get; private set; }
    public double Opacity { get; private set; } = 1;
    public string Hint => IsPinned
        ? "Kept open for reading. Close when finished."
        : "Hides automatically. Use ! in the footer to reopen.";

    public void Update(string? pageWarning, string? pageError, string? refreshWarning, string? refreshError,
        bool allowStartupPopup = true)
    {
        var errors = new[] { pageError, refreshError }.Where(value => !string.IsNullOrWhiteSpace(value)).ToArray();
        var message = string.Join("\n\n", errors.Concat([pageWarning, refreshWarning])
            .Where(value => !string.IsNullOrWhiteSpace(value)).Select(value => value!.Trim()).Distinct(StringComparer.Ordinal));
        var hasErrors = errors.Length > 0;
        var changed = Message != message || HasErrors != hasErrors;
        var show = message.Length > 0 && allowStartupPopup && !IsVisible && _session.TryShowStartupWarning();
        if (!changed && !show)
        {
            return;
        }
        Message = message;
        HasErrors = hasErrors;
        if (!HasMessages)
        {
            Dismiss();
            return;
        }
        if (show)
        {
            _elapsed = TimeSpan.Zero;
            IsVisible = true;
            IsPinned = false;
            Opacity = 1;
        }
        Notify();
    }

    public void Replay()
    {
        if (!HasMessages)
        {
            return;
        }
        _session.TryShowStartupWarning();
        IsVisible = true;
        IsPinned = true;
        Opacity = 1;
        Notify();
    }

    public void Dismiss()
    {
        IsVisible = false;
        IsPinned = false;
        Opacity = 1;
        Notify();
    }

    public void Advance(TimeSpan elapsed, bool animate)
    {
        ArgumentOutOfRangeException.ThrowIfLessThan(elapsed, TimeSpan.Zero);
        if (!IsVisible || IsPinned)
        {
            return;
        }
        _elapsed += elapsed;
        if (_elapsed < ReadingTime)
        {
            return;
        }
        if (!animate || _elapsed >= ReadingTime + FadeTime)
        {
            Dismiss();
            return;
        }
        Opacity = 1 - (_elapsed - ReadingTime).TotalMilliseconds / FadeTime.TotalMilliseconds;
        OnPropertyChanged(nameof(Opacity));
    }

    private void Notify()
    {
        foreach (var property in new[] { nameof(Message), nameof(HasMessages), nameof(HasErrors),
            nameof(Title), nameof(IsVisible), nameof(IsPinned), nameof(Opacity), nameof(Hint) })
        {
            OnPropertyChanged(property);
        }
    }
}

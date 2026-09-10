using System.ComponentModel;
using System.Diagnostics;
using ESAIF.ConfigWizard.Pages;
using ESAIF.ConfigWizard.Services;
using ESAIF.ConfigWizard.ViewModels;

namespace ESAIF.ConfigWizard.Controls;

public partial class WarningToast : ContentView
{
    private readonly Page _owner;
    private readonly AzureRefreshCoordinator _refresh;
    private readonly WarningToastState _state;
    private readonly IDispatcherTimer _timer;
    private OperationViewModel? _source;
    private Window? _window;
    private bool _loaded;
    private bool _pageActive = true;
    private bool _windowActive = true;
    private bool _hovered;
    private long _lastTick;

    public WarningToast(Page owner, AzureRefreshCoordinator refresh, WarningToastState state)
    {
        InitializeComponent();
        _owner = owner;
        _refresh = refresh;
        _state = state;
        BindingContext = state;
        _timer = Dispatcher.CreateTimer();
        _timer.Interval = TimeSpan.FromMilliseconds(50);
        _timer.Tick += OnTick;
        var pointer = new PointerGestureRecognizer();
        pointer.PointerEntered += (_, _) => { _hovered = true; UpdateTimer(); };
        pointer.PointerExited += (_, _) => { _hovered = false; UpdateTimer(); };
        ToastPanel.GestureRecognizers.Add(pointer);
        CloseButton.Focused += OnToastFocused;
        DetailsButton.Focused += OnToastFocused;
        Loaded += OnLoaded;
        Unloaded += OnUnloaded;
        InputTransparent = true;
    }

    private void OnLoaded(object? sender, EventArgs e)
    {
        if (_loaded)
        {
            return;
        }
        _loaded = true;
        _pageActive = true;
        _windowActive = true;
        _state.PropertyChanged += OnStateChanged;
        _refresh.PropertyChanged += OnSourceChanged;
        _owner.BindingContextChanged += OnBindingContextChanged;
        _owner.Appearing += OnAppearing;
        _owner.Disappearing += OnDisappearing;
        _window = Window;
        if (_window is not null)
        {
            _window.Activated += OnActivated;
            _window.Deactivated += OnDeactivated;
            _window.Stopped += OnDeactivated;
        }
        OnBindingContextChanged(this, EventArgs.Empty);
        RenderState();
    }

    private void OnUnloaded(object? sender, EventArgs e)
    {
        _loaded = false;
        _state.Dismiss();
        _timer.Stop();
        _state.PropertyChanged -= OnStateChanged;
        _refresh.PropertyChanged -= OnSourceChanged;
        _owner.BindingContextChanged -= OnBindingContextChanged;
        _owner.Appearing -= OnAppearing;
        _owner.Disappearing -= OnDisappearing;
        if (_source is not null)
        {
            _source.PropertyChanged -= OnSourceChanged;
            _source = null;
        }
        if (_window is not null)
        {
            _window.Activated -= OnActivated;
            _window.Deactivated -= OnDeactivated;
            _window.Stopped -= OnDeactivated;
            _window = null;
        }
    }

    private void OnBindingContextChanged(object? sender, EventArgs e)
    {
        if (_source is not null)
        {
            _source.PropertyChanged -= OnSourceChanged;
        }
        _source = _owner.BindingContext as OperationViewModel;
        if (_source is not null)
        {
            _source.PropertyChanged += OnSourceChanged;
        }
        UpdateMessages();
    }

    private void OnSourceChanged(object? sender, PropertyChangedEventArgs e)
    {
        if (string.IsNullOrEmpty(e.PropertyName) || e.PropertyName is
            nameof(OperationViewModel.Warning) or nameof(OperationViewModel.ErrorMessage) or
            nameof(AzureRefreshCoordinator.Details) or nameof(AzureRefreshCoordinator.State))
        {
            if (Dispatcher.IsDispatchRequired)
            {
                Dispatcher.Dispatch(() => { if (_loaded) UpdateMessages(); });
            }
            else
            {
                UpdateMessages();
            }
        }
    }

    private void UpdateMessages()
    {
        var failed = _refresh.State == AzureRefreshState.Failed;
        _state.Update(_source?.Warning, _source?.ErrorMessage,
            failed ? null : _refresh.Details, failed ? _refresh.Details : null,
            allowStartupPopup: _loaded && _pageActive && _windowActive);
    }

    private void OnStateChanged(object? sender, PropertyChangedEventArgs e)
    {
        if (e.PropertyName != nameof(WarningToastState.Opacity))
        {
            RenderState();
        }
    }

    private void RenderState()
    {
        InputTransparent = !_state.IsVisible;
        var color = _state.HasErrors ? "Danger" : "Warning";
        ToastPanel.SetDynamicResource(Border.StrokeProperty, color);
        ToastTitle.SetDynamicResource(Label.TextColorProperty, color);
        UpdateTimer();
    }

    private void UpdateTimer()
    {
        var shouldRun = _loaded && _pageActive && _windowActive && !_hovered &&
            _state.IsVisible && !_state.IsPinned;
        if (shouldRun && !_timer.IsRunning)
        {
            _lastTick = Stopwatch.GetTimestamp();
            _timer.Start();
        }
        else if (!shouldRun)
        {
            _timer.Stop();
        }
    }

    private void OnTick(object? sender, EventArgs e)
    {
        var now = Stopwatch.GetTimestamp();
        var elapsed = Stopwatch.GetElapsedTime(_lastTick, now);
        _lastTick = now;
        _state.Advance(elapsed, MotionPreferences.Current.AreStatusLightAnimationsEnabled);
    }

    private void OnActivated(object? sender, EventArgs e) { _windowActive = true; UpdateMessages(); UpdateTimer(); }
    private void OnDeactivated(object? sender, EventArgs e) { _windowActive = false; UpdateTimer(); }
    private void OnAppearing(object? sender, EventArgs e) { _pageActive = true; UpdateMessages(); UpdateTimer(); }
    private void OnDisappearing(object? sender, EventArgs e) { _pageActive = false; _state.Dismiss(); UpdateTimer(); }
    private void OnCloseClicked(object? sender, EventArgs e) => _state.Dismiss();

    private void OnToastFocused(object? sender, FocusEventArgs e)
    {
        // Hiding a focused button can move focus to its sibling during layout.
        // That focus restoration must not reopen a dismissed toast.
        if (_state.IsVisible && !_state.IsPinned)
        {
            _state.Replay();
        }
    }

    private async void OnDetailsClicked(object? sender, EventArgs e)
    {
        _state.Replay();
        await MessageDetailsPage.ShowAsync(_owner, _state.Title, _state.Message);
    }
}

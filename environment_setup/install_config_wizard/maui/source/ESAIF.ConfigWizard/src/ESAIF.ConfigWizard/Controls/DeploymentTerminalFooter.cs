using ESAIF.ConfigWizard.Services;

namespace ESAIF.ConfigWizard.Controls;

public sealed class DeploymentTerminalFooter : ContentView
{
    private readonly DeploymentTerminalSession _session;
    private readonly DeploymentTerminalView _terminal = new() { HeightRequest = 260 };
    private readonly TechnicalLabel _title = new() { Caption = "Terminal details", FontSize = 11, LineBreakMode = LineBreakMode.MiddleTruncation, VerticalOptions = LayoutOptions.Center };
    private readonly TechnicalLabel _notice = new() { Caption = "Terminal notice", FontSize = 11, LineBreakMode = LineBreakMode.WordWrap };
    private readonly StatusLight _status = new();
    private readonly Button _toggle = new() { Text = "Collapse", FontSize = 11, Padding = new Thickness(9, 3), HeightRequest = 30 };
    private readonly Button _interrupt = new() { Text = "Ctrl+C", FontSize = 11, Padding = new Thickness(9, 3), HeightRequest = 30 };
    private readonly Grid _body;
    private bool _loaded;
    private bool _pageVisible;
    private bool _ready;
    private bool? _inputEnabled;
    private string _inputScope = string.Empty;

    public DeploymentTerminalFooter(Page page, DeploymentTerminalSession session)
    {
        _session = session;
        SetDynamicResource(BackgroundColorProperty, "Surface");
        _title.SetDynamicResource(Label.TextColorProperty, "Text");
        _notice.SetDynamicResource(Label.TextColorProperty, "Muted");
        var copy = new Button { Text = "Copy selection", FontSize = 11, Padding = new Thickness(9, 3), HeightRequest = 30 };
        var reconnect = new Button { Text = "Reconnect", FontSize = 11, Padding = new Thickness(9, 3), HeightRequest = 30 };
        var header = new Grid
        {
            Padding = new Thickness(10, 4), ColumnSpacing = 8,
            ColumnDefinitions = [new(GridLength.Auto), new(GridLength.Star), new(GridLength.Auto),
                new(GridLength.Auto), new(GridLength.Auto), new(GridLength.Auto)]
        };
        View[] items = [_status, _title, _interrupt, copy, reconnect, _toggle];
        for (var column = 0; column < items.Length; column++)
        {
            header.Children.Add(items[column]);
            Grid.SetColumn(items[column], column);
        }
        _body = new Grid { RowDefinitions = [new(GridLength.Auto), new(GridLength.Auto)] };
#if WINDOWS
        _body.Children.Add(_terminal);
#else
        _body.Children.Add(new Label { Text = "Interactive deployment terminals are supported on Windows.", Padding = 12 });
#endif
        _body.Children.Add(_notice);
        Grid.SetRow(_notice, 1);
        _notice.Margin = new Thickness(12, 3, 12, 6);
        Content = new VerticalStackLayout { Spacing = 0, Children = { header, _body } };
        IsVisible = false;
        _toggle.Clicked += (_, _) => _session.ToggleExpanded();
        reconnect.Clicked += async (_, _) =>
        {
            _session.Reconnect();
            if (!_ready)
            {
                try { await _terminal.ReloadAsync(); }
                catch (Exception exception) when (TerminalFailurePolicy.IsExpected(exception))
                {
                    _notice.Value = "The terminal renderer could not reload. Reopen this page.";
                }
            }
        };
        _interrupt.Clicked += async (_, _) => await _session.SendInputAsync("\x03");
        copy.Clicked += async (_, _) =>
        {
            try { await _terminal.CopySelectionAsync(); }
            catch (Exception exception) when (TerminalFailurePolicy.IsExpected(exception))
            {
                _notice.Value = "Selection could not be copied.";
            }
        };
        _terminal.TerminalReady += (_, _) => { _ready = true; _inputEnabled = null; Refresh(); };
        _terminal.TerminalUnavailable += (_, _) =>
        {
            _ready = false;
            _session.Detach(this);
            _notice.Value = "The local terminal renderer is unavailable. Reopen the page to reload it.";
        };
        _terminal.TerminalInput += async (_, data) =>
        {
            if (_loaded && _pageVisible && _session.Expanded) await _session.SendInputAsync(data);
        };
        _terminal.TerminalResize += async (_, size) =>
        {
            if (_loaded && _pageVisible && _session.Expanded) await _session.ResizeAsync(size.Columns, size.Rows);
        };
        Loaded += OnLoaded;
        Unloaded += OnUnloaded;
        // A collapsed footer may not receive native Loaded until after its first job is opened.
        page.Appearing += OnAppearing;
        page.Disappearing += OnDisappearing;
    }

    private void OnLoaded(object? sender, EventArgs e)
    {
        if (_loaded) return;
        _loaded = true;
        _session.Changed += OnChanged;
        Refresh();
    }

    private void OnUnloaded(object? sender, EventArgs e)
    {
        _loaded = false;
        _session.Changed -= OnChanged;
        _session.Detach(this);
    }

    private void OnAppearing(object? sender, EventArgs e)
    {
        _pageVisible = true;
        if (!_loaded) OnLoaded(sender, e);
        else Refresh();
    }
    private void OnDisappearing(object? sender, EventArgs e)
    {
        _pageVisible = false;
        OnUnloaded(sender, e);
    }
    private void OnChanged(object? sender, EventArgs e) => Refresh();

    private void Refresh()
    {
        IsVisible = _session.HasJob;
        _body.IsVisible = _session.Expanded;
        _toggle.Text = _session.Expanded ? "Collapse" : "Expand";
        _title.Value = _session.Title;
        _notice.Value = _session.Notice;
        _status.Label = _session.Status;
        _status.SetDynamicResource(StatusLight.LightColorProperty, _session.Status switch
        {
            "queued" or "running" => "Success",
            "failed" or "cancelled" or "interrupted" or "expired" => "Danger",
            "active" => "Secondary",
            _ => "Muted"
        });
        _status.IsPulsing = _session.IsRunning;
        _interrupt.IsEnabled = _session.CanType;
        _terminal.InputScope = _session.InputScope;
        if (!_loaded || !_pageVisible || !_ready) return;
        if (_inputEnabled != _session.CanType || _inputScope != _session.InputScope)
        {
            _inputEnabled = _session.CanType;
            _inputScope = _session.InputScope;
            _ = UpdateInputAsync(_session.CanType);
        }
        if (_session.Expanded)
            _ = _session.AttachAsync(this, RenderAsync);
        else
            _session.Detach(this);
    }

    private async Task RenderAsync(string output, bool reset)
    {
        var scope = _session.InputScope;
        _terminal.InputScope = scope;
        // ConPTY can request terminal capabilities in its very first live output chunk.
        await _terminal.EnableInputAsync(_session.CanType);
        if (!_loaded || !_pageVisible || scope != _session.InputScope)
            throw new OperationCanceledException();
        await _terminal.WriteAsync(output, reset);
    }

    private async Task UpdateInputAsync(bool enabled)
    {
        try
        {
            await _terminal.EnableInputAsync(enabled);
            if (enabled) await _terminal.FitAsync();
        }
        catch (Exception exception) when (TerminalFailurePolicy.IsExpected(exception))
        {
            _inputEnabled = null;
            _notice.Value = "The terminal input bridge is unavailable. Reconnect before typing.";
        }
    }
}

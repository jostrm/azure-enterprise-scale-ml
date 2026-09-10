using System.Text;
using System.Text.Json;
using ESAIF.ConfigWizard.Controls;
using ESAIF.ConfigWizard.Services;
using Microsoft.Maui.Handlers;
using Microsoft.Web.WebView2.Core;
using Microsoft.UI.Xaml.Controls;

namespace ESAIF.ConfigWizard.Platforms.Windows;

public sealed class DeploymentTerminalHandler : ViewHandler<DeploymentTerminalView, WebView2>
{
    private const string Origin = "https://esaif-terminal.invalid";
    private readonly Dictionary<string, (byte[] Bytes, string Type)> _assets = new(StringComparer.Ordinal);
    private readonly Dictionary<int, TaskCompletionSource> _writes = [];
    private readonly string _nonce = Guid.NewGuid().ToString("N");
    private string _documentUri = string.Empty;
    private CoreWebView2? _core;
    private bool _connected;
    private bool _initializing;
    private bool _ready;
    private int _writeId;
    private long _inputSequence;

    public DeploymentTerminalHandler() : base(ViewMapper) { }
    protected override WebView2 CreatePlatformView() => new();

    protected override void ConnectHandler(WebView2 platformView)
    {
        base.ConnectHandler(platformView);
        _connected = true;
        platformView.Loaded += OnPlatformLoaded;
        if (platformView.IsLoaded) _ = InitializeAsync(platformView);
    }

    private async void OnPlatformLoaded(object sender, Microsoft.UI.Xaml.RoutedEventArgs args) =>
        await InitializeAsync(PlatformView);

    private async Task InitializeAsync(WebView2 platformView)
    {
        if (!_connected || _initializing) return;
        _initializing = true;
        try
        {
            await LoadAssetsAsync();
            if (!_connected) return;
            await platformView.EnsureCoreWebView2Async();
            if (!_connected) return;
            _core = platformView.CoreWebView2;
            var settings = _core.Settings;
            settings.AreDevToolsEnabled = false;
            settings.AreDefaultContextMenusEnabled = false;
            settings.AreDefaultScriptDialogsEnabled = false;
            settings.AreHostObjectsAllowed = false;
            settings.IsPasswordAutosaveEnabled = false;
            settings.IsGeneralAutofillEnabled = false;
            settings.IsStatusBarEnabled = false;
            settings.AreBrowserAcceleratorKeysEnabled = false;
            settings.IsWebMessageEnabled = true;
            _core.AddWebResourceRequestedFilter("*", CoreWebView2WebResourceContext.All);
            _core.WebResourceRequested += OnResourceRequested;
            _core.NavigationStarting += OnNavigationStarting;
            _core.FrameNavigationStarting += OnFrameNavigationStarting;
            _core.NewWindowRequested += OnNewWindowRequested;
            _core.PermissionRequested += OnPermissionRequested;
            _core.DownloadStarting += OnDownloadStarting;
            _core.WebMessageReceived += OnWebMessageReceived;
            _core.ProcessFailed += OnProcessFailed;
            VirtualView.OutputWriter = WriteAsync;
            VirtualView.InputEnabler = enabled => ExecuteAsync(
                $"window.esaifTerminal.enable({JsonSerializer.Serialize(enabled)},{JsonSerializer.Serialize(VirtualView.InputScope)})");
            VirtualView.SelectionCopier = CopySelectionAsync;
            VirtualView.Refitter = () => ExecuteAsync("window.esaifTerminal.fit()");
            VirtualView.Reloader = () =>
            {
                _ready = false;
                _inputSequence = 0;
                foreach (var write in _writes.Values) write.TrySetCanceled();
                _writes.Clear();
                _core.Navigate(_documentUri);
                return Task.CompletedTask;
            };
            var app = Application.Current;
            var selectedTheme = app?.UserAppTheme is AppTheme.Light or AppTheme.Dark ? app.UserAppTheme : app?.RequestedTheme;
            var theme = selectedTheme == AppTheme.Dark ? "dark" : "light";
            _documentUri = $"{Origin}/index.html?scoutTheme={theme}";
            _core.Navigate(_documentUri);
        }
        catch (Exception exception) when (TerminalFailurePolicy.IsExpected(exception))
        {
            if (_connected) VirtualView.Unavailable();
        }
    }

    private async Task LoadAssetsAsync()
    {
        foreach (var (path, type) in new[]
        {
            ("index.html", "text/html; charset=utf-8"),
            ("terminal.js", "text/javascript; charset=utf-8"),
            ("vendor/xterm.js", "text/javascript; charset=utf-8"),
            ("vendor/addon-fit.js", "text/javascript; charset=utf-8"),
            ("vendor/xterm.css", "text/css; charset=utf-8")
        })
        {
            await using var input = await FileSystem.OpenAppPackageFileAsync(
                "terminal\\" + path.Replace('/', '\\'));
            using var memory = new MemoryStream();
            await input.CopyToAsync(memory);
            var bytes = memory.ToArray();
            if (path == "index.html")
                bytes = Encoding.UTF8.GetBytes(Encoding.UTF8.GetString(bytes).Replace("__BRIDGE_NONCE__", _nonce, StringComparison.Ordinal));
            _assets["/" + path] = (bytes, type);
        }
    }

    private void OnResourceRequested(CoreWebView2 sender, CoreWebView2WebResourceRequestedEventArgs args)
    {
        if (Uri.TryCreate(args.Request.Uri, UriKind.Absolute, out var uri) &&
            uri.GetLeftPart(UriPartial.Authority) == Origin && args.Request.Method == "GET" &&
            _assets.TryGetValue(uri.AbsolutePath, out var asset))
        {
            args.Response = sender.Environment.CreateWebResourceResponse(
                new MemoryStream(asset.Bytes, writable: false).AsRandomAccessStream(), 200, "OK",
                $"Content-Type: {asset.Type}\r\nCache-Control: no-store\r\nX-Content-Type-Options: nosniff");
        }
        else
            args.Response = sender.Environment.CreateWebResourceResponse(
                new MemoryStream().AsRandomAccessStream(), 403, "Blocked", "Cache-Control: no-store");
    }

    private void OnNavigationStarting(CoreWebView2 sender, CoreWebView2NavigationStartingEventArgs args) =>
        args.Cancel = _ready || !string.Equals(args.Uri, _documentUri, StringComparison.Ordinal);
    private static void OnFrameNavigationStarting(CoreWebView2 sender, CoreWebView2NavigationStartingEventArgs args) => args.Cancel = true;
    private static void OnNewWindowRequested(CoreWebView2 sender, CoreWebView2NewWindowRequestedEventArgs args) => args.Handled = true;
    private static void OnPermissionRequested(CoreWebView2 sender, CoreWebView2PermissionRequestedEventArgs args) => args.State = CoreWebView2PermissionState.Deny;
    private static void OnDownloadStarting(CoreWebView2 sender, CoreWebView2DownloadStartingEventArgs args) => args.Cancel = true;
    private void OnProcessFailed(CoreWebView2 sender, CoreWebView2ProcessFailedEventArgs args)
    {
        _ready = false;
        foreach (var write in _writes.Values) write.TrySetException(new TerminalUnavailableException("The terminal renderer stopped."));
        _writes.Clear();
        VirtualView.Unavailable();
    }

    private async void OnWebMessageReceived(CoreWebView2 sender, CoreWebView2WebMessageReceivedEventArgs args)
    {
        if (!_connected || args.Source != _documentUri) return;
        try
        {
            var json = args.WebMessageAsJson;
            if (json.Length > 110_000) return;
            using var message = JsonDocument.Parse(json);
            var root = message.RootElement;
            if (root.GetProperty("nonce").GetString() != _nonce) return;
            switch (root.GetProperty("type").GetString())
            {
                case "ready":
                    if (_ready) return;
                    _ready = true;
                    VirtualView.Ready();
                    break;
                case "rendered":
                    if (_writes.Remove(root.GetProperty("id").GetInt32(), out var completion)) completion.TrySetResult();
                    break;
                case "input" when _ready:
                    var sequence = root.GetProperty("sequence").GetInt64();
                    if (sequence != _inputSequence + 1)
                    {
                        VirtualView.Unavailable();
                        return;
                    }
                    _inputSequence = sequence;
                    var data = root.GetProperty("data").GetString();
                    if (root.GetProperty("scope").GetString() == VirtualView.InputScope &&
                        data is { Length: > 0 and <= 8_192 }) VirtualView.Input(data);
                    await ExecuteAsync("window.esaifTerminal.acknowledgeInput()");
                    break;
                case "inputOverflow":
                    VirtualView.Unavailable();
                    break;
                case "resize" when _ready:
                    var columns = root.GetProperty("columns").GetInt32();
                    var rows = root.GetProperty("rows").GetInt32();
                    if (root.GetProperty("scope").GetString() == VirtualView.InputScope &&
                        columns is >= 20 and <= 500 && rows is >= 5 and <= 200)
                        VirtualView.Resize(columns, rows);
                    break;
                case "copy" when _ready:
                    await CopySelectionAsync();
                    break;
            }
        }
        catch (Exception exception) when (TerminalFailurePolicy.IsExpected(exception))
        {
            if (_connected) VirtualView.Unavailable();
        }
    }

    private async Task WriteAsync(string value, bool reset)
    {
        if (!_ready || value.Length > 524_288 || _writes.Count >= 2) throw new TerminalUnavailableException("Terminal unavailable.");
        var id = ++_writeId;
        var completion = new TaskCompletionSource(TaskCreationOptions.RunContinuationsAsynchronously);
        _writes.Add(id, completion);
        try
        {
            await ExecuteAsync($"window.esaifTerminal.write({JsonSerializer.Serialize(value)},{JsonSerializer.Serialize(reset)},{id})");
            await completion.Task.WaitAsync(TimeSpan.FromSeconds(10));
        }
        finally { _writes.Remove(id); }
    }

    private async Task ExecuteAsync(string script)
    {
        if (!_connected || !_ready || _core is null || _core.Source != _documentUri)
            throw new TerminalUnavailableException("Terminal unavailable.");
        await _core.ExecuteScriptAsync(script);
    }

    private async Task CopySelectionAsync()
    {
        if (!_connected || !_ready || _core is null || _core.Source != _documentUri) return;
        var json = await _core.ExecuteScriptAsync("window.esaifTerminal.selection()");
        var selection = JsonSerializer.Deserialize<string>(json);
        if (selection is { Length: > 0 and <= 65_536 }) await Clipboard.Default.SetTextAsync(selection);
    }

    protected override void DisconnectHandler(WebView2 platformView)
    {
        _connected = false;
        _initializing = false;
        _ready = false;
        platformView.Loaded -= OnPlatformLoaded;
        VirtualView.Unavailable();
        VirtualView.OutputWriter = null;
        VirtualView.InputEnabler = null;
        VirtualView.SelectionCopier = null;
        VirtualView.Refitter = null;
        VirtualView.Reloader = null;
        if (_core is not null)
        {
            _core.WebResourceRequested -= OnResourceRequested;
            _core.NavigationStarting -= OnNavigationStarting;
            _core.FrameNavigationStarting -= OnFrameNavigationStarting;
            _core.NewWindowRequested -= OnNewWindowRequested;
            _core.PermissionRequested -= OnPermissionRequested;
            _core.DownloadStarting -= OnDownloadStarting;
            _core.WebMessageReceived -= OnWebMessageReceived;
            _core.ProcessFailed -= OnProcessFailed;
        }
        foreach (var write in _writes.Values) write.TrySetCanceled();
        _writes.Clear();
        _assets.Clear();
        _core = null;
        platformView.Close();
        base.DisconnectHandler(platformView);
    }
}

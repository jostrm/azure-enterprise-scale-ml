using Microsoft.Extensions.DependencyInjection;
using ESAIF.ConfigWizard.Services;

namespace ESAIF.ConfigWizard;

public partial class App : Application
{
    private readonly IServiceProvider _services;

    public App(IServiceProvider services, IThemeService themeService)
    {
        InitializeComponent();
        _services = services;
        themeService.Initialize(this);
    }

    protected override Window CreateWindow(IActivationState? activationState)
    {
        var shell = _services.GetRequiredService<AppShell>();
        var window = new Window(shell)
        {
            Title = "Enterprise Scale AI Factory"
        };
        var monitor = _services.GetRequiredService<AzureAuthenticationMonitor>();
        var refresh = _services.GetRequiredService<AzureRefreshCoordinator>();
        var apiHost = _services.GetRequiredService<IBundledApiHost>();
        var timer = Dispatcher.CreateTimer();
        timer.Interval = TimeSpan.FromMinutes(5);
        CancellationTokenSource? foreground = null;
        async void Check(object? sender, EventArgs args)
        {
            if (foreground is { IsCancellationRequested: false } lifetime)
            {
                try
                {
                    await apiHost.StartAsync(lifetime.Token);
                }
                catch (Exception exception)
                {
                    RuntimeDiagnostics.Write("api-host-startup.log", exception);
                    return;
                }
                await monitor.CheckAsync(lifetime.Token);
            }
        }
        void Activate(object? sender, EventArgs args)
        {
            if (foreground is { IsCancellationRequested: false }) { return; }
            foreground?.Dispose();
            foreground = new();
            timer.Start();
            Check(sender, args);
        }
        void Deactivate(object? sender, EventArgs args)
        {
            timer.Stop();
            foreground?.Cancel();
        }
        async void LoginRequired(object? sender, EventArgs args)
        {
            await _services.GetRequiredService<AzureLoginCoordinator>()
                .AuthenticateAsync(shell.CurrentPage, allowLogout: false);
        }
        async void Destroy(object? sender, EventArgs args)
        {
            Deactivate(sender, args);
            try
            {
                await apiHost.StopAsync();
            }
            catch (Exception exception)
            {
                RuntimeDiagnostics.Write("api-host-shutdown.log", exception);
            }
            foreground?.Dispose();
            foreground = null;
            timer.Tick -= Check;
            window.Created -= Activate;
            window.Activated -= Activate;
            window.Deactivated -= Deactivate;
            window.Destroying -= Destroy;
            refresh.LoginRequired -= LoginRequired;
        }
        timer.Tick += Check;
        window.Created += Activate;
        window.Activated += Activate;
        window.Deactivated += Deactivate;
        window.Destroying += Destroy;
        refresh.LoginRequired += LoginRequired;
        return window;
    }
}

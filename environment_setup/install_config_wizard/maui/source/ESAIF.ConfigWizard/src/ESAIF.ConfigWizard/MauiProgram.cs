using ESAIF.BaseLayer.Networking;
using ESAIF.DomainLayer.Configuration;
using ESAIF.ConfigWizard.Pages;
using ESAIF.ConfigWizard.Services;
using ESAIF.ConfigWizard.ViewModels;
using LiveChartsCore.SkiaSharpView.Maui;
using Microsoft.Extensions.Logging;
using SkiaSharp.Views.Maui.Controls.Hosting;

namespace ESAIF.ConfigWizard;

public static class MauiProgram
{
    public static MauiApp CreateMauiApp()
    {
        var builder = MauiApp.CreateBuilder();
        Microsoft.Maui.Handlers.LabelHandler.Mapper.AppendToMapping("SelectableText", (handler, _) =>
        {
#if WINDOWS
            handler.PlatformView.IsTextSelectionEnabled = true;
#elif ANDROID
            handler.PlatformView.SetTextIsSelectable(true);
#endif
        });
        builder
            .UseMauiApp<App>()
            .UseSkiaSharp()
            .UseLiveCharts()
            .ConfigureMauiHandlers(handlers =>
            {
#if WINDOWS
                handlers.AddHandler<Controls.DeploymentTerminalView, Platforms.Windows.DeploymentTerminalHandler>();
#endif
            })
            .ConfigureFonts(fonts =>
            {
                fonts.AddFont("OpenSans-Regular.ttf", "OpenSansRegular");
                fonts.AddFont("OpenSans-Semibold.ttf", "OpenSansSemibold");
            });

        builder.Services.AddSingleton(_ => new HttpClient
        {
            Timeout = TimeSpan.FromMinutes(5)
        });
        builder.Services.AddSingleton<ApiConnectionState>();
        builder.Services.AddSingleton<HttpJsonApiTransport>();
        builder.Services.AddSingleton<IJsonApiTransport>(services =>
            new ConnectionTrackingTransport(
                services.GetRequiredService<HttpJsonApiTransport>(),
                services.GetRequiredService<ApiConnectionState>()));
        builder.Services.AddSingleton<ConnectionSettingsService>();
        builder.Services.AddSingleton<IConnectionSettingsService>(
            services => services.GetRequiredService<ConnectionSettingsService>());
        builder.Services.AddSingleton<IAiFactoryConnectionProvider>(
            services => services.GetRequiredService<ConnectionSettingsService>());
        builder.Services.AddSingleton<IBundledApiHost, BundledApiHost>();
        builder.Services.AddSingleton<AiFactoryApiClient>();
        builder.Services.AddSingleton<IAiFactoryApiClient>(services => services.GetRequiredService<AiFactoryApiClient>());
        builder.Services.AddSingleton<IFactoryConfigurationClient>(services => services.GetRequiredService<AiFactoryApiClient>());
        builder.Services.AddSingleton<IAzureAuthenticationClient>(services => services.GetRequiredService<AiFactoryApiClient>());
        builder.Services.AddSingleton<IRegionFindingsClient>(services => services.GetRequiredService<AiFactoryApiClient>());
        builder.Services.AddSingleton<IProjectConfigurationClient>(services => services.GetRequiredService<AiFactoryApiClient>());
        builder.Services.AddSingleton<IScaleSetConfigurationClient>(services => services.GetRequiredService<AiFactoryApiClient>());
        builder.Services.AddSingleton<IScaleSetVerificationClient>(services => services.GetRequiredService<AiFactoryApiClient>());
        builder.Services.AddSingleton<IProjectVerificationClient>(services => services.GetRequiredService<AiFactoryApiClient>());
        builder.Services.AddSingleton<IFactoryAnalyticsClient>(services => services.GetRequiredService<AiFactoryApiClient>());
        builder.Services.AddSingleton<ITicketClient>(services => services.GetRequiredService<AiFactoryApiClient>());
        builder.Services.AddSingleton<ISimpleFactoryClient>(services => services.GetRequiredService<AiFactoryApiClient>());
        builder.Services.AddSingleton<IFactoryCatalogClient>(services => services.GetRequiredService<AiFactoryApiClient>());
        builder.Services.AddSingleton<IFactoryCatalogSettingsClient>(services => services.GetRequiredService<AiFactoryApiClient>());
        builder.Services.AddSingleton<IProjectDeploymentClient>(services => services.GetRequiredService<AiFactoryApiClient>());
        builder.Services.AddSingleton<ProjectTerminalTransport>();
        builder.Services.AddSingleton<IFactoryCatalogTerminalClient>(services => new AiFactoryApiClient(
            services.GetRequiredService<ProjectTerminalTransport>(),
            services.GetRequiredService<IAiFactoryConnectionProvider>()));
        builder.Services.AddSingleton<FactoryTerminalRouter>(services => new FactoryTerminalRouter(
            new AiFactoryApiClient(services.GetRequiredService<ProjectTerminalTransport>(),
                services.GetRequiredService<IAiFactoryConnectionProvider>()),
            services.GetRequiredService<IFactoryCatalogTerminalClient>()));
        builder.Services.AddSingleton<IProjectTerminalClient>(services => services.GetRequiredService<FactoryTerminalRouter>());
        builder.Services.AddSingleton<DeploymentTerminalSession>();
        builder.Services.AddSingleton<IDeploymentTerminalSession>(services => services.GetRequiredService<DeploymentTerminalSession>());
        builder.Services.AddSingleton<IFactoryCatalogTerminalSession>(services => services.GetRequiredService<DeploymentTerminalSession>());
        builder.Services.AddSingleton<INetworkPlacementClient>(services => services.GetRequiredService<AiFactoryApiClient>());
        builder.Services.AddTransient<SavedConfigurationVerifier>();
        builder.Services.AddSingleton<IRecentProjectLoader, RecentProjectLoader>();
        builder.Services.AddSingleton<IConfigurationFileService, MauiConfigurationFileService>();
        builder.Services.AddSingleton<IAiFactoryFolderPickerService, AiFactoryFolderPickerService>();
        builder.Services.AddSingleton<IThemePreferenceStore, MauiThemePreferenceStore>();
        builder.Services.AddSingleton<IThemeService, ThemeService>();
        builder.Services.AddSingleton<WizardSession>();
        builder.Services.AddSingleton<OperationsSession>();
        builder.Services.AddSingleton<FactoryNetworkSession>();
        builder.Services.AddSingleton<FactoryCatalogSession>();
        builder.Services.AddSingleton<AzureAuthenticationMonitor>();
        builder.Services.AddSingleton<AzureLoginCoordinator>();
        builder.Services.AddSingleton<AzureRefreshCoordinator>();
        builder.Services.AddSingleton<WarningToastSession>();
        builder.Services.AddSingleton<IPostAzureLoginRefresh, PostAzureLoginRefresh>();

        builder.Services.AddSingleton<WizardViewModel>();
        builder.Services.AddSingleton<SimpleFactoryViewModel>();
        builder.Services.AddSingleton<ConnectionViewModel>();
        builder.Services.AddSingleton<ProjectsViewModel>();
        builder.Services.AddSingleton<ScaleSetsViewModel>();
        builder.Services.AddSingleton<AppearanceViewModel>();
        builder.Services.AddSingleton<AzureAuthenticationViewModel>();
        builder.Services.AddSingleton<MonitoringViewModel>();
        builder.Services.AddSingleton<CurrentFactoryAnalyticsViewModel>();
        builder.Services.AddSingleton<TicketsViewModel>();
        builder.Services.AddSingleton<TicketConnectionsViewModel>();
        builder.Services.AddSingleton<TicketTabsViewModel>();
        builder.Services.AddSingleton<IProjectTicketLauncher, ProjectTicketLauncher>();
        builder.Services.AddSingleton<AiFactoriesViewModel>();
        builder.Services.AddSingleton<FactoryCatalogViewModel>();
        builder.Services.AddSingleton(services => new AiFactoryViewModel(
            services.GetRequiredService<OperationsSession>(),
            services.GetRequiredService<IProjectDeploymentClient>(),
            connection: services.GetRequiredService<IAiFactoryConnectionProvider>(),
            refresh: services.GetRequiredService<AzureRefreshCoordinator>(),
            terminal: services.GetRequiredService<IDeploymentTerminalSession>(),
            isCatalogScope: folder => !services.GetRequiredService<FactoryCatalogSession>().AllowsLegacyFolder(folder)));
        builder.Services.AddTransient<PromptExplorerViewModel>();
        builder.Services.AddTransient<OperationConfigViewModel>();
        builder.Services.AddTransient<FactoryConfigurationViewModel>();

        builder.Services.AddTransient<MainPage>();
        builder.Services.AddTransient<SimpleFactoryPage>();
        builder.Services.AddTransient<ConnectionPage>();
        builder.Services.AddTransient<ProjectsPage>();
        builder.Services.AddTransient<ScaleSetsPage>();
        builder.Services.AddTransient<AppearancePage>();
        builder.Services.AddTransient<AboutPage>();
        builder.Services.AddTransient<MonitoringPage>();
        builder.Services.AddTransient<TicketsPage>();
        builder.Services.AddTransient<AiFactoriesPage>();
        builder.Services.AddTransient<FactoryCatalogPage>();
        builder.Services.AddTransient<AiFactoryPage>();
        builder.Services.AddTransient<PromptExplorerPage>();
        builder.Services.AddTransient<OperationConfigPage>();
        builder.Services.AddTransient<FactoryConfigurationPage>();
        builder.Services.AddSingleton<AppShell>();

#if DEBUG
        builder.Logging.AddDebug();
#endif

        var app = builder.Build();
        AppServices.Initialize(app.Services);
        return app;
    }
}

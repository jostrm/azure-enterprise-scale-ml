using ESAIF.ConfigWizard.Pages;
using ESAIF.ConfigWizard.Services;
using ESAIF.ConfigWizard.Controls;

namespace ESAIF.ConfigWizard;

public sealed class AppShell : NavigationPage
{
    public const string WizardPageKey = "wizard";
    public const string SimpleFactoryPageKey = "simple-mode";
    public const string MonitoringPageKey = "monitoring";
    public const string FactoriesPageKey = "factories";
    public const string FactoryCatalogPageKey = "factory-catalog";
    public const string FactoryPageKey = "factory";
    public const string TicketsPageKey = "tickets";
    public const string TicketConnectionsPageKey = "ticket-connections";

    private readonly IServiceProvider _services;
    private readonly IReadOnlyDictionary<string, WorkspaceNavigationItem> _items;
    private string _currentWorkspaceKey = WizardPageKey;
    private bool _isNavigating;

    public AppShell(IServiceProvider services)
        : base(ResolvePage<MainPage>(services))
    {
        _services = services;
        NavigationPage.SetHasNavigationBar(CurrentPage, false);
        SetDynamicResource(BarBackgroundColorProperty, "Surface");
        SetDynamicResource(BarTextColorProperty, "PrimaryStrong");

        var items = new[]
        {
            new WorkspaceNavigationItem(WizardPageKey, "Configuration wizard"),
            new WorkspaceNavigationItem(SimpleFactoryPageKey, "Simple Mode"),
            new WorkspaceNavigationItem(MonitoringPageKey, "Monitoring"),
            new WorkspaceNavigationItem(FactoriesPageKey, "AI Factories"),
            new WorkspaceNavigationItem(FactoryCatalogPageKey, "Manage factories"),
            new WorkspaceNavigationItem(FactoryPageKey, "AI Factory"),
            new WorkspaceNavigationItem("projects", "Projects"),
            new WorkspaceNavigationItem("scale-sets", "Scale sets"),
            new WorkspaceNavigationItem(TicketsPageKey, "Tickets"),
            new WorkspaceNavigationItem("connection", "Connection"),
            new WorkspaceNavigationItem("appearance", "Appearance"),
            new WorkspaceNavigationItem("about", "About")
        };
        _items = items.ToDictionary(item => item.Key, StringComparer.Ordinal);
        Loaded += OnLoaded;
    }

    public static Task NavigateToWorkspaceAsync(string key)
    {
        return CurrentShell()?.ShowWorkspacePageAsync(key) ?? Task.CompletedTask;
    }

    public static Task PushPageAsync(Page page)
    {
        ArgumentNullException.ThrowIfNull(page);
        return CurrentShell()?.PushDetailPageAsync(page) ?? Task.CompletedTask;
    }

    public static Task PushOperationConfigAsync(
        string projectNumber,
        string environment,
        string kind)
    {
        var page = AppServices.GetRequiredService<OperationConfigPage>();
        page.ApplyQueryAttributes(new Dictionary<string, object>
        {
            ["projectNumber"] = projectNumber,
            ["environment"] = environment,
            ["kind"] = kind
        });
        return PushPageAsync(page);
    }

    public static Task GoBackAsync()
    {
        var shell = CurrentShell();
        return shell is not null && shell.Navigation.NavigationStack.Count > 1
            ? shell.PopAsync(false)
            : Task.CompletedTask;
    }

    public static Task CloseFlyoutAsync()
    {
        var shell = CurrentShell();
        return shell is not null && shell.Navigation.ModalStack.Count > 0
            ? shell.Navigation.PopModalAsync(false)
            : Task.CompletedTask;
    }

    public static void OpenFlyout()
    {
        var shell = CurrentShell();
        if (shell is null || shell.Navigation.ModalStack.Count > 0)
        {
            return;
        }

        _ = shell.Navigation.PushModalAsync(
            new NavigationMenuPage(
                shell._items.Values.ToArray(),
                shell._currentWorkspaceKey,
                shell.ShowWorkspacePageAsync,
                shell._services.GetRequiredService<ViewModels.AzureAuthenticationViewModel>(),
                shell._services.GetRequiredService<WizardSession>()),
            false);
    }

    public async Task ShowWorkspacePageAsync(string key)
    {
        var connectionsTab = key == TicketConnectionsPageKey;
        if (connectionsTab) key = TicketsPageKey;
        if (_isNavigating || !_items.ContainsKey(key))
        {
            return;
        }

        try
        {
            _isNavigating = true;
            if (Navigation.ModalStack.Count > 0)
            {
                await Navigation.PopModalAsync(false);
            }

            if (key is FactoryPageKey or MonitoringPageKey or "projects" or "scale-sets")
            {
                var catalog = _services.GetRequiredService<FactoryCatalogSession>();
                if (!string.IsNullOrWhiteSpace(catalog.Folder))
                {
                    string? notice = null;
                    try
                    {
                        await catalog.RefreshAsync();
                        if (!catalog.IsLegacy)
                            notice = "This root uses catalog identities. The legacy overview is not factory-scoped. Select the exact factory here; your wizard edits are preserved.";
                    }
                    catch (Exception error) when (error is HttpRequestException or IOException or
                        InvalidOperationException or ArgumentException or System.Text.Json.JsonException or OperationCanceledException)
                    {
                        notice = $"Catalog scope could not be verified. The legacy page was not opened: {error.Message}";
                    }
                    if (notice is not null)
                    {
                        _services.GetRequiredService<ViewModels.FactoryCatalogViewModel>().NavigationNotice = notice;
                        key = FactoryCatalogPageKey;
                    }
                }
            }

            var currentRoot = Navigation.NavigationStack[0];
            if (Navigation.NavigationStack.Count > 1)
            {
                await PopToRootAsync(false);
            }

            if (key == TicketsPageKey && currentRoot is TicketsPage currentTickets)
            {
                await currentTickets.ShowTabAsync(connectionsTab);
                _currentWorkspaceKey = key;
                return;
            }

            var page = CreateWorkspacePage(key);
            if (page is TicketsPage tickets) tickets.SelectTab(connectionsTab);
            NavigationPage.SetHasNavigationBar(page, false);
            Navigation.InsertPageBefore(page, currentRoot);
            await PopToRootAsync(false);
            _currentWorkspaceKey = key;
        }
        finally
        {
            _isNavigating = false;
        }
    }

    private async Task PushDetailPageAsync(Page page)
    {
        AttachFooter(page, _services);
        NavigationPage.SetHasNavigationBar(page, false);
        await PushAsync(page);
    }

    private Page CreateWorkspacePage(string key) =>
        key switch
        {
            WizardPageKey => ResolvePage<MainPage>(_services),
            SimpleFactoryPageKey => ResolvePage<SimpleFactoryPage>(_services),
            MonitoringPageKey => ResolvePage<MonitoringPage>(_services),
            TicketsPageKey => ResolvePage<TicketsPage>(_services),
            FactoriesPageKey => ResolvePage<AiFactoriesPage>(_services),
            FactoryCatalogPageKey => ResolvePage<FactoryCatalogPage>(_services),
            FactoryPageKey => ResolvePage<AiFactoryPage>(_services),
            "projects" => ResolvePage<ProjectsPage>(_services),
            "scale-sets" => ResolvePage<ScaleSetsPage>(_services),
            "connection" => ResolvePage<ConnectionPage>(_services),
            "appearance" => ResolvePage<AppearancePage>(_services),
            "about" => ResolvePage<AboutPage>(_services),
            _ => throw new ArgumentOutOfRangeException(nameof(key), key, null)
        };

    private async void OnLoaded(object? sender, EventArgs e)
    {
        Loaded -= OnLoaded;
        var requested = Environment.GetEnvironmentVariable("ESAIF_START_ROUTE");
        if (string.IsNullOrWhiteSpace(requested))
        {
            return;
        }

        var normalized = requested.Trim('/').ToLowerInvariant();
        var key = normalized switch
        {
            var value when value.Contains("factory-catalog", StringComparison.Ordinal) =>
                FactoryCatalogPageKey,
            var value when value.Contains("simple-mode", StringComparison.Ordinal) =>
                SimpleFactoryPageKey,
            var value when value.Contains("ticket-connections", StringComparison.Ordinal) =>
                TicketConnectionsPageKey,
            var value when value.Contains("tickets", StringComparison.Ordinal) =>
                TicketsPageKey,
            var value when value.Contains("monitoring", StringComparison.Ordinal) =>
                MonitoringPageKey,
            var value when value.Contains("aifactories", StringComparison.Ordinal) =>
                FactoriesPageKey,
            var value when value.Contains("aifactory", StringComparison.Ordinal) =>
                FactoryPageKey,
            _ => WizardPageKey
        };
        // The wizard is already the root; replacing it during initial loading races native navigation.
        if (key != WizardPageKey)
        {
            await ShowWorkspacePageAsync(key);
        }
    }

    private static AppShell? CurrentShell() =>
        Application.Current?.Windows.FirstOrDefault()?.Page as AppShell;

    private static Page ResolvePage<TPage>(IServiceProvider services)
        where TPage : Page
    {
        try
        {
            var page = services.GetRequiredService<TPage>();
            AttachFooter(page, services);
            return page;
        }
        catch (Exception exception)
        {
            RuntimeDiagnostics.Write("last-page-error.log", exception);
            return new ContentPage
            {
                Title = "Page unavailable",
                Content = new VerticalStackLayout
                {
                    Padding = 32,
                    Spacing = 12,
                    Children =
                    {
                        new Label
                        {
                            Text = "This page could not be created.",
                            FontSize = 24,
                            FontAttributes = FontAttributes.Bold
                        },
                        new TechnicalLabel { Caption = "Page error", Value = exception.Message }
                    }
                }
            };
        }
    }

    private static void AttachFooter(Page page, IServiceProvider services)
    {
        if (page is not ContentPage contentPage || contentPage.Content is RefreshPageLayout)
        {
            return;
        }
        var content = contentPage.Content;
        contentPage.Content = null;
        var layout = new RefreshPageLayout();
        if (content is not null)
        {
            layout.Children.Add(content);
        }
        var coordinator = services.GetRequiredService<AzureRefreshCoordinator>();
        var warnings = new WarningToastState(services.GetRequiredService<WarningToastSession>());
        layout.Children.Add(new WarningToast(contentPage, coordinator, warnings));
        var footer = new AzureRefreshFooter(coordinator, warnings);
        var terminal = new DeploymentTerminalFooter(contentPage, services.GetRequiredService<DeploymentTerminalSession>());
        Grid.SetRow(terminal, 1);
        layout.Children.Add(terminal);
        Grid.SetRow(footer, 2);
        layout.Children.Add(footer);
        contentPage.Content = layout;
    }

    private sealed class RefreshPageLayout : Grid
    {
        public RefreshPageLayout()
        {
            RowDefinitions = [new(GridLength.Star), new(GridLength.Auto), new(GridLength.Auto)];
        }
    }
}

public sealed record WorkspaceNavigationItem(string Key, string Title);

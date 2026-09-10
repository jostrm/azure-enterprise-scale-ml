using ESAIF.ConfigWizard.Controls;
using ESAIF.ConfigWizard.Services;
using ESAIF.ConfigWizard.ViewModels;

namespace ESAIF.ConfigWizard.Pages;

public sealed class NavigationMenuPage : ContentPage
{
    private readonly Border _panel;
    private readonly AzureAuthenticationViewModel _azureAuthentication;
    private readonly WizardSession _wizardSession;
    private CancellationTokenSource? _authenticationLifetime;

    public NavigationMenuPage(
        IReadOnlyList<WorkspaceNavigationItem> items,
        string selectedKey,
        Func<string, Task> navigate,
        AzureAuthenticationViewModel azureAuthentication,
        WizardSession wizardSession)
    {
        ArgumentNullException.ThrowIfNull(items);
        ArgumentNullException.ThrowIfNull(navigate);
        _azureAuthentication = azureAuthentication;
        _wizardSession = wizardSession;

        BackgroundColor = Color.FromArgb("#88000000");
        NavigationPage.SetHasNavigationBar(this, false);

        var menu = new VerticalStackLayout { Spacing = 1 };
        foreach (var item in items)
        {
            var selected = string.Equals(item.Key, selectedKey, StringComparison.Ordinal);
            var button = new Button
            {
                AutomationId = $"MenuItem-{item.Key}",
                Text = item.Title,
                BackgroundColor = Colors.Transparent,
                TextColor = Color.FromArgb("#F4F2F7"),
                HorizontalOptions = LayoutOptions.Fill,
                FontSize = 15,
                CornerRadius = 8,
                Padding = new Thickness(16, 10)
            };
            if (selected) button.SetDynamicResource(BackgroundColorProperty, "SurfaceSelected");
            SemanticProperties.SetDescription(button, selected ? $"{item.Title}, current page" : item.Title);
            button.Clicked += async (_, _) => await navigate(item.Key);
            menu.Children.Add(new GlowCard
            {
                IsSelected = selected,
                CornerRadius = 8,
                Card = button,
                AutomationId = $"MenuSelection-{item.Key}"
            });
        }

        _panel = new Border
        {
            WidthRequest = 310,
            HorizontalOptions = LayoutOptions.Start,
            VerticalOptions = LayoutOptions.Fill,
            StrokeThickness = 0,
            TranslationX = -320,
            Content = new Grid
            {
                RowDefinitions =
                {
                    new RowDefinition(new GridLength(188)),
                    new RowDefinition(GridLength.Star),
                    new RowDefinition(GridLength.Auto)
                },
                Children =
                {
                    CreateHeader(),
                    new ScrollView
                    {
                        Content = menu
                    }.AtRow(1),
                    CreateAuthenticationFooter().AtRow(2)
                }
            }
        };
        _panel.SetDynamicResource(Border.BackgroundColorProperty, "Flyout");

        var dismiss = new TapGestureRecognizer();
        dismiss.Tapped += async (_, _) => await AppShell.CloseFlyoutAsync();
        var scrim = new Grid();
        scrim.GestureRecognizers.Add(dismiss);

        Content = new Grid
        {
            Children = { scrim, _panel }
        };
    }

    protected override async void OnAppearing()
    {
        base.OnAppearing();
        _authenticationLifetime?.Dispose();
        _authenticationLifetime = new CancellationTokenSource();
        var check = _azureAuthentication.RefreshAsync(
            _wizardSession.GetString("_save_folder"), _authenticationLifetime.Token);
        await _panel.TranslateToAsync(0, 0, 220, Easing.CubicOut);
        await check;
    }

    protected override void OnDisappearing()
    {
        _authenticationLifetime?.Cancel();
        base.OnDisappearing();
    }

    private Border CreateAuthenticationFooter()
    {
        var light = new StatusLight();
        light.SetBinding(StatusLight.LightColorProperty, nameof(AzureAuthenticationViewModel.LightColor));
        light.SetBinding(StatusLight.IsPulsingProperty, nameof(AzureAuthenticationViewModel.IsWorking));
        var account = new TechnicalLabel
        {
            FontSize = 12, FontAttributes = FontAttributes.Bold, TextColor = Color.FromArgb("#ECF6FF"),
            VerticalOptions = LayoutOptions.Center, LineBreakMode = LineBreakMode.TailTruncation
        };
        account.SetBinding(TechnicalLabel.ValueProperty, nameof(AzureAuthenticationViewModel.AccountName));
        var statusRow = new Grid { ColumnDefinitions = [new(GridLength.Auto), new(GridLength.Star)] };
        statusRow.Children.Add(light);
        statusRow.Children.Add(account);
        Grid.SetColumn(account, 1);
        var message = new TechnicalLabel
        {
            FontSize = 11, TextColor = Color.FromArgb("#B5C7DF"), MaxLines = 3,
            LineBreakMode = LineBreakMode.WordWrap
        };
        message.SetBinding(TechnicalLabel.ValueProperty, nameof(AzureAuthenticationViewModel.Message));
        var button = new Button
        {
            AutomationId = "AzureAuthenticationButton",
            BackgroundColor = Color.FromArgb("#142D36"), TextColor = Color.FromArgb("#70E0EF"),
            BorderColor = Color.FromArgb("#438E9B"), BorderWidth = 1, CornerRadius = 10
        };
        button.SetBinding(Button.TextProperty, nameof(AzureAuthenticationViewModel.ButtonText));
        button.SetBinding(IsEnabledProperty, nameof(AzureAuthenticationViewModel.CanAuthenticate));
        button.Clicked += OnAzureAuthenticationClicked;
        return new Border
        {
            BindingContext = _azureAuthentication,
            Margin = 12, Padding = 14, BackgroundColor = Color.FromArgb("#111E2D"),
            Stroke = Color.FromArgb("#304565"),
            StrokeShape = new Microsoft.Maui.Controls.Shapes.RoundRectangle { CornerRadius = 14 },
            Content = new VerticalStackLayout
            {
                Spacing = 9,
                Children =
                {
                    statusRow, message, button,
                    new Label
                    {
                        Text = "Sign-in does not grant Azure resource permissions.",
                        FontSize = 10, TextColor = Color.FromArgb("#B5C7DF")
                    }
                }
            }
        };
    }

    private async void OnAzureAuthenticationClicked(object? sender, EventArgs e)
    {
        var lifetime = _authenticationLifetime;
        if (lifetime is null || lifetime.IsCancellationRequested || !_azureAuthentication.CanAuthenticate)
        {
            return;
        }
        await AppServices.GetRequiredService<AzureLoginCoordinator>()
            .AuthenticateAsync(this, cancellationToken: lifetime.Token);
    }

    private static Grid CreateHeader()
    {
        var title = new VerticalStackLayout
        {
            VerticalOptions = LayoutOptions.Center,
            Spacing = 7,
            Children =
            {
                new Label
                {
                    Text = "ENTERPRISE SCALE",
                    CharacterSpacing = 2,
                    FontAttributes = FontAttributes.Bold,
                    FontSize = 11,
                    TextColor = Color.FromArgb("#D8FFFFFF")
                },
                new Label
                {
                    Text = "AI Factory",
                    FontAttributes = FontAttributes.Bold,
                    FontSize = 29,
                    TextColor = Colors.White
                },
                new Label
                {
                    Text = "Configuration workspace",
                    FontSize = 14,
                    TextColor = Color.FromArgb("#E8FFFFFF")
                }
            }
        };
        var header = new Grid
        {
            Padding = 24,
            Children = { title }
        };
        header.SetDynamicResource(BackgroundProperty, "HeroBrush");
        return header;
    }
}

internal static class GridPlacementExtensions
{
    public static T AtRow<T>(this T view, int row)
        where T : BindableObject
    {
        Grid.SetRow(view, row);
        return view;
    }
}

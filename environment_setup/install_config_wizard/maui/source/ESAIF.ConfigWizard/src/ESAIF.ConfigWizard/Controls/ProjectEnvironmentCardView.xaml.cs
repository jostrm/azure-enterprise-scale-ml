using System.Windows.Input;
using ESAIF.ConfigWizard.Services;
using ESAIF.ConfigWizard.ViewModels;

namespace ESAIF.ConfigWizard.Controls;

public partial class ProjectEnvironmentCardView : ContentView
{
    public static readonly BindableProperty SelectCommandProperty = CommandProperty(nameof(SelectCommand));
    public static readonly BindableProperty OpenTerminalCommandProperty = CommandProperty(nameof(OpenTerminalCommand));
    public static readonly BindableProperty UpdateCommandProperty = CommandProperty(nameof(UpdateCommand));
    public static readonly BindableProperty ReviewOutcomeCommandProperty = CommandProperty(nameof(ReviewOutcomeCommand));
    public static readonly BindableProperty DeployCommandProperty = CommandProperty(
        nameof(DeployCommand));
    public static readonly BindableProperty ConfigureDataOpsCommandProperty = CommandProperty(
        nameof(ConfigureDataOpsCommand));
    public static readonly BindableProperty ConfigureMLOpsCommandProperty = CommandProperty(
        nameof(ConfigureMLOpsCommand));
    public static readonly BindableProperty ConfigureRagCommandProperty = CommandProperty(
        nameof(ConfigureRagCommand));
    public static readonly BindableProperty ConfigureFineTuningCommandProperty = CommandProperty(
        nameof(ConfigureFineTuningCommand));

    public ProjectEnvironmentCardView()
    {
        InitializeComponent();
    }

    public ICommand? DeployCommand
    {
        get => (ICommand?)GetValue(DeployCommandProperty);
        set => SetValue(DeployCommandProperty, value);
    }

    public ICommand? SelectCommand
    {
        get => (ICommand?)GetValue(SelectCommandProperty);
        set => SetValue(SelectCommandProperty, value);
    }

    public ICommand? UpdateCommand
    {
        get => (ICommand?)GetValue(UpdateCommandProperty);
        set => SetValue(UpdateCommandProperty, value);
    }

    public ICommand? ReviewOutcomeCommand
    {
        get => (ICommand?)GetValue(ReviewOutcomeCommandProperty);
        set => SetValue(ReviewOutcomeCommandProperty, value);
    }

    public ICommand? OpenTerminalCommand
    {
        get => (ICommand?)GetValue(OpenTerminalCommandProperty);
        set => SetValue(OpenTerminalCommandProperty, value);
    }

    public ICommand? ConfigureDataOpsCommand
    {
        get => (ICommand?)GetValue(ConfigureDataOpsCommandProperty);
        set => SetValue(ConfigureDataOpsCommandProperty, value);
    }

    public ICommand? ConfigureMLOpsCommand
    {
        get => (ICommand?)GetValue(ConfigureMLOpsCommandProperty);
        set => SetValue(ConfigureMLOpsCommandProperty, value);
    }

    public ICommand? ConfigureRagCommand
    {
        get => (ICommand?)GetValue(ConfigureRagCommandProperty);
        set => SetValue(ConfigureRagCommandProperty, value);
    }

    public ICommand? ConfigureFineTuningCommand
    {
        get => (ICommand?)GetValue(ConfigureFineTuningCommandProperty);
        set => SetValue(ConfigureFineTuningCommandProperty, value);
    }

    private async void OnOpenResourceGroupClicked(object? sender, EventArgs e)
    {
        if (BindingContext is not ProjectEnvironmentCardViewModel model)
        {
            return;
        }
        Page? page = null;
        for (Element? ancestor = Parent; ancestor is not null; ancestor = ancestor.Parent)
        {
            if (ancestor is Page owner)
            {
                page = owner;
                break;
            }
        }
        if (page is null)
        {
            return;
        }
        await ProjectResourceGroupNavigator.OpenAsync(page, model.ResourceGroupLinks, model.ResourceGroupLinkHint);
    }

    private void OnPlanningOptionsClicked(object? sender, EventArgs e)
    {
        if (BindingContext is ProjectEnvironmentCardViewModel { IsDeployed: true } model)
        {
            model.ShowPlanningOptions = !model.ShowPlanningOptions;
        }
    }

    private static BindableProperty CommandProperty(string name) =>
        BindableProperty.Create(
            name,
            typeof(ICommand),
            typeof(ProjectEnvironmentCardView));
}

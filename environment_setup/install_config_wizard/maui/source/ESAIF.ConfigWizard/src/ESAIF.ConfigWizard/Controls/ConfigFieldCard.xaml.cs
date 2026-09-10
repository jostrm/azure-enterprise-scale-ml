using ESAIF.ConfigWizard.ViewModels;

namespace ESAIF.ConfigWizard.Controls;

public partial class ConfigFieldCard : ContentView
{
    public ConfigFieldCard()
    {
        InitializeComponent();
    }

    protected override void OnBindingContextChanged()
    {
        base.OnBindingContextChanged();
        if (SpecializedEditor is null)
        {
            return;
        }
        SpecializedEditor.Content = BindingContext switch
        {
            ConfigFieldViewModel { ScalingMode: { } scaling } =>
                new ScalingModeEditor { BindingContext = scaling },
            ConfigFieldViewModel { NetworkMode: { } network } =>
                new NetworkModeEditor { BindingContext = network },
            ConfigFieldViewModel { HubTopology: { } hub } =>
                new HubTopologyEditor { BindingContext = hub },
            ConfigFieldViewModel { RunnerConfiguration: { } runner } =>
                new RunnerConfigurationEditor { BindingContext = runner },
            _ => null
        };
        SpecializedEditor.IsVisible = SpecializedEditor.Content is not null;
    }
}

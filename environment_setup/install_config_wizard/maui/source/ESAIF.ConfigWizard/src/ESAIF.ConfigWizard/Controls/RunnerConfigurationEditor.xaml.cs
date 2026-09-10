using ESAIF.ConfigWizard.ViewModels;

namespace ESAIF.ConfigWizard.Controls;

public partial class RunnerConfigurationEditor : ContentView
{
    public RunnerConfigurationEditor()
    {
        InitializeComponent();
        _ = new RadioChoiceGroup<RunnerConfigurationViewModel>(this,
            (HostedRadio, model => model.IsHosted, model => model.IsHosted = true),
            (SelfHostedRadio, model => model.IsSelfHosted, model => model.IsSelfHosted = true));
    }
}

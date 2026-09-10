using ESAIF.ConfigWizard.ViewModels;

namespace ESAIF.ConfigWizard.Controls;

public partial class HubTopologyEditor : ContentView
{
    public HubTopologyEditor()
    {
        InitializeComponent();
        _ = new RadioChoiceGroup<HubTopologyViewModel>(this,
            (StandaloneRadio, model => model.IsStandalone, model => model.IsStandalone = true),
            (OwnHubRadio, model => model.IsOwnHub, model => model.IsOwnHub = true),
            (ExternalHubRadio, model => model.IsExternalHub, model => model.IsExternalHub = true));
    }
}

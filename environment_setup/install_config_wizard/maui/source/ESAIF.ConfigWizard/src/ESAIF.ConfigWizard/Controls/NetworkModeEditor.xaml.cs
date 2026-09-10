using ESAIF.ConfigWizard.ViewModels;

namespace ESAIF.ConfigWizard.Controls;

public partial class NetworkModeEditor : ContentView
{
    public NetworkModeEditor()
    {
        InitializeComponent();
        _ = new RadioChoiceGroup<NetworkModeViewModel>(this,
            (PrivateRadio, model => model.IsPrivate, model => model.IsPrivate = true),
            (HybridRadio, model => model.IsHybrid, model => model.IsHybrid = true),
            (PublicRadio, model => model.IsPublic, model => model.IsPublic = true));
    }
}

using ESAIF.ConfigWizard.ViewModels;
using ESAIF.ConfigWizard.Services;

namespace ESAIF.ConfigWizard.Pages;

public partial class AppearancePage : ContentPage
{
    public AppearancePage()
        : this(AppServices.GetRequiredService<AppearanceViewModel>())
    {
    }

    public AppearancePage(AppearanceViewModel viewModel)
    {
        InitializeComponent();
        BindingContext = viewModel;
    }
}

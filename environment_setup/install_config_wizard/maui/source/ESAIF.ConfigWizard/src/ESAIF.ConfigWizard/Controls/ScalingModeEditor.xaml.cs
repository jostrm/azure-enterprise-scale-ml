using ESAIF.ConfigWizard.ViewModels;
using ESAIF.ConfigWizard.Pages;

namespace ESAIF.ConfigWizard.Controls;

public partial class ScalingModeEditor : ContentView
{
    public ScalingModeEditor()
    {
        InitializeComponent();
        _ = new RadioChoiceGroup<ScalingModeViewModel>(this,
            (OwnRadio, model => model.IsOwn, model => model.IsOwn = true),
            (SharedRadio, model => model.IsShared, model => model.IsShared = true));
    }

    private async void OnApplyDefaultsClicked(object? sender, EventArgs e)
    {
        if (BindingContext is not ScalingModeViewModel model) return;
        var page = RequirePage();
        var changes = model.DefaultChanges;
        if (await MessageDetailsPage.ConfirmAsync(page, "Replace draft network defaults?",
            $"For new networks only. XX resolves to separate, non-overlapping Dev/Stage/Prod VNets. Existing deployed addresses will not be moved. These draft fields will be replaced:\n\n{changes}",
            "Apply to draft", "Cancel") && BindingContext == model && model.DefaultChanges == changes)
            model.ApplyDefaults();
    }

    private async void OnOptimizeSpaceClicked(object? sender, EventArgs e)
    {
        if (BindingContext is not ScalingModeViewModel model || !model.CanOptimize) return;
        var page = RequirePage();
        var preview = model.PrepareOptimization();
        if (!await MessageDetailsPage.ConfirmAsync(page, "Optimize draft subnet placement?", preview.Message, "Apply to draft", "Cancel"))
            return;
        if (BindingContext != model || !model.ApplyOptimization(preview))
            await page.DisplayAlertAsync("Configuration changed", "Review a new optimization preview for the current network settings.", "OK");
    }

    private Page RequirePage()
    {
        Element? ancestor = Parent;
        while (ancestor is not null and not Page) ancestor = ancestor.Parent;
        return ancestor as Page ?? throw new InvalidOperationException("Open the configuration page before editing network placement.");
    }
}

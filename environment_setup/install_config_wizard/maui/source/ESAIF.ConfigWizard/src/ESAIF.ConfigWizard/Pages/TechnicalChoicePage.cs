using ESAIF.ConfigWizard.Controls;
using ESAIF.ConfigWizard.Services;

namespace ESAIF.ConfigWizard.Pages;

/// <summary>A native choice dialog with friendly labels and a separate details action.</summary>
public sealed class TechnicalChoicePage : ContentPage
{
    private readonly TaskCompletionSource<int> _result = new(TaskCreationOptions.RunContinuationsAsynchronously);

    private TechnicalChoicePage(string title, IReadOnlyList<string> values)
    {
        Title = TechnicalValuePresentation.Summary(title);
        NavigationPage.SetHasNavigationBar(this, false);
        var choices = values.Select((value, index) => new Choice(index, value)).ToList();
        var picker = new TechnicalPicker
        {
            Title = "Choose an option", ItemsSource = choices,
            ItemDisplayBinding = new Binding(nameof(Choice.Value)), SelectedItem = choices.FirstOrDefault(),
            AutomationId = "TechnicalChoicePicker"
        };
        var cancel = new Button { Text = "Cancel" };
        var select = new Button { Text = "Use selected option", AutomationId = "ConfirmTechnicalChoice" };
        cancel.Clicked += async (_, _) => await CloseAsync(-1);
        select.Clicked += async (_, _) =>
        {
            if (picker.SelectedItem is Choice choice) await CloseAsync(choice.Index);
        };
        Content = new VerticalStackLayout
        {
            Padding = 24, Spacing = 16,
            Children =
            {
                new Label { Text = Title, FontSize = 24, FontAttributes = FontAttributes.Bold },
                new Label { Text = "Choose by name. Use Details to inspect or copy a full identifier." },
                picker, select, cancel
            }
        };
    }

    private async Task CloseAsync(int index)
    {
        await Navigation.PopModalAsync(false);
        _result.TrySetResult(index);
    }

    protected override bool OnBackButtonPressed()
    {
        _result.TrySetResult(-1);
        return base.OnBackButtonPressed();
    }

    public static async Task<int> ChooseAsync(Page owner, string title, IReadOnlyList<string> values)
    {
        if (values.Count == 0) return -1;
        var page = new TechnicalChoicePage(title, values);
        await owner.Navigation.PushModalAsync(page, false);
        return await page._result.Task;
    }

    private sealed record Choice(int Index, string Value);
}

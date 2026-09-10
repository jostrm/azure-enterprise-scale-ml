using System.Runtime.InteropServices;
using ESAIF.ConfigWizard.Services;

namespace ESAIF.ConfigWizard.Pages;

public sealed class MessageDetailsPage : ContentPage
{
    private readonly TaskCompletionSource _closed = new(TaskCreationOptions.RunContinuationsAsynchronously);
    private readonly Editor _text;
    private readonly string _message;
    private readonly Label _copyStatus;
    private readonly Button[] _valueActions;
    private string? _editedValue;
    private bool _invalid;
    private bool _accepted;

    private MessageDetailsPage(string title, string message, string closeText, bool reveal, bool editable = false, string? acceptText = null)
    {
        Title = TechnicalValuePresentation.Summary(title);
        _message = message;
        NavigationPage.SetHasNavigationBar(this, false);
        var heading = new Label { Text = Title, FontSize = 24, FontAttributes = FontAttributes.Bold };
        var instruction = new Label
        {
            Text = "Select text with your mouse and copy it, or use Copy all.",
            FontSize = 12
        };
        instruction.SetDynamicResource(Label.TextColorProperty, "Muted");
        var concealed = !reveal && TechnicalValuePresentation.HasDetails(message);
        var text = _text = new Editor
        {
            Text = concealed ? TechnicalValuePresentation.Summary(message) : message,
            IsReadOnly = !editable, AutoSize = EditorAutoSizeOption.Disabled,
            IsSpellCheckEnabled = false, IsTextPredictionEnabled = false,
            FontSize = 14, AutomationId = "SelectableMessageDetails",
            HorizontalOptions = LayoutOptions.Fill, VerticalOptions = LayoutOptions.Fill
        };
        text.SetDynamicResource(Editor.TextColorProperty, "Text");
        text.SetDynamicResource(Editor.BackgroundColorProperty, "Surface");
        SemanticProperties.SetDescription(text, editable ? "Edit the full field value." : "Read-only message details. Select and copy text.");
        var copy = new Button { Text = "Copy all", AutomationId = "CopyMessageDetails" };
        copy.Clicked += OnCopyClicked;
        var close = new Button { Text = closeText, AutomationId = "CloseMessageDetails" };
        var revealButton = new Button { Text = "Reveal full details", IsVisible = concealed, AutomationId = "RevealMessageDetails" };
        revealButton.Clicked += (_, _) =>
        {
            if (_invalid) return;
            text.Text = message;
            revealButton.IsVisible = false;
        };
        var save = new Button { Text = editable ? "Save value" : acceptText, IsVisible = editable || acceptText is not null, AutomationId = "SaveTechnicalValue" };
        _valueActions = [copy, revealButton, save];
        save.Clicked += async (_, _) =>
        {
            if (_invalid) return;
            if (editable) _editedValue = text.Text ?? string.Empty;
            else _accepted = true;
            await Navigation.PopModalAsync(false);
            _closed.TrySetResult();
        };
        close.Clicked += async (_, _) =>
        {
            await Navigation.PopModalAsync(false);
            _closed.TrySetResult();
        };
        _copyStatus = new Label { FontSize = 12, VerticalOptions = LayoutOptions.Center };
        var actions = new Grid { ColumnDefinitions = [new(GridLength.Star), new(GridLength.Auto), new(GridLength.Auto), new(GridLength.Auto), new(GridLength.Auto)], ColumnSpacing = 12 };
        actions.Children.Add(_copyStatus);
        actions.Children.Add(copy);
        actions.Children.Add(close);
        actions.Children.Add(revealButton);
        actions.Children.Add(save);
        Grid.SetColumn(copy, 1);
        Grid.SetColumn(revealButton, 2);
        Grid.SetColumn(save, 3);
        Grid.SetColumn(close, 4);
        var content = new Grid
        {
            Padding = 24, RowSpacing = 12,
            RowDefinitions = [new(GridLength.Auto), new(GridLength.Auto), new(GridLength.Star), new(GridLength.Auto)]
        };
        content.Children.Add(heading);
        content.Children.Add(instruction);
        content.Children.Add(text);
        content.Children.Add(actions);
        Grid.SetRow(instruction, 1);
        Grid.SetRow(text, 2);
        Grid.SetRow(actions, 3);
        Content = content;
    }

    public static async Task ShowAsync(Page owner, string title, string message, string closeText = "Close", bool reveal = false,
        CancellationToken validity = default)
    {
        var page = new MessageDetailsPage(title, message, closeText, reveal);
        await owner.Navigation.PushModalAsync(page, false);
        using var registration = validity.Register(() => MainThread.BeginInvokeOnMainThread(page.Invalidate));
        await page._closed.Task;
    }

    public static async Task<string?> EditAsync(Page owner, string title, string value, int maxLength = int.MaxValue,
        CancellationToken validity = default)
    {
        var page = new MessageDetailsPage(title, value, "Cancel", reveal: true, editable: true);
        page._text.MaxLength = maxLength;
        await owner.Navigation.PushModalAsync(page, false);
        using var registration = validity.Register(() => MainThread.BeginInvokeOnMainThread(page.Invalidate));
        await page._closed.Task;
        return page._invalid ? null : page._editedValue;
    }

    public static async Task<bool> ConfirmAsync(Page owner, string title, string message, string acceptText, string cancelText)
    {
        var page = new MessageDetailsPage(title, message, cancelText, reveal: false, acceptText: acceptText);
        await owner.Navigation.PushModalAsync(page, false);
        await page._closed.Task;
        return page._accepted;
    }

    private void Invalidate()
    {
        _invalid = true;
        _text.IsReadOnly = true;
        _text.Text = "This value changed or is no longer selected. Close and reopen details to see the current value.";
        _copyStatus.Text = "Previous details are no longer available.";
        foreach (var action in _valueActions) action.IsEnabled = false;
    }

    protected override void OnDisappearing()
    {
        base.OnDisappearing();
        _closed.TrySetResult();
    }

    private async void OnCopyClicked(object? sender, EventArgs e)
    {
        if (_invalid) return;
        try
        {
            await Clipboard.Default.SetTextAsync(_text.IsReadOnly ? _message : _text.Text ?? string.Empty);
            _copyStatus.Text = "Copied.";
        }
        catch (Exception exception) when (exception is IOException or UnauthorizedAccessException or
            NotSupportedException or COMException)
        {
            _copyStatus.Text = "Could not copy. Select the text and copy it manually.";
        }
    }
}

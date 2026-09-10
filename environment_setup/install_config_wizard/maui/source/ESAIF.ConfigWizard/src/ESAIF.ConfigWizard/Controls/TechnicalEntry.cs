using ESAIF.ConfigWizard.Pages;
using ESAIF.ConfigWizard.Services;
using System.Windows.Input;

namespace ESAIF.ConfigWizard.Controls;

/// <summary>Edits raw values only after disclosure; ordinary text remains an inline input.</summary>
public sealed class TechnicalEntry : Grid
{
    public static readonly BindableProperty TextProperty = BindableProperty.Create(
        nameof(Text), typeof(string), typeof(TechnicalEntry), string.Empty, BindingMode.TwoWay, propertyChanged: Refresh);
    public static readonly BindableProperty CaptionProperty = BindableProperty.Create(
        nameof(Caption), typeof(string), typeof(TechnicalEntry), "Field value", propertyChanged: Refresh);
    public static readonly BindableProperty ContextProperty = BindableProperty.Create(
        nameof(Context), typeof(string), typeof(TechnicalEntry), string.Empty, propertyChanged: Refresh);
    public static readonly BindableProperty ConcealProperty = BindableProperty.Create(
        nameof(Conceal), typeof(bool), typeof(TechnicalEntry), false, propertyChanged: Refresh);
    public static readonly BindableProperty IsReadOnlyProperty = BindableProperty.Create(
        nameof(IsReadOnly), typeof(bool), typeof(TechnicalEntry), false, propertyChanged: Refresh);
    public static readonly BindableProperty PlaceholderProperty = BindableProperty.Create(
        nameof(Placeholder), typeof(string), typeof(TechnicalEntry), string.Empty, propertyChanged: Refresh);
    public static readonly BindableProperty FontSizeProperty = BindableProperty.Create(
        nameof(FontSize), typeof(double), typeof(TechnicalEntry), 14d, propertyChanged: Refresh);
    public static readonly BindableProperty KeyboardProperty = BindableProperty.Create(
        nameof(Keyboard), typeof(Keyboard), typeof(TechnicalEntry), Keyboard.Default, propertyChanged: Refresh);
    public static readonly BindableProperty HorizontalTextAlignmentProperty = BindableProperty.Create(
        nameof(HorizontalTextAlignment), typeof(TextAlignment), typeof(TechnicalEntry), TextAlignment.Start, propertyChanged: Refresh);
    public static readonly BindableProperty IsMultilineProperty = BindableProperty.Create(
        nameof(IsMultiline), typeof(bool), typeof(TechnicalEntry), false, propertyChanged: Refresh);
    public static readonly BindableProperty MaxLengthProperty = BindableProperty.Create(
        nameof(MaxLength), typeof(int), typeof(TechnicalEntry), int.MaxValue, propertyChanged: Refresh);
    public static readonly BindableProperty ReturnCommandProperty = BindableProperty.Create(
        nameof(ReturnCommand), typeof(ICommand), typeof(TechnicalEntry), null, propertyChanged: Refresh);

    private readonly Entry _entry = new();
    private readonly Editor _editor = new() { AutoSize = EditorAutoSizeOption.TextChanges };
    private readonly Button _details = new() { BackgroundColor = Colors.Transparent, HorizontalOptions = LayoutOptions.Fill };
    private bool _syncing;
    private bool _writingFromInput;
    private bool _typing;
    private bool _showing;
    private long _revision;
    private CancellationTokenSource? _disclosure;

    public string Text { get => (string)GetValue(TextProperty); set => SetValue(TextProperty, value); }
    public string Caption { get => (string)GetValue(CaptionProperty); set => SetValue(CaptionProperty, value); }
    public string Context { get => (string)GetValue(ContextProperty); set => SetValue(ContextProperty, value); }
    public bool Conceal { get => (bool)GetValue(ConcealProperty); set => SetValue(ConcealProperty, value); }
    public new bool IsReadOnly { get => (bool)GetValue(IsReadOnlyProperty); set => SetValue(IsReadOnlyProperty, value); }
    public string Placeholder { get => (string)GetValue(PlaceholderProperty); set => SetValue(PlaceholderProperty, value); }
    public double FontSize { get => (double)GetValue(FontSizeProperty); set => SetValue(FontSizeProperty, value); }
    public Keyboard Keyboard { get => (Keyboard)GetValue(KeyboardProperty); set => SetValue(KeyboardProperty, value); }
    public TextAlignment HorizontalTextAlignment { get => (TextAlignment)GetValue(HorizontalTextAlignmentProperty); set => SetValue(HorizontalTextAlignmentProperty, value); }
    public bool IsMultiline { get => (bool)GetValue(IsMultilineProperty); set => SetValue(IsMultilineProperty, value); }
    public int MaxLength { get => (int)GetValue(MaxLengthProperty); set => SetValue(MaxLengthProperty, value); }
    public ICommand? ReturnCommand { get => (ICommand?)GetValue(ReturnCommandProperty); set => SetValue(ReturnCommandProperty, value); }

    public TechnicalEntry()
    {
        _details.SetDynamicResource(Button.TextColorProperty, "PrimaryStrong");
        Children.Add(_entry);
        Children.Add(_editor);
        Children.Add(_details);
        _entry.TextChanged += OnTextChanged;
        _editor.TextChanged += OnTextChanged;
        _entry.Focused += (_, _) => _typing = true;
        _editor.Focused += (_, _) => _typing = true;
        _entry.Unfocused += (_, _) => { _typing = false; Refresh(); };
        _editor.Unfocused += (_, _) => { _typing = false; Refresh(); };
        _details.Clicked += OnDetailsClicked;
        Refresh();
    }

    protected override void OnBindingContextChanged()
    {
        _typing = false;
        _disclosure?.Cancel();
        _revision++;
        base.OnBindingContextChanged();
        Refresh();
    }

    private static void Refresh(BindableObject target, object oldValue, object newValue)
    {
        var control = (TechnicalEntry)target;
        if (!control._writingFromInput) control._typing = false;
        control._disclosure?.Cancel();
        control._revision++;
        control.Refresh();
    }

    private void OnTextChanged(object? sender, TextChangedEventArgs args)
    {
        if (_syncing) return;
        _writingFromInput = true;
        try { Text = args.NewTextValue; }
        finally { _writingFromInput = false; }
    }

    private void Refresh()
    {
        var secret = TechnicalValuePresentation.IsSecret(Context);
        var hidden = !secret && !_typing && (Conceal || TechnicalValuePresentation.HasDetails(Text) ||
            TechnicalValuePresentation.IsLocalField(Context) && !string.IsNullOrWhiteSpace(Text));
        _syncing = true;
        try
        {
            _entry.IsPassword = secret;
            _entry.IsVisible = !hidden && (!IsMultiline || secret);
            _editor.IsVisible = !hidden && IsMultiline && !secret;
            // Never populate hidden inline editors with undisclosed technical values.
            _entry.Text = hidden ? string.Empty : Text;
            _editor.Text = hidden || secret ? string.Empty : Text;
            _entry.IsReadOnly = _editor.IsReadOnly = IsReadOnly;
            _entry.MaxLength = _editor.MaxLength = MaxLength;
            _entry.ReturnCommand = ReturnCommand;
            _entry.Placeholder = _editor.Placeholder = Placeholder;
            _entry.FontSize = _editor.FontSize = _details.FontSize = FontSize;
            _entry.Keyboard = _editor.Keyboard = Keyboard;
            _entry.HorizontalTextAlignment = _editor.HorizontalTextAlignment = HorizontalTextAlignment;
            _details.IsVisible = hidden;
            _details.Text = TechnicalValuePresentation.SafeCaption(Caption) + (IsReadOnly ? " · view / copy" : " · view / edit");
            ToolTipProperties.SetText(_details, secret ? string.Empty : Text ?? string.Empty);
        }
        finally { _syncing = false; }
    }

    private async void OnDetailsClicked(object? sender, EventArgs args)
    {
        if (_showing || TechnicalLabel.FindPage(this) is not { } page) return;
        _showing = true;
        _disclosure = new();
        var revision = _revision;
        try
        {
            if (IsReadOnly)
                await MessageDetailsPage.ShowAsync(page, TechnicalValuePresentation.SafeCaption(Caption), Text, reveal: true, validity: _disclosure.Token);
            else
            {
                var edited = await MessageDetailsPage.EditAsync(page, TechnicalValuePresentation.SafeCaption(Caption), Text, MaxLength, _disclosure.Token);
                // A recycled field or refreshed model must not accept edits to its previous value.
                if (edited is not null && revision == _revision) Text = edited;
            }
        }
        finally { _showing = false; _disclosure.Dispose(); _disclosure = null; Refresh(); }
    }
}

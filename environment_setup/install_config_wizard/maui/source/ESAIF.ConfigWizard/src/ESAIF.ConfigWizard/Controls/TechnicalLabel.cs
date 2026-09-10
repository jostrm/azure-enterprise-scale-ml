using ESAIF.ConfigWizard.Pages;
using ESAIF.ConfigWizard.Services;

namespace ESAIF.ConfigWizard.Controls;

/// <summary>An explicit raw-value binding with a safe default and on-demand original details.</summary>
public sealed class TechnicalLabel : Label
{
    public static readonly BindableProperty ValueProperty = BindableProperty.Create(
        nameof(Value), typeof(string), typeof(TechnicalLabel), string.Empty, propertyChanged: Refresh);
    public static readonly BindableProperty CaptionProperty = BindableProperty.Create(
        nameof(Caption), typeof(string), typeof(TechnicalLabel), "Details", propertyChanged: Refresh);
    public static readonly BindableProperty ConcealProperty = BindableProperty.Create(
        nameof(Conceal), typeof(bool), typeof(TechnicalLabel), false, propertyChanged: Refresh);

    private bool _showing;
    private readonly TapGestureRecognizer _tap = new();
    private CancellationTokenSource? _disclosure;
    public string Value { get => (string)GetValue(ValueProperty); set => SetValue(ValueProperty, value); }
    public string Caption { get => (string)GetValue(CaptionProperty); set => SetValue(CaptionProperty, value); }
    public bool Conceal { get => (bool)GetValue(ConcealProperty); set => SetValue(ConcealProperty, value); }

    public TechnicalLabel()
    {
        _tap.Tapped += async (_, _) =>
        {
            if (_showing || !HasDetails || FindPage(this) is not { } page) return;
            _showing = true;
            _disclosure = new();
            try { await MessageDetailsPage.ShowAsync(page, TechnicalValuePresentation.SafeCaption(Caption), Value, reveal: true, validity: _disclosure.Token); }
            finally { _showing = false; _disclosure.Dispose(); _disclosure = null; }
        };
    }

    protected override void OnBindingContextChanged()
    {
        _disclosure?.Cancel();
        base.OnBindingContextChanged();
        Refresh();
    }

    private bool HasDetails => !string.IsNullOrEmpty(Value) &&
        (Conceal || TechnicalValuePresentation.HasDetails(Value));

    private static void Refresh(BindableObject target, object oldValue, object newValue) =>
        ((TechnicalLabel)target).Refresh();

    private void Refresh()
    {
        _disclosure?.Cancel();
        Text = TechnicalValuePresentation.Summary(Value, Caption, Conceal) + (HasDetails ? " · details" : "");
        ToolTipProperties.SetText(this, HasDetails ? Value ?? string.Empty : string.Empty);
        SemanticProperties.SetHint(this, HasDetails ? "Click or tap to view and copy the full value." : null);
        if (HasDetails && !GestureRecognizers.Contains(_tap)) GestureRecognizers.Add(_tap);
        else if (!HasDetails) GestureRecognizers.Remove(_tap);
    }

    internal static Page? FindPage(Element? element)
    {
        while (element is not null)
        {
            if (element is Page page) return page;
            element = element.Parent;
        }
        return null;
    }
}

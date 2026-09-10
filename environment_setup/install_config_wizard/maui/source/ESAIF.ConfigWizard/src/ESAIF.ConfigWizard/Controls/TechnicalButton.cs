using ESAIF.ConfigWizard.Services;

namespace ESAIF.ConfigWizard.Controls;

/// <summary>Preserves the action and command parameter while presenting a safe action caption.</summary>
public sealed class TechnicalButton : Button
{
    public static readonly BindableProperty ValueProperty = BindableProperty.Create(
        nameof(Value), typeof(string), typeof(TechnicalButton), string.Empty,
        propertyChanged: (target, _, _) => ((TechnicalButton)target).Refresh());
    public string Value { get => (string)GetValue(ValueProperty); set => SetValue(ValueProperty, value); }

    private void Refresh()
    {
        Text = TechnicalValuePresentation.Summary(Value);
        ToolTipProperties.SetText(this, TechnicalValuePresentation.HasDetails(Value) ? Value : string.Empty);
    }
}

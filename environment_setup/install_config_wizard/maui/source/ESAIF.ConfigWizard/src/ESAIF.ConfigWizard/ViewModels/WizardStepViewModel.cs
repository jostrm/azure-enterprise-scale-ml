using System.Collections.ObjectModel;
using ESAIF.BaseLayer.Application;

namespace ESAIF.ConfigWizard.ViewModels;

public sealed class WizardStepViewModel : ObservableObject
{
    private bool _isSelected;

    public WizardStepViewModel(
        int number,
        string title,
        string description,
        IEnumerable<ConfigFieldViewModel> fields,
        bool isReview = false,
        bool isSkuStep = false)
    {
        Number = number;
        Title = title;
        Description = description;
        Fields = new ObservableCollection<ConfigFieldViewModel>(fields);
        IsReview = isReview;
        IsSkuStep = isSkuStep;
        DevSkuFields = new ObservableCollection<ConfigFieldViewModel>(
            Fields
                .Where(field =>
                    IsSharedSku(field.Key) ||
                    field.Key.EndsWith("Dev", StringComparison.Ordinal))
                .OrderBy(field => field.Label, StringComparer.OrdinalIgnoreCase));
        StageProdSkuFields = new ObservableCollection<ConfigFieldViewModel>(
            Fields
                .Where(field =>
                    IsSharedSku(field.Key) ||
                    field.Key.EndsWith("StageProd", StringComparison.Ordinal))
                .OrderBy(field => field.Label, StringComparer.OrdinalIgnoreCase));
    }

    public int Number { get; }

    public string Title { get; }

    public string Description { get; }

    public ObservableCollection<ConfigFieldViewModel> Fields { get; }

    public int FieldCount => Fields.Count;

    public bool IsReview { get; }

    public bool IsSkuStep { get; }
    public ScalingModeViewModel? NetworkFormatHelp { get; init; }
    public bool HasNetworkFormatHelp => NetworkFormatHelp is not null;

    public ObservableCollection<ConfigFieldViewModel> DevSkuFields { get; }

    public ObservableCollection<ConfigFieldViewModel> StageProdSkuFields { get; }

    public bool IsSelected
    {
        get => _isSelected;
        set => SetProperty(ref _isSelected, value);
    }

    public string NumberLabel => Number.ToString("00");

    private static bool IsSharedSku(string key)
    {
        return !key.EndsWith("Dev", StringComparison.Ordinal) &&
               !key.EndsWith("StageProd", StringComparison.Ordinal);
    }
}

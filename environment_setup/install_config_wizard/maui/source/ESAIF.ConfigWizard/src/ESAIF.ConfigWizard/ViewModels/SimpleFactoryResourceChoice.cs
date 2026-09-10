using ESAIF.BaseLayer.Application;
using ESAIF.DomainLayer.Configuration;

namespace ESAIF.ConfigWizard.ViewModels;

public sealed class SimpleFactoryResourceChoice : ObservableObject
{
    private readonly Action<SimpleFactoryResourceChoice> _selectionChanged;
    private bool _isSelected;

    public SimpleFactoryResourceChoice(SimpleFactoryResource resource, bool selected,
        string dependencyGuidance, Action<SimpleFactoryResourceChoice> selectionChanged)
    {
        Resource = resource;
        _isSelected = resource.Required || selected;
        DependencyGuidance = dependencyGuidance;
        _selectionChanged = selectionChanged;
    }

    public SimpleFactoryResource Resource { get; }
    public string Id => Resource.Id;
    public string Label => Resource.Label;
    public string Description => Resource.Description;
    public bool IsRequired => Resource.Required;
    public bool CanChange => !IsRequired;
    public string Requirement => IsRequired ? "Required · always included" : "Optional";
    public string DependencyGuidance { get; }
    public bool IsSelected
    {
        get => _isSelected;
        set
        {
            if (IsRequired && !value)
            {
                OnPropertyChanged(nameof(IsSelected));
                return;
            }
            if (SetProperty(ref _isSelected, value)) _selectionChanged(this);
        }
    }
}

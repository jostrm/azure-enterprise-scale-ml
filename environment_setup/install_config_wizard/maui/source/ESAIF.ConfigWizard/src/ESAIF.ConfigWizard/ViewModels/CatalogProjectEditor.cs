using System.Collections.ObjectModel;
using ESAIF.BaseLayer.Application;
using ESAIF.ConfigWizard.Services;
using ESAIF.DomainLayer.Configuration;

namespace ESAIF.ConfigWizard.ViewModels;

public sealed class CatalogProjectEditor : ObservableObject
{
    private string _scope = string.Empty;
    private string _number = string.Empty, _displayName = string.Empty;
    public event EventHandler? Edited;
    public ObservableCollection<CatalogPlacementEditor> Environments { get; } = [];
    public string Number { get => _number; set { if (SetProperty(ref _number, value)) Edited?.Invoke(this, EventArgs.Empty); } }
    public string DisplayName { get => _displayName; set { if (SetProperty(ref _displayName, value)) Edited?.Invoke(this, EventArgs.Empty); } }

    public CatalogProjectEditor()
    {
        foreach (var environment in FactoryCatalogPresentation.Environments)
        {
            var row = new CatalogPlacementEditor(environment.Value, environment.Display);
            row.Edited += (_, _) => Edited?.Invoke(this, EventArgs.Empty);
            Environments.Add(row);
        }
    }

    public void LoadScope(string folder, CatalogFactory? factory, CatalogProject? project, bool append)
    {
        var scope = $"{folder}\0{factory?.Id}\0{append}\0{(append ? project?.Id : null)}";
        var reset = scope != _scope;
        _scope = scope;
        foreach (var row in Environments) row.Update(factory, append ? project : null, reset);
    }

    public IReadOnlyList<CatalogPlacement> BuildPlacements(string folder, CatalogFactory factory, CatalogProject? project, bool append)
    {
        if (_scope != $"{folder}\0{factory.Id}\0{append}\0{(append ? project?.Id : null)}")
            throw new InvalidOperationException("The project placement scope changed. Select the exact factory and project again.");
        if (append && project is null) throw new InvalidOperationException("Select the exact existing project before adding placements.");
        if (!append) project = null;
        var number = append ? project!.Number : Number;
        if (number.Length != 3 || number.Any(character => !char.IsAsciiDigit(character)) || !append && number == "000")
            throw new InvalidOperationException("Enter an explicit project number from 001 through 999.");
        if (!append && (string.IsNullOrWhiteSpace(DisplayName) || DisplayName.Length > 128))
            throw new InvalidOperationException("Enter a readable project name from 1 through 128 characters.");
        var placements = new List<CatalogPlacement>();
        foreach (var row in Environments.Where(row => row.Selected?.ScaleSetId is not null))
        {
            if (row.IsExisting)
                throw new InvalidOperationException("Existing environment placements cannot be retargeted or removed.");
            var scale = factory.ScaleSets.SingleOrDefault(scale => scale.Id == row.Selected!.ScaleSetId && scale.Environment == row.Environment)
                ?? throw new InvalidOperationException("Select an exact scale set in the intended project environment.");
            var occupants = factory.Projects.Where(candidate => candidate.Placements.Any(placement => placement.ScaleSetId == scale.Id)).ToArray();
            if (occupants.Any(candidate => candidate.Number == number && candidate.Id != project?.Id))
                throw new InvalidOperationException($"Project number {number} is already placed in {scale.Environment.ToUpperInvariant()}{scale.Suffix}.");
            if (scale.Network.MaxProjects is < 1 or > 8 || occupants.Length >= scale.Network.MaxProjects)
                throw new InvalidOperationException($"{scale.Environment.ToUpperInvariant()}{scale.Suffix} has no configured project capacity. The server also validates actual allocator capacity.");
            placements.Add(new() { Environment = row.Environment, ScaleSetId = scale.Id });
        }
        if (placements.Count == 0)
            throw new InvalidOperationException(append ? "Explicitly select at least one additional environment placement." :
                "Explicitly select at least one project environment and scale-set placement.");
        return placements;
    }
}

public sealed record CatalogPlacementChoice(string? ScaleSetId, string Display, string Details);

public sealed class CatalogPlacementEditor(string environment, string display) : ObservableObject
{
    private CatalogPlacementChoice? _selected;
    public event EventHandler? Edited;
    public string Environment { get; } = environment;
    public string Display { get; } = display;
    public ObservableCollection<CatalogPlacementChoice> Choices { get; } = [];
    public bool IsExisting { get; private set; }
    public bool CanAdd => !IsExisting;
    public string ExistingDescription { get; private set; } = string.Empty;
    public string ExistingDetails { get; private set; } = string.Empty;
    public CatalogPlacementChoice? Selected
    {
        get => _selected;
        set
        {
            if (value is null || !Choices.Contains(value) || IsExisting || !SetProperty(ref _selected, value)) return;
            Edited?.Invoke(this, EventArgs.Empty);
        }
    }

    public void Update(CatalogFactory? factory, CatalogProject? project, bool reset)
    {
        var previous = reset ? null : Selected?.ScaleSetId;
        var existing = project?.Placements.SingleOrDefault(placement => placement.Environment == Environment);
        IsExisting = existing is not null;
        var existingScale = factory?.ScaleSets.SingleOrDefault(scale => scale.Id == existing?.ScaleSetId);
        ExistingDescription = existing is null ? string.Empty : existingScale is null
            ? $"{Display}: existing unresolved placement is retained." : $"{Display}: {existingScale.Environment.ToUpperInvariant()}{existingScale.Suffix} is retained.";
        ExistingDetails = existing?.ScaleSetId ?? string.Empty;
        Choices.Clear();
        Choices.Add(new(null, "No additional placement", string.Empty));
        foreach (var scale in factory?.ScaleSets.Where(scale => scale.Environment == Environment) ?? [])
        {
            var used = factory!.Projects.Count(candidate => candidate.Placements.Any(placement => placement.ScaleSetId == scale.Id));
            Choices.Add(new(scale.Id, $"{scale.Environment.ToUpperInvariant()}{scale.Suffix} · {scale.Orchestrator} · {used}/{scale.Network.MaxProjects} projects",
                new CatalogScaleSetRow(scale).Details));
        }
        _selected = IsExisting ? Choices[0] : Choices.FirstOrDefault(choice => choice.ScaleSetId == previous) ?? Choices[0];
        foreach (var property in new[] { nameof(Selected), nameof(IsExisting), nameof(CanAdd), nameof(ExistingDescription), nameof(ExistingDetails) })
            OnPropertyChanged(property);
    }
}

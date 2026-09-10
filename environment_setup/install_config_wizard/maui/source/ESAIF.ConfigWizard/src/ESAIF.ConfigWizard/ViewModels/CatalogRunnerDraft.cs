using System.Text.RegularExpressions;
using ESAIF.BaseLayer.Application;
using ESAIF.ConfigWizard.Services;
using ESAIF.DomainLayer.Configuration;

namespace ESAIF.ConfigWizard.ViewModels;

public sealed class CatalogRunnerDraft : ObservableObject
{
    private bool _loading;
    private string _route = string.Empty;
    private CatalogChoice? _choice, _image;
    private string _labels = string.Empty, _pool = string.Empty, _agent = string.Empty;
    public event EventHandler? Edited;
    public IReadOnlyList<CatalogChoice> Choices { get; } =
        [new("none", "No runtime runner selected"), new("hosted", "Hosted Linux worker"), new("self-hosted", "Self-hosted Linux worker")];
    public IReadOnlyList<CatalogChoice> Images { get; } =
        [new("ubuntu-latest", "Ubuntu latest"), new("ubuntu-24.04", "Ubuntu 24.04"), new("ubuntu-22.04", "Ubuntu 22.04")];
    public CatalogChoice? Choice
    {
        get => _choice;
        set
        {
            if (value is null) return;
            Change(ref _choice, value);
            NotifyShape();
        }
    }
    public CatalogChoice? Image { get => _image; set => Change(ref _image, value); }
    public string Labels { get => _labels; set => Change(ref _labels, value); }
    public string Pool { get => _pool; set => Change(ref _pool, value); }
    public string AgentName { get => _agent; set => Change(ref _agent, value); }
    public bool ShowsHosted => Choice?.Value == "hosted";
    public bool ShowsGithub => Choice?.Value == "self-hosted" && _route == "gha";
    public bool ShowsAdo => Choice?.Value == "self-hosted" && _route == "ado";

    public void Load(CatalogRunnerSelection? runner, string route)
    {
        _loading = true;
        try
        {
            _route = route;
            Choice = Choices.FirstOrDefault(choice => choice.Value == (runner?.Kind ?? "none")) ??
                new(runner!.Kind, "Unsupported saved runner kind");
            Image = runner?.Image is { } image
                ? Images.FirstOrDefault(choice => choice.Value == image) ?? new(image, "Unsupported saved image") : null;
            Labels = string.Join(Environment.NewLine, runner?.Labels ?? []);
            Pool = runner?.Pool ?? string.Empty;
            AgentName = runner?.AgentName ?? string.Empty;
        }
        finally { _loading = false; }
        NotifyShape();
    }

    public CatalogRunnerSelection? Build(string route) => Create(Choice?.Value, Image?.Value, Labels, Pool, AgentName, route);

    internal static CatalogRunnerSelection? Create(string? kind, string? image, string labels, string pool, string agent, string route)
    {
        if (kind == "none") return null;
        if (kind is not ("hosted" or "self-hosted"))
            throw new InvalidOperationException("Select an explicitly supported Linux runner kind.");
        if (kind == "hosted")
        {
            if (image is not ("ubuntu-latest" or "ubuntu-24.04" or "ubuntu-22.04"))
                throw new InvalidOperationException("Explicitly choose an allowed Ubuntu hosted runner image.");
            return new() { Kind = kind, Os = "linux", Image = image };
        }
        if (route == "gha")
        {
            var values = labels.Split(["\r\n", "\n", "\r"], StringSplitOptions.RemoveEmptyEntries);
            if (values.Length is < 2 or > 16 || !values.Contains("self-hosted", StringComparer.OrdinalIgnoreCase) ||
                !values.Contains("linux", StringComparer.OrdinalIgnoreCase) || values.Any(value => !ValidName(value)))
                throw new InvalidOperationException("GitHub self-hosted selection requires 2–16 valid labels including self-hosted and linux.");
            return new() { Kind = kind, Os = "linux", Labels = values };
        }
        if (route != "ado" || !ValidName(pool) || agent.Length > 0 && !ValidName(agent))
            throw new InvalidOperationException("Enter an explicit Azure DevOps Linux pool and a valid optional agent name.");
        return new() { Kind = kind, Os = "linux", Pool = pool, AgentName = agent.Length == 0 ? null : agent };
    }

    private static bool ValidName(string value) => !string.IsNullOrWhiteSpace(value) &&
        Regex.IsMatch(value, @"^[A-Za-z0-9_. -]{1,128}$", RegexOptions.CultureInvariant);
    private void Change<T>(ref T field, T value, [System.Runtime.CompilerServices.CallerMemberName] string? property = null)
    {
        if (SetProperty(ref field, value, property) && !_loading) Edited?.Invoke(this, EventArgs.Empty);
    }
    private void NotifyShape()
    {
        foreach (var property in new[] { nameof(ShowsHosted), nameof(ShowsGithub), nameof(ShowsAdo) }) OnPropertyChanged(property);
    }
}

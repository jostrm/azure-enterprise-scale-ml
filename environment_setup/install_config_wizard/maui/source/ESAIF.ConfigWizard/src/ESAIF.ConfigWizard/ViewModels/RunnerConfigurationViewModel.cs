using System.Collections.ObjectModel;
using System.Text.Json.Nodes;
using ESAIF.BaseLayer.Application;

namespace ESAIF.ConfigWizard.ViewModels;

public sealed class RunnerConfigurationViewModel : ObservableObject
{
    public const string SelectionKey = "useSelfHostedBuildAgent";
    public static IReadOnlyList<string> DetailKeys { get; } = Array.AsReadOnly(new[]
    {
        "selfHostedRunnerLabel", "adminVMBuildAgentPool", "adminVMBuildAgentName",
        "disable_whitelisting_for_build_agents"
    });
    private readonly Action<bool> _select;
    private IReadOnlyDictionary<string, ConfigFieldViewModel> _fields = new Dictionary<string, ConfigFieldViewModel>();
    private bool? _selfHosted;
    private bool _selecting;
    private string _orchestrator = string.Empty;

    public RunnerConfigurationViewModel(JsonObject state, Action<bool> select)
    {
        _select = select;
        Synchronize(state);
    }

    public bool IsSelfHosted { get => _selfHosted == true; set { if (value) Select(true); } }
    public bool IsHosted { get => _selfHosted == false; set { if (value) Select(false); } }
    public bool IsGitHub => _orchestrator == "gha";
    public bool IsAzureDevOps => _orchestrator == "ado";
    public string SelfHostedLabel => IsGitHub ? "Self-hosted GitHub runner" : "Self-hosted build agent";
    public string HostedLabel => IsGitHub ? "GitHub-hosted runner" : "Microsoft-hosted build agent";
    public string FlagValue { get; private set; } = "(not set)";
    public string SavedAgentName { get; private set; } = string.Empty;
    public string VmNameReference => string.IsNullOrWhiteSpace(SavedAgentName)
        ? "VM name: not specified in this configuration."
        : $"Stored VM / ADO agent name: {SavedAgentName}";
    public bool ShowVmNameReference => IsSelfHosted && IsGitHub;
    public string Guidance => _selfHosted is null
        ? "The saved self-hosting value is missing or invalid. Choose a runner type; no setting has been inferred from the VM or pool name."
        : IsHosted
            ? "The CI provider supplies the build machine. Saved self-hosted settings are retained if you switch back."
            : IsGitHub
                ? "GitHub schedules by runner labels, not VM name. The matching Windows runner and its VM must be online. adminVMBuildAgentName is an ADO field, not a GitHub runner selector."
                : "Azure DevOps schedules in the configured agent pool, optionally demanding the exact agent name. The agent service and its VM must be online.";
    public ObservableCollection<ConfigFieldViewModel> Details { get; } = [];

    public void AttachFields(IReadOnlyDictionary<string, ConfigFieldViewModel> fields)
    {
        _fields = fields;
        RefreshDetails();
    }

    public void Synchronize(JsonObject state)
    {
        _orchestrator = state["orchestrator"]?.ToString().ToLowerInvariant() ?? string.Empty;
        var text = state[SelectionKey]?.ToString();
        _selfHosted = bool.TryParse(text, out var enabled) ? enabled : null;
        FlagValue = _selfHosted?.ToString().ToLowerInvariant() ?? text ?? "(not set)";
        SavedAgentName = state["adminVMBuildAgentName"]?.ToString() ?? string.Empty;
        RefreshDetails();
        Notify();
    }

    private void Select(bool selfHosted)
    {
        if (_selecting || _selfHosted == selfHosted)
        {
            return;
        }
        _selecting = true;
        try
        {
            _select(selfHosted);
            _selfHosted = selfHosted;
            FlagValue = selfHosted.ToString().ToLowerInvariant();
            RefreshDetails();
            Notify();
        }
        finally
        {
            _selecting = false;
        }
    }

    private void RefreshDetails()
    {
        var keys = IsGitHub
            ? new[] { "selfHostedRunnerLabel", "disable_whitelisting_for_build_agents" }
            : new[] { "adminVMBuildAgentName", "adminVMBuildAgentPool", "disable_whitelisting_for_build_agents" };
        var desired = IsSelfHosted
            ? keys.Where(_fields.ContainsKey).Select(key => _fields[key]).ToArray()
            : [];
        if (Details.SequenceEqual(desired))
        {
            return;
        }
        Details.Clear();
        foreach (var field in desired)
        {
            Details.Add(field);
        }
    }

    private void Notify()
    {
        foreach (var property in new[] { nameof(IsSelfHosted), nameof(IsHosted), nameof(IsGitHub), nameof(IsAzureDevOps),
            nameof(SelfHostedLabel), nameof(HostedLabel), nameof(FlagValue), nameof(SavedAgentName), nameof(VmNameReference),
            nameof(ShowVmNameReference), nameof(Guidance) })
        {
            OnPropertyChanged(property);
        }
    }
}

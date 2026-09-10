using System.Globalization;
using System.Text.RegularExpressions;
using ESAIF.BaseLayer.Application;
using ESAIF.ConfigWizard.Services;
using ESAIF.DomainLayer.Configuration;

namespace ESAIF.ConfigWizard.ViewModels;

public sealed class CatalogBindingEditor : ObservableObject
{
    private string _scope = string.Empty;
    private CatalogRuntimeBinding? _baseline;
    private string? _baselineError;
    private CatalogFactory? _factory;
    private CatalogScaleSet? _scale;
    private bool _loading;
    private string _writerId = string.Empty, _repository = string.Empty, _ref = "refs/heads/main";
    private string _authNamespace = string.Empty, _deploymentObjectId = string.Empty;
    private string _accountUrl = string.Empty, _container = string.Empty, _blob = string.Empty, _hash = string.Empty;
    private string _revision = "1", _resourceGroupIds = string.Empty, _dependencyIds = string.Empty;
    private bool _sharedRemote;
    private bool _allowUnreadableReplacement;
    private CatalogChoice _runnerChoice = RunnerKinds[0];
    private CatalogChoice? _runnerImage;
    private string _runnerLabels = string.Empty, _runnerPool = string.Empty, _runnerAgent = string.Empty;
    private bool _useTargetExecution;
    private string _targetWriterId = string.Empty, _targetAuthNamespace = string.Empty, _targetObjectId = string.Empty;

    public CatalogBindingEditor() => TargetRunner.Edited += (_, _) => MarkEdited();
    public CatalogRunnerDraft TargetRunner { get; } = new();
    public bool UseTargetExecution { get => _useTargetExecution; set => Change(ref _useTargetExecution, value); }
    public string TargetWriterId { get => _targetWriterId; set => Change(ref _targetWriterId, value); }
    public string TargetAuthNamespace { get => _targetAuthNamespace; set => Change(ref _targetAuthNamespace, value); }
    public string TargetDeploymentObjectId { get => _targetObjectId; set => Change(ref _targetObjectId, value); }

    private static IReadOnlyList<CatalogChoice> RunnerKinds { get; } =
        [new("none", "No runtime runner selected"), new("hosted", "Hosted Linux worker"), new("self-hosted", "Self-hosted Linux worker")];
    public IReadOnlyList<CatalogChoice> RunnerChoices => RunnerKinds;
    public IReadOnlyList<CatalogChoice> HostedImages { get; } =
        [new("ubuntu-latest", "Ubuntu latest"), new("ubuntu-24.04", "Ubuntu 24.04"), new("ubuntu-22.04", "Ubuntu 22.04")];

    public event EventHandler? Edited;
    public bool IsDirty { get; private set; }
    public bool HasConflict { get; private set; }
    public bool IsUnreadable => !string.IsNullOrWhiteSpace(_baselineError) && _baseline is null;
    public bool AllowUnreadableReplacement { get => _allowUnreadableReplacement; set => Change(ref _allowUnreadableReplacement, value); }
    public string Status { get; private set; } = "Select an exact scale set to configure its pipeline binding.";
    public string Route => _scale?.Orchestrator ?? string.Empty;
    public string SelectedTarget => _scale is null ? "No scale set selected" :
        $"{_factory?.Key} · {_scale.Environment.ToUpperInvariant()}{_scale.Suffix} · {_scale.Orchestrator}";
    public string ScopeDetails => _scale is null ? string.Empty :
        $"Factory: {_factory?.Id}\nScale set: {_scale.Id}\nSubscription: {_scale.SubscriptionId}\nTenant: {_scale.TenantId}";
    public string WriterId { get => _writerId; set => Change(ref _writerId, value); }
    public string Repository { get => _repository; set => Change(ref _repository, value); }
    public string ConsumerRef { get => _ref; set => Change(ref _ref, value); }
    public bool SharedRemote { get => _sharedRemote; set => Change(ref _sharedRemote, value); }
    public string AuthNamespace { get => _authNamespace; set => Change(ref _authNamespace, value); }
    public string DeploymentObjectId { get => _deploymentObjectId; set => Change(ref _deploymentObjectId, value); }
    public string LockAccountUrl { get => _accountUrl; set => Change(ref _accountUrl, value); }
    public string LockContainer { get => _container; set => Change(ref _container, value); }
    public string CoordinationBlob { get => _blob; set => Change(ref _blob, value); }
    public string CoordinationHash { get => _hash; set => Change(ref _hash, value); }
    public string CoordinationRevision { get => _revision; set => Change(ref _revision, value); }
    public string ResourceGroupIds { get => _resourceGroupIds; set => Change(ref _resourceGroupIds, value); }
    public string CommonDependencyIds { get => _dependencyIds; set => Change(ref _dependencyIds, value); }
    public CatalogChoice RunnerChoice
    {
        get => _runnerChoice;
        set
        {
            if (value is null) return;
            Change(ref _runnerChoice, value);
            NotifyRunner();
        }
    }
    public CatalogChoice? RunnerImage { get => _runnerImage; set => Change(ref _runnerImage, value); }
    public string RunnerLabels { get => _runnerLabels; set => Change(ref _runnerLabels, value); }
    public string RunnerPool { get => _runnerPool; set => Change(ref _runnerPool, value); }
    public string RunnerAgentName { get => _runnerAgent; set => Change(ref _runnerAgent, value); }
    public bool ShowsHostedRunner => RunnerChoice.Value == "hosted";
    public bool ShowsGithubRunner => RunnerChoice.Value == "self-hosted" && Route == "gha";
    public bool ShowsAdoRunner => RunnerChoice.Value == "self-hosted" && Route == "ado";

    public void LoadScope(string folder, CatalogFactory? factory, CatalogScaleSet? scale, bool discardEdits = false)
    {
        _factory = factory;
        _scale = scale;
        var scope = $"{folder}\0{factory?.Id}\0{scale?.Id}";
        var state = factory?.Bindings.SingleOrDefault(x => x.Orchestrator == scale?.Orchestrator);
        if (!discardEdits && scope == _scope && IsDirty)
        {
            HasConflict = !Equivalent(_baseline, state?.Configuration) || _baselineError != state?.Error;
            Status = HasConflict
                ? "The saved binding changed while this draft was edited. Edits are preserved; explicitly reload the binding before preparing."
                : "Unsaved binding edits preserved. Other scale-set targets will remain unchanged.";
            NotifyState();
            return;
        }
        _scope = scope;
        _baseline = state?.Configuration;
        _baselineError = state?.Error;
        _loading = true;
        try
        {
            WriterId = _baseline?.WriterId ?? string.Empty;
            Repository = _baseline?.Repository ?? string.Empty;
            ConsumerRef = _baseline?.Ref ?? "refs/heads/main";
            SharedRemote = _baseline?.SharedRemote ?? false;
            AuthNamespace = _baseline?.AuthNamespace ?? string.Empty;
            DeploymentObjectId = _baseline?.DeploymentObjectId ?? string.Empty;
            LockAccountUrl = _baseline?.Locks.AccountUrl ?? string.Empty;
            LockContainer = _baseline?.Locks.Container ?? string.Empty;
            CoordinationBlob = _baseline?.Locks.CoordinationBlob ?? string.Empty;
            CoordinationHash = _baseline?.Locks.CoordinationHash ?? string.Empty;
            CoordinationRevision = (_baseline?.Locks.Revision ?? 1).ToString(CultureInfo.InvariantCulture);
            var target = _baseline?.Targets.SingleOrDefault(x => x.ScaleSetId == scale?.Id);
            ResourceGroupIds = string.Join(Environment.NewLine, target?.ResourceGroupIds ?? []);
            CommonDependencyIds = string.Join(Environment.NewLine, target?.CommonDependencyIds ?? []);
            UseTargetExecution = target?.Execution is not null;
            TargetWriterId = target?.Execution?.WriterId ?? string.Empty;
            TargetAuthNamespace = target?.Execution?.AuthNamespace ?? string.Empty;
            TargetDeploymentObjectId = target?.Execution?.DeploymentObjectId ?? string.Empty;
            TargetRunner.Load(target?.Execution?.Runner, Route);
            AllowUnreadableReplacement = false;
            var runner = _baseline?.Runner;
            RunnerChoice = RunnerChoices.FirstOrDefault(x => x.Value == (runner?.Kind ?? "none")) ??
                new(runner!.Kind, "Unsupported saved runner kind");
            RunnerImage = HostedImages.FirstOrDefault(x => x.Value == runner?.Image);
            RunnerLabels = string.Join(Environment.NewLine, runner?.Labels ?? []);
            RunnerPool = runner?.Pool ?? string.Empty;
            RunnerAgentName = runner?.AgentName ?? string.Empty;
        }
        finally { _loading = false; }
        IsDirty = HasConflict = false;
        Status = scale is null ? "Select an exact scale set to configure its pipeline binding." :
            !string.IsNullOrWhiteSpace(_baselineError) ? _baselineError :
            _baseline is null ? "No saved binding for this route. Complete the typed setup fields; saving does not provision or verify infrastructure." :
                $"Loaded saved {_baseline.Orchestrator} binding. {_baseline.Targets.Count} target(s); only the selected target's scopes can be edited here.";
        NotifyState();
    }

    public CatalogRuntimeBinding Build(string folder, CatalogFactory factory, CatalogScaleSet scale)
    {
        if (_scope != $"{folder}\0{factory.Id}\0{scale.Id}" || HasConflict)
            throw new InvalidOperationException("The binding scope changed or conflicts with saved edits. Reload its exact scope before preparing.");
        if (IsUnreadable && !AllowUnreadableReplacement)
            throw new InvalidOperationException("The stored binding is unreadable. Explicitly acknowledge full replacement before preparing its new typed configuration.");
        var repositoryPattern = scale.Orchestrator == "gha"
            ? @"^https://github\.com/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$"
            : @"^https://dev\.azure\.com/[A-Za-z0-9_.%-]+/[A-Za-z0-9_.%-]+/_git/[A-Za-z0-9_.%-]+$";
        RequireMatch(WriterId, @"^[A-Za-z0-9_.-]{1,128}$", "Enter a valid physical writer ID.");
        RequireMatch(Repository, repositoryPattern, "Enter a supported credential-free repository URL for the selected route.");
        RequireMatch(ConsumerRef, @"^refs/(heads|tags)/[A-Za-z0-9_./-]+$", "Enter an explicit consumer repository branch or tag ref.");
        if (ConsumerRef.Contains("..", StringComparison.Ordinal) || CoordinationBlob.Contains("..", StringComparison.Ordinal) ||
            Repository.Split('/').Any(part => part is "." or ".."))
            throw new InvalidOperationException("Ref and coordination blob cannot contain parent traversal.");
        if (string.IsNullOrWhiteSpace(AuthNamespace) != string.IsNullOrWhiteSpace(DeploymentObjectId))
            throw new InvalidOperationException("Namespaced runtime setup requires both authentication namespace and deployment object ID.");
        if (AuthNamespace.Length > 0)
        {
            RequireMatch(AuthNamespace, @"^[A-Za-z0-9_.-]{1,128}$", "Enter a valid authentication namespace.");
            if (!Guid.TryParse(DeploymentObjectId, out var id) || id == Guid.Empty)
                throw new InvalidOperationException("Deployment object ID must be a concrete GUID.");
        }
        RequireMatch(LockAccountUrl, @"^https://[a-z0-9]{3,24}\.blob\.core\.windows\.net$", "Enter the enrolled lock storage account HTTPS URL without credentials.");
        RequireMatch(LockContainer, @"^[a-z0-9][a-z0-9-]{1,61}[a-z0-9]$", "Enter the enrolled lock container name.");
        RequireMatch(CoordinationBlob, @"^[A-Za-z0-9_-][A-Za-z0-9_./-]{0,255}$", "Enter the coordination document blob name.");
        RequireMatch(CoordinationHash, @"^[a-f0-9]{64}$", "Enter the exact lowercase SHA-256 coordination document hash.");
        if (!int.TryParse(CoordinationRevision, NumberStyles.None, CultureInfo.InvariantCulture, out var revision) || revision < 1)
            throw new InvalidOperationException("Coordination revision must be a positive whole number.");
        var groups = ParseScopes(ResourceGroupIds);
        var dependencies = ParseScopes(CommonDependencyIds);
        if (groups.Length == 0 || groups.Length > 24 || dependencies.Length > 24)
            throw new InvalidOperationException("Provide 1–24 writable resource groups and at most 24 shared dependency groups.");
        if (groups.Concat(dependencies).Distinct(StringComparer.OrdinalIgnoreCase).Count() != groups.Length + dependencies.Length)
            throw new InvalidOperationException("Writable and dependency resource groups must be unique and disjoint.");
        foreach (var group in groups)
            if (!group.Split('/')[2].Equals(scale.SubscriptionId, StringComparison.OrdinalIgnoreCase))
                throw new InvalidOperationException("Writable resource groups must use the selected scale set's exact subscription.");
        var edited = new CatalogBindingTarget { ScaleSetId = scale.Id, ResourceGroupIds = groups,
            CommonDependencyIds = dependencies, Execution = BuildTargetExecution(scale.Orchestrator) };
        var targets = (_baseline?.Targets ?? []).Select(target => target.ScaleSetId == scale.Id ? edited : target).ToList();
        if (targets.All(target => target.ScaleSetId != scale.Id)) targets.Add(edited);
        return new()
        {
            ContractVersion = 1, Orchestrator = scale.Orchestrator, WriterId = WriterId, Repository = Repository,
            Ref = ConsumerRef, SharedRemote = SharedRemote, AuthNamespace = AuthNamespace.Length == 0 ? null : AuthNamespace,
            DeploymentObjectId = DeploymentObjectId.Length == 0 ? null : DeploymentObjectId,
            Runner = BuildRunner(scale.Orchestrator),
            Locks = new() { AccountUrl = LockAccountUrl, Container = LockContainer, CoordinationBlob = CoordinationBlob,
                CoordinationHash = CoordinationHash, Revision = revision }, Targets = targets
        };
    }

    public static bool Equivalent(CatalogRuntimeBinding? left, CatalogRuntimeBinding? right)
    {
        if (left is null || right is null) return left is null && right is null;
        return left.ContractVersion == right.ContractVersion && left.Orchestrator == right.Orchestrator &&
            left.WriterId == right.WriterId && left.Repository == right.Repository && left.Ref == right.Ref &&
            left.SharedRemote == right.SharedRemote && left.AuthNamespace == right.AuthNamespace &&
            SameObjectId(left.DeploymentObjectId, right.DeploymentObjectId) && EquivalentRunner(left.Runner, right.Runner) && left.Locks == right.Locks &&
            left.Targets.Count == right.Targets.Count && left.Targets.Zip(right.Targets).All(pair =>
                pair.First.ScaleSetId == pair.Second.ScaleSetId &&
                pair.First.ResourceGroupIds.SequenceEqual(pair.Second.ResourceGroupIds) &&
                pair.First.CommonDependencyIds.SequenceEqual(pair.Second.CommonDependencyIds) &&
                EquivalentExecution(pair.First.Execution, pair.Second.Execution));
    }

    private static bool SameObjectId(string? left, string? right) => left == right ||
        Guid.TryParse(left, out var a) && Guid.TryParse(right, out var b) && a == b;

    private CatalogRunnerSelection? BuildRunner(string route)
    {
        if (!RunnerChoices.Contains(RunnerChoice))
            throw new InvalidOperationException("Select an explicitly supported Linux runner kind.");
        if (RunnerChoice.Value == "none") return null;
        if (string.IsNullOrWhiteSpace(AuthNamespace) || string.IsNullOrWhiteSpace(DeploymentObjectId))
            throw new InvalidOperationException("An explicit runner requires the authentication namespace and deployment object ID.");
        return CatalogRunnerDraft.Create(RunnerChoice.Value, RunnerImage?.Value, RunnerLabels, RunnerPool, RunnerAgentName, route);
    }

    private CatalogTargetExecution? BuildTargetExecution(string route)
    {
        if (!UseTargetExecution) return null;
        if (!SharedRemote) throw new InvalidOperationException("Per-scale-set execution overrides require the enrolled shared remote contract.");
        RequireMatch(TargetWriterId, @"^[A-Za-z0-9_.-]{1,128}$", "Enter the exact scale-set execution writer ID.");
        RequireMatch(TargetAuthNamespace, @"^[A-Za-z0-9_.-]{1,128}$", "Enter the exact scale-set authentication namespace.");
        if (!Guid.TryParse(TargetDeploymentObjectId, out var id) || id == Guid.Empty)
            throw new InvalidOperationException("The scale-set deployment object ID must be a concrete GUID.");
        return new() { WriterId = TargetWriterId, AuthNamespace = TargetAuthNamespace, DeploymentObjectId = TargetDeploymentObjectId,
            Runner = TargetRunner.Build(route) ?? throw new InvalidOperationException("Explicitly select this scale set's Linux runner; it cannot be inferred.") };
    }

    private static bool EquivalentExecution(CatalogTargetExecution? left, CatalogTargetExecution? right) =>
        left is null || right is null ? left is null && right is null :
            left.WriterId == right.WriterId && left.AuthNamespace == right.AuthNamespace &&
            SameObjectId(left.DeploymentObjectId, right.DeploymentObjectId) && EquivalentRunner(left.Runner, right.Runner);

    private static bool EquivalentRunner(CatalogRunnerSelection? left, CatalogRunnerSelection? right)
    {
        if (left is null || right is null) return left is null && right is null;
        return left.Kind == right.Kind && left.Os == right.Os && left.Image == right.Image &&
            left.Pool == right.Pool && left.AgentName == right.AgentName &&
            (left.Labels is null || right.Labels is null
                ? left.Labels is null && right.Labels is null : left.Labels.SequenceEqual(right.Labels));
    }

    private static string[] ParseScopes(string text)
    {
        var scopes = text.Split(["\r\n", "\n", "\r"], StringSplitOptions.RemoveEmptyEntries);
        foreach (var scope in scopes)
        {
            RequireMatch(scope, @"^/subscriptions/[a-fA-F0-9-]{36}/resourceGroups/[A-Za-z0-9_.()-]{1,90}$",
                "Use one exact resource-group ARM ID per line, without wildcards or filters.");
            if (!Guid.TryParse(scope.Split('/')[2], out var subscription) || subscription == Guid.Empty)
                throw new InvalidOperationException("Resource-group scopes need concrete subscription GUIDs.");
        }
        return scopes;
    }

    private static void RequireMatch(string value, string pattern, string error)
    {
        if (!Regex.IsMatch(value, pattern, RegexOptions.CultureInvariant)) throw new InvalidOperationException(error);
    }

    private void Change<T>(ref T field, T value, [System.Runtime.CompilerServices.CallerMemberName] string? property = null)
    {
        if (!SetProperty(ref field, value, property) || _loading) return;
        MarkEdited();
    }

    private void MarkEdited()
    {
        if (_loading) return;
        IsDirty = true;
        OnPropertyChanged(nameof(IsDirty));
        Edited?.Invoke(this, EventArgs.Empty);
    }

    private void NotifyState()
    {
        foreach (var property in new[] { nameof(IsDirty), nameof(HasConflict), nameof(IsUnreadable), nameof(Status), nameof(Route), nameof(SelectedTarget), nameof(ScopeDetails) })
            OnPropertyChanged(property);
        NotifyRunner();
    }

    private void NotifyRunner()
    {
        OnPropertyChanged(nameof(ShowsHostedRunner));
        OnPropertyChanged(nameof(ShowsGithubRunner));
        OnPropertyChanged(nameof(ShowsAdoRunner));
    }
}

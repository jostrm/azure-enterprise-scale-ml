using System.Collections.ObjectModel;
using ESAIF.BaseLayer.Application;
using ESAIF.ConfigWizard.Services;
using ESAIF.DomainLayer.Configuration;

namespace ESAIF.ConfigWizard.ViewModels;

public sealed class FactoryCatalogViewModel : OperationViewModel
{
    private readonly IFactoryCatalogClient _client;
    private readonly FactoryCatalogSession _session;
    private readonly IAiFactoryApiClient? _regionOptions;
    private readonly IFactoryCatalogTerminalSession? _terminal;
    private readonly IFactoryCatalogSettingsClient? _settingsClient;
    private static IReadOnlyList<CatalogChoice> SettingsScopeModes { get; } =
        [new("factory", "Selected factory"), new("scale-set", "Selected scale set"), new("project", "Selected project · all placements")];
    private CatalogChoice _settingsScope = SettingsScopeModes[0];
    private readonly Func<DateTimeOffset> _now;
    private FactoryCatalogPreview? _preview;
    private long _inputVersion;
    private long _preparedInput;
    private long _preparedContext;
    private string _preparedFolder = string.Empty;
    private string _reviewDetails = string.Empty;
    private bool _reviewed;
    private bool _accepted;
    private bool _visible;
    private string _typedPhrase = string.Empty;
    private CatalogChoice _action = FactoryCatalogPresentation.Actions[0];
    private CatalogChoice? _environment;
    private CatalogChoice? _orchestrator;
    private CatalogChoice _includeProjects = FactoryCatalogPresentation.ProjectInclusion[0];
    private string _targetPrefix = string.Empty;
    private string _targetRegion = string.Empty;
    private string _suffix = string.Empty;
    private string _subscriptionId = string.Empty;
    private string _tenantId = string.Empty;
    private string _vnetCidr = string.Empty;
    private string _maxProjects = "1";
    private string _versionRef = string.Empty;
    private string _newFactoryVersion = "124", _cloneFactoryVersion = string.Empty;
    private bool _useCustomCommonSubnets;
    private string _commonSubnet = string.Empty, _scoringSubnet = string.Empty, _powerbiSubnet = string.Empty, _bastionSubnet = string.Empty;
    private static IReadOnlyList<CatalogChoice> RuntimeVersionModes { get; } =
        [new("inherit", "Inherit selected factory release"), new("override", "Choose an explicit release override")];
    private CatalogChoice _versionMode = RuntimeVersionModes[0];
    private bool _versionEdited;
    private bool _deploySelectedProject;
    private string? _versionFactory;
    private string? _inputRoot;
    private CancellationTokenSource _disclosure = new();

    public FactoryCatalogViewModel(IFactoryCatalogClient client, FactoryCatalogSession session,
        Func<DateTimeOffset>? now = null, IAiFactoryApiClient? regionOptions = null,
        IFactoryCatalogTerminalSession? terminal = null, IFactoryCatalogSettingsClient? settingsClient = null)
    {
        _client = client;
        _session = session;
        _regionOptions = regionOptions;
        _terminal = terminal;
        _settingsClient = settingsClient ?? client as IFactoryCatalogSettingsClient;
        _now = now ?? (() => DateTimeOffset.UtcNow);
        _session.Changed += (_, _) => Rebuild();
        _session.ConsentInvalidated += (_, _) => InvalidatePreview();
        BindingEditor.Edited += (_, _) => InputChanged();
        ProjectEditor.Edited += (_, _) => InputChanged();
        SettingsEditor.Edited += (_, _) => InputChanged();
        SettingsEditor.PropertyChanged += (_, _) => NotifyConsent();
        RefreshCommand = new AsyncCommand(RefreshAsync);
        PrepareCommand = new AsyncCommand(PrepareAsync);
        ConfirmCommand = new AsyncCommand(ConfirmAsync);
        ReloadJobsCommand = new AsyncCommand(ReloadJobsAsync);
        OpenTerminalCommand = new Command<FactoryCatalogJob>(async job => await OpenTerminalAsync(job));
        SelectFactoryCommand = new Command<CatalogFactoryRow>(row =>
        {
            if (row is not null && Factories.Contains(row)) _session.SelectFactory(row.Id);
        });
        SelectProjectCommand = new Command<CatalogProjectRow>(row =>
        {
            if (row is not null && Projects.Contains(row)) _session.SelectProject(row.Id);
        });
        SelectScaleSetCommand = new Command<CatalogScaleSetRow>(row =>
        {
            if (row is not null && ScaleSets.Contains(row)) _session.SelectScaleSet(row.Id);
        });
        PropertyChanged += (_, e) =>
        {
            if (e.PropertyName == nameof(IsNotBusy)) NotifyConsent();
        };
        Rebuild();
    }

    private static void ValidateProjectPreview(FactoryCatalogRequest request, CatalogFactory source, CatalogFactory? target)
    {
        if (target?.Id != source.Id)
            throw new InvalidDataException("The project preview returned a different factory scope.");
        foreach (var previous in source.Projects)
        {
            var current = target.Projects.SingleOrDefault(project => project.Id == previous.Id);
            var expected = previous.Id == request.ProjectId && request.Placements is not null
                ? previous.Placements.Concat(request.Placements).ToArray() : previous.Placements;
            if (current is null || current.Key != previous.Key || current.Number != previous.Number || current.DisplayName != previous.DisplayName ||
                !SamePlacements(current.Placements, expected))
                throw new InvalidDataException("The project preview changed an existing project identity or placement.");
        }
        var added = target.Projects.Where(project => source.Projects.All(previous => previous.Id != project.Id)).ToArray();
        if (request.Project is { } input)
        {
            if (added.Length != 1 || added[0].Number != input.Number || added[0].DisplayName != input.DisplayName ||
                !SamePlacements(added[0].Placements, input.Placements))
                throw new InvalidDataException("The project preview did not echo the exact new project and requested placements.");
        }
        else if (added.Length != 0)
            throw new InvalidDataException("The placement preview unexpectedly introduced another project.");
    }

    private static bool SamePlacements(IEnumerable<CatalogPlacement> left, IEnumerable<CatalogPlacement> right) =>
        left.OrderBy(placement => placement.Environment, StringComparer.Ordinal).SequenceEqual(
            right.OrderBy(placement => placement.Environment, StringComparer.Ordinal));

    public ObservableCollection<CatalogFactoryRow> Factories { get; } = [];
    public ObservableCollection<CatalogScaleSetRow> ScaleSets { get; } = [];
    public ObservableCollection<CatalogProjectRow> Projects { get; } = [];
    public ObservableCollection<FactoryCatalogJob> Jobs { get; } = [];
    public ObservableCollection<CatalogChoice> RegionChoices { get; } = [];
    public ObservableCollection<CatalogBindingRow> Bindings { get; } = [];
    public CatalogBindingEditor BindingEditor { get; } = new();
    public CatalogProjectEditor ProjectEditor { get; } = new();
    public CatalogSettingsEditor SettingsEditor { get; } = new();
    public IReadOnlyList<CatalogChoice> SettingsScopes => SettingsScopeModes;
    public CatalogChoice SettingsScope
    {
        get => _settingsScope;
        set
        {
            if (value is null || !SettingsScopes.Contains(value) || !SetProperty(ref _settingsScope, value)) return;
            SettingsEditor.UpdateContext(CurrentSettingsScope, _session.Catalog?.Revision);
            InputChanged();
            NotifySettingsScope();
        }
    }
    private CatalogSettingsScope? CurrentSettingsScope => _session.SelectedFactory is not { } factory ? null :
        SettingsScope.Value == "scale-set" ? _session.SelectedScaleSet is { } scale ? new(Folder, factory.Id, scale.Id, null) : null :
        SettingsScope.Value == "project" ? _session.SelectedProject is { } project ? new(Folder, factory.Id, null, project.Id) : null :
        new(Folder, factory.Id, null, null);
    public string SettingsScopeLabel => SettingsScope.Value switch
    {
        "scale-set" => _session.SelectedScaleSet is { } scale ? $"Scale set {scale.Environment.ToUpperInvariant()}{scale.Suffix} in {_session.SelectedFactory?.Key}" : "Select an exact scale set above.",
        "project" => _session.SelectedProject is { } project ? $"Project {project.Number} · {project.DisplayName}, across all existing placements" : "Select an exact existing project above.",
        _ => _session.SelectedFactory is { } factory ? $"Factory {factory.Key}; unset child values continue to inherit" : "Select an exact factory above."
    };
    public string SettingsScopeDetails => CurrentSettingsScope is { } scope
        ? $"Folder: {scope.Folder}\nFactory: {scope.FactoryId}\nScale set: {scope.ScaleSetId ?? "(not targeted)"}\nProject: {scope.ProjectId ?? "(not targeted)"}"
        : "No complete settings scope selected.";
    public IReadOnlyList<CatalogChoice> VersionModes => RuntimeVersionModes;
    public IReadOnlyList<CatalogChoice> Actions => FactoryCatalogPresentation.Actions;
    public IReadOnlyList<CatalogChoice> Environments => FactoryCatalogPresentation.Environments;
    public IReadOnlyList<CatalogChoice> Orchestrators => FactoryCatalogPresentation.Orchestrators;
    public IReadOnlyList<CatalogChoice> ProjectInclusions => FactoryCatalogPresentation.ProjectInclusion;
    public AsyncCommand RefreshCommand { get; }
    public AsyncCommand PrepareCommand { get; }
    public AsyncCommand ConfirmCommand { get; }
    public AsyncCommand ReloadJobsCommand { get; }
    public Command<CatalogFactoryRow> SelectFactoryCommand { get; }
    public Command<CatalogScaleSetRow> SelectScaleSetCommand { get; }
    public Command<FactoryCatalogJob> OpenTerminalCommand { get; }
    public Command<CatalogProjectRow> SelectProjectCommand { get; }
    public string TerminalCapabilityMessage => _terminal is null
        ? "Interactive terminal attachment is unavailable in this client."
        : "Open an available job terminal explicitly in the shared footer. Input is sent only to that owned job; uncertain input is never retried.";
    public string Folder => _session.Folder;
    public string Revision => _session.Catalog?.Revision ?? "Not loaded";
    public bool IsLegacy => _session.IsLegacy;
    public bool IsCatalog => _session.IsCatalog;
    public bool HasSelection => _session.SelectedFactory is not null;
    public string SelectionLabel => _session.SelectedFactory is { } factory
        ? $"{factory.Prefix} · {factory.Region}" + (_session.SelectedScaleSet is { } scale
            ? $" / {scale.Environment.ToUpperInvariant()}{scale.Suffix}" : " / select a scale set for runtime actions")
        : "No factory selected — choose an exact factory below";
    public string SelectionDetails => _session.SelectedFactory is { } factory
        ? new CatalogFactoryRow(factory).Details + (_session.SelectedScaleSet is { } scale
            ? "\n" + new CatalogScaleSetRow(scale).Details : string.Empty) : string.Empty;
    public string SelectedProjectLabel => _session.SelectedProject is { } project
        ? $"{project.Number} · {project.DisplayName}" : "No existing project selected";
    public string SelectedProjectDetails => _session.SelectedProject is { } project
        ? new CatalogProjectRow(project, _session.SelectedFactory!).Details : string.Empty;
    public string ScopeMessage => IsLegacy
        ? "No catalog manifest: existing legacy setup remains available and requires explicit migration. A genuinely empty root can create a new factory; the server checks which case applies."
        : IsCatalog
            ? "Catalog configuration inventory, not observed Azure resources. Legacy maps and editors are not scoped to this catalog; runtime actions stay here."
            : "Reload this root to identify its catalog mode. No action is permitted until the server verifies it.";
    public string NavigationNotice { get; set; } = string.Empty;
    public string CapabilityMessage => IsLegacy && Action.Value is not ("migrate" or "create-factory")
            ? "This is a legacy root. Review migration explicitly, or continue in the existing legacy setup."
            : IsCatalog && Action.Value == "migrate"
                ? "This root already has a catalog. Migration is not needed."
                : "The server validates capability, pipeline bindings, version locks, placement capacity and setup blockers during preview.";
    public bool HasPreview => _preview is not null;
    public string PreviewSummary => _preview?.Summary ?? string.Empty;
    public string PreviewWarnings => _preview is null ? string.Empty : string.Join("\n", _preview.Warnings);
    public string PreviewBlockers => _preview is null ? string.Empty : string.Join("\n", _preview.Blockers);
    public string ConsentStatus => _preview is null ? string.Empty :
        !_preview.CanExecute || _preview.Blockers.Count > 0 ? "Blocked by the server; no confirmation is permitted." :
        !DateTimeOffset.TryParse(_preview.ExpiresAt, out var expires) ? "Invalid expiry; request a fresh server preview." :
        expires <= _now() ? "This review expired. Prepare and review again; nothing will retry automatically." :
        !_reviewed ? "Open the exact server review before accepting." :
        !Accepted ? "Explicitly accept the reviewed plan to continue." :
        IsDelete && TypedPhrase != RequiredPhrase ? "Type the exact deletion phrase to continue." :
        "Ready to submit this receipt once.";
    public string ReviewDetails => _reviewDetails;
    public CancellationToken DisclosureValidity => _disclosure.Token;
    public bool IsDelete => Action.Value is "delete-factory" or "delete-scale-set";
    public bool IsClone => Action.Value == "clone";
    public bool ShowsTarget => Action.Value is "create-factory" or "clone";
    public bool ShowsScaleSetDraft => Action.Value is "create-factory" or "create-scale-set";
    public bool ShowsBindingDraft => Action.Value == "configure-binding";
    public bool ShowsSettingsDraft => Action.Value == "configure-settings";
    public bool ShowsProjectDraft => Action.Value is "add-project" or "add-project-placements";
    public bool IsNewProject => Action.Value == "add-project";
    public bool IsDeploy => Action.Value == "deploy";
    public bool UsesRuntimeVersion => Action.Value is "deploy" or "delete-factory" or "delete-scale-set";
    public bool ShowsRuntimeVersionOverride => UsesRuntimeVersion && VersionMode.Value == "override";
    public string ConfigurationVersionNotice => "Creating or cloning a factory can save its release version. Other configuration changes do not override it. " +
        "Runtime inheritance is resolved for the selected factory. An unresolved legacy version requires an explicit runtime override; review the exact server resolution before confirmation.";
    public string SavedFactoryVersion => _session.SelectedFactory?.FactoryVersion is { Length: > 0 } version ? version :
        "Not reported; the server resolves inheritance during preview.";
    public string LocalVersionGuidance => IsClone
        ? "Leave the clone version blank to inherit the source factory's saved release, or enter an explicit saved override."
        : "The new factory defaults to release 124. This field is saved with the new factory, not submitted as a runtime override.";
    public string RequiredPhrase => Action.Value switch
    {
        "delete-factory" => $"DELETE FACTORY {_session.SelectedFactory?.Key} ALL SCALE SETS",
        "delete-scale-set" => $"DELETE SCALE SET {_session.SelectedFactory?.Key} {_session.SelectedScaleSet?.Environment.ToUpperInvariant()}{_session.SelectedScaleSet?.Suffix}",
        _ => string.Empty
    };
    public string OperationScope => Action.Value == "delete-factory"
        ? "Entire factory deletion: every scale set and owned resource in the server manifest, not just the highlighted scale set."
        : ShowsSettingsDraft ? $"Local settings only: {SettingsScopeLabel}. No deployment, source-root write, or enrollment provisioning."
        : IsDeploy ? DeploySelectedProject
            ? $"Exact selected scale set and one explicitly selected project: {SelectedProjectLabel}."
            : "Common-only deployment in the exact selected scale set. No project deployment is requested."
        : Action.Value == "delete-scale-set"
            ? "Only the exact selected environment, suffix, subscription and tenant scale set is requested."
            : "Configuration-only change until a separate runtime plan is prepared and confirmed.";
    public bool CanPrepare => IsNotBusy && _session.Catalog is not null &&
        (!ShowsSettingsDraft || SettingsEditor.CanPrepare) &&
        (IsLegacy ? Action.Value is "migrate" or "create-factory" : Action.Value != "migrate");
    public bool CanConfirm => _visible && IsNotBusy && ReceiptIsCurrent && _reviewed && Accepted &&
        (!IsDelete || string.Equals(TypedPhrase, RequiredPhrase, StringComparison.Ordinal));
    private bool ReceiptIsCurrent => _preview is { CanExecute: true } preview &&
        preview.Blockers.Count == 0 && !string.IsNullOrWhiteSpace(preview.ConfirmationId) &&
        DateTimeOffset.TryParse(preview.ExpiresAt, out var expires) && expires > _now() && _preparedInput == _inputVersion &&
        _preparedContext == _session.Generation && _preparedFolder == Folder &&
        preview.SourceRevision == _session.Catalog?.Revision;

    public CatalogChoice Action
    {
        get => _action;
        set
        {
            if (value is null || !Actions.Contains(value) || !SetProperty(ref _action, value)) return;
            InputChanged();
            if (!_versionEdited) SetVersionDraft(string.Empty);
            ProjectEditor.LoadScope(Folder, _session.SelectedFactory, _session.SelectedProject, value.Value == "add-project-placements");
            NotifyShape();
        }
    }
    public CatalogChoice? EnvironmentChoice { get => _environment; set { if (SetProperty(ref _environment, value)) InputChanged(); } }
    public CatalogChoice? OrchestratorChoice { get => _orchestrator; set { if (SetProperty(ref _orchestrator, value)) InputChanged(); } }
    public CatalogChoice IncludeProjects { get => _includeProjects; set { if (value is not null && SetProperty(ref _includeProjects, value)) InputChanged(); } }
    public string TargetPrefix { get => _targetPrefix; set { if (SetProperty(ref _targetPrefix, value)) InputChanged(); } }
    public string TargetRegion
    {
        get => _targetRegion;
        set
        {
            if (!SetProperty(ref _targetRegion, value)) return;
            OnPropertyChanged(nameof(TargetRegionChoice));
            InputChanged();
        }
    }
    public CatalogChoice? TargetRegionChoice
    {
        get => RegionChoices.FirstOrDefault(x => x.Value == TargetRegion);
        set
        {
            if (value is not null && RegionChoices.Contains(value)) TargetRegion = value.Value;
        }
    }
    public string Suffix { get => _suffix; set { if (SetProperty(ref _suffix, value)) InputChanged(); } }
    public string SubscriptionId { get => _subscriptionId; set { if (SetProperty(ref _subscriptionId, value)) InputChanged(); } }
    public string TenantId { get => _tenantId; set { if (SetProperty(ref _tenantId, value)) InputChanged(); } }
    public string VnetCidr { get => _vnetCidr; set { if (SetProperty(ref _vnetCidr, value)) InputChanged(); } }
    public string MaxProjects { get => _maxProjects; set { if (SetProperty(ref _maxProjects, value)) InputChanged(); } }
    public bool UseCustomCommonSubnets { get => _useCustomCommonSubnets; set { if (SetProperty(ref _useCustomCommonSubnets, value)) InputChanged(); } }
    public string CommonSubnet { get => _commonSubnet; set { if (SetProperty(ref _commonSubnet, value)) InputChanged(); } }
    public string ScoringSubnet { get => _scoringSubnet; set { if (SetProperty(ref _scoringSubnet, value)) InputChanged(); } }
    public string PowerbiSubnet { get => _powerbiSubnet; set { if (SetProperty(ref _powerbiSubnet, value)) InputChanged(); } }
    public string BastionSubnet { get => _bastionSubnet; set { if (SetProperty(ref _bastionSubnet, value)) InputChanged(); } }
    public string LocalFactoryVersion
    {
        get => IsClone ? _cloneFactoryVersion : _newFactoryVersion;
        set
        {
            if (IsClone ? SetProperty(ref _cloneFactoryVersion, value) : SetProperty(ref _newFactoryVersion, value)) InputChanged();
        }
    }
    public string VersionRef
    {
        get => _versionRef;
        set
        {
            if (!SetProperty(ref _versionRef, value)) return;
            _versionEdited = true;
            if (!string.IsNullOrWhiteSpace(value)) VersionMode = RuntimeVersionModes[1];
            InputChanged();
        }
    }
    public CatalogChoice VersionMode
    {
        get => _versionMode;
        set
        {
            if (value is null || !VersionModes.Contains(value) || !SetProperty(ref _versionMode, value)) return;
            if (value.Value == "override") _versionEdited = true;
            InputChanged();
            OnPropertyChanged(nameof(ShowsRuntimeVersionOverride));
        }
    }
    public bool Accepted { get => _accepted; set { if (SetProperty(ref _accepted, value)) NotifyConsent(); } }
    public bool DeploySelectedProject
    {
        get => _deploySelectedProject;
        set
        {
            if (!SetProperty(ref _deploySelectedProject, value)) return;
            InputChanged();
            OnPropertyChanged(nameof(OperationScope));
        }
    }
    public string TypedPhrase { get => _typedPhrase; set { if (SetProperty(ref _typedPhrase, value)) NotifyConsent(); } }

    public void SetVisible(bool visible)
    {
        _visible = visible;
        if (!visible) InputChanged();
        NotifyConsent();
    }

    public void RefreshConsentExpiry() => NotifyConsent();

    public void SetIntent(string action, string? region = null)
    {
        Action = Actions.Single(x => x.Value == action);
        if (!string.IsNullOrWhiteSpace(region)) TargetRegion = region;
    }

    public Task RefreshAsync() => ExecuteOperationAsync(async () =>
    {
        await _session.RefreshAsync();
        if (_session.Catalog is not null && _regionOptions is not null)
        {
            var generation = _session.Generation;
            var regions = await _regionOptions.GetOperationsRegionsAsync();
            if (!await _session.VerifyContextAsync() || generation != _session.Generation) return;
            var choices = regions.Regions.Where(RegionMapPresentation.IsGeographicRegion)
                .Where(region => !string.IsNullOrWhiteSpace(region.Name))
                .GroupBy(region => region.Name, StringComparer.Ordinal)
                .Select(group => group.First())
                .OrderBy(region => region.DisplayName, StringComparer.OrdinalIgnoreCase)
                .Select(region => new CatalogChoice(region.Name,
                    string.IsNullOrWhiteSpace(region.DisplayName) ? region.Name : region.DisplayName)).ToArray();
            RegionChoices.Clear();
            foreach (var choice in choices) RegionChoices.Add(choice);
            OnPropertyChanged(nameof(TargetRegionChoice));
        }
        StatusMessage = _session.Catalog is null ? ScopeMessage :
            $"{Factories.Count} logical factories. Select exact identities; refresh preserves draft inputs.";
    }, "Reading the factory catalog...");

    public Task PrepareAsync() => ExecuteOperationAsync(async () =>
    {
        InvalidatePreview();
        await _session.VerifyContextAsync();
        var request = BuildRequest();
        var input = _inputVersion;
        var context = _session.Generation;
        var folder = Folder;
        FactoryCatalogPreview preview;
        try
        {
            preview = await _client.PrepareFactoryCatalogAsync(request);
        }
        catch (Exception error) when ((folder != Folder || input != _inputVersion) &&
            error is HttpRequestException or IOException or InvalidOperationException or ArgumentException or
                System.Text.Json.JsonException or OperationCanceledException)
        {
            StatusMessage = "A previous draft request failed after the scope or inputs changed. No consent was retained.";
            return;
        }
        if (!await _session.VerifyContextAsync() || input != _inputVersion ||
            context != _session.Generation || folder != Folder)
        {
            StatusMessage = "The target or inputs changed while preparing. This response was discarded.";
            return;
        }
        if (preview.ContractVersion != 1 || preview.SourceRevision != _session.Catalog?.Revision)
            throw new InvalidDataException("The server preview does not match this catalog revision. Reload and review again.");
        if (request.Binding is not null && preview.CanExecute && !CatalogBindingEditor.Equivalent(request.Binding, preview.Binding))
            throw new InvalidDataException("The server did not echo the complete requested binding. No confirmation is permitted.");
        if (preview.CanExecute && ShowsProjectDraft && preview.OperationMode != "configuration")
            throw new InvalidDataException("A project configuration preview must not start a runtime operation.");
        if (preview.CanExecute && ShowsProjectDraft)
            ValidateProjectPreview(request, _session.SelectedFactory!, preview.Target);
        if (preview.CanExecute && ShowsSettingsDraft &&
            (preview.OperationMode != "configuration" || preview.Target?.Id != request.FactoryId))
            throw new InvalidDataException("The scoped settings preview returned a different factory or operation mode.");
        if (preview.CanExecute)
        {
            var expectedVersion = request.FactoryVersion ?? (IsClone ? _session.SelectedFactory?.FactoryVersion : null);
            if (expectedVersion is not null && preview.Target?.FactoryVersion != expectedVersion)
                throw new InvalidDataException("The server did not echo the saved factory version. Nothing can be confirmed; update the companion API rather than dropping this field.");
            foreach (var inputScale in request.ScaleSets?.Where(scale => scale.Network.CommonSubnets is not null) ?? [])
            {
                var returned = preview.Target?.ScaleSets.SingleOrDefault(scale =>
                    scale.Environment == inputScale.Environment && scale.Suffix == inputScale.Suffix &&
                    SameIdentity(scale.SubscriptionId, inputScale.SubscriptionId) && SameIdentity(scale.TenantId, inputScale.TenantId));
                if (returned?.Network != inputScale.Network)
                    throw new InvalidDataException("The server did not echo the exact custom network and common subnets. No confirmation is permitted.");
            }
        }
        _preview = preview;
        _preparedInput = input;
        _preparedContext = context;
        _preparedFolder = folder;
        _reviewDetails = FactoryCatalogPresentation.PreviewDetails(preview, folder, Action.Value,
            _session.SelectedFactory, Action.Value is "deploy" or "delete-scale-set" || ShowsSettingsDraft && SettingsScope.Value == "scale-set"
                ? _session.SelectedScaleSet : null,
            UsesRuntimeVersion ? request.VersionRef ?? "Inherit selected factory release; review the resolved source version below." :
                ShowsTarget ? request.FactoryVersion ?? "Inherit the source factory's saved release." :
                    "Not submitted — this configuration action does not override the saved factory version.");
        if (IsDeploy) _reviewDetails += request.ProjectId is { } projectId
            ? $"\nSelected project deployment ID: {projectId}\n{SelectedProjectDetails}"
            : "\nCommon-only deployment. No project ID was submitted.";
        if (request.Settings is { } settings)
            _reviewDetails += $"\nSettings scope: {SettingsScopeLabel}\n{SettingsScopeDetails}\nSettings revision: {SettingsEditor.Revision}\n" +
                SettingsEditor.ReviewDelta(settings);
        OnPropertyChanged(nameof(ReviewDetails));
        NotifyConsent();
        StatusMessage = preview.CanExecute ? "Preview ready. Open the full review, then explicitly confirm." :
            "The server blocked this operation. Review the blockers; nothing was changed.";
    }, "Preparing a server-owned plan; no files or resources are changed...");

    public FactoryCatalogRequest BuildRequest()
    {
        if (_session.Catalog is null) throw new InvalidOperationException("Reload the current catalog before preparing.");
        if (IsLegacy && Action.Value is not ("migrate" or "create-factory") || IsCatalog && Action.Value == "migrate")
            throw new InvalidOperationException(CapabilityMessage);
        var factory = _session.SelectedFactory;
        var scale = _session.SelectedScaleSet;
        var project = _session.SelectedProject;
        var settingsScope = ShowsSettingsDraft ? CurrentSettingsScope ??
            throw new InvalidOperationException("Select the exact factory, scale set or project for settings.") : null;
        if (Action.Value is not ("create-factory" or "migrate") && factory is null)
            throw new InvalidOperationException("Choose the exact factory from the current catalog.");
        if (Action.Value is "delete-scale-set" or "deploy" or "configure-binding" && scale is null)
            throw new InvalidOperationException("Choose the exact environment, suffix and subscription scale set.");
        if (ShowsRuntimeVersionOverride && string.IsNullOrWhiteSpace(VersionRef))
            throw new InvalidOperationException("Select an explicit AI Factory version before preparing.");
        if (IsDeploy && DeploySelectedProject && (project is null ||
            !project.Placements.Any(placement => placement.ScaleSetId == scale?.Id && placement.Environment == scale.Environment)))
            throw new InvalidOperationException("Select an exact project already placed in the selected scale set, or explicitly choose common-only deployment.");
        if (ShowsTarget && (string.IsNullOrWhiteSpace(TargetPrefix) || string.IsNullOrWhiteSpace(TargetRegion)))
            throw new InvalidOperationException("Enter the destination factory prefix and region.");
        if (ShowsTarget && TargetRegionChoice is null)
            throw new InvalidOperationException("Choose a canonical destination region from the server region list. Reload catalog if options are unavailable.");
        if (ShowsTarget && (Action.Value == "create-factory" || LocalFactoryVersion.Length > 0) &&
            string.IsNullOrWhiteSpace(LocalFactoryVersion))
            throw new InvalidOperationException("Enter an explicit saved factory version; only a blank clone version means inherit.");

        IReadOnlyList<CatalogScaleSetInput>? scaleSets = null;
        if (ShowsScaleSetDraft)
        {
            if (EnvironmentChoice is null || !Environments.Contains(EnvironmentChoice) ||
                OrchestratorChoice is null || !Orchestrators.Contains(OrchestratorChoice))
                throw new InvalidOperationException("Explicitly select an environment and its pipeline route. No environment is inferred.");
            FactoryCatalogPresentation.ValidateSuffix(Suffix);
            if (!Guid.TryParse(SubscriptionId, out var subscription) || subscription == Guid.Empty ||
                !Guid.TryParse(TenantId, out var tenant) || tenant == Guid.Empty)
                throw new InvalidOperationException("Provide the exact subscription and tenant GUIDs for this scale set.");
            if (string.IsNullOrWhiteSpace(VnetCidr))
                throw new InvalidOperationException("Provide an explicit VNet CIDR; the server will validate placement capacity.");
            var capacity = FactoryCatalogPresentation.ValidateCapacity(MaxProjects);
            if (Action.Value == "create-scale-set" && factory!.ScaleSets.Any(x =>
                    x.Environment == EnvironmentChoice.Value && x.Suffix == Suffix))
                throw new InvalidOperationException("This environment and suffix already exist in the selected factory.");
            scaleSets =
            [
                new()
                {
                    Environment = EnvironmentChoice.Value, Suffix = Suffix,
                    SubscriptionId = SubscriptionId, TenantId = TenantId,
                    Orchestrator = OrchestratorChoice.Value,
                    Network = new() { VnetCidr = VnetCidr, MaxProjects = capacity, CommonSubnets = BuildCommonSubnets() }
                }
            ];
        }
        if (!ProjectInclusions.Contains(IncludeProjects))
            throw new InvalidOperationException("Choose no projects or all project configurations.");
        var placements = ShowsProjectDraft
            ? ProjectEditor.BuildPlacements(Folder, factory!, project, Action.Value == "add-project-placements") : null;
        return new()
        {
            Folder = Folder, ContractVersion = 1, Action = Action.Value, SourceRevision = _session.Catalog.Revision,
            FactoryId = Action.Value is "create-factory" or "migrate" ? null : factory?.Id,
            ScaleSetId = ShowsSettingsDraft ? settingsScope!.ScaleSetId : Action.Value is "deploy" or "delete-scale-set" ? scale?.Id : null,
            TargetPrefix = ShowsTarget ? TargetPrefix : null,
            TargetRegion = ShowsTarget ? TargetRegion : null,
            IncludeProjects = IsClone ? IncludeProjects.Value : "none",
            ScaleSets = scaleSets, VersionRef = ShowsRuntimeVersionOverride ? VersionRef : null,
            FactoryVersion = ShowsTarget && LocalFactoryVersion.Length > 0 ? LocalFactoryVersion : null,
            Binding = ShowsBindingDraft ? BindingEditor.Build(Folder, factory!, scale!) : null,
            ProjectId = ShowsSettingsDraft ? settingsScope!.ProjectId :
                Action.Value == "add-project-placements" || IsDeploy && DeploySelectedProject ? project?.Id : null,
            Project = IsNewProject ? new() { Number = ProjectEditor.Number, DisplayName = ProjectEditor.DisplayName, Placements = placements! } : null,
            Placements = Action.Value == "add-project-placements" ? placements : null,
            Settings = ShowsSettingsDraft ? SettingsEditor.BuildDelta(settingsScope!, _session.Catalog.Revision) : null
        };
    }

    private CatalogCommonSubnets? BuildCommonSubnets()
    {
        if (!UseCustomCommonSubnets) return null;
        if (new[] { CommonSubnet, ScoringSubnet, PowerbiSubnet, BastionSubnet }.Any(string.IsNullOrWhiteSpace))
            throw new InvalidOperationException("Provide all four explicit common subnet CIDRs, or disable custom common subnets.");
        return new() { Common = CommonSubnet, Scoring = ScoringSubnet, Powerbi = PowerbiSubnet, Bastion = BastionSubnet };
    }

    private static bool SameIdentity(string left, string right) => left == right ||
        Guid.TryParse(left, out var a) && Guid.TryParse(right, out var b) && a == b;

    public void ReloadBindingDraft()
    {
        BindingEditor.LoadScope(Folder, _session.SelectedFactory, _session.SelectedScaleSet, discardEdits: true);
        InputChanged();
    }

    public Task LoadSettingsAsync() => ExecuteOperationAsync(async () =>
    {
        if (!_visible || !_session.IsCatalog) throw new InvalidOperationException("Open a verified catalog before loading scoped settings.");
        if (_settingsClient is null || _regionOptions is null)
            throw new NotSupportedException("The scoped settings client is unavailable in this application.");
        await _session.VerifyContextAsync();
        var scope = CurrentSettingsScope ?? throw new InvalidOperationException("Select the exact settings scope before loading.");
        InputChanged();
        var input = _inputVersion;
        var generation = _session.Generation;
        var settingsTask = _settingsClient.GetFactoryCatalogSettingsAsync(scope.Folder, scope.FactoryId, scope.ScaleSetId, scope.ProjectId);
        var schemaTask = _regionOptions.GetSchemaAsync();
        await Task.WhenAll(settingsTask, schemaTask);
        if (!_visible || !await _session.VerifyContextAsync() || input != _inputVersion ||
            generation != _session.Generation || scope != CurrentSettingsScope)
        {
            StatusMessage = "Settings arrived for a changed scope or draft and were discarded.";
            return;
        }
        var settings = await settingsTask;
        if (settings.Revision != _session.Catalog?.Revision)
            throw new InvalidDataException("Settings belong to a newer or different catalog revision. Reload the catalog, then reload this settings scope.");
        SettingsEditor.Load(scope, settings, await schemaTask);
        StatusMessage = "Scoped settings loaded without changing wizard state. Edit only the intended values, then prepare and review.";
        NotifyConsent();
    }, "Loading isolated scoped settings and schema...");

    public void MarkReviewed(string details)
    {
        if (_preview is null || details != ReviewDetails) return;
        _reviewed = true;
        NotifyConsent();
    }

    public Task ConfirmAsync() => ExecuteOperationAsync(async () =>
    {
        await _session.VerifyContextAsync();
        if (!_visible || !ReceiptIsCurrent || !_reviewed || !Accepted ||
            IsDelete && !string.Equals(TypedPhrase, RequiredPhrase, StringComparison.Ordinal))
            throw new InvalidOperationException("Consent is missing, expired or changed. Prepare and review a fresh plan.");
        var receipt = _preview!.ConfirmationId;
        var folder = Folder;
        var generation = _session.Generation;
        var submittedInput = _inputVersion;
        var submittedAction = Action.Value;
        InvalidatePreview();
        // Consume the local receipt before transport: an uncertain response must never trigger an automatic retry.
        FactoryCatalogConfirmation result;
        try
        {
            result = await _client.ConfirmFactoryCatalogAsync(folder, receipt);
        }
        catch (Exception error) when (folder != Folder &&
            error is HttpRequestException or IOException or InvalidOperationException or ArgumentException or
                System.Text.Json.JsonException or OperationCanceledException)
        {
            throw new InvalidOperationException($"Confirmation for the previous root {folder} did not report a successful outcome. " +
                $"Reload that root and its jobs before any further action. {error.Message}", error);
        }
        if (!await _session.VerifyContextAsync() || folder != Folder || generation != _session.Generation)
        {
            StatusMessage = "Confirmation returned for a previous context. Reload that root and its jobs to inspect the outcome.";
            return;
        }
        if (result.ContractVersion != 1 || (result.Catalog is null) == (result.Job is null))
            throw new InvalidDataException("The server must return exactly one catalog or job. Outcome is unknown; reload explicitly, do not retry confirmation.");
        if (submittedAction == "configure-settings" && result.Catalog is null)
            throw new InvalidDataException("A local settings confirmation unexpectedly returned a runtime job. Inspect the outcome; do not retry.");
        if (result.Catalog is not null)
        {
            _session.Apply(result.Catalog);
            if (submittedAction == "configure-binding" && submittedInput == _inputVersion)
                BindingEditor.LoadScope(Folder, _session.SelectedFactory, _session.SelectedScaleSet, discardEdits: true);
            if (submittedAction == "configure-settings" && submittedInput == _inputVersion)
                SettingsEditor.Clear("Reviewed settings saved. Load this exact scope again to inspect its effective values.");
        }
        if (result.Job is { } job)
        {
            Jobs.Insert(0, job);
            if (job.Status is not ("queued" or "running" or "succeeded") || job.ExitCode is not null and not 0)
                throw new InvalidOperationException($"Operation {job.Status}: {job.Message} " +
                    "Inspect the job and reconcile explicitly before any further operation; no retry was started.");
            StatusMessage = $"Operation {job.Status}: {job.Message} Reload jobs explicitly to check progress. " +
                (job.TerminalAvailable ? "An interactive terminal is available; open it explicitly below." :
                    "The server reports that this job has no interactive terminal.");
        }
        else StatusMessage = "Reviewed configuration changes saved. No Azure deployment was started; wizard edits are unchanged.";
    }, "Submitting the reviewed confirmation receipt...");

    public Task ReloadJobsAsync() => ExecuteOperationAsync(async () =>
    {
        if (!_visible) throw new InvalidOperationException("Open Manage factories before reloading catalog jobs.");
        await _session.VerifyContextAsync();
        var folder = Folder;
        var generation = _session.Generation;
        var response = await _client.GetFactoryCatalogJobsAsync(folder);
        if (!_visible || !await _session.VerifyContextAsync() || generation != _session.Generation || folder != Folder) return;
        if (response.ContractVersion != 1) throw new InvalidDataException("Unsupported catalog jobs contract.");
        Jobs.Clear();
        foreach (var job in response.Jobs) Jobs.Add(job);
        StatusMessage = $"{Jobs.Count} server-owned jobs. Reload is manual; failures are not retried. {TerminalCapabilityMessage}";
    }, "Reloading catalog jobs...");

    public Task OpenTerminalAsync(FactoryCatalogJob? job) => ExecuteOperationAsync(async () =>
    {
        if (!_visible || job is null || !Jobs.Contains(job))
            throw new InvalidOperationException("Select a job from this root's current catalog job list.");
        if (_terminal is null || !job.TerminalAvailable)
            throw new NotSupportedException("The server or this client does not provide an interactive terminal for this job.");
        await _session.VerifyContextAsync();
        var folder = Folder;
        var generation = _session.Generation;
        var current = await _client.GetFactoryCatalogJobAsync(folder, job.Id);
        if (!_visible || !await _session.VerifyContextAsync() || folder != Folder || generation != _session.Generation) return;
        if (current.Id != job.Id || current.FactoryId != job.FactoryId || current.ScaleSetId != job.ScaleSetId)
            throw new InvalidDataException("The returned terminal job belongs to a different catalog scope.");
        if (!current.TerminalAvailable)
            throw new NotSupportedException("The server reports that this job's interactive terminal is no longer available.");
        await _terminal.OpenCatalogAsync(folder, current);
        StatusMessage = "Opened the exact server-owned catalog job in the shared terminal footer.";
    }, "Verifying the selected catalog terminal...");

    protected override void OnOperationFailed(Exception exception) => InvalidatePreview();

    private void InputChanged()
    {
        _inputVersion++;
        InvalidatePreview();
    }

    private void InvalidatePreview()
    {
        _preview = null;
        _reviewDetails = string.Empty;
        _reviewed = _accepted = false;
        _typedPhrase = string.Empty;
        _disclosure.Cancel();
        _disclosure.Dispose();
        _disclosure = new();
        OnPropertyChanged(nameof(ReviewDetails));
        OnPropertyChanged(nameof(Accepted));
        OnPropertyChanged(nameof(TypedPhrase));
        NotifyConsent();
    }

    private void Rebuild()
    {
        Factories.Clear();
        ScaleSets.Clear();
        Projects.Clear();
        Bindings.Clear();
        foreach (var factory in _session.Catalog?.Factories ?? []) Factories.Add(new(factory));
        if (_session.SelectedFactory is { } selected)
        {
            foreach (var scale in selected.ScaleSets) ScaleSets.Add(new(scale));
            foreach (var project in selected.Projects) Projects.Add(new(project, selected));
            foreach (var binding in selected.Bindings) Bindings.Add(new(binding));
        }
        if (_inputRoot != Folder)
        {
            _inputRoot = Folder;
            _versionFactory = null;
            _versionEdited = false;
            VersionMode = RuntimeVersionModes[0];
            _newFactoryVersion = "124";
            _cloneFactoryVersion = string.Empty;
            SetVersionDraft(string.Empty);
            Jobs.Clear();
        }
        if (_session.SelectedFactoryId is not null && _versionFactory != _session.SelectedFactoryId)
        {
            _versionFactory = _session.SelectedFactoryId;
            _versionEdited = false;
            VersionMode = RuntimeVersionModes[0];
            _cloneFactoryVersion = string.Empty;
            SetVersionDraft(string.Empty);
        }
        if (_session.Catalog is not null)
        {
            BindingEditor.LoadScope(Folder, _session.SelectedFactory, _session.SelectedScaleSet);
            ProjectEditor.LoadScope(Folder, _session.SelectedFactory, _session.SelectedProject, Action.Value == "add-project-placements");
        }
        else
        {
            Jobs.Clear();
            RegionChoices.Clear();
            OnPropertyChanged(nameof(TargetRegionChoice));
            BindingEditor.LoadScope(Folder, null, null, discardEdits: true);
            ProjectEditor.LoadScope(Folder, null, null, Action.Value == "add-project-placements");
            DeploySelectedProject = false;
        }
        Warning = string.Join("\n", _session.Catalog?.Warnings ?? []);
        SettingsEditor.UpdateContext(CurrentSettingsScope, _session.Catalog?.Revision);
        NotifySettingsScope();
        foreach (var property in new[] { nameof(Folder), nameof(Revision), nameof(IsLegacy), nameof(IsCatalog),
                     nameof(HasSelection), nameof(SelectionLabel), nameof(SelectionDetails), nameof(SelectedProjectLabel), nameof(SelectedProjectDetails),
                     nameof(SavedFactoryVersion), nameof(LocalFactoryVersion), nameof(ScopeMessage) })
            OnPropertyChanged(property);
        NotifyShape();
    }

    private void SetVersionDraft(string version)
    {
        _versionRef = version;
        OnPropertyChanged(nameof(VersionRef));
        InputChanged();
    }

    private void NotifyShape()
    {
        foreach (var property in new[] { nameof(IsDelete), nameof(IsClone), nameof(ShowsTarget),
                     nameof(ShowsScaleSetDraft), nameof(ShowsBindingDraft), nameof(ShowsSettingsDraft), nameof(UsesRuntimeVersion), nameof(ShowsRuntimeVersionOverride),
                     nameof(ShowsProjectDraft), nameof(IsNewProject), nameof(IsDeploy),
                     nameof(LocalFactoryVersion), nameof(LocalVersionGuidance),
                     nameof(CapabilityMessage), nameof(RequiredPhrase), nameof(OperationScope) })
            OnPropertyChanged(property);
        NotifyConsent();
    }

    private void NotifySettingsScope()
    {
        OnPropertyChanged(nameof(SettingsScopeLabel));
        OnPropertyChanged(nameof(SettingsScopeDetails));
        OnPropertyChanged(nameof(OperationScope));
    }

    private void NotifyConsent()
    {
        foreach (var property in new[] { nameof(HasPreview), nameof(PreviewSummary), nameof(PreviewWarnings),
                     nameof(PreviewBlockers), nameof(ConsentStatus), nameof(CanPrepare), nameof(CanConfirm) })
            OnPropertyChanged(property);
    }
}

using System.Collections.ObjectModel;
using System.ComponentModel;
using System.Globalization;
using ESAIF.BaseLayer.Application;
using ESAIF.ConfigWizard.Services;
using ESAIF.DomainLayer.Configuration;
using ESAIF.DomainLayer.Operations;

namespace ESAIF.ConfigWizard.ViewModels;

public sealed class AiFactoryViewModel : OperationViewModel
{
    private readonly OperationsSession _operations;
    private readonly IProjectDeploymentClient _deployments;
    private readonly IAiFactoryConnectionProvider? _connection;
    private readonly TimeProvider _clock;
    private readonly AzureRefreshCoordinator? _refresh;
    private readonly IDeploymentTerminalSession? _terminal;
    private readonly Func<string, bool>? _isCatalogScope;
    private readonly HashSet<string> _refreshedJobs = [];
    private readonly Dictionary<(string Project, string Environment), string> _versionEdits = [];
    private IReadOnlyList<ProjectDeploymentDraft> _drafts = [];
    private FactoryVersionSelection? _factoryVersionSelection;
    private IReadOnlyList<string> _versionBlockers = [];
    private string _draftFolder = string.Empty, _planFolder = string.Empty, _planDraftId = string.Empty;
    private AiFactoryConnection? _planConnection;
    private enum ReviewKind { Deploy, Update, Reconcile }
    private ReviewKind _reviewKind;
    private bool _planPatch;
    private string? _planFactoryVersion;
    private string? _planJobId;
    private long _scopeVersion;
    private long _reviewVersion;
    private bool _draftsLoaded;
    private bool _draftPollingFailed;
    private string _sourceLabel = "Local";
    private string _missingFolderMessage = string.Empty;
    private string _selectionFolder = string.Empty;
    private ProjectEnvironmentCardViewModel? _selectedProject;

    public AiFactoryViewModel(
        OperationsSession operations,
        IProjectDeploymentClient deployments,
        IAiFactoryConnectionProvider? connection = null,
        TimeProvider? clock = null,
        AzureRefreshCoordinator? refresh = null,
        IDeploymentTerminalSession? terminal = null,
        Func<string, bool>? isCatalogScope = null)
    {
        _operations = operations;
        _deployments = deployments;
        _connection = connection;
        _clock = clock ?? TimeProvider.System;
        _refresh = refresh;
        _terminal = terminal;
        _isCatalogScope = isCatalogScope;
        _operations.OverviewChanged += OnOverviewChanged;
        OpenWizardCommand = new AsyncCommand(
            () => AppShell.NavigateToWorkspaceAsync(AppShell.WizardPageKey));
        DeployCommand = new Command<ProjectEnvironmentCardViewModel>(
            async card => await DeployAsync(card), CanDeployCard);
        UpdateCommand = new Command<ProjectEnvironmentCardViewModel>(
            async card => await UpdateAsync(card), CanUpdateCard);
        ReviewOutcomeCommand = new Command<ProjectEnvironmentCardViewModel>(
            async card => await ReviewOutcomeAsync(card), CanReviewOutcomeCard);
        ConfirmDeploymentCommand = new AsyncCommand(ConfirmDeploymentAsync, () => CanConfirmDeployment);
        DismissDeploymentCommand = new AsyncCommand(() => { DismissDeployment(); return Task.CompletedTask; }, () => !IsBusy);
        RefreshDraftsCommand = new AsyncCommand(RefreshDraftsAsync, () => !IsBusy);
        SelectProjectCommand = new Command<ProjectEnvironmentCardViewModel>(SelectProject);
        OpenTerminalCommand = new Command<ProjectEnvironmentCardViewModel>(async card => await OpenTerminalAsync(card),
            card => !IsBusy && !IsCatalogScope && card is { HasTerminal: true } && Cards().Contains(card));
        ConfigureDataOpsCommand = CreateConfigureCommand("dataops");
        ConfigureMLOpsCommand = CreateConfigureCommand("mlops");
        ConfigureRagCommand = CreateConfigureCommand("rag");
        ConfigureFineTuningCommand = CreateConfigureCommand("finetuning");
        PropertyChanged += (_, e) =>
        {
            if (e.PropertyName == nameof(IsBusy)) NotifyDeploymentActions();
        };
        ApplyOverview(_operations.Current);
    }

    public ObservableCollection<ProjectEnvironmentRowViewModel> ProjectRows { get; } = [];
    public int DevCount => ProjectRows.Count(row => row.Dev.IsDeployed);
    public int StageCount => ProjectRows.Count(row => row.Stage.IsDeployed);
    public int ProdCount => ProjectRows.Count(row => row.Prod.IsDeployed);
    public bool IsEmpty => HasOverview && ProjectRows.Count == 0;
    public int DraftCount => ProjectRows.Sum(row => new[] { row.Dev, row.Stage, row.Prod }.Count(card => card.IsDraft));
    public string StageHeader => EnvironmentHeader("Stage", StageCount, ProjectRows.Count(row => row.Stage.IsDraft));
    public string ProdHeader => EnvironmentHeader("Prod", ProdCount, ProjectRows.Count(row => row.Prod.IsDraft));
    public string BoardSummary => $"{ProjectRows.Count} projects · Deployed: Dev {DevCount} · Stage {StageCount} · Prod {ProdCount} · Drafts {DraftCount}. " +
        "Dark gray cards are saved deployment plans, not deployed resources.";
    public bool HasRunningDrafts => _drafts.Any(draft => draft.IsRunning);
    public bool NeedsDraftRefresh => !_draftsLoaded && !IsMissingFolder;
    public bool CanPollDrafts => !IsCatalogScope && !_draftPollingFailed && (HasRunningDrafts || NeedsDraftRefresh);
    public ProjectDeploymentPlan? DeploymentPlan { get; private set; }
    public bool HasDeploymentPlan => DeploymentPlan is not null;
    public string DeploymentEffects => Lines(DeploymentPlan?.Effects);
    public string DeploymentWarnings => Lines(DeploymentPlan?.Warnings);
    public string DeploymentBlockers => Lines(DeploymentPlan?.Blockers);
    public string FactoryVersionWarnings => Lines(_versionBlockers);
    public string DeploymentTemplateBranch => string.IsNullOrWhiteSpace(DeploymentPlan?.Branch)
        ? "Not resolved by the API" : DeploymentPlan.Branch;
    public string DeploymentTemplateRef => DeploymentPlan?.ResolvedRef ?? string.Empty;
    public string DeploymentScope => _planFolder;
    public bool IsReconciliationReview => HasDeploymentPlan && _reviewKind == ReviewKind.Reconcile;
    public string DeploymentReviewTitle => _reviewKind switch
    {
        ReviewKind.Reconcile => "Review deployment outcome",
        ReviewKind.Update => "Review project update",
        _ => "Review project deployment"
    };
    public string ConfirmDeploymentText => _reviewKind switch
    {
        ReviewKind.Reconcile => "Acknowledge reviewed outcome",
        ReviewKind.Update => "Confirm and update",
        _ => "Confirm and deploy"
    };
    public string DeploymentNotice => IsReconciliationReview
        ? "Inspect the terminal, repository and cloud pipeline/resources first. Acknowledgement only releases this job's repository hold; it does not undo changes, clear failure or retry the deployment."
        : "This can publish configuration and start a pipeline that creates billable Azure resources. Patch additionally refreshes shared templates. Review the exact effects and terminal prompts.";
    public bool CanConfirmDeployment => !IsBusy && !IsCatalogScope && DeploymentPlan is { CanExecute: true, Blockers.Count: 0 } plan &&
        !string.IsNullOrWhiteSpace(plan.ConfirmationId) && (IsReconciliationReview || !string.IsNullOrWhiteSpace(plan.Command)) &&
        DateTimeOffset.TryParse(plan.ExpiresAt, CultureInfo.InvariantCulture, DateTimeStyles.AssumeUniversal, out var expires) &&
        expires > _clock.GetUtcNow() && FactoryNetworkSession.SameFolder(_planFolder, _operations.Folder) &&
        HasCurrentReviewCard();

    public AsyncCommand OpenWizardCommand { get; }

    public Command<ProjectEnvironmentCardViewModel> DeployCommand { get; }
    public Command<ProjectEnvironmentCardViewModel> UpdateCommand { get; }
    public Command<ProjectEnvironmentCardViewModel> ReviewOutcomeCommand { get; }
    public Command<ProjectEnvironmentCardViewModel> SelectProjectCommand { get; }
    public Command<ProjectEnvironmentCardViewModel> OpenTerminalCommand { get; }
    public AsyncCommand ConfirmDeploymentCommand { get; }
    public AsyncCommand DismissDeploymentCommand { get; }
    public AsyncCommand RefreshDraftsCommand { get; }
    public ProjectEnvironmentCardViewModel? SelectedProject => _selectedProject;

    public void SelectProject(ProjectEnvironmentCardViewModel? card)
    {
        var cards = ProjectRows.SelectMany(row => new[] { row.Dev, row.Stage, row.Prod }).ToArray();
        if (card is not { HasCard: true } || !cards.Contains(card)) return;
        _selectedProject = card;
        _selectionFolder = _operations.Folder;
        foreach (var item in cards) item.SetSelected(ReferenceEquals(item, card));
        OnPropertyChanged(nameof(SelectedProject));
    }

    public Command<ProjectEnvironmentCardViewModel> ConfigureDataOpsCommand { get; }

    public Command<ProjectEnvironmentCardViewModel> ConfigureMLOpsCommand { get; }

    public Command<ProjectEnvironmentCardViewModel> ConfigureRagCommand { get; }

    public Command<ProjectEnvironmentCardViewModel> ConfigureFineTuningCommand { get; }

    public string SourceLabel
    {
        get => _sourceLabel;
        private set => SetProperty(ref _sourceLabel, value);
    }

    public string MissingFolderMessage
    {
        get => _missingFolderMessage;
        private set
        {
            if (SetProperty(ref _missingFolderMessage, value))
            {
                OnPropertyChanged(nameof(IsMissingFolder));
            }
        }
    }

    public bool IsMissingFolder => !string.IsNullOrWhiteSpace(MissingFolderMessage);

    public bool HasOverview => _operations.HasOverview || _drafts.Count > 0;

    public Task LoadAsync(bool forceRefresh = false) =>
        ExecuteOperationAsync(async () =>
        {
            EnsureSingleFactoryScope(_operations.Folder);
            var overview = await _operations.LoadAsync(
                forceRefresh,
                includeAzure: true);
            ApplyOverview(overview);
            if (!string.IsNullOrWhiteSpace(_operations.Folder)) await ReadDraftsAsync(RequireFolder());
            StatusMessage = overview is null
                ? MissingFolderMessage
                : BoardSummary;
        }, forceRefresh
            ? "Refreshing Azure project environments..."
            : "Loading AI Factory project board...");

    public async Task DeployAsync(ProjectEnvironmentCardViewModel? card)
    {
        if (!CanDeployCard(card))
        {
            StatusMessage = "Choose an observed project with an empty next environment, or a saved draft ready to deploy.";
            return;
        }
        DismissDeployment();
        var folder = RequireFolder();
        var version = _scopeVersion;
        var review = _reviewVersion;
        var patch = card!.Patch;
        var factoryVersion = RequestedVersion(card);
        await ExecuteOperationAsync(async () =>
        {
            var source = _connection is null ? null : await _connection.GetConnectionAsync();
            EnsureSingleFactoryScope(folder);
            if (card.ShowDeployButton)
            {
                await PrepareDeploymentReviewAsync(folder, card.Draft!, patch, factoryVersion, source, version, review);
            }
            else
            {
                var draft = await _deployments.PlanProjectDeploymentAsync(folder, card.ProjectNumber,
                    card.Environment, card.DeploymentTarget!, patch, factoryVersion: factoryVersion);
                if (!IsCurrent(folder, version) || !await IsSameConnectionAsync(source)) return;
                UpdateDraft(folder, draft);
                SelectProject(Cards().FirstOrDefault(target => target.Draft?.Id == draft.Id));
                StatusMessage = $"{card.DeployButtonText} draft saved. Azure is unchanged.";
            }
        }, card!.IsDraft ? "Preparing deployment confirmation..." : "Saving an environment draft. Azure is unchanged...");
    }

    public async Task UpdateAsync(ProjectEnvironmentCardViewModel? card)
    {
        if (!CanUpdateCard(card))
        {
            StatusMessage = "Choose an observed deployment with no running or failed job to review an update.";
            return;
        }
        DismissDeployment();
        var folder = RequireFolder();
        var version = _scopeVersion;
        var review = _reviewVersion;
        var patch = card!.Patch;
        var factoryVersion = RequestedVersion(card);
        await ExecuteOperationAsync(async () =>
        {
            var source = _connection is null ? null : await _connection.GetConnectionAsync();
            EnsureSingleFactoryScope(folder);
            var draft = card.CanSubmitDraft ? card.Draft! :
                await _deployments.PlanProjectDeploymentAsync(folder, card.ProjectNumber,
                    card.Environment, card.Environment, patch, operation: "update", factoryVersion: factoryVersion);
            if (!IsCurrent(folder, version) || !await IsSameConnectionAsync(source)) return;
            UpdateDraft(folder, draft);
            if (review != _reviewVersion) return;
            await PrepareDeploymentReviewAsync(folder, draft, patch, factoryVersion, source, version, review);
        }, "Preparing an update of this project in the same environment. Nothing has been started...");
    }

    private async Task PrepareDeploymentReviewAsync(string folder, ProjectDeploymentDraft draft, bool patch, string? factoryVersion,
        AiFactoryConnection? source, long version, long review)
    {
        var plan = await _deployments.PrepareProjectDeploymentAsync(folder, draft.Id, patch, factoryVersion: factoryVersion);
        if (!IsCurrent(folder, version) || review != _reviewVersion || !await IsSameConnectionAsync(source)) return;
        SetReview(folder, draft, source, plan, draft.Operation == "update" ? ReviewKind.Update : ReviewKind.Deploy, patch, factoryVersion);
        StatusMessage = "Review the exact script, target, template version, Patch choice and effects below. Nothing has been started.";
    }

    public async Task ReviewOutcomeAsync(ProjectEnvironmentCardViewModel? card)
    {
        if (!CanReviewOutcomeCard(card))
        {
            StatusMessage = "Choose an unreconciled failed or interrupted deployment job in this factory.";
            return;
        }
        DismissDeployment();
        var folder = RequireFolder();
        var version = _scopeVersion;
        var review = _reviewVersion;
        var draft = card!.Draft!;
        await ExecuteOperationAsync(async () =>
        {
            var source = _connection is null ? null : await _connection.GetConnectionAsync();
            EnsureSingleFactoryScope(folder);
            var plan = await _deployments.PrepareProjectReconciliationAsync(folder, draft.JobId!);
            if (!IsCurrent(folder, version) || review != _reviewVersion || !await IsSameConnectionAsync(source)) return;
            SetReview(folder, draft, source, plan, ReviewKind.Reconcile, draft.Patch);
            StatusMessage = "Review the terminal and partial local/cloud outcome before explicitly acknowledging it. No retry will occur.";
        }, "Preparing outcome acknowledgement. The repository hold is unchanged...");
    }

    private void SetReview(string folder, ProjectDeploymentDraft draft, AiFactoryConnection? source,
        ProjectDeploymentPlan plan, ReviewKind kind, bool patch, string? factoryVersion = null)
    {
        _planFolder = folder;
        _planDraftId = draft.Id;
        _planJobId = draft.JobId;
        _planPatch = patch;
        _planFactoryVersion = factoryVersion ??
            Cards().Where(card => card.Draft?.Id == draft.Id).Select(RequestedVersion).FirstOrDefault();
        _planConnection = source;
        _reviewKind = kind;
        DeploymentPlan = plan;
        NotifyDeploymentPlan();
    }

    public async Task ConfirmDeploymentAsync()
    {
        if (!CanConfirmDeployment)
        {
            StatusMessage = "The preview is blocked, expired or no longer current. Review the action again.";
            return;
        }
        var plan = DeploymentPlan!;
        var folder = _planFolder;
        var version = _scopeVersion;
        var source = _planConnection;
        var reconciliation = IsReconciliationReview;
        DismissDeployment();
        var review = _reviewVersion;
        await ExecuteOperationAsync(async () =>
        {
            if (_connection is not null && source != await _connection.GetConnectionAsync())
                throw new InvalidOperationException("The API connection changed. Review the action again.");
            if (!IsCurrent(folder, version))
                throw new InvalidOperationException("The selected factory changed. Review the action again.");
            EnsureSingleFactoryScope(folder);
            if (review != _reviewVersion)
                throw new InvalidOperationException("The reviewed version or Patch choice changed. Review the action again.");
            var draft = reconciliation
                ? await _deployments.ReconcileProjectDeploymentAsync(folder, plan.ConfirmationId)
                : await _deployments.StartProjectDeploymentAsync(folder, plan.ConfirmationId);
            if (!await IsSameConnectionAsync(source))
                throw new InvalidOperationException("The action was submitted to the original API. Restore that connection and reload its status; do not submit again.");
            if (IsCurrent(folder, version))
            {
                UpdateDraft(folder, draft);
                StatusMessage = reconciliation
                    ? "Outcome acknowledged. Failure remains visible; nothing was retried or undone. Other unreconciled jobs may still hold this repository."
                    : $"Deployment {draft.Status}: {draft.Message} " +
                    "Azure inventory must confirm the target before it is marked active.";
            }
            if (!reconciliation && _terminal is not null && !string.IsNullOrWhiteSpace(draft.JobId))
                await _terminal.OpenAsync(folder, draft);
        }, reconciliation
            ? "Acknowledging the reviewed outcome. If the response is lost, reload drafts; do not submit again."
            : "Starting the confirmed deployment. Do not submit again if the response is lost; reload drafts to reconcile.");
    }

    public Task RefreshDraftsAsync() => ExecuteOperationAsync(async () =>
    {
        await ReadDraftsAsync(RequireFolder());
        StatusMessage = BoardSummary;
    }, "Refreshing saved deployment status...");

    public Task OpenTerminalAsync(ProjectEnvironmentCardViewModel? card) =>
        ExecuteOperationAsync(async () =>
        {
            if (card is not { HasTerminal: true } || !Cards().Contains(card))
                throw new InvalidOperationException("Choose a deployment job in the current factory.");
            if (_terminal is null)
                throw new InvalidOperationException("The interactive terminal is unavailable.");
            await _terminal.OpenAsync(RequireFolder(), card.Draft!);
            StatusMessage = "Terminal opened for the selected deployment job. Collapsing it does not stop the script.";
        }, "Opening the selected deployment terminal...");

    private async Task ReadDraftsAsync(string folder)
    {
        var version = _scopeVersion;
        var source = _connection is null ? null : await _connection.GetConnectionAsync();
        EnsureSingleFactoryScope(folder);
        _draftsLoaded = true;
        _draftPollingFailed = true;
        var result = await _deployments.GetProjectDeploymentsAsync(folder);
        if (!IsCurrent(folder, version) || !await IsSameConnectionAsync(source)) return;
        _draftPollingFailed = false;
        if (_drafts.SequenceEqual(result.Drafts) && _factoryVersionSelection == result.VersionSelection &&
            _versionBlockers.SequenceEqual(result.VersionBlockers)) return;
        _draftFolder = folder;
        _drafts = result.Drafts;
        _factoryVersionSelection = result.VersionSelection;
        _versionBlockers = result.VersionBlockers;
        ApplyOverview(_operations.Current);
        var completedJobs = _drafts.Where(draft => draft.Status == "submitted" && !string.IsNullOrWhiteSpace(draft.JobId))
            .Select(draft => $"{folder}|{draft.JobId}").ToArray();
        if (_refresh is not null && completedJobs.Any(job => !_refreshedJobs.Contains(job)))
        {
            foreach (var job in completedJobs) _refreshedJobs.Add(job);
            StatusMessage = "Deployment script completed. Refreshing Azure to confirm the target environment.";
            await _refresh.RefreshAsync();
        }
    }

    private void UpdateDraft(string folder, ProjectDeploymentDraft draft)
    {
        _draftFolder = folder;
        _drafts = _drafts.Where(item => item.Id != draft.Id).Append(draft).ToArray();
        ApplyOverview(_operations.Current);
    }

    private bool CanDeployCard(ProjectEnvironmentCardViewModel? card) => !IsBusy && !IsCatalogScope && card is not null &&
        Cards().Contains(card) && (card.ShowDeployButton || (card.CanDeploy &&
            !Cards().Any(target => target.ProjectNumber == card.ProjectNumber &&
                target.Environment == card.DeploymentTarget && target.HasCard)));

    private bool CanUpdateCard(ProjectEnvironmentCardViewModel? card) =>
        !IsBusy && !IsCatalogScope && card is { CanUpdate: true } && Cards().Contains(card);

    private bool CanReviewOutcomeCard(ProjectEnvironmentCardViewModel? card) =>
        !IsBusy && !IsCatalogScope && card is { CanReviewOutcome: true } && Cards().Contains(card);

    private bool HasCurrentReviewCard() => Cards().Any(card => card.Draft is { } draft && draft.Id == _planDraftId &&
        (IsReconciliationReview
            ? card.CanReviewOutcome && draft.JobId == _planJobId
            : card.CanSubmitDraft && card.Patch == _planPatch && RequestedVersion(card) == _planFactoryVersion &&
              card.IsUpdate == (_reviewKind == ReviewKind.Update)));

    private IEnumerable<ProjectEnvironmentCardViewModel> Cards() =>
        ProjectRows.SelectMany(row => new[] { row.Dev, row.Stage, row.Prod });

    private bool IsCurrent(string folder, long version) =>
        version == _scopeVersion && FactoryNetworkSession.SameFolder(folder, _operations.Folder);

    private async Task<bool> IsSameConnectionAsync(AiFactoryConnection? source) =>
        _connection is null || source == await _connection.GetConnectionAsync();

    public void DismissDeployment()
    {
        _reviewVersion++;
        DeploymentPlan = null;
        _planFolder = _planDraftId = string.Empty;
        _planConnection = null;
        _planJobId = null;
        _planFactoryVersion = null;
        NotifyDeploymentPlan();
    }

    public void NotifyDeploymentActions()
    {
        OnPropertyChanged(nameof(CanConfirmDeployment));
        DeployCommand.ChangeCanExecute();
        UpdateCommand.ChangeCanExecute();
        ReviewOutcomeCommand.ChangeCanExecute();
        OpenTerminalCommand.ChangeCanExecute();
        ConfirmDeploymentCommand.NotifyCanExecuteChanged();
        DismissDeploymentCommand.NotifyCanExecuteChanged();
        RefreshDraftsCommand.NotifyCanExecuteChanged();
    }

    private void NotifyDeploymentPlan()
    {
        foreach (var property in new[] { nameof(DeploymentPlan), nameof(HasDeploymentPlan), nameof(DeploymentScope),
            nameof(DeploymentEffects), nameof(DeploymentWarnings), nameof(DeploymentBlockers), nameof(IsReconciliationReview),
            nameof(DeploymentReviewTitle), nameof(ConfirmDeploymentText), nameof(DeploymentNotice),
            nameof(DeploymentTemplateBranch), nameof(DeploymentTemplateRef) }) OnPropertyChanged(property);
        NotifyDeploymentActions();
    }

    private Command<ProjectEnvironmentCardViewModel> CreateConfigureCommand(string kind) =>
        new(async card =>
        {
            if (IsCatalogScope || card is not { IsDeployed: true } || !Cards().Contains(card))
            {
                StatusMessage = "Choose a deployed project card to configure operations.";
                return;
            }

            await AppShell.PushOperationConfigAsync(
                card.ProjectNumber,
                card.Environment,
                kind);
        });

    private void OnOverviewChanged(object? sender, EventArgs e)
    {
        ApplyOverview(_operations.Current);
        StatusMessage = _operations.Current is null ? MissingFolderMessage
            : BoardSummary;
    }

    private void ApplyOverview(OperationsOverview? overview)
    {
        var sameFolder = FactoryNetworkSession.SameFolder(_draftFolder, _operations.Folder);
        var patchChoices = sameFolder
            ? Cards().Where(card => card.HasCard).ToDictionary(card => (card.ProjectNumber, card.Environment), card => card.Patch)
            : [];
        foreach (var card in Cards()) card.PropertyChanged -= OnCardChanged;
        if (!sameFolder)
        {
            _scopeVersion++;
            _drafts = [];
            _factoryVersionSelection = null;
            _versionBlockers = [];
            _versionEdits.Clear();
            _draftFolder = _operations.Folder;
            _draftsLoaded = false;
            _draftPollingFailed = false;
            DismissDeployment();
        }
        var selected = FactoryNetworkSession.SameFolder(_selectionFolder, _operations.Folder) ? _selectedProject : null;
        _selectedProject = null;
        ProjectRows.Clear();
        foreach (var row in ProjectEnvironmentCardViewModel.BuildRows(overview, _drafts, _factoryVersionSelection))
        {
            ProjectRows.Add(row);
        }
        foreach (var card in Cards())
        {
            if (card.CanEditPatch && patchChoices.TryGetValue((card.ProjectNumber, card.Environment), out var patch))
                card.Patch = patch;
            if (card.HasCard && _versionEdits.TryGetValue((card.ProjectNumber, card.Environment), out var factoryVersion))
                card.RestoreVersionEdit(factoryVersion);
            card.PropertyChanged += OnCardChanged;
        }
        if (selected is not null)
            SelectProject(ProjectRows.SelectMany(row => new[] { row.Dev, row.Stage, row.Prod }).FirstOrDefault(card =>
                card.ProjectNumber == selected.ProjectNumber && card.Environment == selected.Environment));
        OnPropertyChanged(nameof(SelectedProject));
        SourceLabel = overview?.ResourceInventory.Source switch
        {
            "azure" => "Azure inventory",
            "cached" => "Cached Azure inventory",
            _ => "Inventory unavailable"
        };
        Warning = _operations.Warning;
        MissingFolderMessage = _operations.MissingFolderMessage;
        OnPropertyChanged(nameof(HasOverview));
        foreach (var property in new[] { nameof(IsEmpty), nameof(DevCount), nameof(StageCount), nameof(ProdCount), nameof(BoardSummary),
            nameof(StageHeader), nameof(ProdHeader), nameof(DraftCount), nameof(HasRunningDrafts), nameof(NeedsDraftRefresh),
            nameof(FactoryVersionWarnings) })
        {
            OnPropertyChanged(property);
        }
        if (HasDeploymentPlan && !HasCurrentReviewCard())
            DismissDeployment();
        NotifyDeploymentActions();
    }

    private void OnCardChanged(object? sender, PropertyChangedEventArgs e)
    {
        if (e.PropertyName is not (nameof(ProjectEnvironmentCardViewModel.Patch) or nameof(ProjectEnvironmentCardViewModel.FactoryVersion))) return;
        if (e.PropertyName == nameof(ProjectEnvironmentCardViewModel.FactoryVersion) && sender is ProjectEnvironmentCardViewModel card)
            _versionEdits[(card.ProjectNumber, card.Environment)] = card.FactoryVersion;
        DismissDeployment();
        StatusMessage = e.PropertyName == nameof(ProjectEnvironmentCardViewModel.Patch)
            ? "Patch choice changed. Review Deploy or Update again before confirming."
            : "Template version changed. Review Deploy or Update again before confirming.";
    }

    private static string? RequestedVersion(ProjectEnvironmentCardViewModel card) =>
        string.IsNullOrWhiteSpace(card.FactoryVersion) ? null : card.FactoryVersion.Trim();

    private static string EnvironmentHeader(string name, int deployed, int drafts) =>
        drafts == 0 ? $"{name} ({deployed})" : $"{name} ({deployed} deployed, {drafts} draft)";

    private static string Lines(IEnumerable<string>? values) =>
        string.Join(Environment.NewLine, (values ?? []).Select(value => $"- {value}"));

    private string RequireFolder()
    {
        var folder = _operations.Folder;
        EnsureSingleFactoryScope(folder);
        return string.IsNullOrWhiteSpace(folder)
            ? throw new InvalidOperationException(OperationsPresentation.MissingFolderMessage)
            : folder;
    }

    private bool IsCatalogScope => _isCatalogScope?.Invoke(_operations.Folder) == true;

    private void EnsureSingleFactoryScope(string folder)
    {
        if (_isCatalogScope?.Invoke(folder) != true) return;
        DismissDeployment();
        throw new InvalidOperationException("This folder is a factory catalog or its single-factory scope is unverified. Open Factory Manager; legacy project actions cannot target an unverified root.");
    }
}

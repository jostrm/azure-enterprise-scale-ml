using System.ComponentModel;
using System.Globalization;
using System.Net;
using System.Runtime.CompilerServices;
using System.Security.Cryptography;
using System.Text;
using System.Text.Json;
using ESAIF.BaseLayer.Application;
using ESAIF.BaseLayer.Networking;
using ESAIF.ConfigWizard.Services;
using ESAIF.DomainLayer.Configuration;

namespace ESAIF.ConfigWizard.ViewModels;

public sealed class SimpleFactoryViewModel : OperationViewModel, IDisposable
{
    private readonly ISimpleFactoryClient _client;
    private readonly AzureAuthenticationMonitor? _authentication;
    private readonly IAiFactoryConnectionProvider? _connection;
    private readonly TimeProvider _clock;
    private readonly HashSet<string> _edited = [];
    private readonly Dictionary<string, bool> _resourceEdits = new(StringComparer.Ordinal);
    private CancellationTokenSource? _visible;
    private bool _isRefreshing;
    private bool _applyingDefaults, _loaded, _optionsReady, _submitted, _submissionUncertain, _disposed;
    private bool _publishingOptions;
    private long _revision;
    private string _identity = string.Empty, _source = string.Empty, _jobSource = string.Empty;
    private string _monitorIdentity = string.Empty;
    private SimpleFactoryDraft? _backendDefaults;
    private SimpleFactoryResourceCatalog? _resourceCatalog;
    private IReadOnlyList<string> _plannedProjectResources = [];
    private string _catalogChangeNotice = string.Empty;
    private SimpleFactoryAzureAccount? _selectedAccount;
    private string _location = "swedencentral", _factoryPrefix = "aif-", _githubRepository = string.Empty;
    private string _teamMemberEmail = string.Empty, _teamGroupName = string.Empty, _costCenter = "123456", _repoRoot = string.Empty;
    private bool _showAdditionalOptions, _showTechnicalDetails, _showMoreInfo;
    private string _monitoringError = string.Empty;
    private string _defaultNameWarning = string.Empty;
    private string _githubVisibility = "private";
    private string _factoryVersion = "124";
    private string _appGatewayHostname = string.Empty, _appGatewayBackendFqdn = string.Empty, _appGatewayCertificateSecretId = string.Empty;

    public SimpleFactoryViewModel(ISimpleFactoryClient client, AzureAuthenticationMonitor? authentication = null,
        IAiFactoryConnectionProvider? connection = null, TimeProvider? clock = null)
    {
        _client = client;
        _authentication = authentication;
        _connection = connection;
        _clock = clock ?? TimeProvider.System;
        PrepareCommand = new AsyncCommand(() => PrepareAsync(VisibleToken), () => CanPrepare);
        ConfirmCommand = new AsyncCommand(ConfirmAsync, () => CanConfirm);
        ReloadCommand = new AsyncCommand(() => LoadOptionsAsync(VisibleToken), () => !IsBusy);
        DismissPlanCommand = new AsyncCommand(() => { InvalidatePlan(); return Task.CompletedTask; }, () => !IsBusy && HasPlan);
        RefreshJobCommand = new AsyncCommand(() => RefreshJobAsync(VisibleToken), () => !IsBusy && !_isRefreshing && HasJob);
        ToggleMoreInfoCommand = new AsyncCommand(() =>
        {
            ShowMoreInfo = !ShowMoreInfo;
            return Task.CompletedTask;
        });
        PropertyChanged += OnStateChanged;
        if (_authentication is not null)
        {
            _monitorIdentity = MonitorIdentity();
            _authentication.PropertyChanged += OnAuthenticationChanged;
        }
    }

    public AsyncCommand PrepareCommand { get; }
    public AsyncCommand ConfirmCommand { get; }
    public AsyncCommand ReloadCommand { get; }
    public AsyncCommand DismissPlanCommand { get; }
    public AsyncCommand RefreshJobCommand { get; }
    public AsyncCommand ToggleMoreInfoCommand { get; }
    public IReadOnlyList<SimpleFactoryAzureAccount> Accounts { get; private set; } = [];
    public IReadOnlyList<string> Regions { get; private set; } = ["swedencentral"];
    public IReadOnlyList<string> GithubVisibilities { get; } = ["private", "public"];
    public IReadOnlyList<SimpleFactoryResourceChoice> ProjectResources { get; private set; } = [];
    public bool HasResourceCatalog => CatalogAvailable(_resourceCatalog);
    public bool HasPlanResourceCatalog => CatalogAvailable(Plan?.ResourceCatalog);
    public string HubResources => DescribeResources(_resourceCatalog?.Hub);
    public string CommonResources => DescribeResources(_resourceCatalog?.Common);
    public string ResourceSelectionWarning => string.Join(Environment.NewLine,
        new[] { _catalogChangeNotice }.Where(value => !string.IsNullOrEmpty(value)).Concat(ResourceSelectionIssues()));
    public bool HasResourceSelectionIssues => ResourceSelectionIssues().Any();
    public bool RequiresApplicationGatewaySettings => _resourceCatalog?.Hub.Any(resource =>
        resource.Id == "application-gateway" && resource.Required) == true;
    public string PlanHubResources => DescribeResources(Plan?.ResourceCatalog?.Hub);
    public string PlanCommonResources => DescribeResources(Plan?.ResourceCatalog?.Common);
    public string PlanProjectResources => DescribeResources(Plan?.ResourceCatalog?.Project, _plannedProjectResources);
    public string GithubAccount { get; private set; } = string.Empty;
    public string OptionsRequirements { get; private set; } = string.Empty;
    public string OptionsWarnings { get; private set; } = string.Empty;
    public string ScriptPath { get; private set; } = string.Empty;
    public SimpleFactoryPlan? Plan { get; private set; }
    public string PlanTemplateBranch => string.IsNullOrWhiteSpace(Plan?.Branch) ? "Not resolved by the API" : Plan.Branch;
    public string PlanTemplateRef => Plan?.ResolvedRef ?? string.Empty;
    public SimpleFactoryJob? Job { get; private set; }
    public string JobOwner { get; private set; } = string.Empty;
    public string JobId => Job?.Id ?? string.Empty;
    public bool HasJob => Job is not null;
    public bool HasPlan => Plan is not null;
    public bool HasActiveJob => Job is { IsTerminal: false };
    public bool CanEdit => !IsBusy && !HasActiveJob && !_submissionUncertain;
    public bool CanPrepare => CanEdit && _optionsReady && SelectedAccount is not null && !string.IsNullOrWhiteSpace(FactoryVersion);
    public bool CanConfirm => !IsBusy && !_submitted && !_submissionUncertain && !HasActiveJob &&
        _optionsReady && Plan is { CanExecute: true, Blockers.Count: 0 } &&
        !string.IsNullOrWhiteSpace(Plan.ConfirmationId) && PlanHasValidExpiry &&
        !HasResourceSelectionIssues && !PlanResourceIssues().Any();
    public bool PlanHasValidExpiry => Plan is not null &&
        DateTimeOffset.TryParse(Plan.ExpiresAt, CultureInfo.InvariantCulture,
            DateTimeStyles.AssumeUniversal, out var expires) && expires > _clock.GetUtcNow();
    public string PlanExpiry => !HasPlan ? string.Empty : PlanHasValidExpiry
        ? $"Confirmation expires: {Plan!.ExpiresAt}"
        : "This preview has expired or has an unknown expiry. Review creation again; nothing will start.";
    public string PlanBlockers => Bullets((Plan?.Blockers ?? []).Concat(ResourceSelectionIssues()).Concat(PlanResourceIssues()));
    public bool HasBlockers => Plan is not null &&
        (Plan.Blockers.Count > 0 || !Plan.CanExecute || HasResourceSelectionIssues || PlanResourceIssues().Any());
    public string PlanEffects => Bullets(Plan?.Effects ?? []);
    public string PlanRequirements => Bullets(Plan?.Requirements ?? []);
    public string PlanWarnings => Bullets(Plan?.Warnings ?? []);
    public string PlanEnvironment => string.Join(Environment.NewLine,
        (Plan?.Environment ?? new Dictionary<string, string>()).OrderBy(item => item.Key, StringComparer.Ordinal)
            .Select(item => $"{item.Key}={item.Value}"));
    public string PlanScope { get; private set; } = string.Empty;
    public string MonitoringError { get => _monitoringError; private set => SetProperty(ref _monitoringError, value); }
    public string DefaultNameWarning { get => _defaultNameWarning; private set => SetProperty(ref _defaultNameWarning, value); }
    public string JobEvents => string.Join(Environment.NewLine, Job?.Events ?? []);
    public string JobExit => Job?.ExitCode is int code ? $"Exit code: {code}" : "Exit code: not reported";
    public bool JobNeedsAttention => Job?.Status is "failed" or "interrupted";
    public bool CanOpenRepository => Job?.Status == "succeeded" &&
        Uri.TryCreate(Job.RepositoryUrl, UriKind.Absolute, out var uri) &&
        uri.Scheme == Uri.UriSchemeHttps && string.IsNullOrEmpty(uri.UserInfo) &&
        uri.Host.Equals("github.com", StringComparison.OrdinalIgnoreCase);
    public string AzureAccount => SelectedAccount?.AccountName ?? "Select an authenticated subscription";
    public string TenantId => SelectedAccount?.TenantId ?? string.Empty;
    public bool ShowAdditionalOptions { get => _showAdditionalOptions; set => SetProperty(ref _showAdditionalOptions, value); }
    public bool ShowTechnicalDetails { get => _showTechnicalDetails; set => SetProperty(ref _showTechnicalDetails, value); }
    public bool ShowMoreInfo
    {
        get => _showMoreInfo;
        set
        {
            if (SetProperty(ref _showMoreInfo, value))
                OnPropertyChanged(nameof(MoreInfoLabel));
        }
    }
    public string MoreInfoLabel => ShowMoreInfo ? "⌄ More info" : "› More info";
    public SimpleFactoryAzureAccount? SelectedAccount
    {
        get => _selectedAccount;
        set
        {
            // Native picker resets may arrive after the ItemsSource notification has completed.
            if (_publishingOptions || value is null || !Accounts.Contains(value)) return;
            if (!SetProperty(ref _selectedAccount, value)) return;
            Edited(nameof(SelectedAccount));
            OnPropertyChanged(nameof(TenantId));
            OnPropertyChanged(nameof(AzureAccount));
            if (!_edited.Contains(nameof(TeamMemberEmail)) && value is not null)
                ApplyDefault(nameof(TeamMemberEmail), () => TeamMemberEmail = value.AccountName);
        }
    }
    public string Location
    {
        get => _location;
        set { if (value is not null) SetDraft(ref _location, value); }
    }
    public string FactoryPrefix
    {
        get => _factoryPrefix;
        set { if (SetDraft(ref _factoryPrefix, value) && !_applyingDefaults) RefreshDerivedNames(); }
    }
    public string GithubRepository
    {
        get => _githubRepository;
        set { if (SetDraft(ref _githubRepository, value) && !_applyingDefaults) RefreshDerivedRoot(); }
    }
    public string TeamMemberEmail { get => _teamMemberEmail; set => SetDraft(ref _teamMemberEmail, value); }
    public string TeamGroupName { get => _teamGroupName; set => SetDraft(ref _teamGroupName, value); }
    public string CostCenter { get => _costCenter; set => SetDraft(ref _costCenter, value); }
    public string RepoRoot { get => _repoRoot; set => SetDraft(ref _repoRoot, value); }
    public string FactoryVersion { get => _factoryVersion; set => SetDraft(ref _factoryVersion, value); }
    public string GithubVisibility
    {
        get => _githubVisibility;
        set
        {
            if (value is not null && GithubVisibilities.Contains(value) && SetDraft(ref _githubVisibility, value))
                OnPropertyChanged(nameof(IsPublicRepository));
        }
    }
    public bool IsPublicRepository => GithubVisibility == "public";
    public string AppGatewayHostname
    {
        get => _appGatewayHostname;
        set { if (SetDraft(ref _appGatewayHostname, value)) NotifyResourceSelection(); }
    }
    public string AppGatewayBackendFqdn
    {
        get => _appGatewayBackendFqdn;
        set { if (SetDraft(ref _appGatewayBackendFqdn, value)) NotifyResourceSelection(); }
    }
    public string AppGatewayCertificateSecretId
    {
        get => _appGatewayCertificateSecretId;
        set { if (SetDraft(ref _appGatewayCertificateSecretId, value)) NotifyResourceSelection(); }
    }
    private CancellationToken VisibleToken => _visible?.Token ?? CancellationToken.None;

    public async Task LoadOptionsAsync(CancellationToken cancellationToken = default)
    {
        if (IsBusy) return;
        InvalidatePlan();
        _optionsReady = false;
        NotifyActions();
        await ExecuteOperationAsync(async () =>
        {
            try
            {
                var revision = _revision;
                var source = await SourceAsync(cancellationToken);
                var options = await _client.GetSimpleFactoryOptionsAsync(cancellationToken);
                cancellationToken.ThrowIfCancellationRequested();
                if (revision != _revision) return;
                var identity = OptionsIdentity(options);
                var identityChanged = _loaded && (_identity != identity || _source != source);
                _identity = identity;
                _source = source;
                Accounts = options.AzureAccounts;
                Regions = options.Regions;
                GithubAccount = options.GithubAccount;
                ScriptPath = options.ScriptPath;
                OptionsRequirements = Bullets(options.Requirements);
                OptionsWarnings = Bullets(options.Warnings);
                var selected = SelectedAccount;
                _selectedAccount = _edited.Contains(nameof(SelectedAccount))
                    ? Accounts.FirstOrDefault(item => item.SubscriptionId == selected?.SubscriptionId &&
                        item.TenantId == selected?.TenantId)
                    : Accounts.FirstOrDefault(item => item.SubscriptionId == options.Defaults.SubscriptionId &&
                        item.TenantId == options.Defaults.TenantId);
                var defaults = _backendDefaults = options.Defaults;
                var location = _edited.Contains(nameof(Location)) ? _location : defaults.Location;
                _location = Regions.Contains(location) ? location : string.Empty;
                ApplyDefault(nameof(FactoryPrefix), () => FactoryPrefix = defaults.FactoryPrefix);
                ApplyDefault(nameof(FactoryVersion), () => FactoryVersion =
                    string.IsNullOrWhiteSpace(defaults.FactoryVersion) ? "124" : defaults.FactoryVersion);
                ApplyDefault(nameof(GithubRepository), () => GithubRepository = defaults.GithubRepository);
                ApplyDefault(nameof(TeamMemberEmail), () => TeamMemberEmail =
                    SelectedAccount is not null && SelectedAccount.SubscriptionId != defaults.SubscriptionId
                        ? SelectedAccount.AccountName : defaults.TeamMemberEmail);
                ApplyDefault(nameof(TeamGroupName), () => TeamGroupName = defaults.TeamGroupName);
                ApplyDefault(nameof(CostCenter), () => CostCenter = defaults.CostCenter);
                ApplyDefault(nameof(RepoRoot), () => RepoRoot = defaults.RepoRoot);
                // Public visibility requires an explicit user choice, never a changed server default.
                ApplyDefault(nameof(GithubVisibility), () => GithubVisibility = "private");
                ApplyDefault(nameof(AppGatewayHostname), () => AppGatewayHostname = defaults.AppGatewayHostname);
                ApplyDefault(nameof(AppGatewayBackendFqdn), () => AppGatewayBackendFqdn = defaults.AppGatewayBackendFqdn);
                ApplyDefault(nameof(AppGatewayCertificateSecretId), () => AppGatewayCertificateSecretId = defaults.AppGatewayCertificateSecretId);
                ApplyResourceCatalog(options.ResourceCatalog);
                if (_edited.Contains(nameof(FactoryPrefix))) RefreshDerivedNames();
                else if (_edited.Contains(nameof(GithubRepository))) RefreshDerivedRoot();
                _loaded = _optionsReady = true;
                // Native pickers can echo a null selection while replacing ItemsSource.
                _publishingOptions = true;
                try
                {
                    foreach (var property in new[] { nameof(Accounts), nameof(Regions), nameof(SelectedAccount),
                        nameof(Location), nameof(GithubAccount), nameof(ScriptPath), nameof(OptionsRequirements),
                        nameof(OptionsWarnings), nameof(AzureAccount), nameof(TenantId) })
                        OnPropertyChanged(property);
                }
                finally { _publishingOptions = false; }
                Warning = identityChanged
                    ? "Sign-in or API host changed. The old preview was discarded; your edited fields were kept. Check the destination and team before reviewing again."
                    : string.Empty;
                StatusMessage = "Defaults loaded from the Python API. Review creation before anything is provisioned.";
            }
            catch (OperationCanceledException) when (cancellationToken.IsCancellationRequested) { }
        }, "Reading cached Azure and GitHub sign-ins…");
    }

    public async Task PrepareAsync(CancellationToken cancellationToken = default)
    {
        if (!CanPrepare) return;
        InvalidatePlan();
        await ExecuteOperationAsync(async () =>
        {
            try
            {
                if (!await SourceMatchesAsync(_source, cancellationToken)) return;
                var revision = _revision;
                var draft = Draft();
                var result = await _client.PrepareSimpleFactoryAsync(draft, cancellationToken);
                cancellationToken.ThrowIfCancellationRequested();
                if (revision != _revision) return;
                Plan = result;
                _plannedProjectResources = draft.ProjectResources;
                _submitted = false;
                PlanScope = $"Azure user: {AzureAccount}\nTenant: {draft.TenantId}\nExisting Dev subscription: {draft.SubscriptionId}" +
                    $"\nRegion: {draft.Location}\nFactory prefix: {draft.FactoryPrefix}\nGitHub account: {GithubAccount}" +
                    $"\nGitHub repository: {draft.GithubRepository}\nRepository visibility: {draft.GithubVisibility}" +
                    "\nAzure networking: private configuration is unchanged by repository visibility" +
                    $"\nTeam member: {draft.TeamMemberEmail}" +
                    $"\nNew Entra group: {draft.TeamGroupName}\nCost center: {draft.CostCenter}" +
                    $"\nDestination on Python API host: {draft.RepoRoot}";
                if (RequiresApplicationGatewaySettings)
                    PlanScope += $"\nApplication Gateway frontend hostname: {draft.AppGatewayHostname}" +
                        $"\nApplication Gateway backend FQDN: {draft.AppGatewayBackendFqdn}" +
                        $"\nKey Vault certificate secret URI: {draft.AppGatewayCertificateSecretId}";
                NotifyPlan();
                StatusMessage = HasBlockers ? "Creation is blocked. Resolve every blocker and review again."
                    : "Review the effects, permissions, costs and exact plan below. Nothing has started.";
            }
            catch (OperationCanceledException) when (cancellationToken.IsCancellationRequested) { }
        }, "Preparing a local, read-only creation preview…");
    }

    public async Task ConfirmAsync()
    {
        if (!CanConfirm) { NotifyPlan(); return; }
        await ExecuteOperationAsync(async () =>
        {
            if (!await SourceMatchesAsync(_source, CancellationToken.None) || !PlanHasValidExpiry ||
                Plan is not { CanExecute: true, Blockers.Count: 0 } ||
                HasResourceSelectionIssues || PlanResourceIssues().Any()) return;
            var confirmationId = Plan.ConfirmationId;
            _submitted = true;
            _submissionUncertain = true;
            JobOwner = $"Azure: {AzureAccount} · tenant {TenantId} · GitHub: {GithubAccount}";
            _jobSource = _source;
            NotifyActions();
            // Submission is not cancelled when the page closes: cancellation cannot undo server-side effects.
            SimpleFactoryJob job;
            try { job = await _client.StartSimpleFactoryAsync(confirmationId); }
            catch (ApiRequestException error) when (error.StatusCode is HttpStatusCode.BadRequest or
                HttpStatusCode.Unauthorized or HttpStatusCode.Forbidden or HttpStatusCode.NotFound or
                HttpStatusCode.Conflict or HttpStatusCode.Gone or HttpStatusCode.UnprocessableEntity)
            {
                _submissionUncertain = false;
                if (error.StatusCode is HttpStatusCode.Unauthorized or HttpStatusCode.Forbidden) InvalidateIdentity();
                else InvalidatePlan();
                Warning = "The server rejected this confirmation. Resolve the reported issue and review a new plan; reload sign-ins if authentication changed.";
                throw;
            }
            if (string.IsNullOrWhiteSpace(job.Id))
                throw new InvalidDataException("The API did not return a job ID. Inspect the backend before attempting another creation.");
            _submissionUncertain = false;
            ApplyJob(job);
            StatusMessage = "Creation submitted. Leaving this page does not cancel deployment. Reopen Simple Mode to resume monitoring.";
        }, "Submitting the explicitly confirmed creation…");
        if (_submissionUncertain)
            Warning = "Submission could not be confirmed. It may already have created resources. Do not blindly rerun; inspect the Python API's job records and cloud resources first.";
    }

    public async Task ActivateAsync()
    {
        ObjectDisposedException.ThrowIf(_disposed, this);
        Deactivate();
        var visible = _visible = new CancellationTokenSource();
        var token = visible.Token;
        try
        {
            var needsInitialLoad = !_loaded;
            if (_loaded) await CheckSourceOnReopenAsync(token);
            while (!token.IsCancellationRequested)
            {
                if (needsInitialLoad && !IsBusy)
                {
                    needsInitialLoad = false;
                    await LoadOptionsAsync(token);
                }
                NotifyPlan();
                if (HasActiveJob && !IsBusy) await RefreshJobAsync(token);
                await Task.Delay(TimeSpan.FromSeconds(4), _clock, token);
            }
        }
        catch (OperationCanceledException) when (token.IsCancellationRequested) { }
        finally
        {
            if (ReferenceEquals(_visible, visible)) _visible = null;
            visible.Dispose();
        }
    }

    public void Deactivate() => _visible?.Cancel();

    public async Task RefreshJobAsync(CancellationToken cancellationToken = default)
    {
        if (Job is null || _isRefreshing) return;
        _isRefreshing = true;
        RefreshJobCommand.NotifyCanExecuteChanged();
        var id = Job.Id;
        try
        {
            if (!await SourceMatchesAsync(_jobSource, cancellationToken))
            {
                MonitoringError = "API connection changed. Switch back to the original API host and credentials to monitor this job.";
                return;
            }
            var result = await _client.GetSimpleFactoryJobAsync(id, cancellationToken);
            cancellationToken.ThrowIfCancellationRequested();
            if (Job?.Id != id) return;
            if (result.Id != id) throw new InvalidDataException("The API returned a different job ID.");
            MonitoringError = string.Empty;
            ApplyJob(result);
        }
        catch (OperationCanceledException) when (cancellationToken.IsCancellationRequested) { }
        catch (Exception error) when (error is ApiRequestException or HttpRequestException or IOException or JsonException or OperationCanceledException)
        {
            MonitoringError = $"Monitoring paused: {error.Message} The last known job is retained; deployment may continue. Check sign-in/connection and refresh status, not creation.";
        }
        finally
        {
            _isRefreshing = false;
            RefreshJobCommand.NotifyCanExecuteChanged();
        }
    }

    public void InvalidateIdentity()
    {
        _optionsReady = false;
        InvalidatePlan();
        Warning = "Authentication changed. Reload sign-ins before reviewing creation. Existing job identity and last known status are retained.";
    }

    private void ApplyJob(SimpleFactoryJob job)
    {
        Job = job;
        foreach (var property in new[] { nameof(Job), nameof(JobId), nameof(HasJob), nameof(HasActiveJob),
            nameof(JobOwner), nameof(JobEvents), nameof(JobExit), nameof(JobNeedsAttention), nameof(CanOpenRepository) })
            OnPropertyChanged(property);
        NotifyActions();
    }

    private SimpleFactoryDraft Draft() => new()
    {
        SubscriptionId = SelectedAccount!.SubscriptionId, TenantId = TenantId, Location = Location,
        FactoryPrefix = FactoryPrefix, GithubRepository = GithubRepository, TeamMemberEmail = TeamMemberEmail,
        FactoryVersion = FactoryVersion.Trim(),
        TeamGroupName = TeamGroupName, CostCenter = CostCenter, RepoRoot = RepoRoot,
        GithubVisibility = GithubVisibility,
        ProjectResources = ProjectResources.Where(resource => resource.IsSelected && !resource.IsRequired)
            .Select(resource => resource.Id).ToArray(),
        AppGatewayHostname = AppGatewayHostname, AppGatewayBackendFqdn = AppGatewayBackendFqdn,
        AppGatewayCertificateSecretId = AppGatewayCertificateSecretId
    };

    private void ApplyResourceCatalog(SimpleFactoryResourceCatalog? catalog)
    {
        var nextIds = (catalog?.Project ?? []).Select(resource => resource.Id).ToHashSet(StringComparer.Ordinal);
        var notices = new List<string>();
        if (catalog is not null)
        {
            notices.AddRange(ProjectResources.Where(resource => resource.IsSelected && !nextIds.Contains(resource.Id))
                .Select(resource => $"{resource.Label} was removed from the backend catalog; its selection was dropped."));
            foreach (var id in _resourceEdits.Keys.Where(id => !nextIds.Contains(id)).ToArray()) _resourceEdits.Remove(id);
        }
        _resourceCatalog = catalog;
        var all = AllResources(catalog).ToArray();
        ProjectResources = (catalog?.Project ?? []).Select(resource =>
        {
            var selected = _resourceEdits.TryGetValue(resource.Id, out var edited) ? edited : resource.DefaultSelected;
            if (resource.Required && !selected && _resourceEdits.Remove(resource.Id))
                notices.Add($"{resource.Label} is now required by the backend and remains included.");
            var guidance = resource.Dependencies.Count == 0 ? string.Empty :
                $"Requires: {string.Join(", ", resource.Dependencies.Select(id => all.FirstOrDefault(item => item.Id == id)?.Label ?? id))}. " +
                (resource.Required ? "Select the dependencies; this resource is required." : "Select the dependencies or uncheck this optional resource.");
            return new SimpleFactoryResourceChoice(resource, selected, guidance, OnResourceSelectionChanged);
        }).ToArray();
        _catalogChangeNotice = string.Join(Environment.NewLine, notices);
        foreach (var property in new[] { nameof(ProjectResources), nameof(HubResources), nameof(CommonResources),
            nameof(HasResourceCatalog), nameof(RequiresApplicationGatewaySettings) }) OnPropertyChanged(property);
        NotifyResourceSelection();
    }

    private void OnResourceSelectionChanged(SimpleFactoryResourceChoice resource)
    {
        if (!ProjectResources.Contains(resource)) return;
        _resourceEdits[resource.Id] = resource.IsSelected;
        Edited(nameof(ProjectResources));
        NotifyResourceSelection();
    }

    private void NotifyResourceSelection()
    {
        OnPropertyChanged(nameof(ResourceSelectionWarning));
        OnPropertyChanged(nameof(HasResourceSelectionIssues));
        NotifyPlan();
    }

    private IEnumerable<string> ResourceSelectionIssues()
    {
        if (!HasResourceCatalog)
        {
            yield return "Resource metadata is unavailable. Reload the backend catalog before confirming; no resources are inferred.";
            yield break;
        }
        if (ProjectResources.Any(resource => string.IsNullOrWhiteSpace(resource.Id)) ||
            ProjectResources.Select(resource => resource.Id).Distinct(StringComparer.Ordinal).Count() != ProjectResources.Count)
            yield return "The backend project catalog has missing or duplicate resource IDs. Reload a corrected catalog before confirming.";
        if (RequiresApplicationGatewaySettings)
        {
            if (string.IsNullOrWhiteSpace(AppGatewayHostname))
                yield return "Application Gateway frontend hostname is required.";
            if (string.IsNullOrWhiteSpace(AppGatewayBackendFqdn))
                yield return "Application Gateway backend FQDN is required.";
            if (string.IsNullOrWhiteSpace(AppGatewayCertificateSecretId))
                yield return "Application Gateway versionless Key Vault certificate secret URI is required.";
        }
        var selected = (_resourceCatalog!.Hub.Concat(_resourceCatalog.Common)
                .Where(resource => resource.Required || resource.DefaultSelected).Select(resource => resource.Id))
            .Concat(ProjectResources.Where(resource => resource.IsSelected).Select(resource => resource.Id))
            .ToHashSet(StringComparer.Ordinal);
        var all = AllResources(_resourceCatalog).ToArray();
        foreach (var resource in ProjectResources.Where(resource => resource.IsSelected))
            foreach (var dependency in resource.Resource.Dependencies.Where(id => !selected.Contains(id)))
                yield return $"{resource.Label} requires {all.FirstOrDefault(item => item.Id == dependency)?.Label ?? dependency}. " +
                    (resource.IsRequired ? "Select the dependency; this resource is required." :
                        "Select the dependency or uncheck the dependent optional resource; nothing is automatically re-enabled.");
    }

    private IEnumerable<string> PlanResourceIssues()
    {
        if (Plan is null) yield break;
        if (!CatalogAvailable(Plan.ResourceCatalog))
        {
            yield return "The creation preview has no resource catalog. The backend must describe the actual hub, common and project resources before confirmation.";
            yield break;
        }
        var described = Plan.ResourceCatalog!.Project.Select(resource => resource.Id).ToHashSet(StringComparer.Ordinal);
        var expected = _plannedProjectResources.Concat((_resourceCatalog?.Project ?? [])
            .Where(resource => resource.Required).Select(resource => resource.Id));
        if (expected.Any(id => !described.Contains(id)))
            yield return "The preview does not describe every selected or required project resource. Review again against the current backend catalog.";
    }

    private static bool CatalogAvailable(SimpleFactoryResourceCatalog? catalog) =>
        catalog is not null && AllResources(catalog).Any();
    private static IEnumerable<SimpleFactoryResource> AllResources(SimpleFactoryResourceCatalog? catalog) =>
        catalog is null ? [] : catalog.Hub.Concat(catalog.Common).Concat(catalog.Project);
    private static string DescribeResources(IReadOnlyList<SimpleFactoryResource>? resources,
        IReadOnlyList<string>? selection = null)
    {
        if (resources is null || resources.Count == 0) return string.Empty;
        return Bullets(resources.Select(resource =>
        {
            var selected = resource.Required || (selection?.Contains(resource.Id) ?? resource.DefaultSelected);
            return $"{resource.Label} · {(selected ? resource.Required ? "Required" : "Included" : "Not selected")}" +
                (string.IsNullOrWhiteSpace(resource.Description) ? string.Empty : $"\n  {resource.Description}");
        }));
    }

    private bool SetDraft(ref string field, string? value, [CallerMemberName] string property = "")
    {
        if (_publishingOptions || !SetProperty(ref field, value ?? string.Empty, property)) return false;
        Edited(property);
        return true;
    }
    private void RefreshDerivedNames()
    {
        if (_backendDefaults is null) return;
        var prefix = FactoryPrefix.Trim();
        var isBackendPrefix = prefix == _backendDefaults.FactoryPrefix.Trim();
        ApplyDefault(nameof(TeamGroupName), () => TeamGroupName = isBackendPrefix
            ? _backendDefaults.TeamGroupName : $"{prefix}prj001-team");
        var owner = GithubAccount.Trim();
        ApplyDefault(nameof(GithubRepository), () => GithubRepository = isBackendPrefix
            ? _backendDefaults.GithubRepository
            : string.IsNullOrEmpty(owner) ? string.Empty : $"{owner}/{prefix.TrimEnd('-')}aifactory-001");
        RefreshDerivedRoot();
    }
    private void RefreshDerivedRoot()
    {
        DefaultNameWarning = string.Empty;
        if (_backendDefaults is null || _edited.Contains(nameof(RepoRoot))) return;
        if (GithubRepository == _backendDefaults.GithubRepository)
        {
            ApplyDefault(nameof(RepoRoot), () => RepoRoot = _backendDefaults.RepoRoot);
            return;
        }
        var segments = GithubRepository.Trim().Split('/');
        var name = segments.Length == 2 ? segments[1] : string.Empty;
        var root = _backendDefaults.RepoRoot.TrimEnd('\\', '/');
        var separator = Math.Max(root.LastIndexOf('\\'), root.LastIndexOf('/'));
        var absolute = root.StartsWith('/') || root.StartsWith(@"\\") ||
            (root.Length > 2 && char.IsLetter(root[0]) && root[1] == ':' && root[2] is '\\' or '/');
        if (!absolute || separator < 0 || string.IsNullOrWhiteSpace(name) || name is "." or ".." ||
            name.Any(character => !(char.IsAsciiLetterOrDigit(character) || character is '-' or '_' or '.')))
        {
            DefaultNameWarning = "The destination could not be derived safely from the backend default. Review the folder in Additional options before creating.";
            return;
        }
        // Preserve the backend host's path syntax, even when it differs from this device's OS.
        ApplyDefault(nameof(RepoRoot), () => RepoRoot = root[..(separator + 1)] + name);
    }
    private void Edited(string property)
    {
        if (!_applyingDefaults) _edited.Add(property);
        InvalidatePlan();
    }
    private void ApplyDefault(string property, Action action)
    {
        if (_edited.Contains(property)) return;
        var previous = _applyingDefaults;
        _applyingDefaults = true;
        try { action(); }
        finally { _applyingDefaults = previous; }
    }
    private void InvalidatePlan()
    {
        _revision++;
        Plan = null;
        _plannedProjectResources = [];
        PlanScope = string.Empty;
        NotifyPlan();
    }
    private void NotifyPlan()
    {
        foreach (var property in new[] { nameof(Plan), nameof(HasPlan), nameof(PlanScope), nameof(PlanEffects),
            nameof(PlanBlockers), nameof(HasBlockers), nameof(PlanRequirements), nameof(PlanWarnings),
            nameof(PlanEnvironment), nameof(PlanExpiry), nameof(PlanHasValidExpiry), nameof(PlanTemplateBranch), nameof(PlanTemplateRef),
            nameof(HasPlanResourceCatalog) })
            OnPropertyChanged(property);
        OnPropertyChanged(nameof(PlanHubResources));
        OnPropertyChanged(nameof(PlanCommonResources));
        OnPropertyChanged(nameof(PlanProjectResources));
        DismissPlanCommand.NotifyCanExecuteChanged();
        NotifyActions();
    }
    private void NotifyActions()
    {
        OnPropertyChanged(nameof(CanEdit));
        OnPropertyChanged(nameof(CanPrepare));
        OnPropertyChanged(nameof(CanConfirm));
        PrepareCommand.NotifyCanExecuteChanged();
        ConfirmCommand.NotifyCanExecuteChanged();
        RefreshJobCommand.NotifyCanExecuteChanged();
    }
    private void OnStateChanged(object? sender, PropertyChangedEventArgs args)
    {
        if (args.PropertyName != nameof(IsBusy)) return;
        NotifyActions();
        ReloadCommand.NotifyCanExecuteChanged();
        DismissPlanCommand.NotifyCanExecuteChanged();
    }
    private void OnAuthenticationChanged(object? sender, PropertyChangedEventArgs args)
    {
        if (args.PropertyName != nameof(AzureAuthenticationMonitor.Status)) return;
        var identity = MonitorIdentity();
        if (identity == _monitorIdentity) return;
        _monitorIdentity = identity;
        InvalidateIdentity();
    }
    private string MonitorIdentity() => _authentication is null ? string.Empty :
        JsonSerializer.Serialize(new { _authentication.Status.IsLoggedIn, _authentication.Status.AccountName,
            _authentication.Status.TenantId, Tenants = _authentication.Status.Tenants
                .OrderBy(item => item.TenantId).Select(item => new { item.TenantId, item.AccountName, item.NeedsLogin }) });
    private static string OptionsIdentity(SimpleFactoryOptions options) =>
        JsonSerializer.Serialize(new { options.GithubAccount, Accounts = options.AzureAccounts
            .OrderBy(item => item.SubscriptionId).Select(item => new { item.SubscriptionId, item.TenantId, item.AccountName }) });
    private async Task<string> SourceAsync(CancellationToken token)
    {
        if (_connection is null) return string.Empty;
        var source = await _connection.GetConnectionAsync(token);
        return Convert.ToHexString(SHA256.HashData(Encoding.UTF8.GetBytes($"{source.BaseAddress}\n{source.ApiKey}")));
    }
    private async Task<bool> SourceMatchesAsync(string expected, CancellationToken token)
    {
        if (await SourceAsync(token) == expected) return true;
        InvalidateIdentity();
        Warning = "API host or credentials changed. Reload sign-ins and review a new plan. The existing job belongs to its original API host.";
        return false;
    }
    private async Task CheckSourceOnReopenAsync(CancellationToken token)
    {
        try { await SourceMatchesAsync(_source, token); }
        catch (OperationCanceledException) when (token.IsCancellationRequested) { }
        catch (Exception error) when (error is HttpRequestException or IOException or JsonException or OperationCanceledException)
        {
            InvalidateIdentity();
            MonitoringError = $"The API connection could not be checked: {error.Message}";
        }
    }
    private static string Bullets(IEnumerable<string> items) =>
        string.Join(Environment.NewLine, items.Select(item => $"• {item}"));

    public void Dispose()
    {
        if (_disposed) return;
        _disposed = true;
        Deactivate();
        PropertyChanged -= OnStateChanged;
        if (_authentication is not null) _authentication.PropertyChanged -= OnAuthenticationChanged;
    }
}

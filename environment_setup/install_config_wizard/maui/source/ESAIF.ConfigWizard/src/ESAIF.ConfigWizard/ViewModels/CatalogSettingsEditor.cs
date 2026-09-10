using System.Collections.ObjectModel;
using System.Text;
using System.Text.Json;
using System.Text.Json.Nodes;
using ESAIF.BaseLayer.Application;
using ESAIF.ConfigWizard.Services;
using ESAIF.DomainLayer.Configuration;

namespace ESAIF.ConfigWizard.ViewModels;

public sealed record CatalogSettingsScope(string Folder, string FactoryId, string? ScaleSetId, string? ProjectId);

public sealed class CatalogSettingsEditor : ObservableObject
{
    private CatalogSettingsScope? _scope;
    private FactorySchema? _schema;
    private JsonObject _baseline = [], _state = [];
    private HashSet<string> _allowed = new(StringComparer.Ordinal);
    private string _filter = string.Empty;
    public event EventHandler? Edited;
    public ObservableCollection<ConfigFieldViewModel> Fields { get; } = [];
    public ObservableCollection<ConfigFieldViewModel> VisibleFields { get; } = [];
    public string Revision { get; private set; } = string.Empty;
    public bool IsLoaded { get; private set; }
    public bool IsStale { get; private set; }
    public bool IsEditable => IsLoaded && !IsStale;
    public bool HasErrors => Fields.Any(item => item.IsInvalid);
    public int ChangedCount => _allowed.Count(key => !JsonNode.DeepEquals(_baseline[key], _state[key]));
    public bool IsDirty => ChangedCount > 0 || HasErrors;
    public bool CanPrepare => IsEditable && !HasErrors && ChangedCount > 0;
    public string Status { get; private set; } = "Select an exact settings scope, then load its allowed fields.";
    public string Filter
    {
        get => _filter;
        set { if (SetProperty(ref _filter, value)) { FilterFields(); Edited?.Invoke(this, EventArgs.Empty); } }
    }

    public void UpdateContext(CatalogSettingsScope? scope, string? revision)
    {
        if (_scope is null) return;
        if (_scope != scope)
        {
            Clear("The settings scope changed. Load the newly selected scope.");
            return;
        }
        if (Revision != revision)
        {
            IsStale = true;
            Status = "Catalog revision changed. Draft inputs are retained but cannot be saved; explicitly reload this scope.";
            NotifyState();
        }
    }

    public void Load(CatalogSettingsScope scope, FactoryCatalogSettings result, FactorySchema schema)
    {
        if (result.ContractVersion != 1 || result.FactoryId != scope.FactoryId ||
            result.ScaleSetId != scope.ScaleSetId || result.ProjectId != scope.ProjectId ||
            string.IsNullOrWhiteSpace(result.Revision) || result.FieldKeys.Distinct(StringComparer.Ordinal).Count() != result.FieldKeys.Count)
            throw new InvalidDataException("Settings were returned for a different or incomplete scope.");
        if (result.FieldKeys.Any(key => !result.State.ContainsKey(key) || result.State[key] is JsonObject or JsonArray))
            throw new InvalidDataException("Scoped settings must contain only the listed scalar fields.");
        var allowed = result.FieldKeys.Where(key => !ForbiddenField(key)).ToHashSet(StringComparer.Ordinal);
        var state = new JsonObject();
        var defaults = new JsonObject();
        foreach (var key in allowed)
        {
            state[key] = result.State[key]?.DeepClone();
            if (schema.Defaults[key] is not (JsonObject or JsonArray)) defaults[key] = schema.Defaults[key]?.DeepClone();
        }
        var options = (JsonObject)schema.Options.DeepClone();
        options.Remove("scaling_modes");
        _schema = new() { Defaults = defaults, Options = options, Orchestrators = schema.Orchestrators,
            Sections = new() { ScaleSetVariables = schema.Sections.ScaleSetVariables.Where(allowed.Contains).ToArray(),
                ProjectVariables = schema.Sections.ProjectVariables.Where(allowed.Contains).ToArray() } };
        _scope = scope;
        _allowed = allowed;
        _state = state;
        _baseline = (JsonObject)state.DeepClone();
        Revision = result.Revision;
        Fields.Clear();
        foreach (var field in WizardFieldCatalog.Build(_schema, _state, SetValue).SelectMany(step => step.Fields).Where(field => allowed.Contains(field.Key)))
        {
            // Project settings span placements with potentially different routes; do not infer one runner provider.
            Fields.Add(field.IsRunnerConfiguration
                ? new(field.Key, field.Label, field.Description, state[field.Key], defaults[field.Key], field.Options, SetValue)
                : field);
        }
        foreach (var key in allowed.Where(key => Fields.All(field => field.Key != key)).Order(StringComparer.Ordinal))
            Fields.Add(new(key, key.Replace('_', ' '), $"API field: {key}", state[key], defaults[key], [], SetValue));
        IsLoaded = true;
        IsStale = false;
        Status = $"{Fields.Count} whitelisted non-secret fields. Only actual edits will be submitted. {result.Message}";
        FilterFields();
        NotifyState();
    }

    public JsonObject BuildDelta(CatalogSettingsScope scope, string revision)
    {
        if (!IsEditable || _scope != scope || Revision != revision)
            throw new InvalidOperationException("Reload settings for the exact current scope and catalog revision.");
        if (HasErrors) throw new InvalidOperationException("Correct the invalid settings fields before preparing.");
        if (_allowed.Contains(HubTopologyViewModel.DnsKey) && _allowed.Contains(HubTopologyViewModel.OwnHubKey))
            ConfigurationStateEditing.ValidateTopology(_state, _schema);
        var delta = new JsonObject();
        foreach (var key in _allowed)
            if (!JsonNode.DeepEquals(_baseline[key], _state[key])) delta[key] = _state[key]?.DeepClone();
        if (delta.Count == 0) throw new InvalidOperationException("Edit at least one allowed setting before preparing.");
        return delta;
    }

    public string ReviewDelta(JsonObject delta)
    {
        var text = new StringBuilder("\nExact scoped settings changes (other fields remain inherited/unchanged):\n");
        foreach (var item in delta.OrderBy(item => item.Key, StringComparer.Ordinal))
        {
            if (!_allowed.Contains(item.Key) || ForbiddenField(item.Key) || item.Value is JsonObject or JsonArray)
                throw new InvalidDataException("The settings review contains an unlisted or non-scalar field.");
            text.AppendLine($"{item.Key}\n  Before: {Display(_baseline[item.Key])}\n  After: {Display(item.Value)}");
        }
        return text.ToString();
    }

    public void Clear(string status)
    {
        _scope = null;
        _schema = null;
        _baseline = [];
        _state = [];
        _allowed.Clear();
        Fields.Clear();
        VisibleFields.Clear();
        IsLoaded = IsStale = false;
        Revision = string.Empty;
        Status = status;
        NotifyState();
    }

    private void SetValue(string key, JsonNode? value)
    {
        var field = Fields.FirstOrDefault(field => field.Key == key) ??
            Fields.FirstOrDefault(field => key == HubTopologyViewModel.StateKey && field.IsHubTopology);
        try
        {
            if (!IsEditable) throw new InvalidOperationException("Reload this settings scope before editing.");
            var virtualHub = key == HubTopologyViewModel.StateKey &&
                _allowed.Contains(HubTopologyViewModel.DnsKey) && _allowed.Contains(HubTopologyViewModel.OwnHubKey);
            if (!_allowed.Contains(key) && !virtualHub || value is JsonObject or JsonArray)
                throw new InvalidOperationException("This field is not editable in the current settings scope.");
            if (field is not null) field.IssueMessage = string.Empty;
            var candidate = (JsonObject)_state.DeepClone();
            ConfigurationStateEditing.SetValue(candidate, _schema, key, value?.DeepClone());
            foreach (var item in candidate)
            {
                if (JsonNode.DeepEquals(item.Value, _state[item.Key])) continue;
                if (item.Key == HubTopologyViewModel.StateKey) continue;
                if (!_allowed.Contains(item.Key) || ForbiddenField(item.Key))
                    throw new InvalidOperationException("This change requires a dependent field outside the server whitelist.");
                ValidateScalar(item.Key, item.Value);
            }
            _state = candidate;
            foreach (var current in Fields)
            {
                if (current.IsInvalid) continue;
                current.SynchronizeValue(_state[current.Key]);
                current.NetworkMode?.Synchronize(_state);
                current.HubTopology?.Synchronize(_state);
            }
            Status = HasErrors ? "Correct the invalid settings fields before preparing." :
                $"{ChangedCount} changed field(s). Untouched fields remain inherited or unchanged.";
        }
        catch (Exception error) when (error is InvalidOperationException or ArgumentException or FormatException)
        {
            if (field is not null) field.IssueMessage = error.Message;
            Status = error.Message;
        }
        NotifyState();
        Edited?.Invoke(this, EventArgs.Empty);
    }

    private void ValidateScalar(string key, JsonNode? value)
    {
        if (value is JsonObject or JsonArray) throw new InvalidOperationException("Use a scalar settings value.");
        var expected = _baseline[key] ?? _schema?.Defaults[key];
        if (expected is null || value is null) return;
        if (expected.GetValueKind() is JsonValueKind.Number or JsonValueKind.True or JsonValueKind.False &&
            value.GetValueKind() != expected.GetValueKind() &&
            !(expected.GetValueKind() is JsonValueKind.True or JsonValueKind.False && value.GetValueKind() is JsonValueKind.True or JsonValueKind.False))
            throw new InvalidOperationException("Enter a value matching this field's numeric or Boolean schema type.");
        if (value is JsonValue scalar && scalar.TryGetValue<double>(out var number) && !double.IsFinite(number))
            throw new InvalidOperationException("Enter a finite number.");
    }

    private static bool ForbiddenField(string key) =>
        TechnicalValuePresentation.IsSecret(key) || key.Contains("connection_string", StringComparison.OrdinalIgnoreCase) ||
        key.EndsWith("_token", StringComparison.OrdinalIgnoreCase) || key.StartsWith('_') ||
        key.Contains("cidr", StringComparison.OrdinalIgnoreCase) ||
        key.StartsWith("delete", StringComparison.OrdinalIgnoreCase) || key.StartsWith("clean", StringComparison.OrdinalIgnoreCase) ||
        key.StartsWith("update", StringComparison.OrdinalIgnoreCase) ||
        key is "orchestrator" or "aifactory_version" or "version_ref" or "version_major" or "version_minor" or "version_branch" or
            "admin_aifactoryPrefixRG" or "admin_aifactorySuffixRG" or "admin_location" or "admin_locationSuffix" or
            "tenantId" or "dev_sub_id" or "test_sub_id" or "prod_sub_id" or "project_number_000" or "projectName" or
            "enableDeleteForDisabledResources" or "debugEnableCleaning";

    private static string Display(JsonNode? value) => value?.ToJsonString() ?? "null";
    private void FilterFields()
    {
        VisibleFields.Clear();
        foreach (var field in Fields.Where(field => string.IsNullOrWhiteSpace(Filter) ||
                     field.Key.Contains(Filter, StringComparison.OrdinalIgnoreCase) || field.Label.Contains(Filter, StringComparison.OrdinalIgnoreCase)))
            VisibleFields.Add(field);
    }
    private void NotifyState()
    {
        foreach (var property in new[] { nameof(Revision), nameof(IsLoaded), nameof(IsStale), nameof(IsEditable),
                     nameof(HasErrors), nameof(ChangedCount), nameof(IsDirty), nameof(CanPrepare), nameof(Status) }) OnPropertyChanged(property);
    }
}

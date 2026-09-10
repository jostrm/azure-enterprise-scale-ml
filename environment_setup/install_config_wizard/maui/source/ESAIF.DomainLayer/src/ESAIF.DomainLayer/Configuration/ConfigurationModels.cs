using System.Text.Json.Nodes;
using System.Text.Json.Serialization;

namespace ESAIF.DomainLayer.Configuration;

public sealed class HealthStatus
{
    public string Status { get; init; } = string.Empty;

    public string Version { get; init; } = string.Empty;
}

public sealed class FactorySchema
{
    public IReadOnlyList<string> Formats { get; init; } = [];

    public IReadOnlyList<string> Orchestrators { get; init; } = [];

    public JsonObject Defaults { get; init; } = [];

    public JsonObject Mappings { get; init; } = [];

    public SchemaSections Sections { get; init; } = new();

    public JsonObject Options { get; init; } = [];
}

public sealed class SchemaSections
{
    [JsonPropertyName("scale_set_variables")]
    public IReadOnlyList<string> ScaleSetVariables { get; init; } = [];

    [JsonPropertyName("project_variables")]
    public IReadOnlyList<string> ProjectVariables { get; init; } = [];
}

public sealed class StateResult
{
    public JsonObject State { get; init; } = [];
}

public sealed class ValidationResult
{
    public bool Valid { get; init; }

    public IReadOnlyList<ValidationIssue> Issues { get; init; } = [];
}

public sealed class ValidationIssue
{
    public string Field { get; init; } = string.Empty;

    public string Code { get; init; } = string.Empty;

    public string Message { get; init; } = string.Empty;
}

public sealed class ImportResult
{
    public string Format { get; init; } = string.Empty;

    [JsonPropertyName("fields_loaded")]
    public int FieldsLoaded { get; init; }

    public JsonObject State { get; init; } = [];
}

public sealed class ExportResult
{
    public string Format { get; init; } = string.Empty;

    public string? Path { get; init; }

    public string Content { get; init; } = string.Empty;
}

public sealed class StartupLoadResult
{
    [JsonPropertyName("source_path")]
    public string? SourcePath { get; init; }

    public string Orchestrator { get; init; } = string.Empty;

    [JsonPropertyName("fields_loaded")]
    public int FieldsLoaded { get; init; }

    public JsonObject State { get; init; } = [];
}

public sealed class ProjectsResult
{
    public IReadOnlyList<ProjectSummary> Projects { get; init; } = [];
}

public sealed class ProjectSummary
{
    public string Owner { get; init; } = string.Empty;

    [JsonPropertyName("planned_environments")]
    public IReadOnlyList<string> PlannedEnvironments { get; init; } = [];

    [JsonPropertyName("deployment_scope")]
    public ProjectDeploymentScope? DeploymentScope { get; init; }

    [JsonPropertyName("project_number")]
    public string ProjectNumber { get; init; } = string.Empty;

    public string Path { get; init; } = string.Empty;

    public string Label { get; init; } = string.Empty;
}

public sealed class ProjectLoadResult
{
    public string Path { get; init; } = string.Empty;

    public JsonObject State { get; init; } = [];
}

public sealed class ProjectSaveResult
{
    [JsonPropertyName("snapshot_path")]
    public string SnapshotPath { get; init; } = string.Empty;

    [JsonPropertyName("variables_path")]
    public string? VariablesPath { get; init; }
}

public sealed class ScaleSetsResult
{
    [JsonPropertyName("scale_sets")]
    public IReadOnlyList<ScaleSetSummary> ScaleSets { get; init; } = [];
}

public sealed class ScaleSetSummary
{
    [JsonPropertyName("deployment_scope")]
    public ProjectDeploymentScope? DeploymentScope { get; init; }

    [JsonPropertyName("scale_set_id")]
    public string ScaleSetId { get; init; } = string.Empty;

    public string Path { get; init; } = string.Empty;
}

public sealed class ScaleSetLoadResult
{
    public string Path { get; init; } = string.Empty;

    public JsonObject State { get; init; } = [];
}

public sealed class PathResult
{
    public string Path { get; init; } = string.Empty;
}

public sealed class RecentProjectsResult
{
    [JsonPropertyName("recent_projects")]
    public IReadOnlyList<RecentProject> RecentProjects { get; init; } = [];
}

public sealed class RecentProject
{
    public string Folder { get; init; } = string.Empty;

    public string Project { get; init; } = string.Empty;

    public string Orchestrator { get; init; } = string.Empty;

    [JsonPropertyName("prefix_rg")]
    public string PrefixResourceGroup { get; init; } = string.Empty;

    [JsonPropertyName("suffix_rg")]
    public string SuffixResourceGroup { get; init; } = string.Empty;
}

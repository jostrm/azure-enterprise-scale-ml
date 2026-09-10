using System.Globalization;
using System.Text;
using ESAIF.DomainLayer.Configuration;

namespace ESAIF.ConfigWizard.Services;

public sealed record CatalogChoice(string Value, string Display);

public sealed record CatalogFactoryRow(CatalogFactory Factory)
{
    public string Id => Factory.Id;
    public string Display => $"{Factory.Prefix} · {Factory.Region}";
    public string Summary => $"{Factory.Status} · {Factory.ScaleSets.Count} scale sets · {Factory.Projects.Count} projects";
    public string Details => $"Factory: {Factory.Id}\nKey: {Factory.Key}\nDefault route: {Factory.DefaultOrchestrator}\n" +
        $"Saved factory version: {Factory.FactoryVersion ?? "(not reported)"}";
}

public sealed record CatalogScaleSetRow(CatalogScaleSet ScaleSet)
{
    public string Id => ScaleSet.Id;
    public string Display => $"{ScaleSet.Environment.ToUpperInvariant()}{ScaleSet.Suffix} · {ScaleSet.Orchestrator}";
    public string Summary => $"{ScaleSet.Status} · capacity {ScaleSet.Network.MaxProjects}";
    public string Details => $"Scale set: {Id}\nEnvironment: {ScaleSet.Environment}\nSuffix: {ScaleSet.Suffix}\n" +
        $"Subscription: {ScaleSet.SubscriptionId}\nTenant: {ScaleSet.TenantId}\n" +
        $"Route: {ScaleSet.Orchestrator}\nVNet: {ScaleSet.Network.VnetCidr}\nCapacity: {ScaleSet.Network.MaxProjects}\n" +
        (ScaleSet.Network.CommonSubnets is { } subnets
            ? $"Common subnet: {subnets.Common}\nScoring subnet: {subnets.Scoring}\nPower BI subnet: {subnets.Powerbi}\nBastion subnet: {subnets.Bastion}"
            : "Common subnets: server allocation (no custom override reported).");
}

public sealed record CatalogProjectRow(CatalogProject Project, CatalogFactory Factory)
{
    public string Id => Project.Id;
    public string Display => $"{Project.Number} · {Project.DisplayName}";
    public string Summary => $"{Project.Status} · " + string.Join(", ", Project.Placements.Select(placement =>
    {
        var scale = Factory.ScaleSets.SingleOrDefault(x => x.Id == placement.ScaleSetId);
        return scale is null ? $"{placement.Environment}: unresolved placement" :
            $"{placement.Environment}: {scale.Environment.ToUpperInvariant()}{scale.Suffix}";
    }));
    public string Details => $"Project: {Project.Id}\nKey: {Project.Key}\n" +
        string.Join("\n", Project.Placements.Select(x => $"{x.Environment}: {x.ScaleSetId}"));
}

public static class FactoryCatalogPresentation
{
    public static IReadOnlyList<CatalogChoice> Actions { get; } =
    [
        new("create-factory", "New factory draft"),
        new("clone", "Clone configuration"),
        new("create-scale-set", "Add scale set"),
        new("add-project", "Add a new project"),
        new("add-project-placements", "Add existing project placements"),
        new("configure-binding", "Configure pipeline binding and locks"),
        new("configure-settings", "Edit scoped configuration settings"),
        new("migrate", "Review explicit legacy migration"),
        new("deploy", "Deploy selected scale set"),
        new("delete-scale-set", "Delete selected scale set"),
        new("delete-factory", "Delete selected factory")
    ];
    public static IReadOnlyList<CatalogChoice> Environments { get; } =
        [new("dev", "Development"), new("stage", "Staging"), new("prod", "Production")];
    public static IReadOnlyList<CatalogChoice> Orchestrators { get; } =
        [new("gha", "GitHub Actions"), new("ado", "Azure DevOps")];
    public static IReadOnlyList<CatalogChoice> ProjectInclusion { get; } =
        [new("none", "No projects (configuration only)"), new("all", "All project configurations")];

    public static int ValidateCapacity(string value)
    {
        if (!int.TryParse(value, NumberStyles.None, CultureInfo.InvariantCulture, out var capacity) ||
            capacity is < 1 or > 8)
            throw new InvalidOperationException("Scale-set capacity must be a whole number from 1 through 8.");
        return capacity;
    }

    public static void ValidateSuffix(string suffix)
    {
        if (suffix.Length != 3 || suffix.Any(c => !char.IsAsciiDigit(c)) || suffix == "000")
            throw new InvalidOperationException("Enter an explicit three-digit scale-set suffix, for example 001 or 002.");
    }

    public static string PreviewDetails(FactoryCatalogPreview preview, string folder,
        string action, CatalogFactory? factory, CatalogScaleSet? scaleSet, string version)
    {
        var text = new StringBuilder();
        text.AppendLine($"Root: {folder}");
        text.AppendLine($"Revision: {preview.SourceRevision}");
        text.AppendLine($"Action: {action} ({preview.OperationMode})");
        text.AppendLine($"Factory: {factory?.Id ?? "(new / legacy migration)"}");
        text.AppendLine($"Scale set: {scaleSet?.Id ?? "(not selected)"}");
        if (scaleSet is not null) text.AppendLine(new CatalogScaleSetRow(scaleSet).Details);
        if (action == "delete-factory" && factory is not null)
        {
            text.AppendLine("ENTIRE FACTORY — all scale sets, not only a highlighted scale set:");
            foreach (var scale in factory.ScaleSets) text.AppendLine(new CatalogScaleSetRow(scale).Details);
        }
        text.AppendLine($"Requested version: {version}");
        text.AppendLine(preview.OperationMode == "runtime" || preview.SourceVersion is not null
            ? SourceVersionDetails(preview.SourceVersion) : "Runtime source resolution is not required for this local configuration save.");
        text.AppendLine($"Expires: {preview.ExpiresAt}");
        text.AppendLine($"Summary: {preview.Summary}");
        if (preview.Target is { } target)
        {
            text.AppendLine($"Saved target factory version: {target.FactoryVersion ?? "(not reported)"}");
            text.AppendLine($"Result factory: {target.Id} · {target.Key} · {target.Prefix} · {target.Region}");
            text.AppendLine($"Result version: {target.VersionRef}");
            foreach (var scale in target.ScaleSets) text.AppendLine(new CatalogScaleSetRow(scale).Details);
            foreach (var project in target.Projects)
            {
                var row = new CatalogProjectRow(project, target);
                text.AppendLine($"Project: {row.Display} · {project.Status}\n{row.Details}");
            }
        }
        if (preview.Binding is { } binding) text.AppendLine(BindingDetails(binding));
        text.AppendLine("\nEffects:");
        foreach (var effect in preview.Effects) text.AppendLine(effect);
        text.AppendLine("\nWarnings:");
        foreach (var warning in preview.Warnings) text.AppendLine(warning);
        text.AppendLine("\nBlockers:");
        foreach (var blocker in preview.Blockers) text.AppendLine(blocker);
        text.AppendLine("\nServer-owned resource manifest (not editable):");
        foreach (var resource in preview.Inventory)
        {
            text.AppendLine(resource.ResourceId);
            foreach (var dependency in resource.Dependencies) text.AppendLine($"  Depends on: {dependency}");
        }
        return text.ToString();
    }

    public static string SourceVersionDetails(CatalogSourceVersion? source) => source is null
        ? "Pinned source version: not available; inspect the server blockers."
        : $"Server version input echo: {source.FactoryVersion ?? "(not supplied)"}\nCanonical source version: {source.RequestedVersion}\n" +
            $"Source branch: {source.Branch}\nPinned source commit: {source.ResolvedRef}";

    public static string BindingDetails(CatalogRuntimeBinding binding) =>
        $"\nComplete reviewed {binding.Orchestrator} binding:\nWriter: {binding.WriterId}\nRepository: {binding.Repository}\n" +
        $"Consumer ref: {binding.Ref}\nShared remote: {binding.SharedRemote}\nAuthentication namespace: {binding.AuthNamespace}\n" +
        $"Deployment object ID: {binding.DeploymentObjectId}\nLock account: {binding.Locks.AccountUrl}\n" +
        RunnerDetails(binding.Runner) + "\n" +
        $"Container: {binding.Locks.Container}\nCoordination blob: {binding.Locks.CoordinationBlob}\n" +
        $"Coordination hash: {binding.Locks.CoordinationHash}\nEnrollment revision: {binding.Locks.Revision}\n" +
        string.Join("\n", binding.Targets.Select(target =>
            $"Scale set: {target.ScaleSetId}\nWritable groups:\n{string.Join("\n", target.ResourceGroupIds)}\n" +
            $"Shared dependencies:\n{string.Join("\n", target.CommonDependencyIds)}\n" +
            (target.Execution is { } execution
                ? $"Scale-set execution override:\nWriter: {execution.WriterId}\nAuthentication namespace: {execution.AuthNamespace}\n" +
                  $"Deployment object ID: {execution.DeploymentObjectId}\n{RunnerDetails(execution.Runner)}"
                : "Scale-set execution: inherits the shared route binding.")));

    private static string RunnerDetails(CatalogRunnerSelection? runner) => runner is null
        ? "Runtime runner: not selected"
        : $"Runtime runner: {runner.Kind} ({runner.Os})\nHosted image: {runner.Image}\n" +
            $"GitHub labels: {string.Join(", ", runner.Labels ?? [])}\nAzure DevOps pool: {runner.Pool}\nAgent name: {runner.AgentName}";
}

public sealed record CatalogBindingRow(CatalogBindingState Binding)
{
    public string Display => Binding.Orchestrator == "gha" ? "GitHub Actions" : "Azure DevOps";
    public string Status => Binding.Error is { Length: > 0 } ? "Saved binding needs repair" :
        Binding.Verified ? "Server-verified binding" : "Saved setup · runtime verification pending";
    public string Details => Binding.Error ?? (Binding.Configuration is { } config
        ? FactoryCatalogPresentation.BindingDetails(config) : "No readable configuration was returned.");
}

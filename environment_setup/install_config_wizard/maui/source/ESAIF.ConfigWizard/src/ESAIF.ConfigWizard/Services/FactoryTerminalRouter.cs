using ESAIF.DomainLayer.Configuration;

namespace ESAIF.ConfigWizard.Services;

public enum FactoryTerminalJobKind { ProjectDeployment, FactoryCatalog }

/// <summary>Only the explicitly opened job can select one of the two fixed terminal protocols.</summary>
public sealed class FactoryTerminalRouter(
    IProjectTerminalClient project,
    IFactoryCatalogTerminalClient catalog) : IProjectTerminalClient
{
    private TerminalScope? _scope;

    public void Register(AiFactoryConnection connection, string folder, string jobId, FactoryTerminalJobKind kind)
    {
        ArgumentNullException.ThrowIfNull(connection);
        ArgumentException.ThrowIfNullOrWhiteSpace(folder);
        ArgumentException.ThrowIfNullOrWhiteSpace(jobId);
        if (!Enum.IsDefined(kind)) throw new ArgumentOutOfRangeException(nameof(kind));
        _scope = new(connection, folder, jobId, kind);
    }

    public Task<ProjectTerminalOutput> ReadProjectTerminalAsync(AiFactoryConnection connection, string folder,
        string jobId, long cursor, CancellationToken cancellationToken = default) =>
        RequireKind(connection, folder, jobId) == FactoryTerminalJobKind.FactoryCatalog
            ? catalog.ReadFactoryCatalogTerminalAsync(connection, folder, jobId, cursor, cancellationToken)
            : project.ReadProjectTerminalAsync(connection, folder, jobId, cursor, cancellationToken);

    public Task WriteProjectTerminalAsync(AiFactoryConnection connection, string folder, string jobId, string data,
        CancellationToken cancellationToken = default) =>
        RequireKind(connection, folder, jobId) == FactoryTerminalJobKind.FactoryCatalog
            ? catalog.WriteFactoryCatalogTerminalAsync(connection, folder, jobId, data, cancellationToken)
            : project.WriteProjectTerminalAsync(connection, folder, jobId, data, cancellationToken);

    public Task ResizeProjectTerminalAsync(AiFactoryConnection connection, string folder, string jobId,
        int columns, int rows, CancellationToken cancellationToken = default) =>
        RequireKind(connection, folder, jobId) == FactoryTerminalJobKind.FactoryCatalog
            ? catalog.ResizeFactoryCatalogTerminalAsync(connection, folder, jobId, columns, rows, cancellationToken)
            : project.ResizeProjectTerminalAsync(connection, folder, jobId, columns, rows, cancellationToken);

    private FactoryTerminalJobKind RequireKind(AiFactoryConnection connection, string folder, string jobId)
    {
        var scope = _scope;
        if (scope is null || scope.Connection != connection || scope.Folder != folder || scope.JobId != jobId)
            throw new ProjectTerminalConnectionException("This exact terminal job, root and connection have not been opened.");
        return scope.Kind;
    }

    private sealed record TerminalScope(AiFactoryConnection Connection, string Folder, string JobId, FactoryTerminalJobKind Kind);
}

public interface IFactoryCatalogTerminalSession
{
    Task OpenCatalogAsync(string folder, FactoryCatalogJob job);
}

namespace ESAIF.DomainLayer.Configuration;

public interface IAiFactoryConnectionProvider
{
    Task<AiFactoryConnection> GetConnectionAsync(
        CancellationToken cancellationToken = default);
}

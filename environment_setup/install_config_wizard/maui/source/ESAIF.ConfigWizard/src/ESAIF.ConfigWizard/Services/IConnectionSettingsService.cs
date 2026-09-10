using ESAIF.DomainLayer.Configuration;

namespace ESAIF.ConfigWizard.Services;

public interface IConnectionSettingsService : IAiFactoryConnectionProvider
{
    Task SaveConnectionAsync(
        AiFactoryConnection connection,
        CancellationToken cancellationToken = default);
}

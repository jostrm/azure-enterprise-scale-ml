namespace ESAIF.ConfigWizard.Services;

public interface IBundledApiHost : IAsyncDisposable
{
    bool IsAvailable { get; }

    Task StartAsync(CancellationToken cancellationToken = default);

    Task StopAsync(CancellationToken cancellationToken = default);
}

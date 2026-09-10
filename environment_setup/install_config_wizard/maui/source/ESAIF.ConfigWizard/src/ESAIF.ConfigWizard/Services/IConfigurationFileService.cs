namespace ESAIF.ConfigWizard.Services;

public interface IConfigurationFileService
{
    Task<PickedConfigurationFile?> PickAsync(
        CancellationToken cancellationToken = default);

    Task<string> SaveExportAsync(
        string format,
        string content,
        CancellationToken cancellationToken = default);
}

public sealed record PickedConfigurationFile(
    string Name,
    string Format,
    string Content);

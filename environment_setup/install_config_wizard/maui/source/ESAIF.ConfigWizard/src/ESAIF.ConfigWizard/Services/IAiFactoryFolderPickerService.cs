namespace ESAIF.ConfigWizard.Services;

public interface IAiFactoryFolderPickerService
{
    Task<string?> PickFolderAsync(
        string currentFolder,
        CancellationToken cancellationToken = default);
}

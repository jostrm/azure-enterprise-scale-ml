namespace ESAIF.ConfigWizard.Services;

public sealed class AiFactoryFolderPickerService : IAiFactoryFolderPickerService
{
    public async Task<string?> PickFolderAsync(
        string currentFolder,
        CancellationToken cancellationToken = default)
    {
#if WINDOWS
        var window = Microsoft.Maui.Controls.Application.Current?
            .Windows
            .FirstOrDefault()?
            .Handler?
            .PlatformView as Microsoft.UI.Xaml.Window;
        if (window is null)
        {
            throw new InvalidOperationException(
                "The application window is not available for folder selection.");
        }

        var picker = new Windows.Storage.Pickers.FolderPicker
        {
            SuggestedStartLocation =
                Windows.Storage.Pickers.PickerLocationId.DocumentsLibrary
        };
        picker.FileTypeFilter.Add("*");
        WinRT.Interop.InitializeWithWindow.Initialize(
            picker,
            WinRT.Interop.WindowNative.GetWindowHandle(window));
        var folder = await picker.PickSingleFolderAsync();
        cancellationToken.ThrowIfCancellationRequested();
        return folder?.Path;
#else
        await Task.CompletedTask;
        throw new PlatformNotSupportedException(
            "Folder browsing is available in the Windows application. Enter the server-local path manually on this device.");
#endif
    }
}

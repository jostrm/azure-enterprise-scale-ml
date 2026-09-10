namespace ESAIF.ConfigWizard.Services;

public sealed class MauiConfigurationFileService : IConfigurationFileService
{
    public async Task<PickedConfigurationFile?> PickAsync(
        CancellationToken cancellationToken = default)
    {
        var result = await FilePicker.Default.PickAsync(new PickOptions
        {
            PickerTitle = "Import variables.yaml, .env, or variables.json",
            FileTypes = new FilePickerFileType(
                new Dictionary<DevicePlatform, IEnumerable<string>>
                {
                    [DevicePlatform.WinUI] = [".yaml", ".yml", ".env", ".json"],
                    [DevicePlatform.Android] =
                        ["application/x-yaml", "application/json", "text/plain"],
                    [DevicePlatform.iOS] = ["public.json", "public.text"],
                    [DevicePlatform.MacCatalyst] = ["public.json", "public.text"]
                })
        });

        if (result is null)
        {
            return null;
        }

        cancellationToken.ThrowIfCancellationRequested();
        await using var stream = await result.OpenReadAsync();
        using var reader = new StreamReader(stream);
        var content = await reader.ReadToEndAsync(cancellationToken);
        return new PickedConfigurationFile(
            result.FileName,
            DetectFormat(result.FileName),
            content);
    }

    public async Task<string> SaveExportAsync(
        string format,
        string content,
        CancellationToken cancellationToken = default)
    {
        var exportDirectory = Path.Combine(FileSystem.AppDataDirectory, "exports");
        Directory.CreateDirectory(exportDirectory);
        var extension = format switch
        {
            "yaml" => ".yaml",
            "env" => ".env",
            "json" => ".json",
            _ => throw new ArgumentOutOfRangeException(nameof(format))
        };
        var path = Path.Combine(
            exportDirectory,
            $"esaif-config-{DateTimeOffset.Now:yyyyMMdd-HHmmss}{extension}");
        await File.WriteAllTextAsync(path, content, cancellationToken);
        return path;
    }

    private static string DetectFormat(string fileName)
    {
        if (fileName.Equals(".env", StringComparison.OrdinalIgnoreCase) ||
            Path.GetExtension(fileName).Equals(".env", StringComparison.OrdinalIgnoreCase))
        {
            return "env";
        }

        return Path.GetExtension(fileName).ToLowerInvariant() switch
        {
            ".yaml" or ".yml" => "yaml",
            ".json" => "json",
            _ => throw new InvalidDataException(
                "Select a .yaml, .yml, .env, or .json configuration file.")
        };
    }
}

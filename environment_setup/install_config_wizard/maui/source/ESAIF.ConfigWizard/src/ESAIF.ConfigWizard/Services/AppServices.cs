using Microsoft.Extensions.DependencyInjection;

namespace ESAIF.ConfigWizard.Services;

public static class AppServices
{
    private static IServiceProvider? _provider;

    public static IServiceProvider Provider =>
        _provider ??
        throw new InvalidOperationException(
            "Application services have not been initialized.");

    public static void Initialize(IServiceProvider provider)
    {
        ArgumentNullException.ThrowIfNull(provider);
        _provider = provider;
    }

    public static T GetRequiredService<T>()
        where T : notnull
    {
        try
        {
            return Provider.GetRequiredService<T>();
        }
        catch (Exception exception)
        {
            var directory = Path.Combine(
                Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),
                "ESAIF.ConfigWizard");
            try
            {
                Directory.CreateDirectory(directory);
                File.WriteAllText(
                    Path.Combine(directory, "last-page-error.log"),
                    exception.ToString());
            }
            catch (IOException)
            {
            }
            catch (UnauthorizedAccessException)
            {
            }

            throw;
        }
    }
}

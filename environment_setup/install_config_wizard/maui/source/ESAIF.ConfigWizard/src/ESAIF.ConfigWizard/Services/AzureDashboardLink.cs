namespace ESAIF.ConfigWizard.Services;

public static class AzureDashboardLink
{
    public static Uri? Parse(string? value)
    {
        if (!Uri.TryCreate(value?.Trim(), UriKind.Absolute, out var uri) ||
            uri.Scheme != Uri.UriSchemeHttps ||
            !uri.Host.Equals("portal.azure.com", StringComparison.OrdinalIgnoreCase) ||
            !uri.IsDefaultPort || !string.IsNullOrEmpty(uri.UserInfo))
        {
            return null;
        }
        var route = Uri.UnescapeDataString(uri.Fragment).TrimStart('#');
        if (route.StartsWith('@'))
        {
            var separator = route.IndexOf('/');
            route = separator < 0 ? string.Empty : route[(separator + 1)..];
        }
        return route.StartsWith("dashboard/private/", StringComparison.OrdinalIgnoreCase) && route.Length > "dashboard/private/".Length ||
               route.StartsWith("dashboard/arm/", StringComparison.OrdinalIgnoreCase) && route.Length > "dashboard/arm/".Length
            ? uri : null;
    }
}

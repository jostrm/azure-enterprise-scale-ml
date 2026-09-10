namespace ESAIF.DomainLayer.Configuration;

public sealed record AiFactoryConnection(string BaseAddress, string ApiKey)
{
    public static AiFactoryConnection LocalDefault { get; } =
        new("http://127.0.0.1:8765", string.Empty);

    public Uri BaseUri
    {
        get
        {
            if (!Uri.TryCreate(BaseAddress, UriKind.Absolute, out var baseAddress) ||
                (baseAddress.Scheme != Uri.UriSchemeHttp &&
                 baseAddress.Scheme != Uri.UriSchemeHttps))
            {
                throw new InvalidOperationException(
                    "The API address must be an absolute HTTP or HTTPS URL.");
            }

            return baseAddress.AbsoluteUri.EndsWith("/", StringComparison.Ordinal)
                ? baseAddress
                : new Uri($"{baseAddress.AbsoluteUri}/");
        }
    }

    public Uri DocumentationUri => new(BaseUri, "docs");
}

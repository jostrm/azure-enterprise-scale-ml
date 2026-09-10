namespace ESAIF.BaseLayer.Networking;

public interface IJsonApiTransport
{
    Task<TResponse> SendAsync<TResponse>(
        HttpRequestMessage request,
        CancellationToken cancellationToken = default);
}

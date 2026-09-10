using System.Net;

namespace ESAIF.BaseLayer.Networking;

public sealed class ApiRequestException : HttpRequestException
{
    public ApiRequestException(HttpStatusCode statusCode, string message, string responseBody)
        : base(message, null, statusCode)
    {
        ResponseBody = responseBody;
    }

    public string ResponseBody { get; }
}

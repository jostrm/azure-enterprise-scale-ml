using System.Runtime.InteropServices;
using System.Text.Json;
using ESAIF.DomainLayer.Configuration;

namespace ESAIF.ConfigWizard.Services;

internal sealed class TerminalUnavailableException(string message) : InvalidOperationException(message);

internal static class TerminalFailurePolicy
{
    public static bool IsExpected(Exception exception) => exception is
        HttpRequestException or IOException or InvalidDataException or JsonException or OperationCanceledException or
        TimeoutException or COMException or ObjectDisposedException or UnauthorizedAccessException or
        ProjectTerminalConnectionException or TerminalUnavailableException;
}

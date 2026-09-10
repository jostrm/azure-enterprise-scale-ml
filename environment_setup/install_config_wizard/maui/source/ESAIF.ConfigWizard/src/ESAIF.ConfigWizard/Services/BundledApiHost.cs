using System.Diagnostics;
using System.Net;
using System.Net.Sockets;
using System.Security.Cryptography;
using ESAIF.DomainLayer.Configuration;

namespace ESAIF.ConfigWizard.Services;

public sealed class BundledApiHost(IConnectionSettingsService connections) : IBundledApiHost
{
    private readonly SemaphoreSlim _lifecycle = new(1, 1);
    private Process? _process;

    public bool IsAvailable =>
        OperatingSystem.IsWindows() &&
        File.Exists(GetExecutablePath());

    public async Task StartAsync(CancellationToken cancellationToken = default)
    {
        if (!OperatingSystem.IsWindows() || !File.Exists(GetExecutablePath()))
        {
            return;
        }

        await _lifecycle.WaitAsync(cancellationToken).ConfigureAwait(false);
        try
        {
            if (_process is { HasExited: false })
            {
                return;
            }

            var port = FindAvailablePort();
            var apiKey = Convert.ToHexString(RandomNumberGenerator.GetBytes(32));
            var baseAddress = $"http://127.0.0.1:{port}";
            var dataDirectory = Path.Combine(
                Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),
                "ESAIF.ConfigWizard",
                "ApiHost");
            Directory.CreateDirectory(dataDirectory);

            var executable = GetExecutablePath();
            var startInfo = new ProcessStartInfo(executable)
            {
                CreateNoWindow = true,
                UseShellExecute = false,
                WorkingDirectory = Path.GetDirectoryName(executable)!
            };
            startInfo.ArgumentList.Add("--host");
            startInfo.ArgumentList.Add("127.0.0.1");
            startInfo.ArgumentList.Add("--port");
            startInfo.ArgumentList.Add(port.ToString(System.Globalization.CultureInfo.InvariantCulture));
            startInfo.ArgumentList.Add("--parent-pid");
            startInfo.ArgumentList.Add(
                Environment.ProcessId.ToString(System.Globalization.CultureInfo.InvariantCulture));
            startInfo.Environment["AIFACTORY_API_KEY"] = apiKey;
            using var identity = System.Security.Principal.WindowsIdentity.GetCurrent();
            startInfo.Environment["AIFACTORY_CATALOG_OWNER"] = "windows:" +
                (identity.User?.Value ?? throw new InvalidOperationException("The Windows account identity is unavailable."));
            startInfo.Environment["AIFACTORY_OPERATIONS_DB"] =
                Path.Combine(dataDirectory, "operations.db");
            startInfo.Environment["AIFACTORY_ACCELERATOR_ROOT"] =
                Path.Combine(Path.GetDirectoryName(executable)!, "accelerator");

            _process = Process.Start(startInfo) ??
                throw new InvalidOperationException("The bundled Python API did not start.");
            try
            {
                await WaitForHealthAsync(baseAddress, _process, cancellationToken)
                    .ConfigureAwait(false);
                await connections.SaveConnectionAsync(
                        new AiFactoryConnection(baseAddress, apiKey))
                    .ConfigureAwait(false);
            }
            catch
            {
                StopOwnedProcess();
                throw;
            }
        }
        finally
        {
            _lifecycle.Release();
        }
    }

    public async Task StopAsync(CancellationToken cancellationToken = default)
    {
        await _lifecycle.WaitAsync(cancellationToken).ConfigureAwait(false);
        try
        {
            StopOwnedProcess();
        }
        finally
        {
            _lifecycle.Release();
        }
    }

    public async ValueTask DisposeAsync()
    {
        await StopAsync().ConfigureAwait(false);
        _lifecycle.Dispose();
    }

    private static string GetExecutablePath() =>
        Path.Combine(AppContext.BaseDirectory, "ApiHost", "aifactory-api.exe");

    private static int FindAvailablePort()
    {
        using var listener = new TcpListener(IPAddress.Loopback, 0);
        listener.Start();
        return ((IPEndPoint)listener.LocalEndpoint).Port;
    }

    private static async Task WaitForHealthAsync(
        string baseAddress,
        Process process,
        CancellationToken cancellationToken)
    {
        using var timeout = CancellationTokenSource.CreateLinkedTokenSource(cancellationToken);
        timeout.CancelAfter(TimeSpan.FromSeconds(30));
        using var client = new HttpClient { Timeout = TimeSpan.FromSeconds(2) };
        var healthUri = new Uri($"{baseAddress}/health");

        while (true)
        {
            timeout.Token.ThrowIfCancellationRequested();
            if (process.HasExited)
            {
                throw new InvalidOperationException(
                    $"The bundled Python API exited with code {process.ExitCode}.");
            }

            try
            {
                using var response = await client.GetAsync(healthUri, timeout.Token)
                    .ConfigureAwait(false);
                if (response.IsSuccessStatusCode)
                {
                    return;
                }
            }
            catch (HttpRequestException)
            {
            }
            catch (TaskCanceledException) when (!timeout.IsCancellationRequested)
            {
            }

            await Task.Delay(TimeSpan.FromMilliseconds(250), timeout.Token)
                .ConfigureAwait(false);
        }
    }

    private void StopOwnedProcess()
    {
        if (!OperatingSystem.IsWindows())
        {
            return;
        }

        var process = _process;
        _process = null;
        if (process is null)
        {
            return;
        }

        try
        {
            if (!process.HasExited)
            {
                process.Kill(entireProcessTree: true);
                process.WaitForExit(5000);
            }
        }
        finally
        {
            process.Dispose();
        }
    }
}

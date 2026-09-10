using ESAIF.ConfigWizard.Services;
using ESAIF.DomainLayer.Configuration;

namespace ESAIF.ConfigWizard.Tests;

public sealed class BundledApiHostTests
{
    [Fact]
    public async Task MissingBundleIsAnExplicitNoOp()
    {
        var settings = new Settings();
        await using var host = new BundledApiHost(settings);

        Assert.False(host.IsAvailable);
        await host.StartAsync();
        Assert.Equal(0, settings.SaveCalls);
    }

    [Fact]
    public void WindowsBuildBundlesSelfContainedRuntimesAndExplicitAcceleratorSnapshot()
    {
        var script = File.ReadAllText(
            Path.Combine(AppContext.BaseDirectory, "Assets", "build-windows.ps1"));

        Assert.Contains("build-api.ps1", script);
        Assert.Contains("& $gitCommand clone --quiet --depth 1 --branch $AcceleratorBranch", script);
        Assert.Contains("[string]$AcceleratorBranch = \"main\"", script);
        Assert.Contains("ApiHost", script);
        Assert.Contains("AIFACTORY", script, StringComparison.OrdinalIgnoreCase);
        Assert.Contains("[string]$AcceleratorSource", script);
        Assert.Contains("\"python-api\"", script);
        Assert.Contains("\"accelerator\"", script);
        Assert.Contains("Copy-AcceleratorSnapshot.ps1", script);
        Assert.Contains("--runtime win-x64", script);
        Assert.Contains("--self-contained true", script);
        Assert.Contains("-p:WindowsAppSDKSelfContained=true", script);
        Assert.Contains("coreclr.dll", script);
        Assert.Contains("Microsoft.UI.Xaml.dll", script);
        Assert.Contains("Build-Installer.ps1", script);
        Assert.Contains("-Install is no longer supported", script);
        Assert.DoesNotContain("Remove-Item -LiteralPath $installDirectory", script);
    }

    [Fact]
    public void DurableCatalogOwnerIsIndependentOfRotatingTransportKey()
    {
        var source = File.ReadAllText(Path.Combine(AppContext.BaseDirectory, "Assets", "BundledApiHost.cs"));
        Assert.Contains("RandomNumberGenerator.GetBytes(32)", source);
        Assert.Contains("WindowsIdentity.GetCurrent()", source);
        Assert.Contains("startInfo.Environment[\"AIFACTORY_CATALOG_OWNER\"] = \"windows:\"", source);
        Assert.Contains("identity.User?.Value", source);
    }

    private sealed class Settings : IConnectionSettingsService
    {
        public int SaveCalls { get; private set; }

        public Task<AiFactoryConnection> GetConnectionAsync(
            CancellationToken cancellationToken = default) =>
            Task.FromResult(AiFactoryConnection.LocalDefault);

        public Task SaveConnectionAsync(
            AiFactoryConnection connection,
            CancellationToken cancellationToken = default)
        {
            SaveCalls++;
            return Task.CompletedTask;
        }
    }
}

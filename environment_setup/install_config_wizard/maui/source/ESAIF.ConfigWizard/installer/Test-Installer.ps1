param(
    [Parameter(Mandatory)][string]$Setup,
    [switch]$SkipDesktopLaunch
)
$ErrorActionPreference = "Stop"
$root = Split-Path $PSScriptRoot -Parent
$testRoot = Join-Path $root ("artifacts\installer-smoke-" + [Guid]::NewGuid().ToString("N"))
$app = Join-Path ([IO.Path]::GetTempPath()) ("aif-smoke-" + [Guid]::NewGuid().ToString("N").Substring(0, 8))
New-Item -ItemType Directory $testRoot -Force | Out-Null
$process = $null
$api = $null
$result = [ordered]@{ setupSha256 = (Get-FileHash $Setup -Algorithm SHA256).Hash; installed = $false; desktopLaunchRequested = (-not $SkipDesktopLaunch) }
try {
    $setupProcess = Start-Process $Setup -ArgumentList @(
        '/VERYSILENT', '/SUPPRESSMSGBOXES', '/NORESTART', '/NOCLOSEAPPLICATIONS', '/NOICONS', '/TASKS=', '/SMOKETEST=1',
        "/DIR=`"$app`"", "/LOG=`"$(Join-Path $testRoot 'install.log')`"") -Wait -PassThru
    if ($setupProcess.ExitCode -ne 0 -or -not (Test-Path (Join-Path $app "ESAIF.ConfigWizard.exe"))) {
        throw "Isolated installer smoke failed: $($setupProcess.ExitCode). See $testRoot."
    }
    $result.installed = $true
    foreach ($runtime in @("coreclr.dll", "hostfxr.dll", "hostpolicy.dll", "Microsoft.UI.Xaml.dll", "Microsoft.WindowsAppRuntime.dll")) {
        if (-not (Test-Path (Join-Path $app $runtime))) { throw "Installed app runtime missing: $runtime" }
    }
    if (-not $SkipDesktopLaunch) {
        $start = [Diagnostics.ProcessStartInfo]::new((Join-Path $app "ESAIF.ConfigWizard.exe"))
        $start.WorkingDirectory = $app
        $start.UseShellExecute = $false
        $start.Environment["DOTNET_ROOT"] = Join-Path $testRoot "no-installed-dotnet"
        $start.Environment["DOTNET_MULTILEVEL_LOOKUP"] = "0"
        $process = [Diagnostics.Process]::Start($start)
        Start-Sleep -Seconds 20
        $process.Refresh()
        if ($process.HasExited -or -not $process.Responding -or -not $process.MainWindowTitle) {
            throw "The installed desktop app did not present a responsive window."
        }
        $loaded = @()
        foreach ($name in @("coreclr.dll", "hostfxr.dll", "hostpolicy.dll", "Microsoft.UI.Xaml.dll", "Microsoft.WindowsAppRuntime.dll")) {
            $module = $process.Modules | Where-Object ModuleName -eq $name | Select-Object -First 1
            if (-not $module -or -not $module.FileName.StartsWith($app + '\', [StringComparison]::OrdinalIgnoreCase)) {
                throw "The app did not load $name from its isolated installation."
            }
            $loaded += @{ name = $name; path = $module.FileName }
        }
        $result.localRuntimeModules = $loaded
        $result.windowTitle = $process.MainWindowTitle
        $process.Kill($true)
        $process.WaitForExit(10000) | Out-Null
    }
    $listener = [Net.Sockets.TcpListener]::new([Net.IPAddress]::Loopback, 0)
    $listener.Start()
    $port = $listener.LocalEndpoint.Port
    $listener.Stop()
    $key = [Guid]::NewGuid().ToString("N")
    $start = [Diagnostics.ProcessStartInfo]::new((Join-Path $app "ApiHost\aifactory-api.exe"))
    $start.UseShellExecute = $false
    $start.CreateNoWindow = $true
    $start.WorkingDirectory = Join-Path $app "ApiHost"
    foreach ($argument in @("--host", "127.0.0.1", "--port", "$port", "--parent-pid", "$PID")) {
        $start.ArgumentList.Add($argument)
    }
    $start.Environment["AIFACTORY_API_KEY"] = $key
    $start.Environment["AIFACTORY_CATALOG_OWNER"] = "installer-smoke"
    $start.Environment["AIFACTORY_OPERATIONS_DB"] = Join-Path $testRoot "operations.db"
    $start.Environment["AIFACTORY_ACCELERATOR_ROOT"] = Join-Path $app "ApiHost\accelerator"
    $start.Environment["PATH"] = "$env:SystemRoot\System32;$env:SystemRoot"
    $api = [Diagnostics.Process]::Start($start)
    $health = $null
    for ($attempt = 0; $attempt -lt 100; $attempt++) {
        if ($api.HasExited) { throw "The installed frozen API exited with code $($api.ExitCode)." }
        try {
            $health = Invoke-RestMethod "http://127.0.0.1:$port/health" -TimeoutSec 2
            break
        }
        catch { Start-Sleep -Milliseconds 250 }
    }
    if ($health.status -ne "ok") { throw "The installed API did not become healthy." }
    $schema = Invoke-RestMethod "http://127.0.0.1:$port/api/v1/schema" -Headers @{"X-API-Key" = $key} -TimeoutSec 15
    if (-not $schema.defaults -or $schema.formats.Count -lt 3) { throw "API template/schema defaults are missing." }
    foreach ($template in @(".env", "variables.json", "variables.yaml")) {
        if (-not (Test-Path (Join-Path $app "ApiHost\_internal\template-files\$template"))) {
            throw "Bundled template missing: $template."
        }
    }
    $result.health = $health
    $result.schemaFormats = $schema.formats
    $result.schemaDefaultCount = @($schema.defaults.PSObject.Properties).Count
    $result.templatesPresent = $true
    foreach ($runtime in @("_tkinter.pyd", "tcl86t.dll", "tk86t.dll")) {
        if (-not (Test-Path (Join-Path $app "ApiHost\_internal\$runtime"))) { throw "Installed Tcl/Tk runtime missing: $runtime" }
    }
    if (-not (Get-ChildItem (Join-Path $app "ApiHost\_internal") -Filter "python3*.dll")) { throw "Installed Python runtime missing." }
    $result.pythonAndTkPresent = $true
    $result.pythonOnPath = $false
    $result.passed = $true
}
finally {
    foreach ($owned in @($api, $process)) {
        if ($owned -and -not $owned.HasExited) {
            $owned.Kill($true)
            $owned.WaitForExit(10000) | Out-Null
        }
        if ($owned) { $owned.Dispose() }
    }
    $uninstaller = Join-Path $app "unins000.exe"
    if (Test-Path $uninstaller) {
        $uninstall = Start-Process $uninstaller -ArgumentList @('/VERYSILENT', '/SUPPRESSMSGBOXES', '/NORESTART') -Wait -PassThru
        $result.uninstalled = $uninstall.ExitCode -eq 0 -and -not (Test-Path (Join-Path $app "ESAIF.ConfigWizard.exe"))
    }
    $result | ConvertTo-Json -Depth 8 | Set-Content (Join-Path $testRoot "result.json") -Encoding utf8
}
if (-not $result.uninstalled) { throw "Isolated installer uninstall did not complete: $testRoot" }
Write-Host "Installation, API, runtime files, templates and uninstall passed (desktop launch: $(-not $SkipDesktopLaunch)): $testRoot" -ForegroundColor Green

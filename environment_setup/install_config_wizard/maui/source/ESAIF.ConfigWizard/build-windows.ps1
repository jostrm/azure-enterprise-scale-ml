param(
    [string]$ApiSource,
    [string]$AcceleratorRepository = "https://github.com/jostrm/azure-enterprise-scale-ml.git",
    [string]$AcceleratorBranch = "main",
    [string]$AcceleratorSource,
    [string]$Python,
    [string]$DotNet,
    [string]$InstallerCompiler,
    [ValidatePattern('^\d+\.\d+\.\d+(\.\d+)?$')]
    [string]$Version = "1.0.0",
    [switch]$SkipInstaller,
    [switch]$SkipApiRestore,
    [switch]$SkipApiBuild,
    [switch]$Install
)

$ErrorActionPreference = "Stop"
$root = $PSScriptRoot
if (-not $ApiSource) {
    $siblingApi = Join-Path (Split-Path $root -Parent) "python-api"
    if (Test-Path (Join-Path $siblingApi "build-api.ps1")) { $ApiSource = $siblingApi }
    else { $ApiSource = "C:\code\code_py_25\008_aifactory_admin_ux_tkinter" }
}
if (-not $AcceleratorSource) {
    $siblingAccelerator = Join-Path (Split-Path $root -Parent) "accelerator"
    if (Test-Path $AcceleratorRepository -PathType Container) {
        $AcceleratorSource = $AcceleratorRepository
    }
    elseif (-not $PSBoundParameters.ContainsKey("AcceleratorRepository") -and
        (Test-Path (Join-Path $siblingAccelerator "bootstrap\GHA-create-new-aifactory-scaleset.sh"))) {
        $AcceleratorSource = $siblingAccelerator
    }
}
if ($Install) {
    throw "-Install is no longer supported: use the generated per-user setup installer. Existing installations are not deleted by this build."
}
$tooling = Join-Path $root "installer"
$dotnetFallback = Join-Path $env:ProgramFiles "dotnet\dotnet.exe"
if (-not $DotNet) {
    $DotNet = (Get-Command dotnet.exe -ErrorAction SilentlyContinue).Source
    if (-not $DotNet -and (Test-Path $dotnetFallback)) { $DotNet = $dotnetFallback }
}
if (-not $DotNet) { throw "The .NET 10 SDK and Windows MAUI workload are required to build." }
if (-not $Python) {
    $venvPython = Join-Path $ApiSource ".venv\Scripts\python.exe"
    if (Test-Path $venvPython) { $Python = $venvPython }
    else { $Python = "python" }
}
$project = Join-Path $root "src\ESAIF.ConfigWizard\ESAIF.ConfigWizard.csproj"
$staging = Join-Path $root "artifacts\windows-staging"
$publish = Join-Path $root "artifacts\windows"
$apiOutput = Join-Path $staging "api"
$accelerator = Join-Path $apiOutput "aifactory-api\accelerator"

if (Test-Path -LiteralPath $publish) {
    Remove-Item -LiteralPath $publish -Recurse -Force
}
if (-not $SkipApiBuild -and (Test-Path -LiteralPath $staging)) {
    Remove-Item -LiteralPath $staging -Recurse -Force
}

if (-not (Test-Path -LiteralPath (Join-Path $ApiSource "build-api.ps1") -PathType Leaf)) {
    throw "The Python API source was not found at $ApiSource."
}

if (-not $SkipApiBuild) {
    & (Join-Path $ApiSource "build-api.ps1") `
        -OutputRoot $apiOutput `
        -WorkRoot (Join-Path $staging "pyinstaller") `
        -Python $Python `
        -SkipRestore:$SkipApiRestore
    if ($LASTEXITCODE -ne 0) {
        throw "The Python API build failed."
    }
}
elseif (-not (Test-Path -LiteralPath (Join-Path $apiOutput "aifactory-api\aifactory-api.exe") -PathType Leaf)) {
    throw "No staged Python API build is available to reuse."
}

$gitCommand = (Get-Command git.exe -ErrorAction SilentlyContinue).Source
if (-not $gitCommand) {
    $fallbackGit = Join-Path $env:ProgramFiles "Git\cmd\git.exe"
    if (Test-Path -LiteralPath $fallbackGit -PathType Leaf) {
        $gitCommand = $fallbackGit
    }
}
if (-not $gitCommand) {
    throw "Git for Windows is required to bundle the accelerator clone."
}
if (Test-Path -LiteralPath $accelerator) {
    Remove-Item -LiteralPath $accelerator -Recurse -Force
}
if ($AcceleratorSource) {
    & (Join-Path $tooling "Copy-AcceleratorSnapshot.ps1") -Source $AcceleratorSource -Destination $accelerator
}
else {
    Write-Warning "No explicit accelerator snapshot: bundling remote branch $AcceleratorBranch, not local unpublished changes."
    & $gitCommand clone --quiet --depth 1 --branch $AcceleratorBranch $AcceleratorRepository $accelerator
    if ($LASTEXITCODE -ne 0) { throw "The accelerator source clone failed." }
    $recursiveInstaller = Join-Path $accelerator "environment_setup\install_config_wizard"
    if (Test-Path $recursiveInstaller) { Remove-Item $recursiveInstaller -Recurse -Force }
}
$bootstrapScript = Join-Path $accelerator "bootstrap\GHA-create-new-aifactory-scaleset.sh"
if (-not (Test-Path -LiteralPath $bootstrapScript -PathType Leaf)) {
    throw "The selected accelerator branch does not contain the Simple Mode bootstrap."
}

# Restrict the MAUI restore to Windows without imposing its TFM on net10.0 libraries.
& $DotNet restore $project -p:TargetFrameworks=net10.0-windows10.0.19041.0 `
    --runtime win-x64 -p:SelfContained=true -p:WindowsAppSDKSelfContained=true
if ($LASTEXITCODE -ne 0) { throw "Windows MAUI restore failed." }
[xml]$projectXml = Get-Content $project
foreach ($reference in $projectXml.Project.ItemGroup.ProjectReference) {
    if (-not $reference.Include) { continue }
    $referencePath = [IO.Path]::GetFullPath((Join-Path (Split-Path $project) $reference.Include))
    & $DotNet restore $referencePath --runtime win-x64 -p:SelfContained=true
    if ($LASTEXITCODE -ne 0) { throw "Shared library restore failed: $referencePath" }
}
& $DotNet publish $project `
    --no-restore `
    --configuration Release `
    --framework net10.0-windows10.0.19041.0 `
    -p:TargetFrameworks=net10.0-windows10.0.19041.0 `
    --runtime win-x64 `
    --self-contained true `
    -p:WindowsPackageType=None `
    -p:WindowsAppSDKSelfContained=true `
    -p:PublishSingleFile=false `
    -p:PublishTrimmed=false `
    "-p:ApplicationDisplayVersion=$Version" `
    --output $publish
if ($LASTEXITCODE -ne 0) {
    throw "The Windows MAUI publish failed."
}

Copy-Item `
    -LiteralPath (Join-Path $apiOutput "aifactory-api") `
    -Destination (Join-Path $publish "ApiHost") `
    -Recurse `
    -Force

$executable = Join-Path $publish "ESAIF.ConfigWizard.exe"
if (-not (Test-Path -LiteralPath $executable -PathType Leaf)) {
    throw "The Windows app executable was not created."
}

foreach ($runtimeFile in @("coreclr.dll", "hostfxr.dll", "hostpolicy.dll", "Microsoft.UI.Xaml.dll", "Microsoft.WindowsAppRuntime.dll")) {
    if (-not (Test-Path (Join-Path $publish $runtimeFile))) {
        throw "Self-contained publish is incomplete: missing $runtimeFile."
    }
}
$runtimeConfig = Get-Content (Join-Path $publish "ESAIF.ConfigWizard.runtimeconfig.json") -Raw | ConvertFrom-Json
if ($runtimeConfig.runtimeOptions.framework -or $runtimeConfig.runtimeOptions.frameworks) {
    throw "The published app still requires an installed .NET runtime."
}
Copy-Item (Join-Path $tooling "SUPPORT.txt") (Join-Path $publish "SUPPORT.txt")
& $Python (Join-Path $tooling "collect-licenses.py") --root $root --output (Join-Path $publish "Licenses") --accelerator $accelerator --publish $publish
if ($LASTEXITCODE -ne 0) { throw "Dependency license collection failed." }
$acceleratorFiles = @(Get-ChildItem $accelerator -File -Recurse -Force |
    Where-Object { $_.FullName -notlike "$accelerator\.git\*" } |
    Sort-Object FullName |
    ForEach-Object {
        @{
            path = [IO.Path]::GetRelativePath($accelerator, $_.FullName)
            sha256 = (Get-FileHash $_.FullName -Algorithm SHA256).Hash
        }
    })
[ordered]@{
    applicationVersion = $Version
    builtAtUtc = [DateTime]::UtcNow.ToString("o")
    runtimeIdentifier = "win-x64"
    selfContainedDotNet = $true
    selfContainedWindowsAppSdk = $true
    dotNetRuntime = $runtimeConfig.runtimeOptions.includedFrameworks
    apiExecutableSha256 = (Get-FileHash (Join-Path $publish "ApiHost\aifactory-api.exe")).Hash
    acceleratorSource = $(if ($AcceleratorSource) { "explicit-local-snapshot" } else { "$AcceleratorRepository@$AcceleratorBranch" })
    acceleratorHasGitMetadata = (Test-Path (Join-Path $accelerator ".git"))
    acceleratorFiles = $acceleratorFiles
} | ConvertTo-Json -Depth 8 | Set-Content (Join-Path $publish "BUILD-INFO.json") -Encoding utf8
if (-not $SkipInstaller) {
    & (Join-Path $tooling "Build-Installer.ps1") -PublishDirectory $publish -Version $Version -Compiler $InstallerCompiler
}

Write-Host "Windows app: $executable" -ForegroundColor Green

[CmdletBinding()]
param(
    [string]$Destination = (Join-Path $PSScriptRoot "artifacts\accelerator-source"),
    [ValidatePattern('^[0-9a-f]{40}$')]
    [string]$Revision = "fa91eba28ce6e6c94a1f3866671a181718c580f0",
    [string]$Git
)

$ErrorActionPreference = "Stop"
if (-not $Git) {
    $Git = (Get-Command git.exe -ErrorAction SilentlyContinue).Source
    if (-not $Git) { $Git = Join-Path $env:ProgramFiles "Git\cmd\git.exe" }
}
if (-not (Test-Path -LiteralPath $Git)) { throw "Git for Windows is required." }
if (Test-Path -LiteralPath $Destination) { throw "Choose a new, empty snapshot destination: $Destination" }
New-Item -ItemType Directory -Path (Split-Path ([IO.Path]::GetFullPath($Destination))) -Force | Out-Null

function Invoke-Git([string[]]$Arguments) {
    & $Git @Arguments
    if ($LASTEXITCODE -ne 0) { throw "Git failed while preparing the pinned accelerator source." }
}

$remote = "https://github.com/jostrm/azure-enterprise-scale-ml.git"
Invoke-Git @("clone", "--quiet", "--depth", "1", "--no-checkout", "--filter=blob:none", $remote, $Destination)
Invoke-Git @("-C", $Destination, "config", "--local", "core.longpaths", "true")
$head = Invoke-Git @("-C", $Destination, "rev-parse", "HEAD")
if ($head.Trim() -ne $Revision) {
    Invoke-Git @("-C", $Destination, "fetch", "--quiet", "--depth", "1", "origin", $Revision)
}
Invoke-Git @("-C", $Destination, "sparse-checkout", "set", "--no-cone",
    "/bootstrap/", "/environment_setup/", "!/environment_setup/install_config_wizard/", "/.github/", "/LICENSE", "/00-start.sh")
Invoke-Git @("-C", $Destination, "checkout", "--quiet", "--detach", $Revision)

# Backend readiness uses exact Git objects, not just the visible source files.
$archive = Join-Path $Destination ".git\source-hydration.tar"
try {
    Invoke-Git @("-C", $Destination, "archive", "--format=tar", "-o", $archive, $Revision)
}
finally {
    if (Test-Path -LiteralPath $archive) { Remove-Item -LiteralPath $archive }
}
foreach ($directory in @(".git\hooks", ".git\logs")) {
    $path = Join-Path $Destination $directory
    if (Test-Path -LiteralPath $path) { Remove-Item -LiteralPath $path -Recurse -Force }
}
if (Invoke-Git @("-C", $Destination, "status", "--porcelain")) { throw "The source snapshot is not clean." }
Write-Host "Pinned accelerator $Revision prepared at $Destination"

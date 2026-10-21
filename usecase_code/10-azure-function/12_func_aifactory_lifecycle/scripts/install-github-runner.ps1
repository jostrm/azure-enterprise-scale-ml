<#
.SYNOPSIS
  Install and register a GitHub Actions runner as a Windows service for ONE repository. Runs ON the management VM.

.DESCRIPTION
  Repositories owned by a user account can't share runners, so the management VM gets one runner instance (folder
  and service) per factory repository, all with the same label (default aif-lifecycle-mgmt) and never the factory's
  own runner label. The package hash is verified before anything is extracted. Windows PowerShell 5.1 compatible.

  Usually started from the laptop by register-management-runner.ps1 (VM run command, token as a protected parameter).
#>
param(
    [Parameter(Mandatory = $true)] [string] $RepositoryUrl,
    [Parameter(Mandatory = $true)] [string] $RegistrationToken,
    [Parameter(Mandatory = $true)] [string] $RunnerName,
    [string] $Labels = 'aif-lifecycle-mgmt',
    [string] $Version = '2.338.0',
    [string] $Sha256 = 'f48e0750a21812bca5f82de5f7f5aeae71abee647fab5a582f1742d07eba455f',
    [string] $Root = 'C:\actions-runners'
)

$ErrorActionPreference = 'Stop'
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
if ($RepositoryUrl -notmatch '^https://github\.com/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$') { throw 'RepositoryUrl must be https://github.com/<owner>/<repo>.' }
if ($Labels -notmatch '^[A-Za-z0-9_.,-]+$') { throw 'Labels must be letters, digits, dots, dashes, underscores or commas.' }

$repository = ($RepositoryUrl -split '/')[-1]
$directory = Join-Path $Root $repository
if (Test-Path -LiteralPath (Join-Path $directory '.runner')) {
    Write-Output "A runner is already configured in $directory; nothing to do."
    exit 0
}
New-Item -ItemType Directory -Force -Path $directory | Out-Null

$package = Join-Path $env:TEMP "actions-runner-win-x64-$Version.zip"
Invoke-WebRequest -UseBasicParsing -OutFile $package `
    -Uri "https://github.com/actions/runner/releases/download/v$Version/actions-runner-win-x64-$Version.zip"
$hash = (Get-FileHash -Algorithm SHA256 -LiteralPath $package).Hash.ToLowerInvariant()
if ($hash -ne $Sha256.ToLowerInvariant()) {
    Remove-Item -LiteralPath $package -Force
    throw "Runner package hash $hash does not match the expected $Sha256."
}
Add-Type -AssemblyName System.IO.Compression.FileSystem
[IO.Compression.ZipFile]::ExtractToDirectory($package, $directory)
Remove-Item -LiteralPath $package -Force

Push-Location -LiteralPath $directory
try {
    & .\config.cmd --unattended --url $RepositoryUrl --token $RegistrationToken --name $RunnerName --labels $Labels `
        --work _work --runasservice --replace
    if ($LASTEXITCODE -ne 0) { throw "config.cmd failed with exit code $LASTEXITCODE." }
}
finally {
    Pop-Location
}
Get-Service -Name 'actions.runner.*' | Where-Object { $_.Name -like "*$repository*" } |
    ForEach-Object { Write-Output "$($_.Name): $($_.Status)" }

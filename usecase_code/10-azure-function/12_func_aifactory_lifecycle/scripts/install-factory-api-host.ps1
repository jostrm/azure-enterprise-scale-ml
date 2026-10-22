<#
.SYNOPSIS
    Installs the Factory API (a pinned AI Factory Config Wizard release in API-only mode) as a loopback service on the
    management VM. Runs ON the VM as SYSTEM, for example through `az vm run-command`.

.DESCRIPTION
    The Factory API runs az, gh and git with its own Windows user's logins and passes no token variables to them, and
    it seals confirmations for that user. This script makes SYSTEM that user:
    - gh is logged in for SYSTEM with a GitHub token read from Key Vault by the VM's managed identity (never printed),
      with gh as git's credential helper, a git identity and long paths (the API publishes to the factory repo).
      A classic PAT needs the scopes repo, workflow and read:org; the script checks them before it changes anything;
    - az for SYSTEM must already be logged in with `az login --identity` (the managed identity needs the factory
      subscription's Owner role, plus Microsoft Graph Group.ReadWrite.All and User.Read.All for the team group);
    - the pinned release asset is downloaded with gh and checked against the release's SHA256SUMS.txt;
    - start-api.ps1 reads the API key from Key Vault at every start and runs `aifactory-config.exe --api-host`;
    - a scheduled task runs it as SYSTEM at startup and restarts it on failure.
    Windows PowerShell 5.1 compatible.

.EXAMPLE
    .\install-factory-api-host.ps1 -KeyVaultName kv-p001-sdc-dev-bltsc01
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory)][string]$KeyVaultName,
    [string]$ApiKeySecretName = 'aif-factory-api-key',
    [string]$GitHubTokenSecretName = 'aif-factory-api-gh-token',
    [string]$Release = 'v0.47.29',
    [string]$Repository = 'jostrm/azure-aifactory-config',
    [string]$Asset = 'aifactory-config-windows.zip',
    [string]$InstallRoot = 'C:\aif-api',
    [string]$ConsumerRoot = 'C:\aif',
    [int]$Port = 8765,
    [string]$CatalogOwner = 'aif-lifecycle-mgmt',
    [string]$GitUserName = 'AI Factory lifecycle',
    [string]$GitUserEmail = 'aif-lifecycle@users.noreply.github.com',
    [string]$TaskName = 'AIFactoryApi'
)
$ErrorActionPreference = 'Stop'
[Net.ServicePointManager]::SecurityProtocol = [Net.ServicePointManager]::SecurityProtocol -bor [Net.SecurityProtocolType]::Tls12
if ($KeyVaultName -notmatch '^[A-Za-z0-9-]{3,24}$') { throw 'KeyVaultName is not a vault name.' }

function Invoke-Native([string]$File, [string[]]$Arguments) {
    & $File @Arguments
    if ($LASTEXITCODE -ne 0) { throw "$File $($Arguments -join ' ') failed with exit code $LASTEXITCODE" }
}

function Get-VaultSecret([string]$Name) {
    $imds = 'http://169.254.169.254/metadata/identity/oauth2/token?api-version=2018-02-01&resource=https%3A%2F%2Fvault.azure.net'
    $token = (Invoke-RestMethod -Headers @{ Metadata = 'true' } -Uri $imds -TimeoutSec 15).access_token
    $uri = "https://$KeyVaultName.vault.azure.net/secrets/$Name`?api-version=7.4"
    return (Invoke-RestMethod -Headers @{ Authorization = "Bearer $token" } -Uri $uri -TimeoutSec 15).value
}

function Get-MissingGitHubScope([string]$Granted) {
    # A classic token for the API host: gh auth login requires repo and read:org (write:org and admin:org include it),
    # and the bootstrap pushes workflow files to the factory repo, which needs workflow.
    $have = @($Granted -split ',' | ForEach-Object { $_.Trim() } | Where-Object { $_ })
    $missing = @()
    if ($have -notcontains 'repo') { $missing += 'repo' }
    if ($have -notcontains 'workflow') { $missing += 'workflow' }
    if (-not ($have | Where-Object { @('read:org', 'write:org', 'admin:org') -contains $_ })) { $missing += 'read:org' }
    return $missing
}

function Assert-GitHubTokenScope([string]$Token) {
    $response = Invoke-WebRequest -UseBasicParsing -Uri 'https://api.github.com/user' -TimeoutSec 15 `
        -Headers @{ Authorization = "token $Token"; 'User-Agent' = 'aif-factory-api-host' }
    if (-not $response.Headers.ContainsKey('X-OAuth-Scopes')) { return }  # fine-grained tokens list no scopes
    $missing = @(Get-MissingGitHubScope ([string]::Join(',', @($response.Headers['X-OAuth-Scopes']))))
    if ($missing.Count) {
        throw ("The GitHub token in Key Vault secret '$GitHubTokenSecretName' lacks $($missing -join ', '). " +
               'A classic PAT for the API host needs repo, workflow and read:org.')
    }
}

# The GitHub token is checked before anything changes; it goes from Key Vault to gh's stdin, never written or printed.
$token = Get-VaultSecret $GitHubTokenSecretName
Assert-GitHubTokenScope $token

foreach ($folder in @($InstallRoot, $ConsumerRoot)) {
    New-Item -ItemType Directory -Force -Path $folder | Out-Null
    # SYSTEM and Administrators only: the runner account calls the API over loopback and never needs these folders.
    Invoke-Native icacls @($folder, '/inheritance:r', '/grant:r', '*S-1-5-18:(OI)(CI)F', '*S-1-5-32-544:(OI)(CI)F', '/Q')
    Invoke-Native icacls @((Join-Path $folder '*'), '/reset', '/T', '/C', '/Q')
}

# GitHub for SYSTEM.
$token | gh auth login --hostname github.com --with-token
if ($LASTEXITCODE -ne 0) { throw 'gh auth login failed.' }
$token = $null
Invoke-Native gh @('auth', 'setup-git', '--hostname', 'github.com')
Invoke-Native git @('config', '--global', 'user.name', $GitUserName)
Invoke-Native git @('config', '--global', 'user.email', $GitUserEmail)
Invoke-Native git @('config', '--global', 'core.longpaths', 'true')
Write-Output ("gh: " + ((& gh api user --jq .login) -join ''))

# The pinned release, checked against its SHA256SUMS.txt.
$target = Join-Path $InstallRoot $Release
if (-not (Test-Path (Join-Path $target 'installed.txt'))) {
    $download = Join-Path $InstallRoot 'download'
    Remove-Item -Recurse -Force $download -ErrorAction SilentlyContinue
    Invoke-Native gh @('release', 'download', $Release, '--repo', $Repository, '--pattern', $Asset, '--pattern',
                       'SHA256SUMS.txt', '--dir', $download)
    $expected = (Get-Content (Join-Path $download 'SHA256SUMS.txt') | Where-Object { $_ -match "\s\*?$([regex]::Escape($Asset))$" } |
        ForEach-Object { ($_ -split '\s+')[0] } | Select-Object -First 1)
    $actual = (Get-FileHash (Join-Path $download $Asset) -Algorithm SHA256).Hash
    if (-not $expected -or $actual -ne $expected.ToUpperInvariant()) { throw "$Asset does not match SHA256SUMS.txt." }
    Remove-Item -Recurse -Force $target -ErrorAction SilentlyContinue
    Expand-Archive -Path (Join-Path $download $Asset) -DestinationPath $target
    Set-Content -Path (Join-Path $target 'installed.txt') -Value "$Release $actual"
    Remove-Item -Recurse -Force $download
}
$exe = Get-ChildItem -Path $target -Recurse -Filter 'aifactory-config.exe' | Select-Object -First 1 -ExpandProperty FullName
if (-not $exe) { throw "aifactory-config.exe not found under $target." }

# The service script reads the API key at every start, so rotating it in Key Vault needs only a restart.
$start = @"
`$ErrorActionPreference = 'Stop'
`$imds = 'http://169.254.169.254/metadata/identity/oauth2/token?api-version=2018-02-01&resource=https%3A%2F%2Fvault.azure.net'
`$token = (Invoke-RestMethod -Headers @{ Metadata = 'true' } -Uri `$imds -TimeoutSec 15).access_token
`$env:AIFACTORY_API_KEY = (Invoke-RestMethod -Headers @{ Authorization = "Bearer `$token" } -Uri 'https://$KeyVaultName.vault.azure.net/secrets/$ApiKeySecretName`?api-version=7.4' -TimeoutSec 15).value
`$env:AIFACTORY_CATALOG_OWNER = '$CatalogOwner'
& '$exe' --api-host --port $Port
exit `$LASTEXITCODE
"@
$startScript = Join-Path $InstallRoot 'start-api.ps1'
Set-Content -Path $startScript -Value $start -Encoding UTF8

$action = New-ScheduledTaskAction -Execute 'powershell.exe' -Argument "-NoProfile -ExecutionPolicy Bypass -File `"$startScript`""
$principal = New-ScheduledTaskPrincipal -UserId 'SYSTEM' -LogonType ServiceAccount -RunLevel Highest
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -RestartCount 999 -RestartInterval (New-TimeSpan -Minutes 1) `
    -ExecutionTimeLimit ([TimeSpan]::Zero) -MultipleInstances IgnoreNew
Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger (New-ScheduledTaskTrigger -AtStartup) -Principal $principal `
    -Settings $settings -Force | Out-Null
Stop-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
Start-ScheduledTask -TaskName $TaskName

$deadline = (Get-Date).AddSeconds(90)
while ((Get-Date) -lt $deadline) {
    try {
        $health = Invoke-RestMethod -Uri "http://127.0.0.1:$Port/health" -TimeoutSec 5
        Write-Output "Factory API $Release is up on 127.0.0.1:$Port ($($health.status))."
        return
    } catch { Start-Sleep -Seconds 3 }
}
throw "The Factory API did not answer on 127.0.0.1:$Port within 90 s; check the $TaskName task."

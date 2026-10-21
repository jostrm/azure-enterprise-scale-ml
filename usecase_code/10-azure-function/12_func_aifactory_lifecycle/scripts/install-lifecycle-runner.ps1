<#
.SYNOPSIS
    Installs the lifecycle runner entry point on the management VM (AIF_EXECUTOR=github-runner). Runs ON the VM.

.DESCRIPTION
    Checks out this template from the public purple repository at a pinned commit, creates a virtual environment with
    its requirements and writes runner.json. aif-ops.yml then runs
    `<InstallRoot>\venv\Scripts\python.exe -P -m aif_lifecycle.runner` with PYTHONPATH=<InstallRoot>\app as the runner
    service account, which gets read and execute rights only. Re-run it with a new commit to update.
    Windows PowerShell 5.1 compatible, so it can run through `az vm run-command`.

.EXAMPLE
    .\install-lifecycle-runner.ps1 -Commit <40-char sha> -FactoryFolder C:\aif\byor-122\azurefactory `
        -KeyVaultName kv-p001-sdc-dev-bltsc01
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory)][string]$Commit,
    [Parameter(Mandatory)][string]$FactoryFolder,
    [Parameter(Mandatory)][string]$KeyVaultName,
    [string]$ApiKeySecretName = 'aif-factory-api-key',
    [string]$ApiUrl = 'http://127.0.0.1:8765',
    [string]$InstallRoot = 'C:\aif-lifecycle',
    [string]$Python = 'C:\Program Files\AIFactory\Python312\python.exe',
    [string]$Repository = 'https://github.com/jostrm/azure-enterprise-scale-ml.git',
    [string]$RunnerSid = 'S-1-5-20'  # NETWORK SERVICE, the runner service's default account
)
$ErrorActionPreference = 'Stop'
if ($Commit -notmatch '^[0-9a-f]{40}$') { throw 'Commit must be a full 40-character SHA.' }
if ($ApiUrl -notmatch '^http://(127\.0\.0\.1|localhost)(:\d+)?$') { throw 'ApiUrl must be a loopback http URL.' }
if (-not (Test-Path $Python)) { throw "Python not found: $Python" }

$template = 'usecase_code/10-azure-function/12_func_aifactory_lifecycle'
$source = Join-Path $InstallRoot 'src'
$app = Join-Path $InstallRoot 'app'
$venv = Join-Path $InstallRoot 'venv'
New-Item -ItemType Directory -Force -Path $InstallRoot | Out-Null

function Invoke-Native([string]$File, [string[]]$Arguments) {
    & $File @Arguments
    if ($LASTEXITCODE -ne 0) { throw "$File $($Arguments -join ' ') failed with exit code $LASTEXITCODE" }
}

if (-not (Test-Path (Join-Path $source '.git'))) {
    Invoke-Native git @('clone', '--filter=blob:none', '--no-checkout', '--sparse', $Repository, $source)
}
Invoke-Native git @('-C', $source, 'sparse-checkout', 'set', $template)
Invoke-Native git @('-C', $source, 'fetch', '--depth', '1', 'origin', $Commit)
Invoke-Native git @('-C', $source, 'checkout', '--force', '--detach', $Commit)

# Mirror the template without its tests and local state.
& robocopy (Join-Path $source $template) $app /MIR /NFL /NDL /NJH /NJS /NP /XD tests __pycache__ .venv /XF local.settings.json
if ($LASTEXITCODE -ge 8) { throw "robocopy failed with exit code $LASTEXITCODE" }

if (-not (Test-Path (Join-Path $venv 'Scripts\python.exe'))) { Invoke-Native $Python @('-m', 'venv', $venv) }
Invoke-Native (Join-Path $venv 'Scripts\python.exe') @('-m', 'pip', 'install', '--disable-pip-version-check',
                                                      '--quiet', '-r', (Join-Path $app 'requirements.txt'))

$settings = [ordered]@{
    AIF_FACTORY_API_URL      = $ApiUrl
    AIF_FACTORY_FOLDER       = $FactoryFolder
    AIF_KEY_VAULT_NAME       = $KeyVaultName
    AIF_FACTORY_API_KEY_NAME = $ApiKeySecretName
}
$json = $settings | ConvertTo-Json
[IO.File]::WriteAllText((Join-Path $InstallRoot 'runner.json'), $json, (New-Object Text.UTF8Encoding $false))

# Only SYSTEM and Administrators may change the install; the runner service account reads and runs it. Inheritance is
# removed because C:\ lets Authenticated Users modify new folders, which would let one job rewrite the runner code.
Invoke-Native icacls @($InstallRoot, '/inheritance:r', '/grant:r', '*S-1-5-18:(OI)(CI)F', '*S-1-5-32-544:(OI)(CI)F',
                       "*${RunnerSid}:(OI)(CI)RX", '/T', '/Q')
Write-Output "Lifecycle runner installed at $InstallRoot from $Commit."

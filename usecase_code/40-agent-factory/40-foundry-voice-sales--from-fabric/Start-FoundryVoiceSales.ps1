#requires -Version 7.2
[CmdletBinding()]
param(
    [ValidateSet('Check', 'Setup', 'Validate', 'Diagnose', 'Connectivity', 'Discover',
        'Publish', 'Text', 'Smoke', 'Start', 'Stop', 'Test')]
    [string] $Action = 'Check',
    [string] $EnvFile = '',
    [string] $PythonExecutable = 'python',
    [switch] $Notebook,
    [switch] $AllowAzure,
    [switch] $RequirePrivate,
    [string] $Question = '',
    [ValidateRange(1024, 65535)]
    [int] $Port = 8765,
    [switch] $OpenBrowser
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$root = [System.IO.Path]::GetFullPath($PSScriptRoot)
$venvPython = Join-Path $root '.venv\Scripts\python.exe'
if (-not $IsWindows) { $venvPython = Join-Path $root '.venv/bin/python' }

function Invoke-LocalExecutable {
    param([string] $Executable, [string[]] $Arguments)
    $startInfo = [System.Diagnostics.ProcessStartInfo]::new()
    $startInfo.FileName = $Executable
    $startInfo.WorkingDirectory = $root
    $startInfo.UseShellExecute = $false
    foreach ($argument in $Arguments) { $startInfo.ArgumentList.Add($argument) }
    $process = [System.Diagnostics.Process]::Start($startInfo)
    try {
        $process.WaitForExit()
        if ($process.ExitCode -ne 0) {
            throw "Local command failed (exit $($process.ExitCode)). See the diagnostic above."
        }
    }
    finally { $process.Dispose() }
}

function Get-BootstrapPython {
    $command = Get-Command $PythonExecutable -CommandType Application -ErrorAction Stop | Select-Object -First 1
    return $command.Source
}

function Assert-Python313 {
    param([string] $Executable)
    Invoke-LocalExecutable $Executable @(
        '-c',
        'import sys; print("Python " + sys.version.split()[0]); sys.exit(0 if sys.version_info[:2] == (3, 13) else "Python 3.13 is required; select it with -PythonExecutable.")'
    )
}

function Assert-Venv {
    if (-not (Test-Path -LiteralPath $venvPython -PathType Leaf)) {
        throw 'Local .venv is missing. Run -Action Setup first; no global packages are installed.'
    }
}

try {
    if ($Notebook -and $Action -ne 'Setup') {
        throw '-Notebook applies only to -Action Setup.'
    }
    $onlineActions = @('Diagnose', 'Connectivity', 'Discover', 'Publish', 'Text', 'Smoke', 'Start')
    if ($Action -in $onlineActions -and -not $AllowAzure) {
        throw "$Action requires -AllowAzure. The default Check action is offline."
    }
    if ($Action -in @('Text', 'Smoke') -and [string]::IsNullOrWhiteSpace($Question)) {
        throw "$Action requires -Question with an approved sales question."
    }
    if ($RequirePrivate -and $Action -ne 'Connectivity') {
        throw '-RequirePrivate applies only to -Action Connectivity.'
    }
    if ($OpenBrowser -and $Action -ne 'Start') {
        throw '-OpenBrowser applies only to -Action Start.'
    }

    if ($Action -eq 'Check') {
        Write-Host 'Checking local prerequisites only; no installs, sign-in, or Azure requests.'
        Assert-Python313 (Get-BootstrapPython)
        $null = Get-Command git -CommandType Application -ErrorAction Stop
        Write-Host "PowerShell $($PSVersionTable.PSVersion): OK; Git: available."
        if (Get-Command az -ErrorAction SilentlyContinue) {
            Write-Host 'Azure CLI: available (not invoked).'
        }
        else { Write-Warning 'Azure CLI is missing; an administrator must install it before Azure actions.' }
        if (Get-Command node -CommandType Application -ErrorAction SilentlyContinue) {
            Write-Host 'Node: available (needed only for offline UI tests).'
        }
        else { Write-Warning 'Node is missing; text and voice runtime do not require Node, but UI tests do.' }
        Write-Host 'Next: Setup, prepare .env, then Validate. Azure access is not checked here.'
        return
    }

    if ($Action -eq 'Setup') {
        $bootstrap = Get-BootstrapPython
        Assert-Python313 $bootstrap
        $lockName = if ($Notebook) { 'requirements-notebook.lock.txt' } else { 'requirements.lock.txt' }
        $lockFile = Join-Path $root $lockName
        if (-not (Test-Path -LiteralPath $lockFile -PathType Leaf)) {
            throw "$lockName is missing; restore the complete template before Setup."
        }
        if (-not (Test-Path -LiteralPath $venvPython -PathType Leaf)) {
            Invoke-LocalExecutable $bootstrap @('-m', 'venv', (Join-Path $root '.venv'))
        }
        Assert-Python313 $venvPython
        Invoke-LocalExecutable $venvPython @('-m', 'pip', 'install', '-r', $lockFile)
        Write-Host 'Local .venv is ready. Package download may use the configured package index; no Azure resources were accessed or provisioned.'
        if ($Notebook) {
            Write-Host 'Notebook dependencies are installed only in .venv; no global kernel registration. Select this .venv interpreter in the existing VS Code Jupyter extension.'
        }
        return
    }

    if ($Action -eq 'Stop') {
        $stopPython = if (Test-Path -LiteralPath $venvPython -PathType Leaf) { $venvPython } else { Get-BootstrapPython }
        Invoke-LocalExecutable $stopPython @(
            (Join-Path $root 'scripts\workflow_process.py'), 'stop', '--root', $root
        )
        return
    }

    Assert-Venv
    if ($Action -eq 'Test') {
        $node = Get-Command node -CommandType Application -ErrorAction Stop | Select-Object -First 1
        Invoke-LocalExecutable $venvPython @('-m', 'unittest', 'discover', '-s', 'tests', '-p', 'test_*.py')
        $frontendTests = @(Get-ChildItem -LiteralPath (Join-Path $root 'tests') -Filter 'frontend*.test.js' -File |
            Sort-Object Name | ForEach-Object { $_.FullName })
        if ($frontendTests.Count -eq 0) { throw 'No tests\frontend*.test.js found; restore the complete template.' }
        Invoke-LocalExecutable $node.Source (@('--test') + $frontendTests)
        return
    }

    $absoluteEnv = if ([string]::IsNullOrWhiteSpace($EnvFile)) {
        Join-Path $root '.env'
    }
    else { [System.IO.Path]::GetFullPath($EnvFile, (Get-Location).Path) }
    if (-not (Test-Path -LiteralPath $absoluteEnv -PathType Leaf)) {
        throw '.env is missing. Copy .env.example to .env and set your approved resource values. No configuration is printed.'
    }

    if ($Action -eq 'Start') {
        Invoke-LocalExecutable $venvPython @(
            (Join-Path $root 'scripts\workflow_process.py'), 'start',
            '--allow-azure', '--root', $root, '--env-file', $absoluteEnv, '--python', $venvPython,
            '--port', [string]$Port
        )
        if ($OpenBrowser) { Start-Process "http://127.0.0.1:$Port/" }
        return
    }

    $moduleAction = if ($Action -eq 'Validate') { 'check' } else { $Action.ToLowerInvariant() }
    $moduleArguments = @('-m', 'sales_agent', '--env-file', $absoluteEnv, $moduleAction)
    if ($Action -in $onlineActions) { $moduleArguments += '--allow-azure' }
    if ($RequirePrivate) { $moduleArguments += '--require-private' }
    if ($Action -in @('Text', 'Smoke')) { $moduleArguments += @('--question', $Question) }
    if ($Action -eq 'Publish') {
        Write-Warning 'WRITE: Publish creates a persisted Foundry prompt agent version. It does not provision resources. Record the returned version in .env; Start never publishes.'
    }
    Invoke-LocalExecutable $venvPython $moduleArguments
}
catch {
    Write-Error $_ -ErrorAction Continue
    exit 1
}

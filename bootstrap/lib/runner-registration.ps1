[CmdletBinding()]
param(
    [ValidateSet('ado', 'gha')][string] $Provider,
    [string] $RegistrationToken,
    [string] $RegistrationUrl,
    [string] $AgentPool,
    [string] $AgentName,
    [string] $PackageUrl,
    [string] $PackageSha256,
    [string] $PrerequisitesScript,
    [ValidateSet('true', 'false')][string] $InstallMissing = 'false',
    [ValidateSet('true', 'false')][string] $RemoteExists = 'false',
    [string] $RunnerLabel,
    [string] $RemoteAgentId
)

$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'

function ConvertTo-AifRunnerScope {
    param([string] $Url, [string] $Provider)
    $uri = [uri]$Url
    if (-not $uri.IsAbsoluteUri -or $uri.Scheme -ne 'https' -or $uri.Query -or $uri.Fragment -or $uri.UserInfo) {
        throw 'Runner scope must be an absolute HTTPS URL without credentials, query, or fragment.'
    }
    $value = $uri.AbsoluteUri.TrimEnd('/').ToLowerInvariant()
    if ($Provider -eq 'ado' -and $uri.Host -match '^([^.]+)\.visualstudio\.com$' -and $uri.AbsolutePath -eq '/') {
        $value = "https://dev.azure.com/$($Matches[1])"
    }
    $value
}

function Test-AifRunnerConfiguration {
    param([string] $Provider, [string] $AgentRoot, [string] $Url, [string] $Pool, [string] $Name, [string] $RemoteAgentId)
    $configPath = Join-Path $AgentRoot $(if ($Provider -eq 'ado') { '.agent' } else { '.runner' })
    if (-not (Test-Path -LiteralPath $configPath -PathType Leaf)) { return $false }
    $config = Get-Content -LiteralPath $configPath -Raw | ConvertFrom-Json
    $actualUrl = if ($Provider -eq 'ado') { $config.serverUrl } else { $config.gitHubUrl }
    if (-not $actualUrl -or
        (ConvertTo-AifRunnerScope $actualUrl $Provider) -cne (ConvertTo-AifRunnerScope $Url $Provider) -or
        $config.agentName -cne $Name -or
        ($Provider -eq 'ado' -and $config.poolName -cne $Pool)) {
        throw "Existing $configPath belongs to a different organization/repository, pool, or agent name. Refusing reconfiguration; choose an unused runner folder/VM."
    }
    if ($RemoteAgentId -and [string]$config.agentId -cne $RemoteAgentId) {
        throw "Existing $configPath has a different provider agent ID; refusing stale registration/takeover."
    }
    return $true
}

function Get-AifOwnedRunnerService {
    param([string] $Provider, [string] $AgentRoot)
    $prefix = if ($Provider -eq 'ado') { 'vstsagent.' } else { 'actions.runner.' }
    $executable = if ($Provider -eq 'ado') { 'AgentService.exe' } else { 'RunnerService.exe' }
    $expected = [IO.Path]::GetFullPath((Join-Path $AgentRoot "bin\$executable"))
    $services = @(Get-CimInstance Win32_Service | Where-Object {
        $image = $_.PathName
        $path = ''
        if ($image -match '^\s*"([^"]+)"') { $path = $Matches[1] }
        elseif ($image -match '^\s*(.+?\.exe)(?:\s|$)') { $path = $Matches[1] }
        $_.Name.StartsWith($prefix, [StringComparison]::OrdinalIgnoreCase) -and
            $path -and [IO.Path]::GetFullPath($path) -ieq $expected
    })
    if ($services.Count -ne 1) {
        throw "Expected exactly one $Provider service whose executable belongs to $AgentRoot; found $($services.Count). No other services were touched."
    }
    $serviceFile = Join-Path $AgentRoot '.service'
    if (Test-Path -LiteralPath $serviceFile) {
        if ((Get-Content -LiteralPath $serviceFile -Raw).Trim() -cne $services[0].Name) {
            throw "Service ownership does not match $serviceFile."
        }
    }
    $services[0]
}

function Start-AifOwnedRunnerService {
    param($Service)
    if ($Service.State -eq 'Running') { return }
    if ($Service.State -ne 'Stopped' -or $Service.StartMode -eq 'Disabled') {
        throw "Owned runner service '$($Service.Name)' is $($Service.State)/$($Service.StartMode); resolve this explicitly."
    }
    Start-Service -Name $Service.Name
    $running = Get-Service -Name $Service.Name
    $running.WaitForStatus('Running', [TimeSpan]::FromSeconds(60))
}

function Invoke-AifWindowsRunnerRegistration {
    param(
        [string] $Provider, [string] $RegistrationToken, [string] $RegistrationUrl,
        [string] $AgentPool, [string] $AgentName, [string] $PackageUrl,
        [string] $PackageSha256, [string] $PrerequisitesScript,
        [bool] $InstallMissing, [bool] $RemoteExists, [string] $RunnerLabel, [string] $RemoteAgentId
    )
    if ($env:OS -ne 'Windows_NT') { throw 'Use newrunner-registration.sh for Ubuntu 22.04/24.04.' }
    if ($Provider -notin @('ado', 'gha') -or -not $AgentName) { throw 'Provider and agent name are required.' }
    $expectedUrl = ConvertTo-AifRunnerScope $RegistrationUrl $Provider
    if (($Provider -eq 'gha' -and $expectedUrl -notmatch '^https://github\.com/[^/]+/[^/]+$') -or
        ($Provider -eq 'ado' -and $expectedUrl -notmatch '^https://dev\.azure\.com/[^/]+$')) {
        throw 'Unsupported provider organization/repository URL.'
    }
    $agentRoot = if ($Provider -eq 'ado') { 'C:\aifactory-agent' } else { 'C:\aifactory-gha-runner' }
    $configured = Test-AifRunnerConfiguration $Provider $agentRoot $RegistrationUrl $AgentPool $AgentName $RemoteAgentId
    $service = $null
    if ($configured) { $service = Get-AifOwnedRunnerService $Provider $agentRoot }
    elseif ($RemoteExists) {
        throw 'The provider already has this runner name but this VM folder is not registered. Refusing to replace or take over another runner.'
    }
    elseif ((Test-Path -LiteralPath $agentRoot) -and (Get-ChildItem -LiteralPath $agentRoot -Force | Select-Object -First 1)) {
        throw "Unregistered nonempty runner folder $agentRoot; inspect it explicitly. Nothing was deleted."
    }

    if (-not $PrerequisitesScript) {
        $PrerequisitesScript = Get-Content -LiteralPath (Join-Path $PSScriptRoot 'runner-prerequisites.ps1') -Raw
    }
    . ([scriptblock]::Create($PrerequisitesScript)) -InstallMissing:$InstallMissing -RequirePython3 -RequireAzModules
    $report = Invoke-AifRunnerPrerequisites -InstallMissing:$InstallMissing -RequirePython3 -RequireAzModules
    if ($configured) {
        $restartMarker = Join-Path $env:ProgramFiles 'AIFactory\prerequisites-changed.json'
        if ($service.State -eq 'Running' -and (Test-Path -LiteralPath $restartMarker)) {
            $marker = Get-Content -LiteralPath $restartMarker -Raw | ConvertFrom-Json
            $started = (Get-Process -Id $service.ProcessId).StartTime.ToUniversalTime()
            if ($started -le [DateTime]::Parse($marker.ChangedUtc).ToUniversalTime()) {
                throw "Prerequisites installed, but running service '$($service.Name)' was left untouched. Schedule an explicit restart when idle to inherit the machine PATH, then rerun verification."
            }
        }
        if (-not $InstallMissing) {
            Write-Output "Prerequisites and local $Provider runner scope checked. Check mode did not register or start any service."
            return
        }
        Start-AifOwnedRunnerService $service
        Write-Output "Reused $Provider runner '$AgentName'; registration and running/busy services were not changed."
        return
    }
    if (-not $InstallMissing) {
        Write-Output "Prerequisites checked; $Provider runner is not registered. Check mode made no registration changes."
        return
    }
    if (-not $RegistrationToken) { throw 'A protected registration token is required only for first registration.' }
    $uri = [uri]$PackageUrl
    $allowedHosts = @('download.agent.dev.azure.com', 'vstsagentpackage.azureedge.net', 'vstsagentpackage.blob.core.windows.net')
    if ($uri.Scheme -ne 'https' -or $uri.UserInfo -or $uri.Query -or $uri.Fragment -or
        ($Provider -eq 'ado' -and ($uri.Host -notin $allowedHosts -or
            $uri.AbsolutePath -notmatch '^/agent/([0-9]+\.[0-9]+\.[0-9]+)/vsts-agent-win-x64-\1\.zip$')) -or
        ($Provider -eq 'gha' -and $PackageUrl -notmatch '^https://github\.com/actions/runner/releases/download/v[0-9.]+/actions-runner-win-x64-[0-9.]+\.zip$')) {
        throw 'Runner package must come from the official provider release endpoint.'
    }
    if ($PackageSha256 -notmatch '^[a-fA-F0-9]{64}$') {
        throw 'Official runner SHA256 metadata is required for both providers.'
    }
    [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
    New-Item -ItemType Directory -Path $agentRoot -Force | Out-Null
    $acl = New-Object Security.AccessControl.DirectorySecurity
    $acl.SetAccessRuleProtection($true, $false)
    foreach ($sid in @('S-1-5-18', 'S-1-5-32-544')) {
        $rule = New-Object Security.AccessControl.FileSystemAccessRule(
            [Security.Principal.SecurityIdentifier]$sid, 'FullControl', 'ContainerInherit,ObjectInherit', 'None', 'Allow')
        $acl.AddAccessRule($rule)
    }
    $workerRule = New-Object Security.AccessControl.FileSystemAccessRule(
        [Security.Principal.SecurityIdentifier]'S-1-5-20', 'Modify', 'ContainerInherit,ObjectInherit', 'None', 'Allow')
    $acl.AddAccessRule($workerRule)
    Set-Acl -LiteralPath $agentRoot -AclObject $acl
    $archive = Join-Path $agentRoot 'runner-package.zip'
    try {
        Invoke-WebRequest -Uri $PackageUrl -OutFile $archive -UseBasicParsing
        if ($PackageSha256 -and (Get-FileHash -LiteralPath $archive -Algorithm SHA256).Hash -ine $PackageSha256) {
            throw 'Runner package SHA256 verification failed.'
        }
        Expand-Archive -LiteralPath $archive -DestinationPath $agentRoot
    } finally {
        if (Test-Path -LiteralPath $archive) { Remove-Item -LiteralPath $archive }
    }
    $arguments = @('--unattended', '--url', $RegistrationUrl,
        '--runasservice', '--windowslogonaccount', 'NT AUTHORITY\NETWORK SERVICE', '--work', '_work')
    if ($Provider -eq 'ado') { $arguments += @('--auth', 'pat', '--pool', $AgentPool, '--agent', $AgentName) }
    else {
        if ($RunnerLabel -notmatch '^[a-zA-Z0-9][a-zA-Z0-9_.-]{0,99}$') { throw 'A safe, unique GitHub runner label is required.' }
        $arguments += @('--name', $AgentName, '--labels', $RunnerLabel)
    }
    Push-Location $agentRoot
    try {
        # Both providers consume and mask *_INPUT_TOKEN, without a secret in config.cmd's argv.
        $tokenVariable = if ($Provider -eq 'ado') { 'VSTS_AGENT_INPUT_TOKEN' } else { 'ACTIONS_RUNNER_INPUT_TOKEN' }
        [Environment]::SetEnvironmentVariable($tokenVariable, $RegistrationToken, 'Process')
        $RegistrationToken = ''
        # Capture rather than log command output: provider diagnostics can contain credentials.
        $null = & .\config.cmd @arguments 2>&1
        if ($LASTEXITCODE -ne 0) { throw "Runner configuration failed with exit code $LASTEXITCODE; existing registrations were not replaced." }
    } finally {
        Pop-Location
        if ($tokenVariable) { [Environment]::SetEnvironmentVariable($tokenVariable, $null, 'Process') }
        $RegistrationToken = ''
        $arguments = @()
    }
    if (-not (Test-AifRunnerConfiguration $Provider $agentRoot $RegistrationUrl $AgentPool $AgentName)) {
        throw 'Runner configuration did not produce the expected registration.'
    }
    Start-AifOwnedRunnerService (Get-AifOwnedRunnerService $Provider $agentRoot)
    Write-Output "Registered $Provider runner '$AgentName' with verified prerequisites."
}

if ($MyInvocation.InvocationName -ne '.') {
    Invoke-AifWindowsRunnerRegistration -Provider $Provider -RegistrationToken $RegistrationToken `
        -RegistrationUrl $RegistrationUrl -AgentPool $AgentPool -AgentName $AgentName `
        -PackageUrl $PackageUrl -PackageSha256 $PackageSha256 -PrerequisitesScript $PrerequisitesScript `
        -InstallMissing ($InstallMissing -eq 'true') -RemoteExists ($RemoteExists -eq 'true') -RunnerLabel $RunnerLabel -RemoteAgentId $RemoteAgentId
}

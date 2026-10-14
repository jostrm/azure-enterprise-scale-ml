Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

function Get-LocalArmToken {
    param([hashtable]$Configuration)
    $contextText = & az account show --only-show-errors -o json
    if ($LASTEXITCODE -ne 0) { throw 'Sign in using az login before invoking the optimizer.' }
    $context = $contextText | ConvertFrom-Json -AsHashtable
    if ($context.tenantId -ne $Configuration.tenantId -or $context.id -ne $Configuration.subscriptionId) {
        throw 'Select the exact variables.json tenant and subscription using az login / az account set first.'
    }
    if ($null -ne $script:LocalArmToken -and $script:LocalArmToken.expires -gt [DateTimeOffset]::UtcNow -and
        $script:LocalArmToken.tenant -eq $Configuration.tenantId -and $script:LocalArmToken.subscription -eq $Configuration.subscriptionId) {
        return $script:LocalArmToken.token
    }
    $token = & az account get-access-token --subscription $Configuration.subscriptionId `
        --resource 'https://management.azure.com/' --query accessToken --only-show-errors -o tsv
    if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrWhiteSpace($token)) { throw 'ARM authentication failed.' }
    $script:LocalArmToken = @{
        token = $token
        expires = [DateTimeOffset]::UtcNow.AddMinutes(5)
        tenant = $Configuration.tenantId
        subscription = $Configuration.subscriptionId
    }
    return $token
}

function Invoke-ControlArm {
    param(
        [hashtable]$Configuration,
        [string]$Path,
        [ValidateSet('Get', 'Put', 'Post', 'Patch', 'Delete')][string]$Method = 'Get',
        [string]$ApiVersion = '2024-10-23',
        [AllowNull()][object]$Body = $null,
        [string]$ContentType = 'application/json; charset=utf-8',
        [int[]]$ExpectedStatuses = @()
    )
    $uri = if ($Path.StartsWith('https://management.azure.com/')) {
        $Path
    } else {
        "https://management.azure.com${Path}?api-version=$ApiVersion"
    }
    for ($attempt = 0; $attempt -lt 5; $attempt++) {
        $parameters = @{
            Uri = $uri
            Method = $Method
            Headers = @{ Authorization = "Bearer $(Get-LocalArmToken -Configuration $Configuration)" }
            TimeoutSec = 60
            SkipHttpErrorCheck = $true
            MaximumRedirection = 0
        }
        if ($null -ne $Body) {
            $text = if ($ContentType.StartsWith('text/plain')) { [string]$Body } else { $Body | ConvertTo-Json -Depth 30 -Compress }
            $parameters.Body = [Text.Encoding]::UTF8.GetBytes($text)
            $parameters.ContentType = $ContentType
        }
        $response = Invoke-WebRequest @parameters
        $status = [int]$response.StatusCode
        $content = if ($response.Content -is [byte[]]) {
            [Text.Encoding]::UTF8.GetString($response.Content)
        } else { [string]$response.Content }
        if (($status -ge 200 -and $status -lt 300) -or $ExpectedStatuses -contains $status) {
            $json = $null
            if (-not [string]::IsNullOrWhiteSpace($content) -and $content.TrimStart().StartsWith('{')) {
                $json = $content | ConvertFrom-Json -AsHashtable -DateKind String
            }
            return @{ status = $status; headers = $response.Headers; json = $json; content = $content }
        }
        if ($status -eq 401 -and $attempt -lt 4) {
            $script:LocalArmToken = $null
            continue
        }
        if (@(408, 429, 500, 502, 503, 504) -contains $status -and $attempt -lt 4) {
            Start-Sleep -Seconds ([Math]::Min(30, [Math]::Pow(2, $attempt + 1)))
            continue
        }
        $detail = if ($content.TrimStart().StartsWith('{')) {
            $errorBody = $content | ConvertFrom-Json -AsHashtable
            if ($errorBody.ContainsKey('error')) { "$($errorBody.error.code): $($errorBody.error.message)" } else { 'No error detail.' }
        } else { 'No error detail.' }
        throw "$Method $uri failed: HTTP $status. $detail"
    }
    throw "ARM retry limit exceeded for $Method $uri."
}

function Get-AutomationPath {
    param([hashtable]$Configuration)
    return "/subscriptions/$($Configuration.subscriptionId)/resourceGroups/$($Configuration.resourceGroup)/providers/Microsoft.Automation/automationAccounts/$($Configuration.automationAccount)"
}

function Wait-ControlOperation {
    param([hashtable]$Configuration, [hashtable]$Response)
    if ($Response.status -ne 202) { return }
    $uri = [string]($Response.headers['Azure-AsyncOperation'] | Select-Object -First 1)
    if ([string]::IsNullOrWhiteSpace($uri)) { $uri = [string]($Response.headers['Location'] | Select-Object -First 1) }
    if ([string]::IsNullOrWhiteSpace($uri)) { return }
    if (-not $uri.StartsWith('https://management.azure.com/')) { throw 'Unexpected ARM operation polling URL.' }
    $deadline = [DateTimeOffset]::UtcNow.AddMinutes(20)
    while ([DateTimeOffset]::UtcNow -lt $deadline) {
        Start-Sleep -Seconds 5
        $result = Invoke-ControlArm -Configuration $Configuration -Path $uri
        if ($result.status -eq 204) { return }
        if ($null -ne $result.json -and $result.json.ContainsKey('status')) {
            if ($result.json.status -eq 'Succeeded') { return }
            if (@('Failed', 'Canceled', 'Cancelled') -contains $result.json.status) {
                throw "ARM asynchronous operation failed: $($result.json | ConvertTo-Json -Depth 10 -Compress)"
            }
        } elseif ($result.status -eq 200) { return }
    }
    throw "ARM operation did not finish within 20 minutes: $uri"
}

function Get-DeterministicGuid {
    param([string]$Seed)
    $hash = [Security.Cryptography.SHA256]::HashData([Text.Encoding]::UTF8.GetBytes($Seed.ToLowerInvariant()))
    return [Guid]::new([byte[]]$hash[0..15]).ToString()
}

function Invoke-HostedOptimizerJob {
    param(
        [hashtable]$Configuration,
        [ValidateSet('STOP', 'START', 'STATUS', 'VERIFY')][string]$Action,
        [ValidateSet('Preview', 'Live')][string]$Mode,
        [switch]$NoWait
    )
    $base = Get-AutomationPath -Configuration $Configuration
    $jobId = [Guid]::NewGuid().ToString()
    $null = Invoke-ControlArm -Configuration $Configuration -Path "$base/jobs/$jobId" -Method Put -Body @{
        properties = @{
            runbook = @{ name = $Configuration.runbookName }
            parameters = @{ Action = $Action; Mode = $Mode }
            runOn = ''
        }
    }
    Write-Host "$Action ($Mode) job: $jobId"
    if ($NoWait) { return @{ jobId = $jobId; status = 'Submitted' } }
    $deadline = [DateTimeOffset]::UtcNow.AddMinutes(45)
    $status = 'Submitted'
    while ([DateTimeOffset]::UtcNow -lt $deadline) {
        $job = (Invoke-ControlArm -Configuration $Configuration -Path "$base/jobs/$jobId").json
        $status = $job.properties.status
        if (@('Completed', 'Failed', 'Stopped', 'Suspended', 'Disconnected') -contains $status) { break }
        Start-Sleep -Seconds 10
    }
    $output = (Invoke-ControlArm -Configuration $Configuration -Path "$base/jobs/$jobId/output").content
    if (-not [string]::IsNullOrWhiteSpace($output)) { Write-Host $output }
    $streams = (Invoke-ControlArm -Configuration $Configuration -Path "$base/jobs/$jobId/streams").json
    foreach ($stream in $streams.value) {
        if (@('Error', 'Warning') -contains $stream.properties.streamType) {
            Write-Warning $stream.properties.summary
        }
    }
    if ($status -ne 'Completed') {
        $detail = if ($job.properties.ContainsKey('exception')) { $job.properties.exception } else { 'No exception detail provided.' }
        throw "Automation job $jobId ended with status $status. $detail No recovery checkpoint was discarded."
    }
    return @{ jobId = $jobId; status = $status; output = $output }
}

$script:LocalArmToken = $null

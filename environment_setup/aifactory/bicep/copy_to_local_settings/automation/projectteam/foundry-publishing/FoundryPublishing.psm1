function Find-FoundryPublisher {
    param([string] $ConfigDirectory, [string] $RepositoryRoot)

    $relative = 'environment_setup\aifactory\bicep\scripts\publish-foundry-agent.py'
    if ($RepositoryRoot) {
        $root = $ExecutionContext.SessionState.Path.GetUnresolvedProviderPathFromPSPath($RepositoryRoot)
        foreach ($candidate in @((Join-Path $root $relative), (Join-Path (Join-Path $root 'azure-enterprise-scale-ml') $relative))) {
            if (Test-Path -LiteralPath $candidate -PathType Leaf) { return $candidate }
        }
        throw "RepositoryRoot does not contain $relative (directly or under azure-enterprise-scale-ml)."
    }

    $visited = [System.Collections.Generic.HashSet[string]]::new([System.StringComparer]::OrdinalIgnoreCase)
    foreach ($start in @($PSScriptRoot, $ConfigDirectory)) {
        $directory = [System.IO.DirectoryInfo]::new($start)
        while ($null -ne $directory) {
            if ($visited.Add($directory.FullName)) {
                foreach ($candidate in @((Join-Path $directory.FullName $relative), (Join-Path (Join-Path $directory.FullName 'azure-enterprise-scale-ml') $relative))) {
                    if (Test-Path -LiteralPath $candidate -PathType Leaf) { return $candidate }
                }
            }
            $directory = $directory.Parent
        }
    }
    throw "Cannot find $relative. Keep the azure-enterprise-scale-ml checkout beside your configuration, or specify -RepositoryRoot."
}

function Get-FoundryPython {
    foreach ($name in @('python', 'python3')) {
        $command = Get-Command $name -CommandType Application -ErrorAction SilentlyContinue | Select-Object -First 1
        if ($command) { return $command.Source }
    }
    throw 'Python was not found. Use the project runner with Python 3 and Azure CLI installed, and ensure python or python3 is on PATH.'
}

function Invoke-FoundryPublisherCommand {
    param([string] $Python, [string] $Backend, [string[]] $Arguments)

    $PSNativeCommandUseErrorActionPreference = $false
    $output = & $Python $Backend @Arguments
    $exitCode = $LASTEXITCODE
    if ($exitCode -ne 0) {
        throw "Foundry publisher '$($Arguments[0])' failed with exit code $exitCode. Review the backend diagnostics above; no further operation was attempted."
    }
    $json = $output -join "`n"
    try {
        $result = $json | ConvertFrom-Json -ErrorAction Stop
    }
    catch [System.ArgumentException] {
        throw "Foundry publisher '$($Arguments[0])' did not return one valid JSON object. Review the backend diagnostics."
    }
    if ($null -eq $result -or $result -isnot [System.Management.Automation.PSCustomObject] -or -not $result.status) {
        throw "Foundry publisher '$($Arguments[0])' returned an invalid JSON result (an object with status is required)."
    }
    return [pscustomobject] @{ Document = $result; Json = $json }
}

function Get-FoundryScope {
    param($Plan)

    foreach ($value in @($Plan.scope, $Plan.publish_body.publishScope, $Plan.publish_body.scope)) {
        if ($value -in @('Shared', 'Tenant')) { return $value }
    }
    throw 'The publishing plan did not identify a valid Shared or Tenant scope. No publication was attempted.'
}

function Write-FoundryPreview {
    param($Plan, [string] $RequestedScope)

    Write-Host "`nFoundry publishing preview (not confirmation of publication)"
    Write-Host 'Actual target (project, tenant/subscription, agent and resolved scope):'
    Write-Host (ConvertTo-Json -InputObject $Plan.target -Depth 100)
    Write-Host "Resolved publication scope: $(Get-FoundryScope $Plan)"
    Write-Host 'Endpoint/network/authentication preparation: before, after and exact patch:'
    Write-Host (ConvertTo-Json -InputObject $Plan.preparation -Depth 100)
    Write-Host 'Exact outgoing publish body:'
    Write-Host (ConvertTo-Json -InputObject $Plan.publish_body -Depth 100)
    Write-Host 'This is one joint native publishing operation for BOTH Teams and Microsoft 365 Copilot catalogs, not a surface-only API.'
    Write-Warning 'Review all metadata, including values sourced from an existing profile or server defaults. Publishing makes this metadata visible in Teams/Microsoft 365; agent responses are processed by Microsoft 365.'
    if ((Get-FoundryScope $Plan) -eq 'Tenant' -or $RequestedScope -eq 'Tenant') {
        Write-Warning 'Tenant scope targets all tenant users and is subject to pending admin approval. Publication does not mean the agent is already available in either store.'
    }
    foreach ($warning in $Plan.warnings) { Write-Warning ([string] $warning) }
    if (@($Plan.missing_fields).Count -gt 0) {
        Write-Host "Missing metadata fields: $($Plan.missing_fields -join ', ')"
    }
    foreach ($reason in $Plan.block_reasons) { Write-Warning "Blocked: $reason" }
}

function Test-FoundryPreparationChange {
    param($Preparation)

    if ($Preparation.changed -eq $true -or $Preparation.needs_update -eq $true) { return $true }
    if ($null -ne $Preparation.patch -and @($Preparation.patch.PSObject.Properties).Count -gt 0) { return $true }
    $before = ConvertTo-Json -InputObject $Preparation.before -Depth 100 -Compress
    $after = ConvertTo-Json -InputObject $Preparation.after -Depth 100 -Compress
    return $before -ne $after
}

function Invoke-FoundryPublishing {
    [CmdletBinding(SupportsShouldProcess = $true, ConfirmImpact = 'High')]
    param(
        [Parameter(Mandatory)] [ValidateSet('Teams', 'Copilot')] [string] $Surface,
        [string] $ConfigFile = (Join-Path (Get-Location).Path 'variables.json'),
        [ValidateSet('dev', 'stage', 'test', 'prod')] [string] $Environment = 'dev',
        [string] $AgentName,
        [string] $ProjectResourceId,
        [string] $ProfileFile,
        [ValidateSet('Shared', 'Tenant')] [string] $Scope,
        [switch] $NonInteractive,
        [switch] $RetryUncertain,
        [string] $RepositoryRoot
    )

    $ErrorActionPreference = 'Stop'
    $explicitApproval = $PSBoundParameters.ContainsKey('Confirm') -and -not $PSBoundParameters['Confirm']
    if (-not $explicitApproval) { $ConfirmPreference = 'High' }
    $config = $ExecutionContext.SessionState.Path.GetUnresolvedProviderPathFromPSPath($ConfigFile)
    if (-not (Test-Path -LiteralPath $config -PathType Leaf)) {
        throw "ConfigFile '$config' was not found. Run from your project directory containing variables.json, or specify -ConfigFile."
    }
    $backend = Find-FoundryPublisher -ConfigDirectory (Split-Path -Parent $config) -RepositoryRoot $RepositoryRoot
    $python = Get-FoundryPython
    $arguments = @('--config-file', $config, '--environment', $Environment, '--surface', $Surface)
    if ($AgentName) { $arguments += @('--agent-name', $AgentName) }
    if ($ProjectResourceId) { $arguments += @('--project-resource-id', $ProjectResourceId) }
    if ($ProfileFile) {
        $profile = $ExecutionContext.SessionState.Path.GetUnresolvedProviderPathFromPSPath($ProfileFile)
        $arguments += @('--profile-file', $profile)
    }
    if ($Scope) { $arguments += @('--scope', $Scope) }
    if ($RetryUncertain) { $arguments += '--retry-uncertain' }

    $metadataPath = $null
    $reviewedPath = $null
    $metadata = @{}
    $metadataFields = @('agentDisplayName', 'shortDescription', 'fullDescription', 'developerName',
        'developerWebsiteUrl', 'privacyUrl', 'termsOfUseUrl', 'appVersion')
    $utf8 = [System.Text.UTF8Encoding]::new($false)
    try {
        $response = Invoke-FoundryPublisherCommand -Python $python -Backend $backend -Arguments (@('plan') + $arguments)
        $plan = $response.Document
        Write-FoundryPreview -Plan $plan -RequestedScope $Scope
        if ($WhatIfPreference) {
            $null = $PSCmdlet.ShouldProcess("BOTH Teams and Microsoft 365 Copilot catalogs (scope: $(Get-FoundryScope $plan)); $(ConvertTo-Json -InputObject $plan.target -Compress -Depth 100)", 'Apply reviewed preparation and native publication')
            return $plan
        }

        for ($attempt = 0; @($plan.missing_fields).Count -gt 0; $attempt++) {
            if ($NonInteractive) {
                throw "Missing metadata in -NonInteractive mode: $($plan.missing_fields -join ', '). Supply a complete saved profile or run interactively."
            }
            if ($attempt -ge 3) { throw "Required metadata is still invalid or missing after three attempts: $($plan.missing_fields -join ', ')." }
            foreach ($field in $plan.missing_fields) {
                if ($field -notin $metadataFields) { throw "Unsupported required metadata field '$field'. Review the backend diagnostics." }
                $value = Read-Host -Prompt $field
                if ([string]::IsNullOrWhiteSpace($value)) { throw "Required metadata '$field' cannot be empty. No publication was attempted." }
                $metadata[$field] = $value
            }
            if (-not $metadataPath) {
                $metadataPath = Join-Path ([System.IO.Path]::GetTempPath()) ("foundry-metadata-{0}.json" -f [guid]::NewGuid().ToString('N'))
                $arguments += @('--metadata-file', $metadataPath)
            }
            [System.IO.File]::WriteAllText($metadataPath, (ConvertTo-Json -InputObject $metadata -Depth 100), $utf8)
            $response = Invoke-FoundryPublisherCommand -Python $python -Backend $backend -Arguments (@('plan') + $arguments)
            $plan = $response.Document
            Write-FoundryPreview -Plan $plan -RequestedScope $Scope
        }

        if ($plan.status -eq 'blocked' -or @($plan.block_reasons).Count -gt 0) {
            throw "Publishing is blocked: $($plan.block_reasons -join '; '). Resolve the reported issue before retrying."
        }
        if ($plan.status -notin @('ready', 'unchanged')) {
            throw "Unexpected publishing plan status '$($plan.status)'; no changes were approved."
        }
        if (-not $plan.needs_publish -and -not (Test-FoundryPreparationChange $plan.preparation)) {
            Write-Host 'No preparation or publication changes are needed. No apply was attempted; store availability and inference are not verified by this preview.'
            return $plan
        }
        if ($NonInteractive -and -not $explicitApproval) {
            throw 'NonInteractive publishing requires explicit -Confirm:$false after reviewing the plan. Use -WhatIf to preview without changes.'
        }
        $target = "BOTH Teams and Microsoft 365 Copilot catalogs (scope: $(Get-FoundryScope $plan)); $(ConvertTo-Json -InputObject $plan.target -Compress -Depth 100)"
        if (-not $PSCmdlet.ShouldProcess($target, 'Apply the displayed network/authentication changes and exact native publish body')) {
            Write-Host 'Publication declined. No apply was attempted.'
            return [pscustomobject] @{ mode = 'plan'; status = 'cancelled'; plan = $plan }
        }

        # Only the approved plan may cross into the mutating backend command.
        $reviewedPath = Join-Path ([System.IO.Path]::GetTempPath()) ("foundry-reviewed-{0}.json" -f [guid]::NewGuid().ToString('N'))
        [System.IO.File]::WriteAllText($reviewedPath, $response.Json, $utf8)
        $applied = Invoke-FoundryPublisherCommand -Python $python -Backend $backend -Arguments (
            @('apply') + $arguments + @('--apply', '--reviewed-plan', $reviewedPath))
        $result = $applied.Document
        Write-Host "Publishing result: $($result.status)"
        Write-Host (ConvertTo-Json -InputObject $result -Depth 100)
        if ($result.status -eq 'pending_admin') {
            Write-Warning 'Pending admin approval: the agent is not confirmed available to all tenant users.'
        }
        if ($result.status -in @('pending_verification', 'verification_pending')) {
            Write-Warning 'Publication verification is pending. Do not retry blindly; follow the returned recovery instructions.'
        }
        Write-Host 'Use the returned store instructions and identifiers. Store caches and admin approval may delay visibility; successful inference has not been verified.'
        return $result
    }
    finally {
        foreach ($path in @($metadataPath, $reviewedPath)) {
            if ($path) {
                try {
                    if (Test-Path -LiteralPath $path) {
                        Remove-Item -LiteralPath $path -Force -Confirm:$false -WhatIf:$false -ErrorAction Stop
                    }
                }
                catch [System.IO.IOException], [System.UnauthorizedAccessException], [System.Management.Automation.ItemNotFoundException] {
                    Write-Warning "Could not remove transient publishing file '$path': $($_.Exception.Message) Remove it manually; it may contain your publishing metadata."
                }
            }
        }
    }
}

Export-ModuleMember -Function Invoke-FoundryPublishing

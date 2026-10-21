#Requires -Version 7.0
<#
.SYNOPSIS
  Provision (idempotently) and publish the AI Factory lifecycle Function into an AI Factory project.

.DESCRIPTION
  1. Infrastructure: infra/function-app.bicep - a private Linux Python Function App with VNet integration, a
     private endpoint, identity-based storage and no basic publishing credentials. Shows what-if first.
  2. Code: zips the Function sources and deploys them with a remote build, using your Microsoft Entra login
     (az functionapp deployment source config-zip), so basic authentication stays off. Waits until the private
     DNS name of the deployment endpoint resolves before publishing.

  Run it from a machine that reaches the private endpoint (for example over the factory's P2S VPN).
  The publish replaces every function in the app: deploy this template only to an app that is dedicated to it.

.PARAMETER SettingsFile
  JSON with subscriptionId, resourceGroup, functionAppName, planName (optional), authClientId (optional), planSku, pythonVersion,
  integrationSubnetId, privateEndpointSubnetId, privateDnsZoneId, storageAccountName, appInsightsName,
  logAnalyticsWorkspaceId, keyVaultName, appSettings and tags. See settings.example.json. No secret values.

.PARAMETER AcceptPurpleFunctionName
  Allow a name of purple's own project Function pattern (func-prj<NNN>-...). Purple's project pipelines treat such
  an app as theirs: with enableFunction=false and enableDeleteForDisabledResources=true they delete it.

.EXAMPLE
  .\deploy.ps1 -SettingsFile .\settings.<consumer>.json -WhatIf
#>
[CmdletBinding(SupportsShouldProcess)]
param(
    [Parameter(Mandatory)] [string] $SettingsFile,
    [switch] $SkipInfrastructure,
    [switch] $SkipCode,
    [switch] $AcceptPurpleFunctionName
)

$ErrorActionPreference = 'Stop'
$here = $PSScriptRoot
$settings = Get-Content -LiteralPath $SettingsFile -Raw | ConvertFrom-Json
foreach ($name in 'subscriptionId', 'resourceGroup', 'functionAppName') {
    if (-not $settings.$name) { throw "Settings file is missing '$name'." }
}
if ($settings.functionAppName -match '^func-prj\d{3}-' -and -not $AcceptPurpleFunctionName) {
    throw "'$($settings.functionAppName)' matches purple's own project Function name, so purple's project pipelines " +
          "would treat it as theirs (and can delete it). Use a name like aiflc-prj001-... or pass -AcceptPurpleFunctionName."
}

function Invoke-Az {
    & az @args
    if ($LASTEXITCODE -ne 0) { throw "az $($args[0]) $($args[1]) failed with exit code $LASTEXITCODE." }
}

function Wait-PrivateDns([string] $hostName, [int] $timeoutSeconds = 600) {
    $deadline = (Get-Date).AddSeconds($timeoutSeconds)
    while ((Get-Date) -lt $deadline) {
        $address = (Resolve-DnsName -Name $hostName -Type A -ErrorAction SilentlyContinue |
            Where-Object { $_.Type -eq 'A' } | Select-Object -First 1).IPAddress
        if ($address -match '^(10\.|172\.(1[6-9]|2\d|3[01])\.|192\.168\.)') { return $address }
        Start-Sleep -Seconds 15
    }
    throw "$hostName does not resolve to a private address. Connect to the VPN or wait for the DNS zone group."
}

Invoke-Az account set --subscription $settings.subscriptionId
Write-Host "Function App $($settings.functionAppName) in $($settings.resourceGroup)" -ForegroundColor Cyan
$temporary = @()
try {
    if (-not $SkipInfrastructure) {
        $values = @{
            functionAppName         = $settings.functionAppName
            planSku                 = $settings.planSku ?? 'B1'
            pythonVersion           = $settings.pythonVersion ?? '3.11'
            integrationSubnetId     = $settings.integrationSubnetId
            privateEndpointSubnetId = $settings.privateEndpointSubnetId
            privateDnsZoneId        = $settings.privateDnsZoneId ?? ''
            storageAccountName      = $settings.storageAccountName
            appInsightsName         = $settings.appInsightsName
            logAnalyticsWorkspaceId = $settings.logAnalyticsWorkspaceId ?? ''
            keyVaultName            = $settings.keyVaultName ?? ''
            authClientId            = $settings.authClientId ?? ''
            grantQueueRole          = ($settings.appSettings.AIF_EVENT_PROCESSING -eq 'queue')
            appSettings             = $settings.appSettings ?? @{}
            tags                    = $settings.tags ?? @{}
        }
        if ($settings.planName) { $values.planName = $settings.planName }
        $parameters = @{
            '$schema'      = 'https://schema.management.azure.com/schemas/2019-04-01/deploymentParameters.json#'
            contentVersion = '1.0.0.0'
            parameters     = @{}
        }
        foreach ($key in $values.Keys) { $parameters.parameters[$key] = @{ value = $values[$key] } }
        $parameterFile = Join-Path ([IO.Path]::GetTempPath()) "aif-lifecycle-$($settings.functionAppName).parameters.json"
        $temporary += $parameterFile
        $parameters | ConvertTo-Json -Depth 10 | Set-Content -LiteralPath $parameterFile -Encoding utf8 -WhatIf:$false
        $template = Join-Path $here 'infra/function-app.bicep'
        $deployment = "aif-lifecycle-$($settings.functionAppName)"

        Write-Host "`nWhat-if:" -ForegroundColor Yellow
        Invoke-Az deployment group what-if --resource-group $settings.resourceGroup --name $deployment `
            --template-file $template --parameters "@$parameterFile"
        if ($PSCmdlet.ShouldProcess($settings.functionAppName, 'Create or update the Function App infrastructure')) {
            Invoke-Az deployment group create --resource-group $settings.resourceGroup --name $deployment `
                --template-file $template --parameters "@$parameterFile" --output none
            Write-Host 'Infrastructure is in place.' -ForegroundColor Green
        }
    }

    if (-not $SkipCode) {
        $staging = Join-Path ([IO.Path]::GetTempPath()) "aif-lifecycle-package-$([Guid]::NewGuid().ToString('N'))"
        $zip = "$staging.zip"
        $temporary += $staging, $zip
        New-Item -ItemType Directory -Path $staging -WhatIf:$false | Out-Null
        foreach ($item in 'function_app.py', 'host.json', 'requirements.txt', 'aif_lifecycle') {
            Copy-Item -LiteralPath (Join-Path $here $item) -Destination $staging -Recurse -WhatIf:$false
        }
        Get-ChildItem -LiteralPath $staging -Recurse -Directory -Filter '__pycache__' | Remove-Item -Recurse -Force -WhatIf:$false
        Compress-Archive -Path (Join-Path $staging '*') -DestinationPath $zip -WhatIf:$false
        if ($PSCmdlet.ShouldProcess($settings.functionAppName, 'Deploy the code with a remote build (replaces all functions in the app)')) {
            $address = Wait-PrivateDns "$($settings.functionAppName).scm.azurewebsites.net"
            Write-Host "Deployment endpoint resolves to $address" -ForegroundColor DarkGray
            Invoke-Az functionapp deployment source config-zip --resource-group $settings.resourceGroup `
                --name $settings.functionAppName --src $zip --build-remote true --timeout 900 --output none
            Write-Host 'Code deployed.' -ForegroundColor Green
        }
    }
}
finally {
    foreach ($path in $temporary) {
        if ($path -and (Test-Path -LiteralPath $path)) { Remove-Item -LiteralPath $path -Recurse -Force -WhatIf:$false }
    }
}

Write-Host "`nNext:" -ForegroundColor Yellow
Write-Host "  Health (no key): https://$($settings.functionAppName).azurewebsites.net/api/v1/health"
Write-Host "  Function key:    az functionapp keys list -g $($settings.resourceGroup) -n $($settings.functionAppName) --query functionKeys.default -o tsv"

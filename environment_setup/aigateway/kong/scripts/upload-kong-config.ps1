# ============================================================================
# Upload Kong declarative config to Azure File Share
# Usage: ./upload-kong-config.ps1 -ResourceGroupName <rg> -StorageAccountName <sa> -SubscriptionId <sub> -ApimGatewayHost <host> -KongConsumerApiKey <key>
# ============================================================================
param(
    [Parameter(Mandatory=$true)]
    [string]$ResourceGroupName,

    [Parameter(Mandatory=$true)]
    [string]$StorageAccountName,

    [Parameter(Mandatory=$true)]
    [string]$SubscriptionId,

    [Parameter(Mandatory=$false)]
    [string]$KongConfigPath = "$PSScriptRoot\..\kong.yaml",

    [Parameter(Mandatory=$false)]
    [string]$FileShareName = "kong-config",

    [Parameter(Mandatory=$false)]
    [Parameter(Mandatory=$true)]
    [string]$ApimGatewayHost,

    [Parameter(Mandatory=$true)]
    [string]$KongConsumerApiKey
)

Write-Host "============================================"
Write-Host "Kong Config Upload Script"
Write-Host "============================================"
Write-Host "Resource Group: $ResourceGroupName"
Write-Host "Storage Account: $StorageAccountName"
Write-Host "File Share: $FileShareName"
Write-Host "Config Path: $KongConfigPath"
Write-Host "============================================"

# Set subscription context
az account set --subscription $SubscriptionId

# Get storage account key
$storageKey = az storage account keys list `
    --resource-group $ResourceGroupName `
    --account-name $StorageAccountName `
    --query "[0].value" -o tsv

if (-not $storageKey) {
    Write-Error "Failed to retrieve storage account key"
    exit 1
}

if (-not (Test-Path -LiteralPath $KongConfigPath -PathType Leaf)) {
    Write-Error "Kong configuration file was not found: $KongConfigPath"
    exit 1
}

# Render the DB-less configuration before upload. The deployed file is complete
# even if the Kong image's configuration parser changes its env-var handling.
$kongConfig = Get-Content -LiteralPath $KongConfigPath -Raw
$kongConfig = $kongConfig.Replace('${APIM_GATEWAY_HOST}', $ApimGatewayHost)
$kongConfig = $kongConfig.Replace('${KONG_CONSUMER_API_KEY}', $KongConsumerApiKey)
if ($kongConfig.Contains('${APIM_GATEWAY_HOST}') -or $kongConfig.Contains('${KONG_CONSUMER_API_KEY}')) {
    Write-Error "Kong configuration contains unresolved placeholders."
    exit 1
}

# Write processed config to temp file
$tempFile = [System.IO.Path]::GetTempFileName()
$kongConfig | Set-Content -Path $tempFile -Encoding UTF8 -NoNewline

# Upload to Azure File Share
Write-Host "Uploading kong.yaml to file share..."
az storage file upload `
    --share-name $FileShareName `
    --source $tempFile `
    --path "kong.yaml" `
    --account-name $StorageAccountName `
    --account-key $storageKey `
    --overwrite

if ($LASTEXITCODE -eq 0) {
    Write-Host "Successfully uploaded kong.yaml to file share '$FileShareName'"
} else {
    Write-Error "Failed to upload kong.yaml"
    Remove-Item -Path $tempFile -Force
    exit 1
}

# Cleanup temp file
Remove-Item -Path $tempFile -Force

Write-Host "============================================"
Write-Host "Kong config upload complete!"
Write-Host "============================================"

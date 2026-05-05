# ============================================================================
# Upload Kong declarative config to Azure File Share
# Usage: ./upload-kong-config.ps1 -ResourceGroupName <rg> -StorageAccountName <sa> -SubscriptionId <sub>
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
    [string]$AzureOpenAIApiKey = "",

    [Parameter(Mandatory=$false)]
    [string]$KongConsumerApiKey = ""
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

# Read and process kong.yaml - replace environment variable placeholders
$kongConfig = Get-Content -Path $KongConfigPath -Raw

if ($AzureOpenAIApiKey) {
    $kongConfig = $kongConfig -replace '\$\{AZURE_OPENAI_API_KEY\}', $AzureOpenAIApiKey
    Write-Host "Replaced AZURE_OPENAI_API_KEY placeholder"
}

if ($KongConsumerApiKey) {
    $kongConfig = $kongConfig -replace '\$\{KONG_CONSUMER_API_KEY\}', $KongConsumerApiKey
    Write-Host "Replaced KONG_CONSUMER_API_KEY placeholder"
} else {
    # Generate a random consumer key if not provided
    $generatedKey = [System.Guid]::NewGuid().ToString()
    $kongConfig = $kongConfig -replace '\$\{KONG_CONSUMER_API_KEY\}', $generatedKey
    Write-Host "Generated KONG_CONSUMER_API_KEY: $generatedKey"
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

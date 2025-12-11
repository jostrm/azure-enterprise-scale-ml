# Azure Function Deployment Script
# This script deploys the Azure Function to Azure

# Configuration
$FUNCTION_APP_NAME = "TODO"
$RESOURCE_GROUP = "TODO"
$SUBSCRIPTION_ID = "TODO"
$LOCATION = "eastus"  # Change as needed
$STORAGE_ACCOUNT_NAME = "<your-storage-account-name>"  # The storage account you want to read from
$RUNTIME = "python"
$RUNTIME_VERSION = "3.11"  # Python version (3.9, 3.10, 3.11)

Write-Host "=== Azure Function Deployment ===" -ForegroundColor Cyan
Write-Host "Function App: $FUNCTION_APP_NAME" -ForegroundColor Green
Write-Host "Resource Group: $RESOURCE_GROUP" -ForegroundColor Green
Write-Host "Subscription: $SUBSCRIPTION_ID" -ForegroundColor Green

# Set the subscription
Write-Host "`nSetting subscription..." -ForegroundColor Yellow
az account set --subscription $SUBSCRIPTION_ID

# Check if resource group exists
Write-Host "`nChecking if resource group exists..." -ForegroundColor Yellow
$rgExists = az group exists --name $RESOURCE_GROUP
if ($rgExists -eq "false") {
    Write-Host "Resource group does not exist. Creating..." -ForegroundColor Yellow
    az group create --name $RESOURCE_GROUP --location $LOCATION
    Write-Host "Resource group created." -ForegroundColor Green
} else {
    Write-Host "Resource group exists." -ForegroundColor Green
}

# Check if function app exists
Write-Host "`nChecking if function app exists..." -ForegroundColor Yellow
$funcAppExists = az functionapp show --name $FUNCTION_APP_NAME --resource-group $RESOURCE_GROUP 2>$null
if ($null -eq $funcAppExists) {
    Write-Host "Function app does not exist. Creating..." -ForegroundColor Yellow
    
    # Create a storage account for the function app (required for Azure Functions)
    $FUNC_STORAGE_ACCOUNT = $FUNCTION_APP_NAME.Replace("-", "").Replace("_", "") + "storage"
    if ($FUNC_STORAGE_ACCOUNT.Length -gt 24) {
        $FUNC_STORAGE_ACCOUNT = $FUNC_STORAGE_ACCOUNT.Substring(0, 24)
    }
    
    Write-Host "Creating storage account for function app: $FUNC_STORAGE_ACCOUNT" -ForegroundColor Yellow
    az storage account create `
        --name $FUNC_STORAGE_ACCOUNT `
        --location $LOCATION `
        --resource-group $RESOURCE_GROUP `
        --sku Standard_LRS `
        --kind StorageV2
    
    # Create the function app
    Write-Host "Creating function app..." -ForegroundColor Yellow
    az functionapp create `
        --name $FUNCTION_APP_NAME `
        --storage-account $FUNC_STORAGE_ACCOUNT `
        --consumption-plan-location $LOCATION `
        --resource-group $RESOURCE_GROUP `
        --runtime $RUNTIME `
        --runtime-version $RUNTIME_VERSION `
        --functions-version 4 `
        --os-type Linux
    
    Write-Host "Function app created." -ForegroundColor Green
} else {
    Write-Host "Function app exists." -ForegroundColor Green
}

# Enable system-assigned managed identity
Write-Host "`nEnabling system-assigned managed identity..." -ForegroundColor Yellow
$identity = az functionapp identity assign `
    --name $FUNCTION_APP_NAME `
    --resource-group $RESOURCE_GROUP | ConvertFrom-Json

$principalId = $identity.principalId
Write-Host "Managed Identity Principal ID: $principalId" -ForegroundColor Green

# Configure app settings (optional - for default storage account)
Write-Host "`nConfiguring app settings..." -ForegroundColor Yellow
az functionapp config appsettings set `
    --name $FUNCTION_APP_NAME `
    --resource-group $RESOURCE_GROUP `
    --settings "STORAGE_ACCOUNT_NAME=$STORAGE_ACCOUNT_NAME"

# Deploy the function code
Write-Host "`nDeploying function code..." -ForegroundColor Yellow
func azure functionapp publish $FUNCTION_APP_NAME --python

Write-Host "`n=== Deployment Complete ===" -ForegroundColor Cyan
Write-Host "`nNext Steps:" -ForegroundColor Yellow
Write-Host "1. Grant the managed identity 'Storage Blob Data Reader' role on your storage account:" -ForegroundColor White
Write-Host "   az role assignment create --role 'Storage Blob Data Reader' --assignee-object-id $principalId --scope /subscriptions/$SUBSCRIPTION_ID/resourceGroups/$RESOURCE_GROUP/providers/Microsoft.Storage/storageAccounts/$STORAGE_ACCOUNT_NAME" -ForegroundColor Gray
Write-Host "`n2. Test your function:" -ForegroundColor White
Write-Host "   Get function URL:" -ForegroundColor White
Write-Host "   az functionapp function show --name $FUNCTION_APP_NAME --resource-group $RESOURCE_GROUP --function-name read_storage --query invokeUrlTemplate -o tsv" -ForegroundColor Gray
Write-Host "`n3. Call the function:" -ForegroundColor White
Write-Host "   Invoke-RestMethod -Uri 'https://${FUNCTION_APP_NAME}.azurewebsites.net/api/read_storage?code=<function-key>&storage_account=<storage>&container=<container>&blob_name=<blob>'" -ForegroundColor Gray

# Azure Function - Storage Reader

This Azure Function reads data from Azure Storage using managed identity authentication.

## Files

- `function_app.py` - Main function code with HTTP triggers
- `requirements.txt` - Python dependencies
- `host.json` - Function host configuration
- `local.settings.json` - Local development settings
- `deploy.ps1` - PowerShell deployment script

## Features

### Endpoints

1. **`/api/read_storage`** - Read from Azure Storage
   - List blobs in a container
   - Read specific blob content
   - Returns text or base64-encoded binary data

2. **`/api/health`** - Health check endpoint

## Local Development

### Prerequisites

- Python 3.9, 3.10, or 3.11
- Azure Functions Core Tools v4
- Azure CLI

### Install Dependencies

```powershell
pip install -r requirements.txt
```

### Update Configuration

Edit `local.settings.json` and set:
- `STORAGE_ACCOUNT_NAME` - Your storage account name
- `CONTAINER_NAME` - Your default container name

### Run Locally

```powershell
func start
```

### Test Locally

```powershell
# Health check
Invoke-RestMethod -Uri "http://localhost:7071/api/health"

# List blobs in container
Invoke-RestMethod -Uri "http://localhost:7071/api/read_storage?storage_account=mystorageacct&container=mycontainer"

# Read specific blob
Invoke-RestMethod -Uri "http://localhost:7071/api/read_storage?storage_account=mystorageacct&container=mycontainer&blob_name=data/file.csv"
```

## Deployment

### Option 1: Using the Deployment Script

```powershell
# Edit deploy.ps1 to set your values
.\deploy.ps1
```

### Option 2: Manual Deployment

1. **Install Azure Functions Core Tools**
   ```powershell
   npm install -g azure-functions-core-tools@4
   ```

2. **Login to Azure**
   ```powershell
   az login
   az account set --subscription asdfasddfsdf
   ```

3. **Create Function App** (if not exists)
   ```powershell
   # Create resource group
   az group create --name my-rg --location eastus

   # Create storage account for function
   az storage account create `
       --name myfunc2storage `
       --location eastus `
       --resource-group my-rg `
       --sku Standard_LRS

   # Create function app
   az functionapp create `
       --name my-func2- `
       --storage-account myfunc2storage `
       --consumption-plan-location eastus `
       --resource-group my-rg `
       --runtime python `
       --runtime-version 3.11 `
       --functions-version 4 `
       --os-type Linux
   ```

4. **Enable Managed Identity**
   ```powershell
   $identity = az functionapp identity assign `
       --name my-func2- `
       --resource-group my-rg | ConvertFrom-Json
   
   $principalId = $identity.principalId
   Write-Host "Principal ID: $principalId"
   ```

5. **Grant Storage Permissions**
   ```powershell
   # Replace <storage-account-name> with your target storage account
   az role assignment create `
       --role "Storage Blob Data Reader" `
       --assignee-object-id $principalId `
       --scope /subscriptions/asdfasddfsdf/resourceGroups/my-rg/providers/Microsoft.Storage/storageAccounts/<storage-account-name>
   ```

6. **Deploy Function Code**
   ```powershell
   func azure functionapp publish my-func2- --python
   ```

7. **Get Function URL**
   ```powershell
   $url = az functionapp function show `
       --name my-func2- `
       --resource-group my-rg `
       --function-name read_storage `
       --query invokeUrlTemplate -o tsv
   
   Write-Host "Function URL: $url"
   ```

## Usage

### Get Function Key

```powershell
$functionKey = az functionapp keys list `
    --name my-func2- `
    --resource-group my-rg `
    --query functionKeys.default -o tsv
```

### Call the Function

```powershell
# List blobs
$uri = "https://my-func2-.azurewebsites.net/api/read_storage?code=$functionKey&storage_account=mystorageacct&container=mycontainer"
Invoke-RestMethod -Uri $uri

# Read specific blob
$uri = "https://my-func2-.azurewebsites.net/api/read_storage?code=$functionKey&storage_account=mystorageacct&container=mycontainer&blob_name=data/file.csv"
Invoke-RestMethod -Uri $uri

# Health check
$uri = "https://my-func2-.azurewebsites.net/api/health?code=$functionKey"
Invoke-RestMethod -Uri $uri
```

## Security

- The function uses **Managed Identity** for authentication to Azure Storage
- No storage account keys are required
- Ensure the function's managed identity has the **Storage Blob Data Reader** role on the target storage account

## Monitoring

View logs in Azure Portal:
1. Navigate to your Function App
2. Go to **Functions** → **read_storage** → **Monitor**
3. View **Invocations** and **Logs**

Or use Azure CLI:
```powershell
az functionapp log tail --name my-func2- --resource-group my-rg
```

## Troubleshooting

### Authentication Errors

If you get authentication errors:
1. Verify managed identity is enabled
2. Check role assignment on storage account
3. Ensure the storage account name is correct

### Deployment Issues

If deployment fails:
1. Check Azure Functions Core Tools version: `func --version` (should be 4.x)
2. Verify you're logged in: `az account show`
3. Check function app exists: `az functionapp show --name my-func2- --resource-group my-rg`

## Environment Variables

Set in Azure Portal or via CLI:

```powershell
az functionapp config appsettings set `
    --name my-func2- `
    --resource-group my-rg `
    --settings "STORAGE_ACCOUNT_NAME=mystorageacct" "CONTAINER_NAME=mycontainer"
```

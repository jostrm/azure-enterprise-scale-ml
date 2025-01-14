
param (
    # required parameters
    [Parameter(Mandatory = $true, HelpMessage = "Resource group name")][string]$resourceGroupName,
    [Parameter(Mandatory=$true, HelpMessage="Storage account name")][string]$storageAccountName,
    [Parameter(Mandatory = $false, HelpMessage = "Azure machine learning workspace name")][string]$workspaceName,
    [Parameter(Mandatory = $false, HelpMessage = "Datastore name")][string]$datastoreName,
    [Parameter(Mandatory = $false, HelpMessage = "Datastore name")][string]$azureAIServices
)

### 1) STORAGE: Public Access, Shared Key Access
# Needed for Azure ML Compute Instance - for notebooks to be able to access the storage account
Set-AzStorageAccount -ResourceGroupName $resourceGroupName -Name $storageAccountName -AllowBlobPublicAccess $true

# Needed for Azure ML Datastore - only KEY or SAS token
Set-AzStorageAccount -ResourceGroupName $resourceGroupName -Name $storageAccountName -AllowSharedKeyAccess $true

### 2) Azure ML DATA STORE
if (-not [String]::IsNullOrEmpty($datastoreName)) {
    # Get datastore
    $datastore = Get-AzMlDatastore -ResourceGroupName $resourceGroupName -WorkspaceName $workspaceName -Name $datastoreName
    # Update datastore, to Entra ID, managed identity ( instead of KEY or SAS token)
    $identity = New-AzMlIdentityConfiguration -Type "SystemAssigned"
    Set-AzMlDatastore -ResourceGroupName $resourceGroupName -WorkspaceName $workspaceName -Name $datastoreName -Identity $identity
    # Verify 
    $updatedDatastore = Get-AzMlDatastore -ResourceGroupName $resourceGroupName -WorkspaceName $workspaceName -Name $datastoreName
    $updatedDatastore.Identity.Type  # Should output 'SystemAssigned'

}

### 3) Azure AI Services: -DisableLocalAuth (very similas as "-AllowSharedKeyAccess" for Storage account)
if (-not [String]::IsNullOrEmpty($azureAIServices)) {
    Set-AzCognitiveServicesAccount -ResourceGroupName $resourceGroupName -Name $azureAIServices -DisableLocalAuth $false
}


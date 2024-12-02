
param (
    # required parameters
    [Parameter(Mandatory = $true, HelpMessage = "Resrouce group name")][string]$resourceGroupName,
    [Parameter(Mandatory=$true, HelpMessage="Storage account name")][string]$storageAccountName,
    [Parameter(Mandatory = $false, HelpMessage = "Azure machine learning workspace name")][string]$workspaceName,
    [Parameter(Mandatory = $false, HelpMessage = "Datastore name")][string]$datastoreName
)

# Needed for Azure ML Compute Instance - for notebooks to be able to access the storage account
Set-AzStorageAccount -ResourceGroupName $resourceGroupName -Name $storageAccountName -AllowBlobPublicAccess $true

# Needed for Azure ML Datastore - only KEY or SAS token
Set-AzStorageAccount -ResourceGroupName $resourceGroupName -Name $storageAccountName -AllowSharedKeyAccess $true

if (-not [String]::IsNullOrEmpty($datastoreName)) {
    # Get datastore
    $datastore = Get-AzMlDatastore -ResourceGroupName $resourceGroupName -WorkspaceName $workspaceName -Name $datastoreName
    # Update datstore, to Entra ID, managed identity ( instead of KEY or SAS token)
    $identity = New-AzMlIdentityConfiguration -Type "SystemAssigned"
    Set-AzMlDatastore -ResourceGroupName $resourceGroupName -WorkspaceName $workspaceName -Name $datastoreName -Identity $identity
    # Verify 
    $updatedDatastore = Get-AzMlDatastore -ResourceGroupName $resourceGroupName -WorkspaceName $workspaceName -Name $datastoreName
    $updatedDatastore.Identity.Type  # Should output 'SystemAssigned'

}


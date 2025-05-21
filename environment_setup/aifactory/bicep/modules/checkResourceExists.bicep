param resourceGroupName string
param resourceName string
param resourceType string

/*
var isStorageAccount = resourceType == 'Microsoft.Storage/storageAccounts'
resource existingStorageAccount 'Microsoft.Storage/storageAccounts@2022-09-01' existing = if (isStorageAccount) {
  name: resourceName
  scope: resourceGroup(resourceGroupName)
}
output exists bool = isStorageAccount ? !empty(existingStorageAccount.id) : false
*/

output exists bool = !empty(subscriptionResourceId(resourceGroupName, resourceType, resourceName))

// ============================================================================
// Kong Storage - Azure Storage Account + File Share for Kong config
// ============================================================================

@description('Storage account name')
param storageAccountName string

@description('Location')
param location string

@description('Tags')
param tags object

@description('Kong subnet ID for network rules')
param kongSubnetId string

// ============================================================================
// Storage Account (for Kong declarative config file share)
// ============================================================================
resource storageAccount 'Microsoft.Storage/storageAccounts@2023-05-01' = {
  name: storageAccountName
  location: location
  tags: tags
  sku: {
    name: 'Standard_LRS'
  }
  kind: 'StorageV2'
  properties: {
    minimumTlsVersion: 'TLS1_2'
    supportsHttpsTrafficOnly: true
    allowBlobPublicAccess: false
    networkAcls: {
      defaultAction: 'Deny'
      bypass: 'AzureServices'
      virtualNetworkRules: [
        {
          id: kongSubnetId
          action: 'Allow'
        }
      ]
    }
  }
}

// ============================================================================
// File Service + Share for Kong declarative config
// ============================================================================
resource fileService 'Microsoft.Storage/storageAccounts/fileServices@2023-05-01' = {
  parent: storageAccount
  name: 'default'
}

resource kongFileShare 'Microsoft.Storage/storageAccounts/fileServices/shares@2023-05-01' = {
  parent: fileService
  name: 'kong-config'
  properties: {
    shareQuota: 1
  }
}

// ============================================================================
// Outputs
// ============================================================================
output storageAccountName string = storageAccount.name
output fileShareName string = kongFileShare.name
output storageAccountId string = storageAccount.id

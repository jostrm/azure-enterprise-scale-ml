@description('Array of merged virtualNetworksules, subnets, to allow in the storage accounts firewwall. If you want to ADD. Read first all, then add your new')
param virtualNetworkRules array = []

@description('Specifies the containerName of the datalake gen2 storage')
param containerName string = ''
@minLength(3)
@maxLength(24)
@description('Specifies the name of the storage')
param storageAccountName string
@allowed([
  'Standard_LRS'
  'Standard_GRS'
  'Standard_ZRS'
  'Premium_LRS'
  'Premium_ZRS'
  'Standard_GRS'
  'Standard_GZRS'
  'Standard_LRS'
  'Standard_RAGRS'
  'Standard_RAGZRS'
  'Standard_ZRS'
])
@description('Specifies the SKU of the storage account')
param skuName string
param location string

@description('Specifies the id of the subnet used for the private endpoints')
param subnetName string

@description('Specifies name of the blob private endpoint')
param blobPrivateEndpointName string

@description('Specifies the name of the file service private endpoint')
param filePrivateEndpointName string

@description('Specifies the name of the dfs service private endpoint')
param dfsPrivateEndpointName string

@description('Specifies the name of the queue service private endpoint')
param queuePrivateEndpointName string

@description('Specifies the name of the table service private endpoint')
param tablePrivateEndpointName string

@description('Specifies the tags that should be applied to the storage acocunt resources')
param tags object

@description('Access keys will automatically be rotated in X days.')
param keyExpirationPeriodInDays int = 14

@description('Amount of days the soft deleted data is stored and available for recovery')
@minValue(1)
@maxValue(365)
param deleteRetentionPolicy int = 7
@description('If soft delete on blobs should be enabled, available for recovery')
param deleteRetentionPolicyEnabled bool = true

@description('Enable blob encryption at rest')
param encryptionEnabled bool = true
param ipWhitelist_array array = []
param virtualNetworkRules_array array = []
param containers array = ['lake3']
param files array = []
param vnetName string
param vnetResourceGroupName string
param corsRules array = [
  {
    allowedOrigins: [
      'https://mlworkspace.azure.ai'
      'https://ml.azure.com'
      'https://*.ml.azure.com'
      'https://ai.azure.com'
      'https://*.ai.azure.com'
      'https://mlworkspacecanary.azure.ai'
      'https://mlworkspace.azureml-test.net'
    ]
    allowedMethods: [
      'GET'
      'HEAD'
      'POST'
      'PUT'
      'DELETE'
      'OPTIONS'
      'PATCH'
    ]
    maxAgeInSeconds: 1800
    exposedHeaders: [
      '*'
    ]
    allowedHeaders: [
      '*'
    ]
  }
]

var groupIds = [
  {
    name: blobPrivateEndpointName
    gid: 'blob'
  }
  {
    name: filePrivateEndpointName
    gid: 'file'
  }
  {
    name: dfsPrivateEndpointName
    gid: 'dfs'
  }
  {
    name: queuePrivateEndpointName
    gid: 'queue'
  }
  {
    name: tablePrivateEndpointName
    gid: 'table'
  }
]

resource vnet 'Microsoft.Network/virtualNetworks@2024-05-01' existing = {
  name: vnetName
  scope: resourceGroup(vnetResourceGroupName)
}

resource subnet 'Microsoft.Network/virtualNetworks/subnets@2024-05-01' existing = {
  name: subnetName
  parent: vnet
}


//resource lake 'Microsoft.Storage/storageAccounts@2021-02-01'= {
resource lake 'Microsoft.Storage/storageAccounts@2023-05-01' = {
  name: storageAccountName // esmldatalake002dev
  sku: {
    name: skuName
  }
  kind: 'StorageV2'
  tags: tags
  location: location
  properties:{
    allowBlobPublicAccess: false
    publicNetworkAccess:'Disabled'
    accessTier: 'Hot'
    isHnsEnabled: true // DATALAKE
    //allowCrossTenantReplication: true  // Not supported if DATALAKE
    // isNfsV3Enabled: false // Not supported if DATALAKE
    allowSharedKeyAccess: true
    encryption: {
      keySource: 'Microsoft.Storage'
      services: {
        blob: {
          enabled: true
          keyType: 'Account'
        }
        file: {
          enabled: true
          keyType: 'Account'
        }
        queue: {
          enabled: true
          keyType: 'Service'
        }
        table: {
          enabled: true
          keyType: 'Service'
        }
      }
    }
    keyPolicy: {
      keyExpirationPeriodInDays: keyExpirationPeriodInDays
    }
    largeFileSharesState: 'Disabled'
    minimumTlsVersion: 'TLS1_2'
    supportsHttpsTrafficOnly: true
    networkAcls:{
      bypass: 'AzureServices'
      defaultAction:'Deny'
      ipRules: [for ip in ipWhitelist_array: {
        action: 'Allow'
        value: ip
      }]
      virtualNetworkRules:[for snet_id in virtualNetworkRules_array:{
          action: 'Allow'
          id: snet_id
        }]
    }
  }
  resource blobServices 'blobServices' = if (!empty(containers)) {
    name: 'default'
    properties: {
      cors: {
        corsRules: corsRules
      }
      deleteRetentionPolicy: {
        enabled: true
        days: deleteRetentionPolicy
      }
    }
    resource container 'containers' = [for container in containers: {
      name: container
      properties: {
        publicAccess: 'None'
      }
    }]
  }
  resource fileServices 'fileServices' = if (!empty(files)) {
    name: 'default'
    properties: {
      cors: {
        corsRules: corsRules
      }
      shareDeleteRetentionPolicy: {
        enabled: true
        days: deleteRetentionPolicy
      }
    }
  }
}
resource pendSaccBlob 'Microsoft.Network/privateEndpoints@2023-04-01' =  {
  name: blobPrivateEndpointName
  location: location
  tags: tags
  properties: {
    subnet: {
      id: subnet.id
    }
    customNetworkInterfaceName: '${blobPrivateEndpointName}-nic'
    privateLinkServiceConnections: [
      {
        name: blobPrivateEndpointName
        properties: {
          privateLinkServiceId: lake.id
          groupIds: [
            'blob'
          ]
          privateLinkServiceConnectionState: {
            status: 'Approved'
            description: 'Auto-Approved'
            actionsRequired: 'None'
          }
        }
      }
    ]
  }
}
resource pendSaccFile 'Microsoft.Network/privateEndpoints@2023-04-01' =  {
  name: filePrivateEndpointName
  location: location
  tags: tags
  properties: {
    subnet: {
      id: subnet.id
    }
    customNetworkInterfaceName: '${filePrivateEndpointName}-nic'
    privateLinkServiceConnections: [
      {
        name: filePrivateEndpointName
        properties: {
          privateLinkServiceId: lake.id
          groupIds: [
            'file'
          ]
          privateLinkServiceConnectionState: {
            status: 'Approved'
            description: 'Auto-Approved'
            actionsRequired: 'None'
          }
        }
      }
    ]
  }
}
resource pendSaccQ 'Microsoft.Network/privateEndpoints@2023-04-01' =  {
  name: queuePrivateEndpointName
  location: location
  tags: tags
  properties: {
    subnet: {
      id: subnet.id
    }
    customNetworkInterfaceName: '${queuePrivateEndpointName}-nic'
    privateLinkServiceConnections: [
      {
        name: queuePrivateEndpointName
        properties: {
          privateLinkServiceId: lake.id
          groupIds: [
            'queue'
          ]
          privateLinkServiceConnectionState: {
            status: 'Approved'
            description: 'Auto-Approved'
            actionsRequired: 'None'
          }
        }
      }
    ]
  }
}
resource pendSaccTable 'Microsoft.Network/privateEndpoints@2023-04-01' =  {
  name: tablePrivateEndpointName
  location: location
  tags: tags
  properties: {
    subnet: {
      id: subnet.id
    }
    customNetworkInterfaceName: '${tablePrivateEndpointName}-nic'
    privateLinkServiceConnections: [
      {
        name: tablePrivateEndpointName
        properties: {
          privateLinkServiceId: lake.id
          groupIds: [
            'table'
          ]
          privateLinkServiceConnectionState: {
            status: 'Approved'
            description: 'Auto-Approved'
            actionsRequired: 'None'
          }
        }
      }
    ]
  }
}
resource pendSaccDfs 'Microsoft.Network/privateEndpoints@2023-04-01' =  {
  name: dfsPrivateEndpointName
  location: location
  tags: tags
  properties: {
    subnet: {
      id: subnet.id
    }
    customNetworkInterfaceName: '${dfsPrivateEndpointName}-nic'
    privateLinkServiceConnections: [
      {
        name: dfsPrivateEndpointName
        properties: {
          privateLinkServiceId: lake.id
          groupIds: [
            'dfs'
          ]
          privateLinkServiceConnectionState: {
            status: 'Approved'
            description: 'Auto-Approved'
            actionsRequired: 'None'
          }
        }
      }
    ]
  }
}

output storageAccountId string = lake.id
output virtualNetworkRules array = lake.properties.networkAcls.virtualNetworkRules

output dnsConfig array = [
  {
    name: pendSaccBlob.name
    type: 'blob'
    id: lake.id
  }
  {
    name: filePrivateEndpointName
    type: 'file'
    id: lake.id
  }
  {
    name: dfsPrivateEndpointName
    type: 'dfs'
    id: lake.id
  }
  {
    name: queuePrivateEndpointName
    type: 'queue'
    id: lake.id
  }
  {
    name: tablePrivateEndpointName
    type: 'table'
    id: lake.id
  }
]

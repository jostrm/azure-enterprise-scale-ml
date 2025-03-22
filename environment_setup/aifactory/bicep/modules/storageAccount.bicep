@description('Specifies the name of the new storage account')
param storageAccountName string

@description('Specifies name of the blob private endpoint')
param blobPrivateEndpointName string

@description('Specifies the name of the file service private endpoint')
param filePrivateEndpointName string

@description('Specifies the name of the queue service private endpoint')
param queuePrivateEndpointName string

@description('Specifies the name of the table service private endpoint')
param tablePrivateEndpointName string

param corsRules array = []
param containers array = []
param files array = []
param networkAcls object = {}
param enablePublicAccessWithPerimeter bool = false

@allowed([
  'Standard_LRS'
  'Standard_ZRS'
  'Standard_GRS'
  'Standard_GZRS'
  'Standard_RAGRS'
  'Standard_RAGZRS'
  'Premium_LRS'
  'Premium_ZRS'
])
@description('Specifies the name of the storage account SKU')
param skuName string

@description('Specifies the id of the virtual network used for private endpoints')
param vnetId string

@description('Specifies the id of the subnet used for the private endpoints')
param subnetName string

@description('Specifies the tags that should be applied to the storage acocunt resources')
param tags object
param vnetRules array = []
param ipRules array = []

var location = resourceGroup().location
var subnetRef = '${vnetId}/subnets/${subnetName}'
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
    name: queuePrivateEndpointName
    gid: 'queue'
  }
  {
    name: tablePrivateEndpointName
    gid: 'table'
  }
]

resource sacc 'Microsoft.Storage/storageAccounts@2023-05-01' = {
  name: storageAccountName
  tags: tags
  location: location
  kind: 'StorageV2'
  sku: {
    name: skuName
  }
  properties:{
    accessTier: 'Hot'
    publicNetworkAccess: enablePublicAccessWithPerimeter?'Enabled':'Disabled'
    allowCrossTenantReplication: true
    allowSharedKeyAccess: true
    allowBlobPublicAccess: false
    isHnsEnabled: false
    isNfsV3Enabled: false
    enableExtendedGroups: false
    supportsHttpsTrafficOnly: true
    encryption: {
      keySource: 'Microsoft.Storage'
      requireInfrastructureEncryption: false
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
      keyExpirationPeriodInDays: 7
    }
    largeFileSharesState: 'Disabled'
    minimumTlsVersion: 'TLS1_2'
    networkAcls: {
      bypass: 'AzureServices' 
      defaultAction: enablePublicAccessWithPerimeter? 'Allow':'Deny' 
      virtualNetworkRules:[for rule in vnetRules:{
        action: 'Allow'
        id: rule
      }]
      ipRules:empty(ipRules)?[]:ipRules
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
        days: 7
      }
    }
    resource container 'containers' = [for container in containers: {
      name: container.name
      properties: {
        publicAccess: contains(container, 'publicAccess') ? container.publicAccess : 'None'
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
        days: 7
      }
    }
  }
  
}

resource pendSacc 'Microsoft.Network/privateEndpoints@2023-04-01' = [for obj in groupIds: {
  name: 'pend-${obj.name}'
  location: location
  tags: tags
  properties: {
    subnet: {
      id: subnetRef
      name: subnetName
    }
    customNetworkInterfaceName: 'pend-${obj.name}-nic'
    privateLinkServiceConnections: [
      {
        name: 'pend-${obj.name}'
        properties: {
          privateLinkServiceId: sacc.id
          groupIds: [
            obj.gid
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
}]

output storageAccountId string = sacc.id
output storageAccountName string = sacc.name
output dnsConfig array = [
  {
    name: pendSacc[0].name
    type: 'blob'
    id:sacc.id
  }
  {
    name: pendSacc[1].name
    type: 'file'
    id:sacc.id
  }
  {
    name: pendSacc[2].name
    type: 'queue'
    id:sacc.id
  }
  {
    name: pendSacc[3].name
    type: 'table'
    id:sacc.id
  }
]

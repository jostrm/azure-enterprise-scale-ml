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

resource sacc 'Microsoft.Storage/storageAccounts@2021-04-01' = {
  name: storageAccountName
  tags: tags
  location: location
  kind: 'StorageV2'
  sku: {
    name: skuName
  }
  properties:{
    accessTier: 'Hot'
    allowCrossTenantReplication: true
    allowSharedKeyAccess: true
    allowBlobPublicAccess: false
    isHnsEnabled: false
    isNfsV3Enabled: false
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
    minimumTlsVersion: 'TLS1_2'  // CHECK?
    networkAcls: {
      bypass: 'AzureServices' // CHECK?
      defaultAction: 'Deny' // CHECK?
    }
    supportsHttpsTrafficOnly: true
  }
}

resource pendSacc 'Microsoft.Network/privateEndpoints@2020-07-01' = [for obj in groupIds: {
  name: obj.name
  location: location
  tags: tags
  properties: {
    subnet: {
      id: subnetRef
      name: subnetName
    }
    privateLinkServiceConnections: [
      {
        id: 'string'
        properties: {
          privateLinkServiceId: sacc.id
          groupIds: [
            obj.gid
          ]
          privateLinkServiceConnectionState: {
            status: 'Approved'
            description: 'Compliance with network design'
          }
        }
        name: 'string'
      }
    ]
  }
}]

output storageAccountId string = sacc.id
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

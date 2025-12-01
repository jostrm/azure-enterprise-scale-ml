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
param enablePublicAccessWithPerimeter bool = false
param enablePublicGenAIAccess bool = false
import { managedIdentityAllType } from 'br/public:avm/utl/types/avm-common-types:0.5.1'
@description('Optional. The managed identity definition for this resource.')
param managedIdentities managedIdentityAllType?

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

//@description('Specifies the id of the virtual network used for private endpoints')
//param vnetId string

@description('Specifies the id of the subnet used for the private endpoints')
param subnetName string

@description('Specifies the tags that should be applied to the storage acocunt resources')
param tags object
param vnetRules array = []
param ipRules array = []
param location string
param vnetName string
param vnetResourceGroupName string

// CMK Parameters
param cmk bool = false
param cmkIdentityId string = ''
param cmkKeyName string = ''
param cmkKeyVaultUri string = ''

//var subnetRef = '${vnetId}/subnets/${subnetName}'
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
var formattedUserAssignedIdentities = reduce(
  map((managedIdentities.?userAssignedResourceIds ?? []), (id) => { '${id}': {} }),
  {},
  (cur, next) => union(cur, next)
) // Converts the flat array to an object like { '${id1}': {}, '${id2}': {} }

var cmkIdentity = cmk && !empty(cmkIdentityId) ? { '${cmkIdentityId}': {} } : {}
var allUserAssignedIdentities = union(formattedUserAssignedIdentities, cmkIdentity)

var identity = !empty(managedIdentities) || !empty(cmkIdentity)
  ? {
      type: (managedIdentities.?systemAssigned ?? false) // Default to true if managedIdentities is null? No, default to false.
        ? (!empty(allUserAssignedIdentities) ? 'SystemAssigned,UserAssigned' : 'SystemAssigned')
        : (!empty(allUserAssignedIdentities) ? 'UserAssigned' : 'None')
      userAssignedIdentities: !empty(allUserAssignedIdentities) ? allUserAssignedIdentities : null
    }
  : {type:'SystemAssigned'} // Default fallback if nothing provided

resource vnet 'Microsoft.Network/virtualNetworks@2024-05-01' existing = {
  name: vnetName
  scope: resourceGroup(vnetResourceGroupName)
}

resource subnet 'Microsoft.Network/virtualNetworks/subnets@2024-05-01' existing = {
  name: subnetName
  parent: vnet
}
var rules = [for rule in vnetRules:{
  action: 'Allow'
  id: rule
}]

resource sacc2 'Microsoft.Storage/storageAccounts@2025-01-01' = if(enablePublicGenAIAccess||enablePublicAccessWithPerimeter) {
  name: storageAccountName
  tags: tags
  location: location
  kind: 'StorageV2'
  identity: identity
  sku: {
    name: skuName
  }
  properties:{
    accessTier: 'Hot'
    publicNetworkAccess:'Enabled'
    allowCrossTenantReplication: true
    allowSharedKeyAccess: true
    allowBlobPublicAccess: false
    isHnsEnabled: false
    isNfsV3Enabled: false
    enableExtendedGroups: false
    supportsHttpsTrafficOnly: true
    encryption: {
      keySource: cmk ? 'Microsoft.Keyvault' : 'Microsoft.Storage'
      identity: cmk ? { userAssignedIdentity: cmkIdentityId } : null
      keyvaultproperties: cmk ? {
          keyname: cmkKeyName
          keyvaulturi: cmkKeyVaultUri
      } : null
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
    networkAcls: (enablePublicAccessWithPerimeter && enablePublicGenAIAccess) ? {
      // Scenario 2: Fully public with vnetRules but no ipRules
      bypass: 'AzureServices'
      defaultAction: 'Allow'
      virtualNetworkRules: rules
      ipRules: []
    } : (!enablePublicAccessWithPerimeter && enablePublicGenAIAccess) ? {
      // Scenario 1: IP-whitelisting with both vnetRules and ipRules
      bypass: 'AzureServices'
      defaultAction: 'Deny'
      virtualNetworkRules: rules
      ipRules: empty(ipRules) ? [] : ipRules
    } : (enablePublicGenAIAccess || !empty(ipRules) || !empty(vnetRules)) ? {
      // Other scenarios
      bypass: 'AzureServices' 
      defaultAction: enablePublicGenAIAccess && empty(ipRules) && empty(vnetRules) ? 'Allow' : 'Deny'
      virtualNetworkRules: rules
      ipRules: empty(ipRules) ? [] : ipRules
    } : null
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
        publicAccess:'None'
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
resource sacc 'Microsoft.Storage/storageAccounts@2025-01-01' = if(!enablePublicGenAIAccess) {
  name: storageAccountName
  tags: tags
  location: location
  kind: 'StorageV2'
  identity: identity
  sku: {
    name: skuName
  }
  properties:{
    accessTier: 'Hot'
    publicNetworkAccess:'Disabled'
    allowCrossTenantReplication: true
    allowSharedKeyAccess: false
    allowBlobPublicAccess: false
    isHnsEnabled: false
    isNfsV3Enabled: false
    enableExtendedGroups: false
    supportsHttpsTrafficOnly: true
    encryption: {
      keySource: cmk ? 'Microsoft.Keyvault' : 'Microsoft.Storage'
      identity: cmk ? { userAssignedIdentity: cmkIdentityId } : null
      keyvaultproperties: cmk ? {
          keyname: cmkKeyName
          keyvaulturi: cmkKeyVaultUri
      } : null
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
    networkAcls:{
      bypass: 'AzureServices' 
      defaultAction: 'Deny' 
      virtualNetworkRules:rules
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
        days: 7
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
          privateLinkServiceId: !enablePublicGenAIAccess? sacc.id: sacc2.id
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
          privateLinkServiceId: !enablePublicGenAIAccess? sacc.id: sacc2.id
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
          privateLinkServiceId: !enablePublicGenAIAccess? sacc.id: sacc2.id
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
          privateLinkServiceId: !enablePublicGenAIAccess? sacc.id: sacc2.id
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


output storageAccountId string = !enablePublicGenAIAccess? sacc.id: sacc2.id
output storageAccountName string = !enablePublicGenAIAccess? sacc.name: sacc2.name
output dnsConfig array = [
  {
    name: pendSaccBlob.name
    type: 'blob'
    id:!enablePublicGenAIAccess? sacc.id: sacc2.id
  }
  {
    name: filePrivateEndpointName
    type: 'file'
    id:!enablePublicGenAIAccess? sacc.id: sacc2.id
  }
  {
    name: queuePrivateEndpointName
    type: 'queue'
    id:!enablePublicGenAIAccess? sacc.id: sacc2.id
  }
  {
    name: tablePrivateEndpointName
    type: 'table'
    id:!enablePublicGenAIAccess? sacc.id: sacc2.id
  }
]

@description('Specifies the name of the Azure Data Factory')
param name string

@description('Location where datafacory should be deployed')
param location string

@description('Specifies a object with key value pairs added as tags to Data Factory resource')
param tags object

@description('(Required) Specifies the virtual network id associated with private endpoint')
param vnetId string

@description('(Required) Specifies the subnet name that will be associated with the private endpoint')
@minLength(1)
param subnetName string

@description('Specifies name of the portal private endpoint')
param portalPrivateEndpointName string

@description('Specifies the name of the runtime service private endpoint')
param runtimePrivateEndpointName string

import { managedIdentityAllType } from 'br/public:avm/utl/types/avm-common-types:0.5.1'
@description('Optional. The managed identity definition for this resource.')
param managedIdentities managedIdentityAllType?
param enablePublicAccessWithPerimeter bool = false
@description('Enable Customer Managed Keys (CMK) encryption')
param cmk bool = false

@description('Name of the Customer Managed Key in Key Vault')
param cmkKeyName string = ''

@description('URI of the Key Vault for CMK')
param keyVaultUri string = ''

// ============================================================================
// Linked Services bootstrap (authenticated via the project User-Assigned MI)
// A Credential of type ManagedIdentity is created on the factory pointing to
// the project UAMI; each linked service references it via CredentialReference.
// The UAMI is also added to the factory identity so the credential is valid.
// NOTE: the UAMI still needs data-plane RBAC on each target (KV/Storage/Cosmos)
// for the linked services to work at runtime - that is handled by RBAC modules.
// ============================================================================
@description('Resource ID of the project User-Assigned Managed Identity used by Data Factory linked services. Also assigned to the factory identity. Empty = no UAMI / no linked services.')
param projectUamiResourceId string = ''

@description('Master switch: create Data Factory linked services (Key Vault, Storage, Cosmos DB, Function) authenticated via the project UAMI.')
param deployLinkedServices bool = false

@description('Key Vault name for the AzureKeyVault linked service. Empty = skip.')
param linkedServiceKeyVaultName string = ''

@description('ADLS Gen2 / Storage account name for the AzureBlobFS linked service. Empty = skip.')
param linkedServiceStorageAccountName string = ''

@description('Cosmos DB account name for the CosmosDb linked service. Empty = skip.')
param linkedServiceCosmosDbName string = ''

@description('Cosmos DB database name for the CosmosDb linked service. Required (with the account name) to create the Cosmos linked service.')
param linkedServiceCosmosDbDatabase string = ''

@description('Create the AzureFunction linked service (optional).')
param enableFunctionLinkedService bool = false

@description('Function App name for the AzureFunction linked service. Empty = skip.')
param linkedServiceFunctionAppName string = ''

@description('AAD resource/audience (Application ID URI or client ID) of the Function App for MSI authentication. Required to create the Function linked service.')
param linkedServiceFunctionResourceId string = ''

// ============================================================================
// Managed VNet + AutoResolve managed Integration Runtime + managed private endpoints
// Puts ADF's data-movement compute (IR) inside a Microsoft-managed VNet and
// reaches the data stores over Private Link (egress). The managed VNet is NOT
// attached to your own VNet; privacy comes from the per-target managed private
// endpoints created below. Those land in 'Pending' and must be APPROVED on each
// target resource (KV/Storage/Cosmos/Function) - see 'managedPrivateEndpoints' output.
// ============================================================================
@description('Create the managed VNet, AutoResolve managed Integration Runtime and managed private endpoints to the data stores. Default false; the caller typically enables this when public access is disabled.')
param enableManagedVnet bool = false

@description('ARM resource ID of the Key Vault to reach via a managed private endpoint (groupId vault). Empty = skip.')
param managedPeKeyVaultResourceId string = ''

@description('ARM resource ID of the ADLS Gen2 / Storage account to reach via a managed private endpoint (groupId dfs). Empty = skip.')
param managedPeStorageResourceId string = ''

@description('ARM resource ID of the Cosmos DB account to reach via a managed private endpoint (groupId Sql). Empty = skip.')
param managedPeCosmosResourceId string = ''

@description('ARM resource ID of the Function App to reach via a managed private endpoint (groupId sites). Used only when enableFunctionLinkedService is true. Empty = skip.')
param managedPeFunctionResourceId string = ''

var projectUamiCredentialName = 'ls_cred_project_uami'

var subnetRef = '${vnetId}/subnets/${subnetName}'

var groupIds = [
  {
    name: portalPrivateEndpointName
    gid: 'portal'
  }
  {
    name: runtimePrivateEndpointName
    gid: 'dataFactory'
  }
]

// Merge any caller-provided UAMIs with the project UAMI (needed for the linked-service credential)
var allUserAssignedResourceIds = union(
  (managedIdentities.?userAssignedResourceIds ?? []),
  empty(projectUamiResourceId) ? [] : [projectUamiResourceId]
)
var formattedUserAssignedIdentities = reduce(
  map(allUserAssignedResourceIds, (id) => { '${id}': {} }),
  {},
  (cur, next) => union(cur, next)
) // Converts the flat array to an object like { '${id1}': {}, '${id2}': {} }
var hasSystemAssigned = managedIdentities.?systemAssigned ?? false
var hasUserAssigned = !empty(allUserAssignedResourceIds)
var identity = (empty(managedIdentities) && empty(projectUamiResourceId))
  ? { type: 'SystemAssigned' }
  : {
      type: hasSystemAssigned
        ? (hasUserAssigned ? 'SystemAssigned,UserAssigned' : 'SystemAssigned')
        : (hasUserAssigned ? 'UserAssigned' : 'None')
      userAssignedIdentities: hasUserAssigned ? formattedUserAssignedIdentities : null
    }


resource adf 'Microsoft.DataFactory/factories@2018-06-01' = {
  name: name
  location: location
  tags: tags
  identity:identity
  properties: {
    globalParameters: {}
    publicNetworkAccess: enablePublicAccessWithPerimeter ? 'Enabled': 'Disabled'
    encryption: cmk ? {
      identity: {
        userAssignedIdentity: managedIdentities!.userAssignedResourceIds![0]
      }
      keyName: cmkKeyName
      keyVersion: ''
      vaultBaseUrl: keyVaultUri
    } : null
  }

}

// ============================================================================
// Managed VNet + AutoResolve managed Integration Runtime
// Declaring AutoResolveIntegrationRuntime with a managedVirtualNetwork reference
// makes ADF's default IR run inside the managed VNet, so linked services that
// use it (the default) route through the managed private endpoints below.
// ============================================================================
resource adfManagedVnet 'Microsoft.DataFactory/factories/managedVirtualNetworks@2018-06-01' = if (enableManagedVnet) {
  parent: adf
  name: 'default'
  properties: {}
}

resource adfAutoResolveIR 'Microsoft.DataFactory/factories/integrationRuntimes@2018-06-01' = if (enableManagedVnet) {
  parent: adf
  name: 'AutoResolveIntegrationRuntime'
  properties: {
    type: 'Managed'
    managedVirtualNetwork: {
      type: 'ManagedVirtualNetworkReference'
      referenceName: 'default'
    }
    typeProperties: {
      computeProperties: {
        location: 'AutoResolve'
      }
    }
  }
  dependsOn: [
    adfManagedVnet
  ]
}

// ============================================================================
// Managed private endpoints (egress to the data stores). Pending until approved
// on each target resource - emitted via the 'managedPrivateEndpoints' output.
// ============================================================================
resource mpeKeyVault 'Microsoft.DataFactory/factories/managedVirtualNetworks/managedPrivateEndpoints@2018-06-01' = if (enableManagedVnet && !empty(managedPeKeyVaultResourceId)) {
  parent: adfManagedVnet
  name: 'mpe_keyvault'
  properties: {
    privateLinkResourceId: managedPeKeyVaultResourceId
    groupId: 'vault'
  }
  dependsOn: [
    adfAutoResolveIR
  ]
}

resource mpeStorage 'Microsoft.DataFactory/factories/managedVirtualNetworks/managedPrivateEndpoints@2018-06-01' = if (enableManagedVnet && !empty(managedPeStorageResourceId)) {
  parent: adfManagedVnet
  name: 'mpe_storage_lake'
  properties: {
    privateLinkResourceId: managedPeStorageResourceId
    groupId: 'dfs'
  }
  dependsOn: [
    adfAutoResolveIR
    mpeKeyVault
  ]
}

resource mpeCosmos 'Microsoft.DataFactory/factories/managedVirtualNetworks/managedPrivateEndpoints@2018-06-01' = if (enableManagedVnet && !empty(managedPeCosmosResourceId)) {
  parent: adfManagedVnet
  name: 'mpe_cosmosdb'
  properties: {
    privateLinkResourceId: managedPeCosmosResourceId
    groupId: 'Sql'
  }
  dependsOn: [
    adfAutoResolveIR
    mpeStorage
  ]
}

resource mpeFunction 'Microsoft.DataFactory/factories/managedVirtualNetworks/managedPrivateEndpoints@2018-06-01' = if (enableManagedVnet && enableFunctionLinkedService && !empty(managedPeFunctionResourceId)) {
  parent: adfManagedVnet
  name: 'mpe_function'
  properties: {
    privateLinkResourceId: managedPeFunctionResourceId
    groupId: 'sites'
  }
  dependsOn: [
    adfAutoResolveIR
    mpeCosmos
  ]
}

// ============================================================================
// Credential (ManagedIdentity) referencing the project UAMI
// ============================================================================
resource adfProjectUamiCredential 'Microsoft.DataFactory/factories/credentials@2018-06-01' = if (deployLinkedServices && !empty(projectUamiResourceId)) {
  parent: adf
  name: projectUamiCredentialName
  properties: {
    type: 'ManagedIdentity'
    typeProperties: {
      resourceId: projectUamiResourceId
    }
  }
}

// ============================================================================
// Linked Services (authenticated via the project UAMI credential)
// ============================================================================
resource lsKeyVault 'Microsoft.DataFactory/factories/linkedservices@2018-06-01' = if (deployLinkedServices && !empty(projectUamiResourceId) && !empty(linkedServiceKeyVaultName)) {
  parent: adf
  name: 'ls_keyvault'
  properties: {
    type: 'AzureKeyVault'
    description: 'Key Vault linked service (project UAMI)'
    typeProperties: {
      baseUrl: 'https://${linkedServiceKeyVaultName}${environment().suffixes.keyvaultDns}/'
      credential: {
        referenceName: projectUamiCredentialName
        type: 'CredentialReference'
      }
    }
  }
  dependsOn: [
    adfProjectUamiCredential
  ]
}

resource lsStorage 'Microsoft.DataFactory/factories/linkedservices@2018-06-01' = if (deployLinkedServices && !empty(projectUamiResourceId) && !empty(linkedServiceStorageAccountName)) {
  parent: adf
  name: 'ls_storage_lake'
  properties: {
    type: 'AzureBlobFS'
    description: 'ADLS Gen2 storage linked service (project UAMI)'
    typeProperties: {
      url: 'https://${linkedServiceStorageAccountName}.dfs.${environment().suffixes.storage}'
      credential: {
        referenceName: projectUamiCredentialName
        type: 'CredentialReference'
      }
    }
  }
  dependsOn: [
    adfProjectUamiCredential
  ]
}

resource lsCosmos 'Microsoft.DataFactory/factories/linkedservices@2018-06-01' = if (deployLinkedServices && !empty(projectUamiResourceId) && !empty(linkedServiceCosmosDbName) && !empty(linkedServiceCosmosDbDatabase)) {
  parent: adf
  name: 'ls_cosmosdb'
  properties: {
    type: 'CosmosDb'
    description: 'Cosmos DB linked service (project UAMI)'
    typeProperties: {
      accountEndpoint: 'https://${linkedServiceCosmosDbName}.documents.azure.com:443/'
      database: linkedServiceCosmosDbDatabase
      credential: {
        referenceName: projectUamiCredentialName
        type: 'CredentialReference'
      }
    }
  }
  dependsOn: [
    adfProjectUamiCredential
  ]
}

resource lsFunction 'Microsoft.DataFactory/factories/linkedservices@2018-06-01' = if (deployLinkedServices && enableFunctionLinkedService && !empty(projectUamiResourceId) && !empty(linkedServiceFunctionAppName) && !empty(linkedServiceFunctionResourceId)) {
  parent: adf
  name: 'ls_function'
  properties: {
    type: 'AzureFunction'
    description: 'Azure Function linked service (project UAMI)'
    typeProperties: {
      functionAppUrl: 'https://${linkedServiceFunctionAppName}.azurewebsites.net'
      authentication: 'MSI'
      resourceId: linkedServiceFunctionResourceId
      credential: {
        referenceName: projectUamiCredentialName
        type: 'CredentialReference'
      }
    }
  }
  dependsOn: [
    adfProjectUamiCredential
  ]
}

resource pendAdf 'Microsoft.Network/privateEndpoints@2023-04-01' = [for obj in groupIds: if(!enablePublicAccessWithPerimeter){
  name: '${name}-${obj.gid}-pend'
  location: location
  tags: tags
  dependsOn: [
    adf
  ]
  properties: {
    subnet: {
      id: subnetRef
    }
    customNetworkInterfaceName: '${name}-${obj.gid}-pend-nic'
    privateLinkServiceConnections: [
      {
        name: '${name}-${obj.gid}-pend'
        properties: {
          privateLinkServiceId: adf.id
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

output adfId string = adf.id
output adfName string = adf.name
output principalId string = adf.identity.principalId
output subnetReference string = subnetRef // Debug output to see the actual subnet reference being used

output dnsConfig array = [
  {
    name: !enablePublicAccessWithPerimeter? pendAdf[0].name: ''
    type: 'portal'
    id:adf.id
    groupid:groupIds[0].gid
  }
  {
    name: !enablePublicAccessWithPerimeter? pendAdf[1].name: ''
    type: 'dataFactory'
    id:adf.id
    groupid:groupIds[1].gid
  }
]

// Managed private endpoints created on the factory's managed VNet. These are in
// 'Pending' state and must be approved on each TARGET resource, e.g.:
//   az network private-endpoint-connection approve --id <connId> --description 'Approved by pipeline'
output managedVnetEnabled bool = enableManagedVnet
output managedPrivateEndpoints array = enableManagedVnet ? concat(
  !empty(managedPeKeyVaultResourceId) ? [{ name: 'mpe_keyvault', targetResourceId: managedPeKeyVaultResourceId, groupId: 'vault' }] : [],
  !empty(managedPeStorageResourceId) ? [{ name: 'mpe_storage_lake', targetResourceId: managedPeStorageResourceId, groupId: 'dfs' }] : [],
  !empty(managedPeCosmosResourceId) ? [{ name: 'mpe_cosmosdb', targetResourceId: managedPeCosmosResourceId, groupId: 'Sql' }] : [],
  (enableFunctionLinkedService && !empty(managedPeFunctionResourceId)) ? [{ name: 'mpe_function', targetResourceId: managedPeFunctionResourceId, groupId: 'sites' }] : []
) : []

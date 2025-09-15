@description('Specifies the name of the new machine learning studio resources')
param name string
param aifactorySuffix string
@description('Specifies the computer pool name')
param aifactoryProjectNumber string
@description('Specifies the location where the new machine learning studio resource should be deployed')
param location string
@description('ESML dev,test or prod. If DEV then AKS cluster is provisioned with 1 agent otherwise 3')
param env string
@description('Specifies the storageaccount id used for the machine learning studio')
param storageAccountName string
@description('Specifies the keyvault id used for the machine learning studio')
param keyVaultName string
@description('Specifies the tags that should be applied to machine learning studio resources')
param tags object
@description('(Required) Specifies the private endpoint name')
param privateEndpointName string
@description('(Required) Specifies the virtual network id associated with private endpoint')
param vnetName string
@description('(Required) Specifies the subnet name that will be associated with the private endpoint')
param subnetName string
param vnetResourceGroupName string
@description('ESML can run in DEMO mode, which creates private DnsZones,DnsZoneGroups, and vNetLinks. You can turn this off, to use your HUB instead.')

import { managedIdentityAllType } from 'br/public:avm/utl/types/avm-common-types:0.5.1'
@description('Optional. The managed identity definition for this resource.')
param managedIdentities managedIdentityAllType?
param defaultProjectName string = ''
param centralDnsZoneByPolicyInHub bool
param allowPublicAccessWhenBehindVnet bool=false
param enablePublicGenAIAccess bool=false
param enablePublicAccessWithPerimeter bool = false
param createPrivateEndpoint bool = true
param aiSearchName string
param aifactorySalt string
param aiHubExists bool = false
param privateLinksDnsZones object
@allowed([
  'Hub'
])
param kindAIHub string = 'Hub'
param ipRules array = []
param aiServicesName string
param logWorkspaceName string
param logWorkspaceResoureGroupName string
param locationSuffix string
param resourceSuffix string
param applicationInsightsName string
param ipWhitelist_array array = []
param acrName string
param acrRGName string

var aiFactoryNumber = substring(aifactorySuffix,1,3) // -001 to 001
var privateDnsZoneName =  {
  azureusgovernment: 'privatelink.api.ml.azure.us'
  azurechinacloud: 'privatelink.api.ml.azure.cn'
  azurecloud: 'privatelink.api.azureml.ms'
}

var privateDnsZoneNameNotebooks = {
    azureusgovernment: 'privatelink.notebooks.usgovcloudapi.net'
    azurechinacloud: 'privatelink.notebooks.chinacloudapi.cn'
    azurecloud: 'privatelink.notebooks.azure.net'
}

resource appInsights 'Microsoft.Insights/components@2020-02-02' existing = {
  name: applicationInsightsName
}
resource aiSearch 'Microsoft.Search/searchServices@2024-03-01-preview' existing = if(!empty(aiSearchName)) {
  name: aiSearchName
}

resource aiServices 'Microsoft.CognitiveServices/accounts@2024-10-01' existing = {
  name: aiServicesName
}
resource logWorkspace 'Microsoft.OperationalInsights/workspaces@2023-09-01' existing = {
  name: logWorkspaceName
  scope:resourceGroup(logWorkspaceResoureGroupName)
}
resource keyVault 'Microsoft.KeyVault/vaults@2023-07-01' existing = {
  name: keyVaultName
  scope: resourceGroup()
}

resource existingStorageAccount 'Microsoft.Storage/storageAccounts@2024-01-01' existing = {
  name: storageAccountName
}

resource vnet 'Microsoft.Network/virtualNetworks@2024-05-01' existing = {
  name: vnetName
  scope: resourceGroup(vnetResourceGroupName)
}

resource subnet 'Microsoft.Network/virtualNetworks/subnets@2024-05-01' existing = {
  name: subnetName
  parent: vnet
}
resource existingAcr 'Microsoft.ContainerRegistry/registries@2023-07-01' existing = {
  name: acrName
  scope: resourceGroup(acrRGName)
}
/*
var azureMLMetricsWriter ='635dd51f-9968-44d3-b7fb-6d9a6bd613ae' // EP -> AI project
resource amlMetricsWriterRole 'Microsoft.Authorization/roleDefinitions@2022-04-01' existing = {
  name: azureMLMetricsWriter
  scope: subscription()
}
*/

@description('Built-in Role: [Cognitive Services OpenAI User](https://learn.microsoft.com/azure/role-based-access-control/built-in-roles#cognitive-services-openai-user)')
resource cognitiveServicesOpenAiUserRole 'Microsoft.Authorization/roleDefinitions@2022-04-01' existing = {
  name: '5e0bd9bd-7b93-4f28-af87-19fc36ad61bd'
  scope: subscription()
}

// SP, user, EP -> AI Hub, AI Project (RG)
@description('Built-in Role: [Azure Machine Learning Workspace Connection Secrets Reader](https://learn.microsoft.com/azure/role-based-access-control/built-in-roles)')
resource amlWorkspaceSecretsReaderRole 'Microsoft.Authorization/roleDefinitions@2022-04-01' existing = {
  name: 'ea01e6af-a1c1-4350-9563-ad00f8c72ec5'
  scope: subscription()
}

// NB! sharedPrivateLinkResources - The HUB, similar as Azure AISearch, can also have sharedPrivateLinkResources
// TODO: Create another resrouce amlAIHubSharedPend, with an IF statement here
// https://learn.microsoft.com/en-us/azure/templates/microsoft.machinelearningservices/2024-07-01-preview/workspaces?pivots=deployment-language-bicep

var azureOpenAIConnectionName ='azureOpenAI'
var azureAIServicesConnectionName ='azureAIServices'
var azureAISearchConnectionName ='azureAISearch'
//var aiHubProjectName ='ai-prj${aifactoryProjectNumber}-01-${locationSuffix}-${env}-${aifactorySalt}${resourceSuffix}'
var aiProjectDiagSettingName ='aiProjectDiagnosticSetting'
var aiHubDiagSettingName ='aiHubDiagnosticSetting'
var epDefaultName ='ep-${aifactoryProjectNumber}-01-${locationSuffix}-${env}-${aifactorySalt}${resourceSuffix}'
var epDefaultName2 ='ep-${aifactoryProjectNumber}-1-${locationSuffix}-${env}-${aifactorySalt}${resourceSuffix}'


/*
https://learn.microsoft.com/en-us/azure/machine-learning/how-to-configure-private-link?view=azureml-api-2&WT.mc_id=Portal-Microsoft_Azure_MLTeamAccounts&tabs=cli#enable-public-access-only-from-internet-ip-ranges-preview

There are two possible properties that you can configure:

1) allow_public_access_when_behind_vnet - used by the Python SDK v1
public_network_access - used by the CLI and Python SDK v2 Each property overrides the other. For example, setting public_network_access will override any previous setting to allow_public_access_when_behind_vnet.
Microsoft recommends using public_network_access to enable or disable public access to a workspace.

2) Allown only IP ranges (max 200 rules)
List IP network rules: az ml workspace network-rule list --resource-group "myresourcegroup" --workspace-name "myWS" --query ipRules
Add a rule for a single IP address: az ml workspace network-rule add --resource-group "myresourcegroup" --workspace-name "myWS" --ip-address "16.17.18.19"
Add a rule for an IP address range: az ml workspace network-rule add --resource-group "myresourcegroup" --workspace-name "myWS" --ip-address "16.17.18.0/24"
Remove a rule for a single IP address: az ml workspace network-rule remove --resource-group "myresourcegroup" --workspace-name "myWS" --ip-address "16.17.18.19"
Remove a rule for an IP address range: az ml workspace network-rule remove --resource-group "myresourcegroup" --workspace-name "myWS" --ip-address "16.17.18.0/24"

az ml -h
az extension update -n ml

*/

// ->2025-07 2024-10-01-preview
// 2025-08-> 2025-07-01-preview 

var formattedUserAssignedIdentities = reduce(
  map((managedIdentities.?userAssignedResourceIds ?? []), (id) => { '${id}': {} }),
  {},
  (cur, next) => union(cur, next)
) // Converts the flat array to an object like { '${id1}': {}, '${id2}': {} }
var identity = !empty(managedIdentities)
  ? {
      type: (managedIdentities.?systemAssigned ?? false)
        ? (!empty(managedIdentities.?userAssignedResourceIds ?? {}) ? 'SystemAssigned,UserAssigned' : 'SystemAssigned')
        : (!empty(managedIdentities.?userAssignedResourceIds ?? {}) ? 'UserAssigned' : 'None')
      userAssignedIdentities: !empty(formattedUserAssignedIdentities) ? formattedUserAssignedIdentities : null
    }
  : {type:'SystemAssigned'}

resource aiHub2 'Microsoft.MachineLearningServices/workspaces@2025-07-01-preview' = if(enablePublicAccessWithPerimeter) {
  name: name
  location: location
  identity: identity
  tags: tags
  kind: kindAIHub
  properties: {
    allowRoleAssignmentOnRG: true
    friendlyName: '${name}-${env}-${aiFactoryNumber}'
    description: 'AI Hub with optional enablePublicAccessWithPerimeter. If using Azure Container Apps for UX and API. Create 2 deployments of your preffered GPT models GPT-4o, called gpt ,gpt-evals'

     // dependent resources
    applicationInsights: appInsights.id 
    storageAccount: existingStorageAccount.id // resourceId('Microsoft.Storage/storageAccounts', storageAccount)
    containerRegistry:existingAcr.id // resourceId('Microsoft.ContainerRegistry/registries', containerRegistry)
    keyVault: keyVault.id

    // configuration
    systemDatastoresAuthMode: 'identity'
    hbiWorkspace:false
    provisionNetworkNow: true // v1.22 false from true -> v1.22.1 true again
    enableDataIsolation: true // v1.22 true from: enablePublicAccessWithPerimeter?false:true
    //discoveryUrl:'https://${location}.api.azureml.ms.net/discovery' // v1.22 Added optional -> v1.22.1 removed again

    // network settings
    publicNetworkAccess:'Enabled'
    allowPublicAccessWhenBehindVnet: enablePublicAccessWithPerimeter? true: allowPublicAccessWhenBehindVnet
    managedNetwork: enablePublicAccessWithPerimeter ? {
      // When enablePublicAccessWithPerimeter is true, use minimal managed network (no outbound rules allowed)
      isolationMode: 'Disabled'
      #disable-next-line BCP037
      enableNetworkMonitor: false
      managedNetworkKind: 'V1' 
      firewallSku:'Basic' // 'Standard' V1.22 remove this param -> -> v1.22.1 added again
    } : {
      // When enablePublicAccessWithPerimeter is false, use full managed network with outbound rules
      isolationMode: 'AllowInternetOutbound'
      #disable-next-line BCP037
      enableNetworkMonitor: false
      managedNetworkKind: 'V1'
      firewallSku:'Basic' // 'Standard'
      outboundRules: union(
        {
          OpenAI: {
            type: 'PrivateEndpoint'
            destination: {
              serviceResourceId: aiServices.id
              subresourceTarget: 'account'
              sparkEnabled: false
              sparkStatus: 'Active'
            }
            status: 'Active'
          }
          SaBlob: {
            type: 'PrivateEndpoint'
            destination: {
              serviceResourceId: existingStorageAccount.id
              subresourceTarget: 'blob'
              sparkEnabled: true
              sparkStatus: 'Active'
            }
            status: 'Active'
          }
          SaFile: {
            type: 'PrivateEndpoint'
            destination: {
              serviceResourceId: existingStorageAccount.id
              subresourceTarget: 'file'
              sparkEnabled: true
              sparkStatus: 'Active'
            }
            status: 'Active'
          }
        },
        !empty(aiSearchName) ? {
          search: {
            type: 'PrivateEndpoint'
            destination: {
              serviceResourceId: aiSearch.id
              subresourceTarget: 'searchService'
              //sparkEnabled: false
              //sparkStatus: 'Inactive'
              sparkEnabled: true
              sparkStatus: 'Active'
            }
            status: 'Active'
          }
        } : {}
      )
    }
  }

}

@description('Azure Diagnostics: Azure AI Foundry hub - allLogs')
resource aiHubDiagSettings 'Microsoft.Insights/diagnosticSettings@2021-05-01-preview' = if(!enablePublicAccessWithPerimeter) {
  name: aiHubDiagSettingName
  scope: aiHub
  properties: {
    workspaceId: logWorkspace.id
    logs: [
      {
        categoryGroup: 'allLogs' // All logs is a good choice for production on this resource.
        enabled: true
        retentionPolicy: {
          enabled: false
          days: 0
        }
      }
    ]
  }
}

@description('Azure Diagnostics: Azure AI Foundry hub 2 - allLogs')
resource aiHub2DiagSettings 'Microsoft.Insights/diagnosticSettings@2021-05-01-preview' = if(enablePublicAccessWithPerimeter) {
  name: aiHubDiagSettingName
  scope: aiHub2
  properties: {
    workspaceId: logWorkspace.id
    logs: [
      {
        categoryGroup: 'allLogs' // All logs is a good choice for production on this resource.
        enabled: true
        retentionPolicy: {
          enabled: false
          days: 0
        }
      }
    ]
  }
}

@description('This is a container for the ai foundry project.')
resource aiProject2 'Microsoft.MachineLearningServices/workspaces@2025-07-01-preview' = if(enablePublicAccessWithPerimeter) {
  name: defaultProjectName
  location: location
  tags: tags
  kind: 'Project'
  sku: {
    name: 'Basic'
    tier: 'Basic'
  }
  identity:identity
  // This resource's identity is automatically assigned priviledge access to ACR, Storage, Key Vault, and Application Insights. 
  // Since the priveleges are granted at the project/hub level have elevated access to the resources, it is recommended to isolate these resources
  // to a resource group that only contains the project/hub.
  properties: {
    friendlyName: defaultProjectName
    description: 'Project for AI Factory project${aifactoryProjectNumber} in ${env} environment in ${location}'
    v1LegacyMode: false
    hbiWorkspace: false
    hubResourceId:aiHub2.id
    //enableDataIsolation: enablePublicAccessWithPerimeter?false:true
    publicNetworkAccess: enablePublicGenAIAccess?'Enabled':'Disabled'
    //allowPublicAccessWhenBehindVnet: allowPublicAccessWhenBehindVnet
    
  }
  /* Object reference not set to an instance of an object.
  resource blob2 'connections' = if(enablePublicAccessWithPerimeter) {
    name: 'default'
    properties: {
      authType: 'AAD'
      category: 'AzureBlob'
      isSharedToAll: false
      useWorkspaceManagedIdentity: true
      peRequirement: enablePublicAccessWithPerimeter?'NotRequired':'Required' // 	'NotApplicable','NotRequired', 'Required'
      peStatus: enablePublicAccessWithPerimeter?'Inactive':'Active' // 'NotApplicable','Active', 'Inactive'
      sharedUserList: []
      metadata: {
        ApiType: 'Azure'
        ResourceId: existingStorageAccount.id // Required metadata property ContainerName is missing;Required metadata property AccountName is missing
        ContainerName: 'default'
        AccountName: existingStorageAccount.name
      }
      target: 'https://${existingStorageAccount.name}.blob.${environment().suffixes.storage}/'
    }
  }
  */
  resource aiServicesConnection2 'connections' = if(enablePublicAccessWithPerimeter) {
    name: azureAIServicesConnectionName
    properties: {
      authType: 'AAD'
      category: 'AIServices'
      isSharedToAll: false
      useWorkspaceManagedIdentity: true
      peRequirement: enablePublicAccessWithPerimeter?'NotRequired':'Required' // 	'NotApplicable','NotRequired', 'Required'
      peStatus: enablePublicAccessWithPerimeter?'Inactive':'Active' // 'NotApplicable','Active', 'Inactive'
      sharedUserList: []
      metadata: {
        ApiType: 'Azure'
        ResourceId: aiServices.id
      }
      target: 'https://${aiServices.name}.cognitiveservices.azure.com/'
      //target: aiServices.properties.endpoint 
    }
  }
  /*
  resource aoaiConnection2 'connections' = if(enablePublicAccessWithPerimeter) {
    name: azureOpenAIConnectionName
    properties: {
      authType: 'AAD'
      category: 'AzureOpenAI'
      isSharedToAll: false
      useWorkspaceManagedIdentity: true
      peRequirement: enablePublicGenAIAccess?'NotRequired':'Required' // 	'NotApplicable','NotRequired', 'Required'
      peStatus: enablePublicGenAIAccess? 'Inactive':'Active' // 'NotApplicable','Active', 'Inactive'
      sharedUserList: []
      metadata: {
        ApiType: 'Azure'
        ResourceId: aiServices.id
      }
      target: 'https://${aiServices.name}.openai.azure.com/'
    }
  }
  */

  resource searchConnection2 'connections' =
  if (!empty(aiSearchName) && enablePublicAccessWithPerimeter) {
    name: azureAISearchConnectionName
    properties: {
      authType: 'AAD'
      category: 'CognitiveSearch'
      isSharedToAll: false
      useWorkspaceManagedIdentity: true
      peRequirement: enablePublicAccessWithPerimeter?'NotRequired':'Required' // 	'NotApplicable','NotRequired', 'Required'
      peStatus: enablePublicAccessWithPerimeter?'Inactive':'Active' // 'NotApplicable','Active', 'Inactive'
      target: 'https://${aiSearch.name}.search.windows.net/'
      metadata: {
        ApiType: 'Azure'
        ResourceId: aiSearch.id
      }
      //authType: 'ApiKey'
      //credentials: {
      //      key: !empty(aiSearchName) ? search.listAdminKeys().primaryKey : ''
      //}
    }
  }
  /* Object reference not set to an instance of an object.
  resource endpoint2 'onlineEndpoints' = if(enablePublicAccessWithPerimeter) {
    name: epDefaultName2
    location: location
    kind: 'Managed'
    identity: {
      type: 'SystemAssigned' // This resource's identity is automatically assigned AcrPull access to ACR, Storage Blob Data Contributor, and AML Metrics Writer on the project. It is also assigned two additional permissions below.
                             // Given the permissions assigned to the identity, it is recommended only include deployments in the Azure OpenAI service that are trusted to be invoked from this endpoint.
    }
    properties: {
      description: 'This is the default inference endpoint for the AI Factory project, prompt flow deployment. Called by the UI hosted in Web Apps.'
      authMode: 'Key' // Ideally this should be based on Microsoft Entra ID access. This sample however uses a key stored in Key Vault.
      publicNetworkAccess: 'Enabled'
    }
  }
  */
}

// ############################### Private or Whitelisted IPs ################ 2025-01-01-preview

resource aiHub 'Microsoft.MachineLearningServices/workspaces@2025-07-01-preview' = if(!enablePublicAccessWithPerimeter) {
  name: name
  location: location
  identity: identity
  tags: tags
  kind: kindAIHub
  properties: {
    allowRoleAssignmentOnRG: true
    friendlyName: '${name}-${env}-${aiFactoryNumber}'
    description: 'AI Foundry hub requires an underlying Azure ML workspace. If using Azure Container Apps for UX and API. Create 2 deployments of your preffered GPT models GPT-4o, called gpt ,gpt-evals'

     // dependent resources
    applicationInsights: appInsights.id 
    storageAccount: existingStorageAccount.id // resourceId('Microsoft.Storage/storageAccounts', storageAccount)
    containerRegistry:existingAcr.id // resourceId('Microsoft.ContainerRegistry/registries', containerRegistry)
    keyVault: keyVault.id

    // configuration
    systemDatastoresAuthMode: 'identity'
    hbiWorkspace:false
    //provisionNetworkNow: true
    //enableDataIsolation:false
    provisionNetworkNow: true // v1.22 false from true -> v1.22.1 true again
    enableDataIsolation: true // v1.22 true from false
    v1LegacyMode:false

    // network settings
    publicNetworkAccess:enablePublicGenAIAccess?'Enabled':'Disabled' // Disabled:The workspace can only be accessed through private endpoints. No IP Whitelisting possible.
    allowPublicAccessWhenBehindVnet: allowPublicAccessWhenBehindVnet // true: Allows controlled public access through IP allow lists while maintaining VNet integration
    ipAllowlist: allowPublicAccessWhenBehindVnet ? ipWhitelist_array: null
    networkAcls: allowPublicAccessWhenBehindVnet ? {
      defaultAction: enablePublicGenAIAccess && empty(ipRules) ? 'Allow' : 'Deny' // When enablePublicGenAIAccess is true, defaultAction must be 'Allow'
      ipRules: ipRules
    } : null
    managedNetwork: {
      firewallSku:'Basic' // 'Standard' V1.22 remove this param -> -> v1.22.1 added again
      managedNetworkKind: 'V1' // v1.22.1 added this, to ensure PG has not defaulted to V2 just now
      isolationMode:'AllowInternetOutbound' // enablePublicGenAIAccess? 'AllowInternetOutbound': 'AllowOnlyApprovedOutbound'
      #disable-next-line BCP037
      enableNetworkMonitor:false
      outboundRules: union(
        !empty(aiSearchName) ? {
          search: {
            type: 'PrivateEndpoint'
            destination: {
              serviceResourceId: aiSearch.id
              subresourceTarget: 'searchService'
              sparkEnabled: true
              sparkStatus: 'Active'
            }
            status: 'Active'
          } 
        } : {},
        {
          OpenAI: {
            type: 'PrivateEndpoint'
            destination: {
              serviceResourceId: aiServices.id
              subresourceTarget: 'account'
              sparkEnabled: false
              sparkStatus: 'Active'
            }
            status: 'Active'
          }
          /* Cannot add these. If so. Error: "There is already an outbound rule to the same destination"
          SaBlob: {
            type: 'PrivateEndpoint'
            destination: {
              serviceResourceId: existingStorageAccount.id
              subresourceTarget: 'blob'
              sparkEnabled: true
              sparkStatus: 'Active'
            }
            status: 'Active'
          }
          SaFile: {
            type: 'PrivateEndpoint'
            destination: {
              serviceResourceId: existingStorageAccount.id
              subresourceTarget: 'file'
              sparkEnabled: true
              sparkStatus: 'Active'
            }
            status: 'Active'
          }
          */
        }
      )
    }

  }
  /*
  resource aoaiConnection 'connections' = if(!enablePublicAccessWithPerimeter) {
    name: azureOpenAIConnectionName
    properties: {
      authType: 'AAD'
      category: 'AzureOpenAI'
      isSharedToAll: false
      useWorkspaceManagedIdentity: true
      peRequirement: enablePublicGenAIAccess?'NotRequired':'Required' // 	'NotApplicable','NotRequired', 'Required'
      peStatus: enablePublicGenAIAccess? 'Inactive':'Active' // 'NotApplicable','Active', 'Inactive'
      sharedUserList: []
      metadata: {
        ApiType: 'Azure'
        ResourceId: aiServices.id
      }
      target: 'https://${aiServices.name}.openai.azure.com/'
      //aiServices.properties.endpoint // https://aiservicesprj001eus2devqoygy94311dbb24001.openai.azure.com/
    }
  }
  */
  
}

@description('This is a container for the ai foundry project.')
resource aiProject 'Microsoft.MachineLearningServices/workspaces@2025-07-01-preview' = if(!enablePublicAccessWithPerimeter) {
  name: defaultProjectName
  location: location
  tags: tags
  kind: 'Project'
  sku: {
    name: 'Basic'
    tier: 'Basic'
  }
  identity: identity
  properties: {
    friendlyName: defaultProjectName
    description: 'Project for AI Factory project${aifactoryProjectNumber} in ${env} environment in ${location}'
    v1LegacyMode: false
    hbiWorkspace: false
    publicNetworkAccess:enablePublicGenAIAccess?'Enabled':'Disabled' //enablePublicGenAIAccess?'Enabled':'Disabled' // Allow public endpoint connectivity when a workspace is private link enabled.
    hubResourceId: aiHub.id
  }
  /*
  resource blob 'connections' = if(!enablePublicAccessWithPerimeter) {
    name: 'default'
    properties: {
      authType: 'AAD'
      category: 'AzureBlob'
      isSharedToAll: false
      useWorkspaceManagedIdentity: true
      peRequirement: enablePublicAccessWithPerimeter?'NotRequired':'Required' // 	'NotApplicable','NotRequired', 'Required'
      peStatus: enablePublicAccessWithPerimeter?'Inactive':'Active' // 'NotApplicable','Active', 'Inactive'
      sharedUserList: []
      metadata: {
        ApiType: 'Azure'
        ResourceId: existingStorageAccount.id // Required metadata property ContainerName is missing;Required metadata property AccountName is missing
        ContainerName: 'default'
        AccountName: existingStorageAccount.name
      }
      target: 'https://${existingStorageAccount.name}.blob.${environment().suffixes.storage}/'
    }
  }
  */
  resource aiServicesConnection 'connections' = if(!enablePublicAccessWithPerimeter) {
    name: azureAIServicesConnectionName
    properties: {
      authType: 'AAD'
      category: 'AIServices'
      isSharedToAll: false
      useWorkspaceManagedIdentity: true
      peRequirement: enablePublicAccessWithPerimeter?'NotRequired':'Required'
      peStatus: enablePublicAccessWithPerimeter? 'Inactive':'Active' // 'NotApplicable','Active', 'Inactive'
      sharedUserList: []
      metadata: {
        ApiType: 'Azure'
        ResourceId: aiServices.id
      }
      target: 'https://${aiServices.name}.cognitiveservices.azure.com/'
      //target: aiServices.properties.endpoint
    }
  }

  resource searchConnection 'connections' =
  if (!empty(aiSearchName) && !enablePublicAccessWithPerimeter) {
    name: azureAISearchConnectionName
    properties: {
      authType: 'AAD'
      category: 'CognitiveSearch'
      isSharedToAll: false
      useWorkspaceManagedIdentity: true
      peRequirement: enablePublicGenAIAccess?'NotRequired':'Required'
      peStatus: enablePublicGenAIAccess? 'Inactive':'Active' // 'NotApplicable','Active', 'Inactive'
      target: 'https://${aiSearch.name}.search.windows.net/'
      metadata: {
        ApiType: 'Azure'
        ResourceId: aiSearch.id
      }
      //authType: 'ApiKey'
      //credentials: {
      //      key: !empty(aiSearchName) ? search.listAdminKeys().primaryKey : ''
      //}
    }
  }
  /*
  resource endpoint 'onlineEndpoints' = if(!enablePublicAccessWithPerimeter) {
    name: epDefaultName
    location: location
    kind: 'Managed'
    identity: identity
    properties: {
      description: 'This is the default inference endpoint for the AI Factory project, prompt flow deployment. Called by the UI hosted in Web Apps.'
      authMode: 'Key' // Ideally this should be based on Microsoft Entra ID access. This sample however uses a key stored in Key Vault.
      publicNetworkAccess: enablePublicGenAIAccess?'Enabled':'Disabled'
    }
  }   */
}

// Built-in roles for AI Project workspace MSI permissions
@description('Built-in Role: [AzureML Data Scientist](https://learn.microsoft.com/azure/role-based-access-control/built-in-roles)')
resource azureMLDataScientistRole 'Microsoft.Authorization/roleDefinitions@2022-04-01' existing = {
  name: 'f6c7c914-8db3-469d-8ca1-694a8f32e121'
  scope: subscription()
}

@description('Built-in Role: [AzureML Compute Operator](https://learn.microsoft.com/azure/role-based-access-control/built-in-roles)')
resource azureMLComputeOperatorRole 'Microsoft.Authorization/roleDefinitions@2022-04-01' existing = {
  name: 'e503ece1-11d0-4e8e-8e2c-7a6c3bf38815'
  scope: subscription()
}

@description('Assign the AI Project MSI the ability to manage online endpoints within its own workspace.')
resource projectDataScientistRoleAssignment 'Microsoft.Authorization/roleAssignments@2022-04-01' = if(!enablePublicAccessWithPerimeter) {
  scope: aiProject
  name: guid(aiProject.id, azureMLDataScientistRole.id, 'data-scientist')
  properties: {
    roleDefinitionId: azureMLDataScientistRole.id
    principalType: 'ServicePrincipal'
    #disable-next-line BCP318
    principalId: aiProject.identity.principalId
    description:'01 - projectDataScientistRoleAssignment with azureMLDataScientistRole'
  }
}

@description('Assign the AI Project MSI compute operator permissions for online endpoints.')
resource projectComputeOperatorRoleAssignment 'Microsoft.Authorization/roleAssignments@2022-04-01' = if(!enablePublicAccessWithPerimeter) {
  scope: aiProject
  name: guid(aiProject.id, azureMLComputeOperatorRole.id, 'compute-operator')
  properties: {
    roleDefinitionId: azureMLComputeOperatorRole.id
    principalType: 'ServicePrincipal'
    #disable-next-line BCP318
    principalId: aiProject.identity.principalId
    description:'02 - projectComputeOperatorRoleAssignment with azureMLComputeOperatorRole'
  }
}

@description('Assign the AI Project MSI the ability to read secrets from the parent project for online endpoint operations.')
resource projectSecretsReaderRoleAssignment 'Microsoft.Authorization/roleAssignments@2022-04-01' = if(!enablePublicAccessWithPerimeter) {
  scope: aiProject
  name: guid(aiProject.id, amlWorkspaceSecretsReaderRole.id, 'secrets-reader')
  properties: {
    roleDefinitionId: amlWorkspaceSecretsReaderRole.id
    principalType: 'ServicePrincipal'
    #disable-next-line BCP318
    principalId: aiProject.identity.principalId
    description:'03 - projectSecretsReaderRoleAssignment with amlWorkspaceSecretsReaderRole'
  }
}

@description('Assign the AI Project MSI the ability to invoke models in Azure OpenAI.')
resource projectOpenAIUserRoleAssignment 'Microsoft.Authorization/roleAssignments@2022-04-01' = if(!enablePublicAccessWithPerimeter && !aiHubExists) {
  scope: aiServices
  name: guid(aiServices.id, aiProject.id, cognitiveServicesOpenAiUserRole.id, 'openai-user')
  properties: {
    roleDefinitionId: cognitiveServicesOpenAiUserRole.id
    principalType: 'ServicePrincipal'
    #disable-next-line BCP318
    principalId: aiProject.identity.principalId
    description:'04 - projectOpenAIUserRoleAssignment with cognitiveServicesOpenAiUserRole'
  }
}

@description('Azure Diagnostics: AI Foundry chat project - allLogs')
resource chatProjectDiagSettings 'Microsoft.Insights/diagnosticSettings@2021-05-01-preview' = if(!enablePublicAccessWithPerimeter) {
  name: aiProjectDiagSettingName
  scope: aiProject
  properties: {
    workspaceId: logWorkspace.id
    logs: [
      {
        categoryGroup: 'allLogs' // Production readiness change: In production, all logs are probably excessive. Please tune to just the log streams that add value to your workload's operations.
                                 // This this scenario, the logs of interest are mostly found in AmlComputeClusterEvent, AmlDataSetEvent, AmlEnvironmentEvent, and AmlModelsEvent
        enabled: true
        retentionPolicy: {
          enabled: false
          days: 0
        }
      }
    ]
  }
}

/*
@description('Azure Diagnostics: AI Foundry chat project online endpoint - allLogs')
resource chatProjectOnlineEndpointDiagSettings 'Microsoft.Insights/diagnosticSettings@2021-05-01-preview' = if(!enablePublicAccessWithPerimeter) {
  name: 'chatProjectOnlineEndpointDiagSettingsDefault'
  scope: aiProject::endpoint
  properties: {
    workspaceId: logWorkspace.id
    logs: [
      {
        categoryGroup: 'allLogs' // All logs is a good choice for production on this resource.
        enabled: true
        retentionPolicy: {
          enabled: false
          days: 0
        }
      }
    ]
  }
}
*/

/*
@description('Key Vault Secret: The Managed Online Endpoint key to be referenced from the Chat UI app.')
resource managedEndpointPrimaryKeyEntry 'Microsoft.KeyVault/vaults/secrets@2023-07-01' = if(!enablePublicAccessWithPerimeter) {
  parent: keyVault
  name: 'aifactory-proj-ep-default-api-key'
  properties: {
    #disable-next-line BCP422
    value: aiProject::endpoint.listKeys().primaryKey // This key is technically already in Key Vault, but it's name is not something that is easy to reference.
    contentType: 'text/plain'
    attributes: {
      enabled: true
    }
  }
}
  */

// privateEndpointName: p-aihub-prj003sdcdevgenaiamlworkspace
resource pendAIHub 'Microsoft.Network/privateEndpoints@2024-05-01' = if(!enablePublicAccessWithPerimeter) {
  name: '${aiHub.name}-pend'
  location: location
  tags: tags
  properties: {
    customNetworkInterfaceName: '${aiHub.name}-pend-nic'
    privateLinkServiceConnections: [
      {
        name: '${aiHub.name}-pend'
        properties: {
          groupIds: [
            'amlworkspace'
          ]
          privateLinkServiceId: aiHub.id
          privateLinkServiceConnectionState: {
            status: 'Approved'
            description: 'Auto-Approved'
            actionsRequired: 'None'
          }
        }
      }
    ]
    subnet: {
      id: subnet.id
    }
  }
}

resource privateEndpointDns 'Microsoft.Network/privateEndpoints/privateDnsZoneGroups@2020-06-01' = if (!centralDnsZoneByPolicyInHub && !enablePublicAccessWithPerimeter) {
  name: '${pendAIHub.name}DnsZone'
  parent: pendAIHub
  properties:{
    privateDnsZoneConfigs: [
      {
        name: privateDnsZoneName[environment().name]
        properties:{
          privateDnsZoneId: privateLinksDnsZones.amlworkspace.id 
        }
      }
      {
        name: privateDnsZoneNameNotebooks[environment().name]
        properties:{
          privateDnsZoneId: privateLinksDnsZones.notebooks.id 
        }
      }
    ]
  }
}

// Hub 2 - Role assignments for aiProject2

@description('Assign the AI Project2 MSI the ability to manage online endpoints within its own workspace.')
resource projectDataScientistRoleAssignment2 'Microsoft.Authorization/roleAssignments@2022-04-01' = if(enablePublicAccessWithPerimeter) {
  scope: aiProject2
  name: guid(aiProject2.id, azureMLDataScientistRole.id, 'data-scientist-2')
  properties: {
    roleDefinitionId: azureMLDataScientistRole.id
    principalType: 'ServicePrincipal'
    #disable-next-line BCP318
    principalId: aiProject2.identity.principalId
    description: '05 - projectDataScientistRoleAssignment with azureMLDataScientistRole'
  }
}

@description('Assign the AI Project2 MSI compute operator permissions for online endpoints.')
resource projectComputeOperatorRoleAssignment2 'Microsoft.Authorization/roleAssignments@2022-04-01' = if(enablePublicAccessWithPerimeter) {
  scope: aiProject2
  name: guid(aiProject2.id, azureMLComputeOperatorRole.id, 'compute-operator-2')
  properties: {
    roleDefinitionId: azureMLComputeOperatorRole.id
    principalType: 'ServicePrincipal'
    #disable-next-line BCP318
    principalId: aiProject2.identity.principalId
    description: '06 - projectComputeOperatorRoleAssignment with azureMLComputeOperatorRole'
  }
}

@description('Assign the AI Project2 MSI the ability to read secrets from the parent project for online endpoint operations.')
resource projectSecretsReaderRoleAssignment2 'Microsoft.Authorization/roleAssignments@2022-04-01' = if(enablePublicAccessWithPerimeter) {
  scope: aiProject2
  name: guid(aiProject2.id, amlWorkspaceSecretsReaderRole.id, 'secrets-reader-2')
  properties: {
    roleDefinitionId: amlWorkspaceSecretsReaderRole.id
    principalType: 'ServicePrincipal'
    #disable-next-line BCP318
    principalId: aiProject2.identity.principalId
    description: '07 - projectSecretsReaderRoleAssignment with amlWorkspaceSecretsReaderRole'
  }
}

@description('Assign the AI Project2 MSI the ability to invoke models in Azure OpenAI.')
resource projectOpenAIUserRoleAssignment2 'Microsoft.Authorization/roleAssignments@2022-04-01' = if(enablePublicAccessWithPerimeter && !aiHubExists) {
  scope: aiServices
  name: guid(aiServices.id, aiProject2.id, cognitiveServicesOpenAiUserRole.id, 'openai-user-2')
  properties: {
    roleDefinitionId: cognitiveServicesOpenAiUserRole.id
    principalType: 'ServicePrincipal'
    #disable-next-line BCP318
    principalId: aiProject2.identity.principalId
    description: '08 - projectOpenAIUserRoleAssignment with cognitiveServicesOpenAiUserRole'
  }
}

/*
@description('Assign the online endpoint the ability to interact with the secrets of the parent project. This is needed to execute the prompt flow from the managed endpoint.')
resource projectSecretsReaderForOnlineEndpointRoleAssignment2 'Microsoft.Authorization/roleAssignments@2022-04-01'  = if(enablePublicAccessWithPerimeter) {
  scope: aiProject2
  name: guid(aiProject2.id, aiProject2::endpoint2.id, amlWorkspaceSecretsReaderRole.id)
  properties: {
    roleDefinitionId: amlWorkspaceSecretsReaderRole.id
    principalType: 'ServicePrincipal'
    #disable-next-line BCP318
    principalId: aiProject2::endpoint2.identity.principalId
  }
}
*/

/*
@description('Assign the online endpoint the ability to invoke models in Azure OpenAI. This is needed to execute the prompt flow from the managed endpoint.')
resource projectOpenAIUserForOnlineEndpointRoleAssignment2 'Microsoft.Authorization/roleAssignments@2022-04-01'  = if(enablePublicAccessWithPerimeter) {
  scope: aiServices
  name: guid(aiServices.id, aiProject2::endpoint2.id, cognitiveServicesOpenAiUserRole.id)
  properties: {
    roleDefinitionId: cognitiveServicesOpenAiUserRole.id
    principalType: 'ServicePrincipal'
    #disable-next-line BCP318
    principalId: aiProject2::endpoint2.identity.principalId
  }
}
*/

@description('Azure Diagnostics: AI Foundry chat project - allLogs')
resource chatProjectDiagSettings2 'Microsoft.Insights/diagnosticSettings@2021-05-01-preview' = if(enablePublicAccessWithPerimeter) {
  name: aiProjectDiagSettingName
  scope: aiProject2
  properties: {
    workspaceId: logWorkspace.id
    logs: [
      {
        categoryGroup: 'allLogs' // Production readiness change: In production, all logs are probably excessive. Please tune to just the log streams that add value to your workload's operations.
                                 // This this scenario, the logs of interest are mostly found in AmlComputeClusterEvent, AmlDataSetEvent, AmlEnvironmentEvent, and AmlModelsEvent
        enabled: true
        retentionPolicy: {
          enabled: false
          days: 0
        }
      }
    ]
  }
}

/*
@description('Azure Diagnostics: AI Foundry chat project online endpoint - allLogs')
resource chatProjectOnlineEndpointDiagSettings2 'Microsoft.Insights/diagnosticSettings@2021-05-01-preview' = if(enablePublicAccessWithPerimeter) {
  name: 'chatProjectOnlineEndpointDiagSettingsDefault2'
  scope: aiProject2::endpoint2
  properties: {
    workspaceId: logWorkspace.id
    logs: [
      {
        categoryGroup: 'allLogs' // All logs is a good choice for production on this resource.
        enabled: true
        retentionPolicy: {
          enabled: false
          days: 0
        }
      }
    ]
  }
}
*/

/*
@description('Key Vault Secret: The Managed Online Endpoint key to be referenced from the Chat UI app.')
resource managedEndpointPrimaryKeyEntry2 'Microsoft.KeyVault/vaults/secrets@2023-07-01' = if(enablePublicAccessWithPerimeter) {
  parent: keyVault
  name: 'aifactory-proj-ep-default2-api-key'
  properties: {
    #disable-next-line BCP422
    value: aiProject2::endpoint2.listKeys().primaryKey // This key is technically already in Key Vault, but it's name is not something that is easy to reference.
    contentType: 'text/plain'
    attributes: {
      enabled: true
    }
  }
}
*/

resource pendAIHub2 'Microsoft.Network/privateEndpoints@2024-05-01' = if(enablePublicAccessWithPerimeter && createPrivateEndpoint) {
  name: '${aiHub2.name}-pend' //'${privateEndpointName}-2'
  location: location
  tags: tags
  properties: {
    customNetworkInterfaceName: '${aiHub2.name}-pend-nic'
    privateLinkServiceConnections: [
      {
        name: '${aiHub2.name}-pend'
        properties: {
          groupIds: [
            'amlworkspace'
          ]
          privateLinkServiceId: aiHub2.id
          privateLinkServiceConnectionState: {
            status: 'Approved'
            description: 'Auto-Approved'
            actionsRequired: 'None'
          }
        }
      }
    ]
    subnet: {
      id: subnet.id
    }
  }
}

resource privateEndpointDns2 'Microsoft.Network/privateEndpoints/privateDnsZoneGroups@2020-06-01' = if (!centralDnsZoneByPolicyInHub && enablePublicAccessWithPerimeter && createPrivateEndpoint) {
  name: '${pendAIHub2.name}DnsZone'
  parent: pendAIHub2
  properties:{
    privateDnsZoneConfigs: [
      {
        name: privateDnsZoneName[environment().name]
        properties:{
          privateDnsZoneId: privateLinksDnsZones.amlworkspace.id 
        }
      }
      {
        name: privateDnsZoneNameNotebooks[environment().name]
        properties:{
          privateDnsZoneId: privateLinksDnsZones.notebooks.id 
        }
      }
    ]
  }
}


output id string = (!enablePublicAccessWithPerimeter)? aiHub.id:aiHub2.id
output name string =(!enablePublicAccessWithPerimeter)? aiHub.name:aiHub2.name
#disable-next-line BCP318
output principalId string = (!enablePublicAccessWithPerimeter)?aiHub.identity.principalId:aiHub2.identity.principalId
#disable-next-line BCP318
output projectPrincipalId string = (!enablePublicAccessWithPerimeter)? aiProject.identity.principalId:aiProject2.identity.principalId
output aiProjectName string = (!enablePublicAccessWithPerimeter)? aiProject.name: aiProject2.name

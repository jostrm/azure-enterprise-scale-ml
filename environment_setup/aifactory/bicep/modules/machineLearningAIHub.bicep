@description('Specifies the name of the new machine learning studio resources')
param name string
param aifactorySuffix string
@description('Specifies the computer pool name')
param aifactoryProjectName string
@description('Specifies the location where the new machine learning studio resource should be deployed')
param location string
@description('ESML dev,test or prod. If DEV then AKS cluster is provisioned with 1 agent otherwise 3')
param env string
@description('Specifies the skuname of the machine learning studio')
param skuName string
@description('Specifies the sku tier of the machine learning studio')
param skuTier string
@description('Specifies the storageaccount id used for the machine learning studio')
param storageAccount string
@description('Specifies the container registry id used for the machine learning studio')
param containerRegistry string
@description('Specifies the keyvault id used for the machine learning studio')
param keyVaultName string
@description('Specifies the application insights id used for the machine learning studio')
param applicationInsights string
@description('Specifies the tags that should be applied to machine learning studio resources')
param tags object
@description('(Required) Specifies the private endpoint name')
param privateEndpointName string
@description('(Required) Specifies the virtual network id associated with private endpoint')
param vnetName string
@description('(Required) Specifies the subnet name that will be associated with the private endpoint')
param subnetName string
param vnetResourceGroupName string
@description('Azure ML allowPublicAccessWhenBehindVnet')
param allowPublicAccessWhenBehindVnet bool
@description('AI Hub public access')
param enablePublicGenAIAccess bool
@description('ESML can run in DEMO mode, which creates private DnsZones,DnsZoneGroups, and vNetLinks. You can turn this off, to use your HUB instead.')
param centralDnsZoneByPolicyInHub bool
param aiSearchName string
param acrName string
param privateLinksDnsZones object
@allowed([
  'Hub'
  ''
])
param kindAIHub string = 'Hub'
param ipRules array = []
param aiServicesName string
param logWorkspaceName string
param logWorkspaceResoureGroupName string
param locationSuffix string
param resourceSuffix string

//var subnetRef = '${vnetId}/subnets/${subnetName}'
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

resource aiSearch 'Microsoft.Search/searchServices@2021-04-01-preview' existing = {
  name: aiSearchName
}
resource acr 'Microsoft.ContainerRegistry/registries@2023-08-01-preview' existing = {
  name: acrName
}
resource aiServices 'Microsoft.CognitiveServices/accounts@2023-05-01' existing = {
  name: aiServicesName
}
resource logWorkspace 'Microsoft.OperationalInsights/workspaces@2022-10-01' existing = {
  name: logWorkspaceName
  scope:resourceGroup(logWorkspaceResoureGroupName)
}
resource keyVault 'Microsoft.KeyVault/vaults@2023-02-01' existing = {
  name: keyVaultName
  scope: resourceGroup()
}
resource vnet 'Microsoft.Network/virtualNetworks@2024-05-01' existing = {
  name: vnetName
  scope: resourceGroup(vnetResourceGroupName)
}

resource subnet 'Microsoft.Network/virtualNetworks/subnets@2024-05-01' existing = {
  name: subnetName
  parent: vnet
}
/*Moved to other place - USER ACCESS
@description('Built-in Role: [Storage Blob Data Contributor](https://learn.microsoft.com/azure/role-based-access-control/built-in-roles#storage-blob-data-contributor)')
resource storageBlobDataContributorRole 'Microsoft.Authorization/roleDefinitions@2022-04-01' existing = {
  name: 'ba92f5b4-2d11-453d-a403-e96b0029c9fe'
  scope: subscription()
}

@description('Built-in Role: [Storage File Data Privileged Contributor](https://learn.microsoft.com/azure/role-based-access-control/built-in-roles#storage-file-data-privileged-contributor)')
resource storageFileDataContributorRole 'Microsoft.Authorization/roleDefinitions@2022-04-01' existing = {
  name: '69566ab7-960f-475b-8e7c-b3118f30c6bd'
  scope: subscription()
}
*/

var azureMachineLearningWorkspaceConnectionSecretsReaderRoleId = 'ea01e6af-a1c1-4350-9563-ad00f8c72ec5'  // SP, user, EP -> AI Hub, AI Project (RG)
var azureMLMetricsWriter ='635dd51f-9968-44d3-b7fb-6d9a6bd613ae' // EP -> AI project

resource amlConnectionReaderRole 'Microsoft.Authorization/roleDefinitions@2022-04-01' existing = {
  name: azureMachineLearningWorkspaceConnectionSecretsReaderRoleId
  scope: subscription()
}
resource amlMetricsWriterRole 'Microsoft.Authorization/roleDefinitions@2022-04-01' existing = {
  name: azureMLMetricsWriter
  scope: subscription()
}

@description('Built-in Role: [Cognitive Services OpenAI User](https://learn.microsoft.com/azure/role-based-access-control/built-in-roles#cognitive-services-openai-user)')
resource cognitiveServicesOpenAiUserRole 'Microsoft.Authorization/roleDefinitions@2022-04-01' existing = {
  name: '5e0bd9bd-7b93-4f28-af87-19fc36ad61bd'
  scope: subscription()
}

@description('Built-in Role: [Azure Machine Learning Workspace Connection Secrets Reader](https://learn.microsoft.com/azure/role-based-access-control/built-in-roles)')
resource amlWorkspaceSecretsReaderRole 'Microsoft.Authorization/roleDefinitions@2022-04-01' existing = {
  name: 'ea01e6af-a1c1-4350-9563-ad00f8c72ec5'
  scope: subscription()
}

@description('Built-in Role: [AcrPull](https://learn.microsoft.com/azure/role-based-access-control/built-in-roles#acrpull)')
resource containerRegistryPullRole 'Microsoft.Authorization/roleDefinitions@2022-04-01' existing = {
  name: '7f951dda-4ed3-4680-a7ca-43fe172d538d'
  scope: subscription()
}

@description('Built-in Role: [AcrPush](https://learn.microsoft.com/azure/role-based-access-control/built-in-roles#acrpush)')
resource containerRegistryPushRole 'Microsoft.Authorization/roleDefinitions@2022-04-01' existing = {
  name: '8311e382-0749-4cb8-b61a-304f252e45ec'
  scope: subscription()
}

// NB! sharedPrivateLinkResources - The HUB, similar as Azure AISearch, can also have sharedPrivateLinkResources
// TODO: Create another resrouce amlAIHubSharedPend, with an IF statement here
// https://learn.microsoft.com/en-us/azure/templates/microsoft.machinelearningservices/2024-07-01-preview/workspaces?pivots=deployment-language-bicep

var azureOpenAIConnectionName ='azureOpenAI'
var azureAIServicesConnectionName ='azureAIServices'
var azureAISearchConnectionName ='azureAISearch'
var aiHubProjectName ='ai-project-${aifactoryProjectName}-${locationSuffix}-${env}${resourceSuffix}'
var aiProjectDiagSettingName ='aiProjectDiagnosticSetting'
var aiHubDiagSettingName ='aiHubDiagnosticSetting'
var epDefaultName ='ep-${aifactoryProjectName}-${locationSuffix}-${env}${resourceSuffix}'

resource aiHub 'Microsoft.MachineLearningServices/workspaces@2024-10-01-preview' = {
  name: name
  location: location
  identity: {
    type: 'SystemAssigned'
  }
  tags: tags
  sku: {
    name: skuName
    tier: skuTier
  }
  kind: kindAIHub
  properties: {
    allowRoleAssignmentOnRG: true
    friendlyName: 'AI Foundry Hub for: ${aifactoryProjectName}-${env}-${aiFactoryNumber}'
    description: 'AI Foundry hub requires an underlying Azure ML workspace. This is setup for ${aifactoryProjectName} in ESML-${env} environment in ${location}'
    storageAccount: storageAccount // resourceId('Microsoft.Storage/storageAccounts', storageAccount)
    containerRegistry:containerRegistry // resourceId('Microsoft.ContainerRegistry/registries', containerRegistry)
    keyVault: keyVault.id
    systemDatastoresAuthMode: 'identity'
    applicationInsights: applicationInsights // resourceId('Microsoft.Insights/components', applicationInsights)
    hbiWorkspace:false

    // network settings
    publicNetworkAccess: enablePublicGenAIAccess?'Enabled':'Disabled'
    allowPublicAccessWhenBehindVnet: allowPublicAccessWhenBehindVnet
    managedNetwork: {
      firewallSku:'Basic' // 'Standard'
      isolationMode: enablePublicGenAIAccess? 'AllowInternetOutBound': 'AllowOnlyApprovedOutbound'
      outboundRules: {
        search: {
          type: 'PrivateEndpoint'
          destination: {
            serviceResourceId: aiSearch.id
            subresourceTarget: 'searchService'
            sparkEnabled: false
            sparkStatus: 'Inactive'
          }
        }
        wikipedia: {
          type: 'FQDN'
          destination: 'en.wikipedia.org'
          category: 'UserDefined'
          status: 'Active'
        }
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
      }
    }
    networkAcls: {
      defaultAction: enablePublicGenAIAccess? 'Allow':'Deny'
      ipRules: ipRules
    }
    
    provisionNetworkNow: true
  }

  resource aoaiConnection 'connections' = {
    name: azureOpenAIConnectionName
    properties: {
      authType: 'AAD'
      category: 'AzureOpenAI'
      isSharedToAll: true
      useWorkspaceManagedIdentity: true
      peRequirement: enablePublicGenAIAccess?'NotRequired':'Required'
      sharedUserList: []
      metadata: {
        ApiType: 'Azure'
        ResourceId: aiServices.id
      }
      target: aiServices.properties.endpoints['OpenAI Language Model Instance API']
    }
  }
  resource aiServicesConnection 'connections' = {
    name: azureAIServicesConnectionName
    properties: {
      authType: 'AAD'
      category: 'AIServices'
      isSharedToAll: true
      useWorkspaceManagedIdentity: true
      peRequirement: enablePublicGenAIAccess?'NotRequired':'Required'
      sharedUserList: []
      metadata: {
        ApiType: 'Azure'
        ResourceId: aiServices.id
      }
      target: aiServices.properties.endpoint
    }
  }

  resource searchConnection 'connections' =
  if (!empty(azureAISearchConnectionName)) {
    name: azureAISearchConnectionName
    properties: {
      authType: 'AAD'
      category: 'CognitiveSearch'
      isSharedToAll: true
      useWorkspaceManagedIdentity: true
      peRequirement: enablePublicGenAIAccess?'NotRequired':'Required'
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
}

//CPU Cluster
resource acrBuildComputeCluster 'Microsoft.MachineLearningServices/workspaces/computes@2022-10-01' = {
  name: 'aif-dont-del-for-acr' // p001-m1-weu-prod (16/16...or 24)
  parent: aiHub
  location: location
  tags: tags
  identity: {
    type: 'SystemAssigned'
  }
  properties: {
    computeType: 'AmlCompute'
    computeLocation: location
    description: 'Dont touch. Dont delete. CPU cluster for building images for Container Registry'
    disableLocalAuth: true
    properties: {
      vmPriority: 'Dedicated'
      vmSize: 'Standard_DS3_v2'
      enableNodePublicIp: false
      isolatedNetwork: false
      osType: 'Linux'
      remoteLoginPortPublicAccess: 'Disabled'
      scaleSettings: {
        minNodeCount: 0
        maxNodeCount: 3
        nodeIdleTimeBeforeScaleDown: 'PT120S'
      }
      subnet: {
        id: subnet.id
      }
    }
  }
  dependsOn:[
    machineLearningPrivateEndpoint
  ]
}


@description('Azure Diagnostics: Azure AI Foundry hub - allLogs')
resource aiHubDiagSettings 'Microsoft.Insights/diagnosticSettings@2021-05-01-preview' = {
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
@description('This is a container for the ai foundry project.')
resource aiProject 'Microsoft.MachineLearningServices/workspaces@2024-10-01-preview' = {
  name: aiHubProjectName
  location: location
  kind: 'Project'
  sku: {
    name: 'Basic'
    tier: 'Basic'
  }
  identity: {
    type: 'SystemAssigned'  // This resource's identity is automatically assigned priviledge access to ACR, Storage, Key Vault, and Application Insights. 
                            // Since the priveleges are granted at the project/hub level have elevated access to the resources, it is recommended to isolate these resources
                            // to a resource group that only contains the project/hub.
  }
  properties: {
    friendlyName: 'Default project for AI Factory project. Outbound access: Wikipedia (chat demo)'
    description: 'Project to support the "Chat with Wikipedia" example prompt flow that is used as part of the Microsoft Learn Azure OpenAI baseline chat implementation. https://learn.microsoft.com/azure/architecture/ai-ml/architecture/baseline-openai-e2e-chat'
    v1LegacyMode: false
    publicNetworkAccess: enablePublicGenAIAccess?'Enabled':'Disabled'
    allowPublicAccessWhenBehindVnet: allowPublicAccessWhenBehindVnet
    enableDataIsolation: true
    hubResourceId: aiHub.id
  }

  resource endpoint 'onlineEndpoints' = {
    name: epDefaultName
    location: location
    kind: 'Managed'
    identity: {
      type: 'SystemAssigned' // This resource's identity is automatically assigned AcrPull access to ACR, Storage Blob Data Contributor, and AML Metrics Writer on the project. It is also assigned two additional permissions below.
                             // Given the permissions assigned to the identity, it is recommended only include deployments in the Azure OpenAI service that are trusted to be invoked from this endpoint.

    }
    properties: {
      description: 'This is the default inference endpoint for the AI Factory project, prompt flow deployment. Called by the UI hosted in Web Apps.'
      authMode: 'Key' // Ideally this should be based on Microsoft Entra ID access. This sample however uses a key stored in Key Vault.
      publicNetworkAccess: enablePublicGenAIAccess?'Enabled':'Disabled'
    }

    // Note: If you reapply this Bicep after an AI Foundry managed compute deployment has happened in this endpoint, the traffic routing reverts to 0% to all existing deployments. You'll need to set that back to 100% to your desired deployment.
  }
}

// Many role assignments are automatically managed by Azure for system managed identities, but the following two were needed to be added
// manually specifically for the endpoint.

/*
@description('Assign the online endpoint the ability to interact with the secrets of the parent project. This is needed to execute the prompt flow from the managed endpoint.')
resource projectSecretsReaderForOnlineEndpointRoleAssignment 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: aiProject
  name: guid(aiProject.id, aiProject::endpoint.id, amlWorkspaceSecretsReaderRole.id)
  properties: {
    roleDefinitionId: amlWorkspaceSecretsReaderRole.id
    principalType: 'ServicePrincipal'
    principalId: aiProject::endpoint.identity.principalId
  }
}
@description('Assign the online endpoint the ability to read connections from AI Project. This is needed to execute the prompt flow from the managed endpoint.')
resource projectEPConnections 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: aiProject
  name: guid(aiProject.id, aiProject::endpoint.id, amlConnectionReaderRole.id)
  properties: {
    roleDefinitionId: amlConnectionReaderRole.id
    principalType: 'ServicePrincipal'
    principalId: aiProject::endpoint.identity.principalId
  }
}

@description('Assign the online endpoint the ability to write metrics. This is needed to enable monitoring and logging to the prompt flow from the managed endpoint.')
resource projectEPMetricsWriter 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: aiProject
  name: guid(aiProject.id, aiProject::endpoint.id, amlMetricsWriterRole.id)
  properties: {
    roleDefinitionId: amlMetricsWriterRole.id
    principalType: 'ServicePrincipal'
    principalId: aiProject::endpoint.identity.principalId
  }
}

@description('Assign the online endpoint the ability to invoke models in Azure OpenAI. This is needed to execute the prompt flow from the managed endpoint.')
resource projectOpenAIUserForOnlineEndpointRoleAssignment 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: aiServices
  name: guid(aiServices.id, aiProject::endpoint.id, cognitiveServicesOpenAiUserRole.id)
  properties: {
    roleDefinitionId: cognitiveServicesOpenAiUserRole.id
    principalType: 'ServicePrincipal'
    principalId: aiProject::endpoint.identity.principalId
  }
}
*/

@description('Azure Diagnostics: AI Foundry chat project - allLogs')
resource chatProjectDiagSettings 'Microsoft.Insights/diagnosticSettings@2021-05-01-preview' = {
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

@description('Azure Diagnostics: AI Foundry chat project online endpoint - allLogs')
resource chatProjectOnlineEndpointDiagSettings 'Microsoft.Insights/diagnosticSettings@2021-05-01-preview' = {
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

// Production readiness change: Client applications that run from compute on Azure should use managed identities instead of
// pre-shared keys. This sample implementation uses a pre-shared key, and should be rewritten to use the managed identity
// provided by Azure Web Apps.
@description('Key Vault Secret: The Managed Online Endpoint key to be referenced from the Chat UI app.')
resource managedEndpointPrimaryKeyEntry 'Microsoft.KeyVault/vaults/secrets@2023-07-01' = {
  parent: keyVault
  name: 'aifactory-proj-ep-default-api-key'
  properties: {
    value: aiProject::endpoint.listKeys().primaryKey // This key is technically already in Key Vault, but it's name is not something that is easy to reference.
    contentType: 'text/plain'
    attributes: {
      enabled: true
    }
  }
}


resource machineLearningPrivateEndpoint 'Microsoft.Network/privateEndpoints@2020-11-01' = {
  name: privateEndpointName
  location: location
  tags: tags
  properties: {
    privateLinkServiceConnections: [
      {
        name: privateEndpointName
        properties: {
          groupIds: [
            'amlworkspace'
          ]
          privateLinkServiceId: aiHub.id
          privateLinkServiceConnectionState: {
            status: 'Approved'
            description: 'Private endpoint for Azure machine learning workspace'
          }
        }
      }
    ]
    subnet: {
      id: subnet.id
    }
  }
}

resource privateEndpointDns 'Microsoft.Network/privateEndpoints/privateDnsZoneGroups@2020-06-01' = if (centralDnsZoneByPolicyInHub == false) {
  name: '${machineLearningPrivateEndpoint.name}DnsZone'
  parent: machineLearningPrivateEndpoint
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


@description('Assign AML Workspace\'s ID: AcrPush to workload\'s container registry.')
resource containerRegistryPushRoleAssignment 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: acr
  name: guid(acr.id, aiHub.name, containerRegistryPushRole.id,acrName)
  properties: {
    roleDefinitionId: containerRegistryPushRole.id
    principalType: 'ServicePrincipal'
    principalId: aiHub.identity.principalId
  }
}

@description('Assign AML Workspace\'s Managed Online Endpoint: AcrPull to workload\'s container registry.')
resource computeInstanceContainerRegistryPullRoleAssignment 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: acr
  name: guid(acr.id, aiHub.name, containerRegistryPullRole.id,acrName)
  properties: {
    roleDefinitionId: containerRegistryPullRole.id
    principalType: 'ServicePrincipal'
    principalId: aiHub.identity.principalId
  }
}

output id string = aiHub.id
output name string = aiHub.name
output principalId string = aiHub.identity.principalId
output aiProjectName string = aiProject.name

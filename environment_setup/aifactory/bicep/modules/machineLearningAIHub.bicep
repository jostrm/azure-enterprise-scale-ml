@description('Specifies the name of the new machine learning studio resources')
param name string
param uniqueDepl string
param aifactorySuffix string
@description('Specifies the computer pool name')
param projectName string
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
param keyVault string
@description('Specifies the application insights id used for the machine learning studio')
param applicationInsights string
@description('Specifies the tags that should be applied to machine learning studio resources')
param tags object
@description('(Required) Specifies the private endpoint name')
param privateEndpointName string
@description('(Required) Specifies the virtual network id associated with private endpoint')
param vnetId string
@description('(Required) Specifies the subnet name that will be associated with the private endpoint')
param subnetName string
@description('Azure ML allowPublicAccessWhenBehindVnet')
param allowPublicAccessWhenBehindVnet bool
@description('AI Hub public access')
param enablePublicGenAIAccess bool
@description('ESML can run in DEMO mode, which creates private DnsZones,DnsZoneGroups, and vNetLinks. You can turn this off, to use your HUB instead.')
param centralDnsZoneByPolicyInHub bool
param aiSearchName string
param acrName string
param privateLinksDnsZones object

var subnetRef = '${vnetId}/subnets/${subnetName}'
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

resource amlAIHub 'Microsoft.MachineLearningServices/workspaces@2024-07-01-preview' = {
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
  kind: 'hub'
  properties: {
    friendlyName: 'AI Hub for: ${projectName}-${env}-${aiFactoryNumber}'
    description: 'AI hub requires an underlying Azure ML workspace. This is setup for ${projectName} in ESML-${env} environment in ${location}'
    storageAccount: storageAccount
    containerRegistry: containerRegistry
    keyVault: keyVault
    systemDatastoresAuthMode: 'identity'
    applicationInsights: applicationInsights
    hbiWorkspace:false

    // network settings
    publicNetworkAccess: enablePublicGenAIAccess?'Enabled':'Disabled'
    allowPublicAccessWhenBehindVnet: allowPublicAccessWhenBehindVnet
    managedNetwork: {
      isolationMode: 'AllowInternetOutBound'
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
      }
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
          privateLinkServiceId: amlAIHub.id
          privateLinkServiceConnectionState: {
            status: 'Approved'
            description: 'Private endpoint for Azure machine learning workspace'
          }
        }
      }
    ]
    subnet: {
      id: subnetRef
    }
  }
}

resource privateEndpointDns 'Microsoft.Network/privateEndpoints/privateDnsZoneGroups@2020-06-01' = if (centralDnsZoneByPolicyInHub == false) {
  name: '${machineLearningPrivateEndpoint.name}/${machineLearningPrivateEndpoint.name}DnsZone'
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
  name: guid(acr.id, amlAIHub.name, containerRegistryPushRole.id,acrName)
  properties: {
    roleDefinitionId: containerRegistryPushRole.id
    principalType: 'ServicePrincipal'
    principalId: amlAIHub.identity.principalId
  }
}

@description('Assign AML Workspace\'s Managed Online Endpoint: AcrPull to workload\'s container registry.')
resource computeInstanceContainerRegistryPullRoleAssignment 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: acr
  name: guid(acr.id, amlAIHub.name, containerRegistryPullRole.id,acrName)
  properties: {
    roleDefinitionId: containerRegistryPullRole.id
    principalType: 'ServicePrincipal'
    principalId: amlAIHub.identity.principalId
  }
}

/*
output dnsConfig array = [
  {
    name: privateEndpointName //pendAml.name
    type: 'amlworkspace'
  }
]
  */
output amlId string = amlAIHub.id
output amlName string = amlAIHub.name
output principalId string = amlAIHub.identity.principalId

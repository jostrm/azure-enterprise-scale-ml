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
@description('Resource name ID on DnsZone')
param amlPrivateDnsZoneID string
@description('Resource name ID on DnsZone')
param notebookPrivateDnsZoneID string
@description('Azure ML allowPublicAccessWhenBehindVnet')
param allowPublicAccessWhenBehindVnet bool
@description('AI Hub public access')
param enablePublicGenAIAccess bool
@description('ESML can run in DEMO mode, which creates private DnsZones,DnsZoneGroups, and vNetLinks. You can turn this off, to use your HUB instead.')
param centralDnsZoneByPolicyInHub bool = false // DONE: jåaj

var subnetRef = '${vnetId}/subnets/${subnetName}'
var aiFactoryNumber = substring(aifactorySuffix,1,3) // -001 to 001

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
    applicationInsights: applicationInsights
    publicNetworkAccess: enablePublicGenAIAccess?'Enabled':'Disabled'
    hbiWorkspace:false

    // network settings
    allowPublicAccessWhenBehindVnet: allowPublicAccessWhenBehindVnet // Not in 2024-07-01 - Microsoft.MachineLearningServices/workspaces@2024-07-01-preview'
    managedNetwork: {
      isolationMode: 'AllowInternetOutBound'
    }
    sharedPrivateLinkResources: []
  }
}

module machineLearningPrivateEndpoint 'machinelearningNetwork.bicep' = {
  name: 'machineLearningNetworking${uniqueDepl}'
  scope: resourceGroup()
  params: {
    location: location
    tags: tags
    workspaceArmId: amlAIHub.id
    subnetId: subnetRef
    machineLearningPleName: privateEndpointName
    amlPrivateDnsZoneID: amlPrivateDnsZoneID
    notebookPrivateDnsZoneID: notebookPrivateDnsZoneID
    centralDnsZoneByPolicyInHub:centralDnsZoneByPolicyInHub
  }
}
output amlId string = amlAIHub.id
output amlName string = amlAIHub.name
output principalId string = amlAIHub.identity.principalId

output dnsConfig array = [
  {
    name: privateEndpointName //pendAml.name
    type: 'amlworkspace'
  }
]

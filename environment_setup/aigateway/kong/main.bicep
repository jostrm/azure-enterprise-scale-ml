// ============================================================================
// Kong API Gateway - Main Deployment (Subscription Level)
// Deploys Kong Gateway OSS on Azure Container Instances with VNet injection
// to proxy requests to Azure OpenAI (private endpoint)
// ============================================================================
targetScope = 'subscription'

// ============================================================================
// Parameters
// ============================================================================
@description('Environment: dev, test, prod')
param env string

@description('Location for all resources')
param location string

@description('Location suffix (e.g., sdc for swedencentral)')
param locationSuffix string

@description('AI Factory suffix for resource group naming')
param aifactorySuffixRG string

@description('Resource group name prefix')
param commonRGNamePrefix string

@description('Tags for all resources')
param tags object

@description('Existing VNet resource group name')
param vnetResourceGroupName string

@description('Existing VNet name')
param vnetName string

@description('Subnet CIDR for Kong ACI (min /28)')
param kongSubnetCidr string

@description('Kong subnet name')
param kongSubnetName string = 'snet-kong-001'

@description('Kong container image')
param kongImage string = 'kong/kong-gateway:3.9'

@description('Kong container CPU cores')
param kongCpu int = 2

@description('Kong container memory in GB')
param kongMemoryGb int = 4

@description('Azure OpenAI endpoint URL (private)')
param azureOpenAIEndpoint string

@description('Azure OpenAI API key (from Key Vault)')
@secure()
param azureOpenAIApiKey string

@description('User-assigned managed identity resource ID (optional)')
param userAssignedIdentityId string = ''

@description('Common resource suffix')
param commonResourceSuffix string = '-001'

// ============================================================================
// Variables
// ============================================================================
var kongResourceGroupName = '${commonRGNamePrefix}esml-common-kong-${locationSuffix}-${env}${aifactorySuffixRG}'
var storageAccountName = 'stkong${locationSuffix}${env}${take(uniqueString(subscription().id, kongResourceGroupName), 6)}'

// ============================================================================
// Resource Group
// ============================================================================
resource kongRG 'Microsoft.Resources/resourceGroups@2024-03-01' = {
  name: kongResourceGroupName
  location: location
  tags: tags
}

// ============================================================================
// Module: Networking - Create subnet in existing VNet for Kong ACI
// ============================================================================
module kongNetworking 'modules/kong-networking.bicep' = {
  name: 'kong-networking-${env}'
  scope: resourceGroup(vnetResourceGroupName)
  params: {
    vnetName: vnetName
    kongSubnetName: kongSubnetName
    kongSubnetCidr: kongSubnetCidr
    location: location
  }
}

// ============================================================================
// Module: Storage - Azure File Share for Kong declarative config
// ============================================================================
module kongStorage 'modules/kong-storage.bicep' = {
  name: 'kong-storage-${env}'
  scope: kongRG
  params: {
    storageAccountName: storageAccountName
    location: location
    tags: tags
    kongSubnetId: kongNetworking.outputs.kongSubnetId
  }
}

// ============================================================================
// Module: ACI - Kong Gateway container
// ============================================================================
module kongAci 'modules/kong-aci.bicep' = {
  name: 'kong-aci-${env}'
  scope: kongRG
  params: {
    location: location
    tags: tags
    env: env
    locationSuffix: locationSuffix
    kongImage: kongImage
    kongCpu: kongCpu
    kongMemoryGb: kongMemoryGb
    kongSubnetId: kongNetworking.outputs.kongSubnetId
    storageAccountName: kongStorage.outputs.storageAccountName
    fileShareName: kongStorage.outputs.fileShareName
    azureOpenAIEndpoint: azureOpenAIEndpoint
    azureOpenAIApiKey: azureOpenAIApiKey
    userAssignedIdentityId: userAssignedIdentityId
    commonResourceSuffix: commonResourceSuffix
  }
}

// ============================================================================
// Outputs
// ============================================================================
output kongResourceGroupName string = kongResourceGroupName
output kongPrivateIp string = kongAci.outputs.kongPrivateIp
output kongSubnetId string = kongNetworking.outputs.kongSubnetId
output storageAccountName string = kongStorage.outputs.storageAccountName

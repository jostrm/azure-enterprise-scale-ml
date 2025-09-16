targetScope = 'subscription'

// ================================================================
// ML PLATFORM DEPLOYMENT - Phase 7 Implementation
// This file deploys ML and AI platform services including:
// - Azure Machine Learning Workspace (v1,v2)
// - Azure Kubernetes Service (AKS), private cluster, for ML workloads
// - Default CPU AML Cluster, Attached AKS to AML
// - Databricks
// - Azure Data Factory 
// - RBAC and permissions for ML platform, Data Factory, Databricks
// ================================================================

// ============== PARAMETERS ==============
@description('Environment: dev, test, prod')
@allowed(['dev', 'test', 'prod'])
param env string

@description('Project number (e.g., "005")')
param projectNumber string

@description('Location for all resources')
param location string

@description('Location suffix (e.g., "weu", "swc")')
param locationSuffix string

@description('Common resource suffix (e.g., "-001")')
param commonResourceSuffix string

@description('Project-specific resource suffix')
param resourceSuffix string

@description('Random salt for unique naming')
param aifactorySalt10char string
param randomValue string

@description('AI Factory suffix for resource groups')
param aifactorySuffixRG string

@description('Common resource group name')
param commonResourceGroupName string

@description('Project resource group name')
param projectResourceGroupName string

@description('Subscription ID for dev/test/prod')
param subscriptionIdDevTestProd string

@description('GenAI subnet ID')
param genaiSubnetId string

@description('AKS subnet ID')
param aksSubnetId string

@description('ACA subnet ID')
param acaSubnetId string

@description('Technical admins object ID')
param technicalAdminsObjectID string = ''

@description('Technical admins email')
param technicalAdminsEmail string = ''

@description('Enable Data Factory deployment')
param enableDatafactory bool = false

@description('Enable public access with perimeter for Data Factory')
param enablePublicAccessWithPerimeter bool = false

@description('Tags to apply to all resources')
param tags object

@description('Network environment (e.g., dev, test, prod)')
param network_env string = env

@description('VNet name with placeholder for network environment')
param vnetNameFull_param string = ''

@description('Base VNet name when no full name is provided')
param vnetNameBase string = 'vnet-cmn'

@description('VNet resource group name with placeholder for network environment')
param vnetResourceGroup_param string = ''

@description('Common resource group name for VNet')
param commonResourceGroup string = commonResourceGroupName

@description('Add AI Foundry Hub with random naming')
param addAIFoundryHub bool = false

@description('Common resource group name prefix')
param commonRGNamePrefix string = ''

@description('Project prefix for resource naming')
param projectPrefix string = ''

@description('Project name for resource group construction')
param projectName string = 'prj${projectNumber}'

@description('Project suffix for resource group naming')
param projectSuffix string = resourceSuffix


// ============================================================================
// SPECIAL - Get PRINICPAL ID of existing MI. Needs static name in existing
// ============================================================================
resource commonResourceGroupRef 'Microsoft.Resources/resourceGroups@2024-07-01' existing = {
  name: commonResourceGroup
  scope: subscription(subscriptionIdDevTestProd)
}
#disable-next-line BCP318
var uniqueInAIFenv_Static = substring(uniqueString(commonResourceGroupRef.id), 0, 5)

// ============== VARS ==============
var targetResourceGroup = '${commonRGNamePrefix}${projectPrefix}${replace(projectName, 'prj', 'project')}-${locationSuffix}-${env}${aifactorySuffixRG}${projectSuffix}'
var vnetNameFull = !empty(vnetNameFull_param) ? replace(vnetNameFull_param, '<network_env>', network_env) : '${vnetNameBase}-${locationSuffix}-${env}${commonResourceSuffix}'
var vnetResourceGroupName = !empty(vnetResourceGroup_param)? replace(vnetResourceGroup_param, '<network_env>', network_env) : commonResourceGroup
var dataFactoryName = 'adf-${projectNumber}-${locationSuffix}-${env}-${uniqueInAIFenv_Static}${resourceSuffix}'

// ============== MODULES ==============

// Import naming convention module
module naming '../modules/common/CmnAIfactoryNaming.bicep' = {
  name: take('01-naming-${targetResourceGroup}', 64)
  scope: resourceGroup(subscriptionIdDevTestProd, targetResourceGroup)
  params: {
    env: env
    projectNumber: projectNumber
    locationSuffix: locationSuffix
    commonResourceSuffix: commonResourceSuffix
    resourceSuffix: resourceSuffix
    aifactorySalt10char: aifactorySalt10char
    randomValue: randomValue
    aifactorySuffixRG: aifactorySuffixRG
    commonResourceGroupName: commonResourceGroupName
    commonRGNamePrefix: commonRGNamePrefix
    subscriptionIdDevTestProd: subscriptionIdDevTestProd
    genaiSubnetId: genaiSubnetId
    aksSubnetId: aksSubnetId
    acaSubnetId: acaSubnetId
    technicalAdminsObjectID: technicalAdminsObjectID
    technicalAdminsEmail: technicalAdminsEmail
    addAIFoundryHub: addAIFoundryHub
  }
}

resource vnet 'Microsoft.Network/virtualNetworks@2024-05-01' existing = {
  name: vnetNameFull
  scope: resourceGroup(vnetResourceGroupName)
}

// Azure Data Factory deployment
module dataFactory '../modules/dataFactory.bicep' = if (enableDatafactory) {
  name: 'data-factory-deployment'
  scope: resourceGroup(subscriptionIdDevTestProd, projectResourceGroupName)
  params: {
    name: dataFactoryName
    location: location
    tags: tags
    vnetId: vnet.id
    subnetName: naming.outputs.defaultSubnet
    portalPrivateEndpointName: '${dataFactoryName}-portal-pend'
    runtimePrivateEndpointName: '${dataFactoryName}-dataFactory-pend'
    enablePublicAccessWithPerimeter: enablePublicAccessWithPerimeter
    managedIdentities: {
      systemAssigned: true
    }
  }
}

// ============== OUTPUTS ==============
output dataFactoryEnabled bool = enableDatafactory

// Conditional outputs for Data Factory - only when enabled
output dataFactoryId string = enableDatafactory ? dataFactory!.outputs.adfId : ''
output dataFactoryName string = enableDatafactory ? dataFactory!.outputs.adfName : ''
output dataFactoryPrincipalId string = enableDatafactory ? dataFactory!.outputs.principalId : ''

targetScope = 'subscription'

param tags object = {}

@description('Subscription that hosts the target resource group. Defaults to the current subscription when omitted.')
param targetSubscriptionId string = subscription().subscriptionId

@description('Explicit target resource group name. Leave empty to derive from the common naming convention inputs.')
param targetResourceGroupName string = ''

@description('Optional pre-calculated common resource group name.')
param commonResourceGroup_param string = ''

@description('Prefix for common resource groups (for example "esml-").')
param commonRGNamePrefix string = ''

@description('Common resource base name (for example "common").')
param commonResourceName string = 'esml-common'

@description('Location suffix component used in naming (for example "weu").')
param locationSuffix string = ''

@description('Deployment environment moniker such as dev, test, or prod.')
@allowed([
	'dev'
	'test'
	'prod'
])
param env string

@description('Project number (three digits) used in naming, for example "001".')
param projectNumber string

@description('Suffix used for shared/common resources (for example "-001").')
param commonResourceSuffix string

@description('Suffix appended to project specific resources (for example "-001").')
param resourceSuffix string

@description('Prefix applied to project resource groups (for example "esml-").')
param projectPrefix string = 'esml-'

@description('Suffix applied to project resource groups (for example "-rg").')
param projectSuffix string = '-rg'

@description('Suffix appended to resource group names (for example "-rg").')
param aifactorySuffixRG string = ''

@description('Azure region for all resources. Defaults to swedencentral per design guidance.')
param location string = 'swedencentral'

@description('Optional deterministic salt (10 chars) used for naming. Leave empty to derive from randomValue.')
param aifactorySalt10char string = ''

@description('Random value used for deterministic naming fallback.')
param randomValue string = uniqueString(subscription().subscriptionId, locationSuffix, env)

@description('Comma separated list of technical admin object IDs.')
param technicalAdminsObjectID string = ''

@description('Comma separated list of technical admin emails.')
param technicalAdminsEmail string = ''

@description('Subscription that hosts the project resources. Defaults to the deployment subscription when not provided.')
param subscriptionIdDevTestProd string = targetSubscriptionId

@description('Existing virtual network Resource ID. Leave empty to derive from project subnet inputs.')
param existingVnetResourceId string = ''

@description('Virtual network name when creating a new network.')
param vnetName string = ''

@description('Address space for the VNet when creating a new network.')
param vnetAddressPrefix string = ''

@description('Subnet name dedicated to agents.')
param agentSubnetName string = ''

@description('Subnet name dedicated to private endpoints.')
param peSubnetName string = ''

@description('CIDR prefix for the agent subnet.')
param agentSubnetPrefix string = ''

@description('CIDR prefix for the private endpoint subnet.')
param peSubnetPrefix string = ''

@description('Existing Azure AI Search resource ID override. Leave empty to derive from the naming module output.')
param aiSearchResourceId string = ''

@description('Existing Azure Storage Account resource ID override. Leave empty to derive from the naming module output.')
param azureStorageAccountResourceId string = ''

@description('Existing Azure Cosmos DB resource ID override. Leave empty to derive from the naming module output.')
param azureCosmosDBAccountResourceId string = ''

@description('Existing API Management instance resource ID. Optional input that can remain empty.')
param apiManagementResourceId string = ''

@description('Optional Databricks public subnet name, retained for compatibility with legacy parameter files.')
param dbxPubSubnetName string = ''

@description('Optional Databricks private subnet name, retained for compatibility with legacy parameter files.')
param dbxPrivSubnetName string = ''

@description('Subscription hosting private DNS zones when centrally managed.')
param privDnsSubscription_param string = ''

@description('Resource group hosting private DNS zones when centrally managed.')
param privDnsResourceGroup_param string = ''

@description('Set to true when private DNS zones are enforced centrally via policy.')
param centralDnsZoneByPolicyInHub bool = false

@description('Subnet resource ID dedicated to private endpoints (genai subnet).')
param genaiSubnetId string = ''

@description('Primary AKS subnet resource ID.')
param aksSubnetId string = ''

@description('Primary ACA subnet resource ID used for agents.')
param acaSubnetId string = ''

@description('Optional secondary ACA subnet resource ID.')
param aca2SubnetId string = ''

@description('Optional secondary AKS subnet resource ID.')
param aks2SubnetId string = ''

@description('Disable agent network injection even when agent subnet inputs are provided.')
param disableAgentNetworkInjection bool = false
param addAIFoundry bool = false

var projectName = 'prj${projectNumber}'
var resolvedCommonResourceGroup = !empty(trim(commonResourceGroup_param)) ? commonResourceGroup_param : '${commonRGNamePrefix}${commonResourceName}-${locationSuffix}-${env}${aifactorySuffixRG}'
var resolvedTargetResourceGroup = !empty(trim(targetResourceGroupName)) ? targetResourceGroupName : '${commonRGNamePrefix}${projectPrefix}${replace(projectName, 'prj', 'project')}-${locationSuffix}-${env}${aifactorySuffixRG}${projectSuffix}'
var resolvedSubscriptionId = !empty(trim(subscriptionIdDevTestProd)) ? subscriptionIdDevTestProd : targetSubscriptionId
var moduleDeploymentSuffix = uniqueString(resolvedSubscriptionId, resolvedTargetResourceGroup, location)

var resolvedPrivDnsSubscription = !empty(trim(privDnsSubscription_param)) ? privDnsSubscription_param : resolvedSubscriptionId
var resolvedPrivDnsResourceGroup = (!empty(trim(privDnsResourceGroup_param)) && centralDnsZoneByPolicyInHub) ? privDnsResourceGroup_param : resolvedCommonResourceGroup

// Legacy-friendly aliases used by downstream modules and Azure DevOps parameter files
var targetResourceGroup = resolvedTargetResourceGroup
var privDnsSubscription = resolvedPrivDnsSubscription
var privDnsResourceGroupName = resolvedPrivDnsResourceGroup

var normalizedGenaiSubnetId = trim(genaiSubnetId)
var normalizedAcaSubnetId = trim(acaSubnetId)
var normalizedAca2SubnetId = trim(aca2SubnetId)

var subnetSourceForVnet = !empty(normalizedGenaiSubnetId) ? normalizedGenaiSubnetId : (!empty(normalizedAca2SubnetId) ? normalizedAca2SubnetId : (!empty(normalizedAcaSubnetId) ? normalizedAcaSubnetId : ''))
var vnetResourceIdFromSubnet = !empty(subnetSourceForVnet) ? split(subnetSourceForVnet, '/subnets/')[0] : ''
var resolvedExistingVnetResourceId = !empty(trim(existingVnetResourceId)) ? existingVnetResourceId : vnetResourceIdFromSubnet
var resolvedVnetName = !empty(trim(vnetName)) ? vnetName : (!empty(resolvedExistingVnetResourceId) ? last(split(resolvedExistingVnetResourceId, '/')) : vnetName)

var candidateAgentSubnetId = (!disableAgentNetworkInjection && !empty(normalizedAca2SubnetId)) ? normalizedAca2SubnetId : ((!disableAgentNetworkInjection && empty(normalizedAca2SubnetId) && !empty(normalizedAcaSubnetId)) ? normalizedAcaSubnetId : '')
var candidatePeSubnetId = !empty(normalizedGenaiSubnetId) ? normalizedGenaiSubnetId : (!empty(subnetSourceForVnet) ? subnetSourceForVnet : '')

var agentSubnetSubscriptionId = !empty(candidateAgentSubnetId) ? split(candidateAgentSubnetId, '/')[2] : resolvedSubscriptionId
var agentSubnetResourceGroupName = !empty(candidateAgentSubnetId) ? split(candidateAgentSubnetId, '/')[4] : resolvedTargetResourceGroup
var agentSubnetVnetName = !empty(candidateAgentSubnetId) ? split(candidateAgentSubnetId, '/')[8] : resolvedVnetName
var agentSubnetNameFromId = !empty(candidateAgentSubnetId) ? split(candidateAgentSubnetId, '/')[10] : ''

var peSubnetSubscriptionId = !empty(candidatePeSubnetId) ? split(candidatePeSubnetId, '/')[2] : resolvedSubscriptionId
var peSubnetResourceGroupName = !empty(candidatePeSubnetId) ? split(candidatePeSubnetId, '/')[4] : resolvedTargetResourceGroup
var peSubnetVnetName = !empty(candidatePeSubnetId) ? split(candidatePeSubnetId, '/')[8] : resolvedVnetName
var peSubnetNameFromId = !empty(candidatePeSubnetId) ? split(candidatePeSubnetId, '/')[10] : ''

resource agentSubnetExisting 'Microsoft.Network/virtualNetworks/subnets@2023-04-01' existing = if (!empty(candidateAgentSubnetId)) {
	name: '${agentSubnetVnetName}/${agentSubnetNameFromId}'
	scope: resourceGroup(agentSubnetSubscriptionId, agentSubnetResourceGroupName)
}

resource peSubnetExisting 'Microsoft.Network/virtualNetworks/subnets@2023-04-01' existing = if (!empty(candidatePeSubnetId)) {
	name: '${peSubnetVnetName}/${peSubnetNameFromId}'
	scope: resourceGroup(peSubnetSubscriptionId, peSubnetResourceGroupName)
}

var derivedAgentSubnetPrefix = !empty(candidateAgentSubnetId) ? agentSubnetExisting!.properties.addressPrefix : ''
var derivedPeSubnetPrefix = !empty(candidatePeSubnetId) ? peSubnetExisting!.properties.addressPrefix : ''

var resolvedAgentSubnetName = !empty(trim(agentSubnetName)) ? agentSubnetName : (!empty(agentSubnetNameFromId) ? agentSubnetNameFromId : 'agent-subnet')
var resolvedPeSubnetName = !empty(trim(peSubnetName)) ? peSubnetName : (!empty(peSubnetNameFromId) ? peSubnetNameFromId : 'pe-subnet')
var resolvedAgentSubnetPrefix = !empty(trim(agentSubnetPrefix)) ? agentSubnetPrefix : derivedAgentSubnetPrefix
var resolvedPeSubnetPrefix = !empty(trim(peSubnetPrefix)) ? peSubnetPrefix : derivedPeSubnetPrefix

module namingConvention '../modules/common/CmnAIfactoryNaming.bicep' = {
	name: take('foundryv2-naming-${resolvedTargetResourceGroup}', 64)
	scope: resourceGroup(resolvedSubscriptionId, resolvedTargetResourceGroup)
	params: {
		env: env
		projectNumber: projectNumber
		locationSuffix: locationSuffix
		commonResourceSuffix: commonResourceSuffix
		resourceSuffix: resourceSuffix
		aifactorySalt10char: aifactorySalt10char
		randomValue: randomValue
		aifactorySuffixRG: aifactorySuffixRG
		commonRGNamePrefix: commonRGNamePrefix
		technicalAdminsObjectID: technicalAdminsObjectID
		technicalAdminsEmail: technicalAdminsEmail
		commonResourceGroupName: resolvedCommonResourceGroup
		subscriptionIdDevTestProd: resolvedSubscriptionId
		genaiSubnetId: genaiSubnetId
		aksSubnetId: aksSubnetId
		acaSubnetId: acaSubnetId
		aca2SubnetId: aca2SubnetId
		aks2SubnetId: aks2SubnetId
	}
}

//param deploymentTimestamp string = utcNow('yyyyMMddHHmmss')
//var uniqueSuffix10 = substring(uniqueString('${targetResourceGroupName}-${deploymentTimestamp}'), 0, 10)

var cleanRandomValue = namingConvention.outputs.randomSalt
var aifRandom = take('aif${cleanRandomValue}',12)
var aifpRandom = take('aif2-p${projectNumber}-${cleanRandomValue}',12)
var aifV2Name = addAIFoundry? aifRandom: namingConvention.outputs.aifV2Name 
var aifV2ProjectName = addAIFoundry? aifpRandom: namingConvention.outputs.aifV2PrjName 

var aiSearchName = namingConvention.outputs.safeNameAISearch
var storageAccountName = namingConvention.outputs.storageAccount1001Name
var cosmosDbName = namingConvention.outputs.cosmosDBName

var computedAiSearchResourceId = !empty(aiSearchName) ? resourceId(resolvedSubscriptionId, resolvedTargetResourceGroup, 'Microsoft.Search/searchServices', aiSearchName) : ''
var computedAzureStorageAccountResourceId = !empty(storageAccountName) ? resourceId(resolvedSubscriptionId, resolvedTargetResourceGroup, 'Microsoft.Storage/storageAccounts', storageAccountName) : ''
var computedAzureCosmosDbResourceId = !empty(cosmosDbName) ? resourceId(resolvedSubscriptionId, resolvedTargetResourceGroup, 'Microsoft.DocumentDB/databaseAccounts', cosmosDbName) : ''

var resolvedAiSearchResourceId = !empty(trim(aiSearchResourceId)) ? aiSearchResourceId : computedAiSearchResourceId
var resolvedAzureStorageAccountResourceId = !empty(trim(azureStorageAccountResourceId)) ? azureStorageAccountResourceId : computedAzureStorageAccountResourceId
var resolvedAzureCosmosDbResourceId = !empty(trim(azureCosmosDBAccountResourceId)) ? azureCosmosDBAccountResourceId : computedAzureCosmosDbResourceId

module privateDns '../modules/common/CmnPrivateDnsZones.bicep' = {
	name: take('foundryv2-dns-${targetResourceGroup}', 64)
	scope: resourceGroup(subscriptionIdDevTestProd, targetResourceGroup)
	params: {
		location: location
		privDnsResourceGroupName: privDnsResourceGroupName
		privDnsSubscription: privDnsSubscription
	}
}

var privateLinksDnsZones = privateDns.outputs.privateLinksDnsZones

module foundryApim '../modules/csFoundry/foundry-apim/main.bicep' = {
	name: take('foundry-apim-${moduleDeploymentSuffix}', 64)
	scope: resourceGroup(resolvedSubscriptionId, resolvedTargetResourceGroup)
	params: {
		aifV2Name:aifV2Name
		aifV2ProjectName:aifV2ProjectName
		location: location
		existingVnetResourceId: resolvedExistingVnetResourceId
		vnetName: resolvedVnetName
		vnetAddressPrefix: vnetAddressPrefix
		agentSubnetName: resolvedAgentSubnetName
		peSubnetName: resolvedPeSubnetName
		agentSubnetPrefix: resolvedAgentSubnetPrefix
		peSubnetPrefix: resolvedPeSubnetPrefix
		aiSearchResourceId: resolvedAiSearchResourceId
		azureStorageAccountResourceId: resolvedAzureStorageAccountResourceId
		azureCosmosDBAccountResourceId: resolvedAzureCosmosDbResourceId
		apiManagementResourceId: apiManagementResourceId
		privateLinksDnsZones: privateLinksDnsZones
		privDnsSubscription: privDnsSubscription
		privDnsResourceGroupName: privDnsResourceGroupName
    targetSubscriptionId: resolvedSubscriptionId
    targetResourceGroup: resolvedTargetResourceGroup
    centralDnsZoneByPolicyInHub: centralDnsZoneByPolicyInHub
    tags: tags

	}
}

targetScope = 'subscription'

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
param env string = ''

@description('Suffix appended to resource group names (for example "-rg").')
param aifactorySuffixRG string = ''

@description('Azure region for all resources. Defaults to swedencentral per design guidance.')
param location string = 'swedencentral'

@description('Existing virtual network Resource ID. Leave empty to create a new network using the provided prefixes.')
param existingVnetResourceId string = ''

@description('Virtual network name when creating a new network.')
param vnetName string = 'agent-vnet-test'

@description('Address space for the VNet when creating a new network.')
param vnetAddressPrefix string = ''

@description('Subnet name dedicated to agents.')
param agentSubnetName string = 'agent-subnet'

@description('Subnet name dedicated to private endpoints.')
param peSubnetName string = 'pe-subnet'

@description('CIDR prefix for the agent subnet.')
param agentSubnetPrefix string = ''

@description('CIDR prefix for the private endpoint subnet.')
param peSubnetPrefix string = ''

@description('Existing Azure AI Search resource ID. Leave empty to create a new search service.')
param aiSearchResourceId string = ''

@description('Existing Azure Storage Account resource ID. Leave empty to create a new account.')
param azureStorageAccountResourceId string = ''

@description('Existing Azure Cosmos DB resource ID. Leave empty to create a new account.')
param azureCosmosDBAccountResourceId string = ''

@description('Existing API Management instance resource ID. Optional input that can remain empty.')
param apiManagementResourceId string = ''

@description('JSON encoded object describing existing DNS zones keyed by zone name. Leave blank to allow creation of new zones.')
param existingDnsZones string = ''

@description('JSON encoded array identifying DNS zones that should be validated. Defaults to the standard AI Foundry zones when blank.')
param dnsZoneNames string = ''

var storagePrivateDnsZone = 'privatelink.blob.${environment().suffixes.storage}'

var defaultDnsZones = {
	'privatelink.services.ai.azure.com': ''
	'privatelink.openai.azure.com': ''
	'privatelink.cognitiveservices.azure.com': ''
	'privatelink.search.windows.net': ''
	'${storagePrivateDnsZone}': ''
	'privatelink.documents.azure.com': ''
	'privatelink.azure-api.net': ''
}

var defaultDnsZoneNames = [
	'privatelink.services.ai.azure.com'
	'privatelink.openai.azure.com'
	'privatelink.cognitiveservices.azure.com'
	'privatelink.search.windows.net'
	storagePrivateDnsZone
	'privatelink.documents.azure.com'
	'privatelink.azure-api.net'
]

var resolvedCommonResourceGroup = !empty(trim(commonResourceGroup_param)) ? commonResourceGroup_param : '${commonRGNamePrefix}${commonResourceName}-${locationSuffix}-${env}${aifactorySuffixRG}'
var resolvedTargetResourceGroup = !empty(trim(targetResourceGroupName)) ? targetResourceGroupName : resolvedCommonResourceGroup
var parsedExistingDnsZones = empty(trim(existingDnsZones)) ? defaultDnsZones : json(existingDnsZones)
var parsedDnsZoneNames = empty(trim(dnsZoneNames)) ? defaultDnsZoneNames : json(dnsZoneNames)
var moduleDeploymentSuffix = uniqueString(targetSubscriptionId, resolvedTargetResourceGroup, location)

module foundryApim '../modules/csFoundry/foundry-apim/main.bicep' = {
	name: take('foundry-apim-${moduleDeploymentSuffix}', 64)
	scope: resourceGroup(targetSubscriptionId, resolvedTargetResourceGroup)
	params: {
		location: location
		existingVnetResourceId: existingVnetResourceId
		vnetName: vnetName
		vnetAddressPrefix: vnetAddressPrefix
		agentSubnetName: agentSubnetName
		peSubnetName: peSubnetName
		agentSubnetPrefix: agentSubnetPrefix
		peSubnetPrefix: peSubnetPrefix
		aiSearchResourceId: aiSearchResourceId
		azureStorageAccountResourceId: azureStorageAccountResourceId
		azureCosmosDBAccountResourceId: azureCosmosDBAccountResourceId
		apiManagementResourceId: apiManagementResourceId
		existingDnsZones: parsedExistingDnsZones
		dnsZoneNames: parsedDnsZoneNames
	}
}

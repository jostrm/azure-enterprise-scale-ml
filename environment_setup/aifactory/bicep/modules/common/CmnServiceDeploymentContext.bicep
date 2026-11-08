targetScope = 'subscription'

param env string
param projectNumber string
param location string
param locationSuffix string
param commonResourceSuffix string
param resourceSuffix string
param randomValue string
param aifactorySuffixRG string
param commonRGNamePrefix string
param vnetNameBase string
param genaiSubnetId string
param aksSubnetId string = ''
param acaSubnetId string = ''
param aca2SubnetId string = ''
param aks2SubnetId string = ''
param webappSubnetId string = ''
param aifactorySalt10char string = ''
param commonResourceGroup_param string = ''
param vnetResourceGroup_param string = ''
param vnetNameFull_param string = ''
param network_env string = ''
param centralDnsZoneByPolicyInHub bool = false
param privDnsSubscription_param string = ''
param privDnsResourceGroup_param string = ''
@description('Own access hub, added scale set: ARM id (/subscriptions/<sub>/resourceGroups/<rg>) of the resource group holding the bootstrap-managed private DNS zones. Empty for the bootstrap scale set and every other topology.')
param own_hub_private_dns_resource_group_id string = ''
param technicalAdminsObjectID string = ''
param technicalAdminsEmail string = ''
param postGresAdminEmails string = ''
param projectPrefix string = 'esml-'
param projectSuffix string = '-rg'
param commonResourceName string = 'esml-common'
param subscriptionIdDevTestProd string = subscription().subscriptionId
param deploymentPrefix string

var projectName = 'prj${projectNumber}'
var commonResourceGroup = !empty(commonResourceGroup_param) ? commonResourceGroup_param : '${commonRGNamePrefix}${commonResourceName}-${locationSuffix}-${env}${aifactorySuffixRG}'
var targetResourceGroup = '${commonRGNamePrefix}${projectPrefix}${replace(projectName, 'prj', 'project')}-${locationSuffix}-${env}${aifactorySuffixRG}${projectSuffix}'
var vnetName = !empty(vnetNameFull_param) ? replace(vnetNameFull_param, '<network_env>', network_env) : '${vnetNameBase}-${locationSuffix}-${env}${commonResourceSuffix}'
var vnetResourceGroupName = !empty(vnetResourceGroup_param) ? replace(vnetResourceGroup_param, '<network_env>', network_env) : commonResourceGroup
// Own access hub, added scale set: zones live in the bootstrap's DNS resource group, not in this scale set's.
// A literal '$(own_hub_private_dns_resource_group_id)' (ADO, variable not defined) is not an id and is ignored.
var ownHubPrivateDns = !centralDnsZoneByPolicyInHub && startsWith(toLower(own_hub_private_dns_resource_group_id), '/subscriptions/')
var ownHubPrivateDnsParts = split('${own_hub_private_dns_resource_group_id}////', '/')
var privDnsResourceGroupName = ownHubPrivateDns ? ownHubPrivateDnsParts[4] : ((!empty(privDnsResourceGroup_param) && centralDnsZoneByPolicyInHub) ? privDnsResourceGroup_param : vnetResourceGroupName)
var privDnsSubscription = ownHubPrivateDns ? ownHubPrivateDnsParts[2] : ((!empty(privDnsSubscription_param) && centralDnsZoneByPolicyInHub) ? privDnsSubscription_param : subscriptionIdDevTestProd)

module namingConvention 'CmnAIfactoryNaming.bicep' = {
  name: take('${deploymentPrefix}-naming-${targetResourceGroup}', 64)
  scope: resourceGroup(subscriptionIdDevTestProd, targetResourceGroup)
  params: {
    env: env
    projectNumber: projectNumber
    locationSuffix: locationSuffix
    commonResourceSuffix: commonResourceSuffix
    resourceSuffix: resourceSuffix
    randomValue: randomValue
    aifactorySalt10char: aifactorySalt10char
    aifactorySuffixRG: aifactorySuffixRG
    commonRGNamePrefix: commonRGNamePrefix
    commonResourceGroupName: commonResourceGroup
    subscriptionIdDevTestProd: subscriptionIdDevTestProd
    genaiSubnetId: genaiSubnetId
    aksSubnetId: aksSubnetId
    acaSubnetId: acaSubnetId
    aca2SubnetId: aca2SubnetId
    aks2SubnetId: aks2SubnetId
    webappSubnetId: webappSubnetId
    technicalAdminsObjectID: technicalAdminsObjectID
    technicalAdminsEmail: technicalAdminsEmail
    postGresAdminEmails: postGresAdminEmails
  }
}

module dnsZones 'CmnPrivateDnsZones.bicep' = {
  name: take('${deploymentPrefix}-dns-${targetResourceGroup}', 64)
  scope: resourceGroup(subscriptionIdDevTestProd, targetResourceGroup)
  params: {
    location: location
    privDnsResourceGroupName: privDnsResourceGroupName
    privDnsSubscription: privDnsSubscription
  }
}

output context object = {
  subscriptionId: subscriptionIdDevTestProd
  targetResourceGroup: targetResourceGroup
  commonResourceGroup: commonResourceGroup
  projectName: projectName
  vnetName: vnetName
  vnetResourceGroupName: vnetResourceGroupName
  privateLinksDnsZones: dnsZones.outputs.privateLinksDnsZones
  names: {
    defaultSubnet: namingConvention.outputs.defaultSubnet
    acaSubnetName: namingConvention.outputs.acaSubnetName
    aca2SubnetName: namingConvention.outputs.aca2SubnetName
    miPrjName: namingConvention.outputs.miPrjName
    miACAName: namingConvention.outputs.miACAName
    safeNameAISearch: namingConvention.outputs.safeNameAISearch
    randomSalt: namingConvention.outputs.randomSalt
    storageAccount2001Name: namingConvention.outputs.storageAccount2001Name
    aiServicesName: namingConvention.outputs.aiServicesName
    keyvaultName: namingConvention.outputs.keyvaultName
    laWorkspaceName: namingConvention.outputs.laWorkspaceName
    postgreSQLName: namingConvention.outputs.postgreSQLName
    redisManagedName: namingConvention.outputs.redisManagedName
    containerAppsEnvName: namingConvention.outputs.containerAppsEnvName
    containerAppAName: namingConvention.outputs.containerAppAName
    containerAppWName: namingConvention.outputs.containerAppWName
    acrCommonName: namingConvention.outputs.acrCommonName
    acrProjectName: namingConvention.outputs.acrProjectName
    applicationInsightName: namingConvention.outputs.applicationInsightName
    bingName: namingConvention.outputs.bingName
    aifV1ProjectName: namingConvention.outputs.aifV1ProjectName
    p011_genai_team_lead_array: namingConvention.outputs.p011_genai_team_lead_array
    postGresAdminEmails: namingConvention.outputs.postGresAdminEmails
  }
}

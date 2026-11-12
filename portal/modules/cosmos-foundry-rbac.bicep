// Replaces 69c_cosmosdb_data_contributor_for_foundry_project: Cosmos DB Built-in Data Contributor for the
// Foundry project identity. Names come from the same CmnAIfactoryNaming module and inputs as stage 09.
targetScope = 'subscription'

param env string
param projectNumber string
param locationSuffix string
param commonResourceSuffix string
param resourceSuffix string
param aifactorySalt10char string = ''
param randomValue string
param aifactorySuffixRG string
param commonRGNamePrefix string
param projectPrefix string
param projectSuffix string
param commonResourceGroup string
param subscriptionIdDevTestProd string
param genaiSubnetId string
param aksSubnetId string
param acaSubnetId string = ''
param aca2SubnetId string = ''
param aks2SubnetId string = ''
param accountName string

var projectName = 'prj${projectNumber}'
var targetResourceGroup = '${commonRGNamePrefix}${projectPrefix}${replace(projectName, 'prj', 'project')}-${locationSuffix}-${env}${aifactorySuffixRG}${projectSuffix}'

module naming '../../environment_setup/aifactory/bicep/modules/common/CmnAIfactoryNaming.bicep' = {
  name: take('portal-naming-${targetResourceGroup}', 64)
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
    commonRGNamePrefix: commonRGNamePrefix
    commonResourceGroupName: commonResourceGroup
    subscriptionIdDevTestProd: subscriptionIdDevTestProd
    genaiSubnetId: genaiSubnetId
    aksSubnetId: aksSubnetId
    acaSubnetId: acaSubnetId
    aca2SubnetId: aca2SubnetId
    aks2SubnetId: aks2SubnetId
  }
}

module assignment 'cosmos-foundry-rbac-assignment.bicep' = {
  name: take('portal-cosmos-rbac-${targetResourceGroup}', 64)
  scope: resourceGroup(subscriptionIdDevTestProd, targetResourceGroup)
  params: {
    cosmosAccountName: naming.outputs.cosmosDBName
    accountName: accountName
    projectName: naming.outputs.aifV2PrjName
  }
}

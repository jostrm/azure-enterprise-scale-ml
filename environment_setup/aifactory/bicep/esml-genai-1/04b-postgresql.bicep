targetScope = 'subscription'

@allowed(['dev', 'test', 'prod'])
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
param aifactorySalt10char string = ''
param commonResourceGroup_param string = ''
param vnetResourceGroup_param string = ''
param vnetNameFull_param string = ''
param network_env string = ''
param centralDnsZoneByPolicyInHub bool = false
param privDnsSubscription_param string = ''
param privDnsResourceGroup_param string = ''
param projectPrefix string = 'esml-'
param projectSuffix string = '-rg'
param commonResourceName string = 'esml-common'
param tagsProject object = {}

param enablePostgreSQL bool = true
param postgreSQLExists bool = false
param skuPostgreSQLDev string = 'Standard_B1ms'
param skuPostgreSQLStageProd string = 'Standard_B1ms'
param skuTierPostgreSQLDev string = 'Burstable'
param skuTierPostgreSQLStageProd string = 'Burstable'
param postgreSQLStorage object = {
  storageSizeGB: 32
}
param postgreSQLVersion string = '17'
param postgreSQLHighAvailability object = {
  mode: 'Disabled'
}
param postgresAvailabilityZone string = ''
param useAdGroups bool = false
param technicalAdminsObjectID string = ''
param technicalAdminsEmail string = ''
param postGresAdminEmails string = ''
param enablePublicAccessWithPerimeter bool = false
@allowed(['gold', 'silver', 'bronze'])
param diagnosticSettingLevel string = 'silver'
param cmk bool = false
param cmkKeyName string = ''
param admin_bicep_kv_fw string = ''
param admin_bicep_kv_fw_rg string = ''
param admin_bicep_input_keyvault_subscription string = ''
param inputKeyvault string
param inputKeyvaultResourcegroup string
param inputKeyvaultSubscription string
param projectServicePrincipleOID_SeedingKeyvaultName string

var standaloneDeploymentSuffix = uniqueString(subscription().subscriptionId, commonRGNamePrefix, aifactorySuffixRG, projectNumber, env, locationSuffix, resourceSuffix)

module deploymentContext '../modules/common/CmnServiceDeploymentContext.bicep' = {
  name: '04b-context-${standaloneDeploymentSuffix}'
  params: {
    deploymentPrefix: '04b'
    env: env
    projectNumber: projectNumber
    location: location
    locationSuffix: locationSuffix
    commonResourceSuffix: commonResourceSuffix
    resourceSuffix: resourceSuffix
    randomValue: randomValue
    aifactorySuffixRG: aifactorySuffixRG
    commonRGNamePrefix: commonRGNamePrefix
    vnetNameBase: vnetNameBase
    genaiSubnetId: genaiSubnetId
    aksSubnetId: aksSubnetId
    acaSubnetId: acaSubnetId
    aca2SubnetId: aca2SubnetId
    aks2SubnetId: aks2SubnetId
    aifactorySalt10char: aifactorySalt10char
    commonResourceGroup_param: commonResourceGroup_param
    vnetResourceGroup_param: vnetResourceGroup_param
    vnetNameFull_param: vnetNameFull_param
    network_env: network_env
    centralDnsZoneByPolicyInHub: centralDnsZoneByPolicyInHub
    privDnsSubscription_param: privDnsSubscription_param
    privDnsResourceGroup_param: privDnsResourceGroup_param
    projectPrefix: projectPrefix
    projectSuffix: projectSuffix
    commonResourceName: commonResourceName
    technicalAdminsObjectID: technicalAdminsObjectID
    technicalAdminsEmail: technicalAdminsEmail
    postGresAdminEmails: postGresAdminEmails
  }
}

var context = deploymentContext.outputs.context
var deployPostgreSQL = enablePostgreSQL && !postgreSQLExists
var targetResourceGroup = '${commonRGNamePrefix}${projectPrefix}${replace('prj${projectNumber}', 'prj', 'project')}-${locationSuffix}-${env}${aifactorySuffixRG}${projectSuffix}'

module getProjectMIPrincipalId '../modules/get-managed-identity-info.bicep' = if (deployPostgreSQL) {
  name: take('04b-getMI-${projectNumber}-${env}', 64)
  scope: resourceGroup(targetResourceGroup)
  params: {
    managedIdentityName: context.names.miPrjName
  }
}

resource externalKv 'Microsoft.KeyVault/vaults@2024-11-01' existing = {
  name: inputKeyvault
  scope: resourceGroup(inputKeyvaultSubscription, inputKeyvaultResourcegroup)
}

module spAndMI2Array '../modules/spAndMiArray.bicep' = if (deployPostgreSQL) {
  name: take('04b-principals-${projectNumber}-${env}', 64)
  scope: resourceGroup(targetResourceGroup)
  params: {
    managedIdentityOID: getProjectMIPrincipalId!.outputs.principalId
    servicePrincipleOIDFromSecret: (!empty(projectServicePrincipleOID_SeedingKeyvaultName) && !contains(toLower(projectServicePrincipleOID_SeedingKeyvaultName), '<todo>') && !contains(toLower(projectServicePrincipleOID_SeedingKeyvaultName), '<optional>')) ? externalKv.getSecret(projectServicePrincipleOID_SeedingKeyvaultName) : ''
  }
}

module postgresql '../modules/services/postgresqlDeployment.bicep' = if (deployPostgreSQL) {
  name: '04b-postgresql-${standaloneDeploymentSuffix}'
  params: {
    context: context
    deploymentSuffix: '${projectNumber}${env}${context.targetResourceGroup}'
    location: location
    tagsProject: tagsProject
    postgreSQLSKU: {
      name: env == 'dev' ? skuPostgreSQLDev : skuPostgreSQLStageProd
      tier: env == 'dev' ? skuTierPostgreSQLDev : skuTierPostgreSQLStageProd
    }
    postgreSQLStorage: postgreSQLStorage
    postgreSQLVersion: postgreSQLVersion
    postgreSQLHighAvailability: postgreSQLHighAvailability
    postgresAvailabilityZone: postgresAvailabilityZone
    useAdGroups: useAdGroups
    usersOrAdGroupArray: context.names.p011_genai_team_lead_array
    servicePrincipleAndMIArray: spAndMI2Array!.outputs.spAndMiArray
    adminNames: context.names.postGresAdminEmails
    enablePublicAccessWithPerimeter: enablePublicAccessWithPerimeter
    centralDnsZoneByPolicyInHub: centralDnsZoneByPolicyInHub
    diagnosticSettingLevel: diagnosticSettingLevel
    cmk: cmk
    cmkKeyName: cmkKeyName
    admin_bicep_kv_fw: admin_bicep_kv_fw
    admin_bicep_kv_fw_rg: admin_bicep_kv_fw_rg
    admin_bicep_input_keyvault_subscription: admin_bicep_input_keyvault_subscription
  }
}

output postgreSQLName string = context.names.postgreSQLName
output postgreSQLDeployed bool = deployPostgreSQL

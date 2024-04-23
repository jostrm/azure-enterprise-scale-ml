@description('Specifies the project number, such as a string "005". This is used to generate the projectName to embed in resources such as "prj005"')
param projectNumber string
@description('Specifies the name of the environment [dev,test,prod]. This name is reflected in resource group and sub-resources')
param env string
@description('ESML COMMON Resource Group prefix. If "rg-msft-word" then "rg-msft-word-esml-common-weu-dev-001"')
param commonRGNamePrefix string
@description('AI Factory suffix. If you have multiple instances, -001')
param aifactorySuffixRG string
@description('Such as "weu" or "swc" (swedencentral datacenter).Reflected in resource group and sub-resources')
param locationSuffix string
@description('Resource group where your vNet resides')
param commonResourceSuffix string // sdf
@description('Specifies the virtual network name')
param vnetNameBase string = 'vnt-esmlcmn'
@description('Specifies the OID array of users')
param technicalAdminsObjectID string
@description('Specifies the kv-cmndec-xys name')
param cmndevKeyvault string
@description('empty string or comma separated list. Specifies a project specific service principles OID comma separated list: asdfbsf,asdfasdf,')
param projectSP_OID_list string

param technicalAdminsObjectID_array array = array(split(technicalAdminsObjectID,','))
var technicalAdminsObjectID_array_safe = technicalAdminsObjectID == 'null'? []: technicalAdminsObjectID_array
var subscriptionIdDevTestProd = subscription().subscriptionId
var commonResourceGroup = '${commonRGNamePrefix}esml-common-${locationSuffix}-${env}${aifactorySuffixRG}' // change this to correct rg
var vnetNameFull = '${vnetNameBase}-${locationSuffix}-${env}${commonResourceSuffix}'

resource commonResourceGroupResource 'Microsoft.Resources/resourceGroups@2021-04-01' existing = {
  name: commonResourceGroup
  scope:subscription(subscriptionIdDevTestProd)
}

module rbacReadUsersToCmnVnetBastion '../../azure-enterprise-scale-ml/environment_setup/aifactory/bicep/modules/vnetRBACReader.bicep' = {
  scope: resourceGroup(subscriptionIdDevTestProd,commonResourceGroup)
  name: 'rbacReadUsersToCmnVnetBastion${projectNumber}${locationSuffix}${env}'
  params: {
    user_object_ids: technicalAdminsObjectID_array_safe
    project_service_principle: projectSP_OID_list
    vNetName: vnetNameFull
    common_bastion_subnet_name: 'AzureBastionSubnet'
    bastion_service_name: 'bastion-${locationSuffix}-${env}${aifactorySuffixRG}'  // bastion-uks-dev-001
    common_kv_name:cmndevKeyvault
  }
  dependsOn: [
    commonResourceGroupResource
  ]
}

var secretGetList = {
  secrets: [ 
    'get'
    'list'
  ]
}

var projectSP_OID_list_array = array(split(projectSP_OID_list,','))
var projectSP_OIDs_array_safe = projectSP_OID_list == 'null'? []: projectSP_OID_list_array
var users_and_serviceprincipals = union(technicalAdminsObjectID_array_safe, projectSP_OIDs_array_safe)

module kvCommonAccessPolicyGetListUtil '../../azure-enterprise-scale-ml/environment_setup/aifactory/bicep/modules/kvCmnAccessPolicys.bicep' = {
  scope: resourceGroup(subscriptionIdDevTestProd,commonResourceGroup)
  name: '${cmndevKeyvault}GetListUtil${projectNumber}${locationSuffix}${env}'
  params: {
    keyVaultPermissions: secretGetList
    keyVaultResourceName: cmndevKeyvault
    policyName: 'add'
    principalId: users_and_serviceprincipals[0]
    additionalPrincipalIds:users_and_serviceprincipals
  }
  dependsOn: [
    commonResourceGroupResource
  ]
}

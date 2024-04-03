// ########### COMMON PARAMS
@description('Specifies the project number, such as a string "005". This is used to generate the projectName to embed in resources such as "prj005"')
param projectNumber string
@description('Specifies the name of the environment [dev,test,prod]. This name is reflected in resource group and sub-resources')
param env string
@description('ESML COMMON Resource Group prefix. If "rg-msft-word" then "rg-msft-word-esml-common-weu-dev-001"')
param commonRGNamePrefix string
@description('AI Factory suffix. If you have multiple instances, -001')
param aifactorySuffixRG string
@description('Specifies the tags2 that should be applied to newly created resources')
param tags object
@description('Deployment location.')
param location string
@description('Such as "weu" or "swc" (swedencentral datacenter).Reflected in resource group and sub-resources')
param locationSuffix string
@description('-001,-002, etc')
param prjResourceSuffix string  // sdf
@description('Resource group where your vNet resides')
param commonResourceSuffix string // sdf
@description('Specifies the virtual network name')
param vnetNameBase string = 'vnt-esmlcmn'
@description('Specifies the OID array of users')
param technicalAdminsObjectID string
@description('Specifies the kv-cmndec-xys name')
param cmndevKeyvault string

var technicalAdminsObjectID_array = array(split(replace(technicalAdminsObjectID,' ',''),','))
var technicalAdminsObjectID_array_safe = technicalAdminsObjectID == 'null'? []: technicalAdminsObjectID_array
var subscriptionIdDevTestProd = subscription().subscriptionId
var projectName = 'prj${projectNumber}'
var targetResourceGroup = '${commonRGNamePrefix}esml-${replace(projectName, 'prj', 'project')}-${locationSuffix}-${env}${aifactorySuffixRG}-rg' // esml-project001-weu-dev-002-rg
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
    additionalUserIds: technicalAdminsObjectID_array_safe
    vNetName: vnetNameFull
    common_bastion_subnet_name: 'AzureBastionSubnet'
    bastion_service_name: 'bastion-${locationSuffix}-${env}${aifactorySuffixRG}'  // bastion-uks-dev-001
    common_kv_name:cmndevKeyvault
  }
  dependsOn: [
    commonResourceGroupResource
  ]
}




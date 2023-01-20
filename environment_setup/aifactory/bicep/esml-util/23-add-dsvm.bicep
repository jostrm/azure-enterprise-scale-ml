@description('Specifies the project number, such as a string "005". This is used to generate the projectName to embed in resources such as "prj005"')
param projectNumber string
@description('Specifies the name of the environment [dev,test,prod]. This name is reflected in resource group and sub-resources')
param env string

@secure()
@description('The password that is saved to keyvault and used by local admin user on VM')
param adminPassword string
@description('The username of the local admin that is created on VM')
param adminUsername string = 'esmladmin'

@description('ESML COMMON Resource Group prefix. If "rg-msft-word" then "rg-msft-word-esml-common-weu-dev-001"')
param commonRGNamePrefix string
@description('Common default subnet')
param common_subnet_name string
@description('Such as "weu" or "swc" (swedencentral datacenter).Reflected in resource group and sub-resources')
param locationSuffix string
@description('AI Factory suffix. If you have multiple instances, -001')
param aifactorySuffixRG string
@description('(Required) true if Hybrid benefits for Windows server VMs, else FALSE for Pay-as-you-go')
param hybridBenefit bool = true
@description('Specifies the tags2 that should be applied to newly created resources')
param tags object
@description('Deployment location.')
param location string
@description('-001,-002, etc')
param prjResourceSuffix string  // sdf
@description('-001,-002, etc')
param dsvmSuffix string  // sdf

@description('Resource group where your vNet resides')
param commonResourceSuffix string // sdf
@description('Specifies the virtual network name')
param vnetNameBase string = 'vnt-esmlcmn'


var deploymentProjSpecificUniqueSuffix = '${projectName}${locationSuffix}${env}${aifactorySuffixRG}'
var projectName = 'prj${projectNumber}'
var subscriptionIdDevTestProd = subscription().subscriptionId
var targetResourceGroup = '${commonRGNamePrefix}esml-${replace(projectName, 'prj', 'project')}-${locationSuffix}-${env}${aifactorySuffixRG}-rg' // esml-project001-weu-dev-002-rg
var commonResourceGroup = '${commonRGNamePrefix}esml-common-${locationSuffix}-${env}${aifactorySuffixRG}' // change this to correct rg

var vnetNameFull = '${vnetNameBase}-${locationSuffix}-${env}${commonResourceSuffix}'
var vnetId = '${subscription().id}/resourceGroups/${commonResourceGroup}/providers/Microsoft.Network/virtualNetworks/${vnetNameFull}'

resource commonResourceGroupRef 'Microsoft.Resources/resourceGroups@2021-04-01' existing = {
  name: commonResourceGroup
  scope:subscription(subscriptionIdDevTestProd)
}

var uniqueInAIFenv = substring(uniqueString(commonResourceGroupRef.id), 0, 5)
var twoNumbers = substring(prjResourceSuffix,2,2) // -001 -> 01
var keyvaultName = 'kv-p${projectNumber}-${locationSuffix}-${env}-${uniqueInAIFenv}${twoNumbers}'

resource projectResourceGroup 'Microsoft.Resources/resourceGroups@2021-04-01' existing = {
  name: targetResourceGroup
  scope:subscription(subscriptionIdDevTestProd)
}

module vmPrivate '../../azure-enterprise-scale-ml/environment_setup/aifactory/bicep/modules/virtualMachinePrivate.bicep' = {
  scope: resourceGroup(subscriptionIdDevTestProd,targetResourceGroup)
  name: 'privateVM4${deploymentProjSpecificUniqueSuffix}'
  params: {
    adminUsername: adminUsername
    adminPassword: adminPassword
    hybridBenefit: hybridBenefit
    vmSize: 'Standard_DS3_v2'
    location: location
    vmName: 'dsvm-${projectName}-${locationSuffix}-${env}${dsvmSuffix}'
    subnetName: common_subnet_name
    vnetId: vnetId
    tags: tags
    keyvaultName: keyvaultName
    kvSecretNameSuffix: dsvmSuffix // esml-dsvm-password-001,esml-dsvm-password-002, esml-dsvm-password-003
  }

  dependsOn: [
    projectResourceGroup
  ]
}

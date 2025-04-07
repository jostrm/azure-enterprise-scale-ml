targetScope = 'subscription'
@description('resource suffix, example: "-002" if this is a new ESML AI Factory')
param aifactorySuffixRG string =''

@allowed([
  'dev'
  'test'
  'prod'
])
@description('Specifies the name of the environment. This name is reflected in resource group and sub-resources')
param env string
@description('Deployment location, westeurope, swedencentral')
param location string
@description('resource location awareness suffix. Example:"-weu"')
param locationSuffix string
@description('Specifies the tags that should be applied to newly created resources')
param tags object
@description('Specifies project owner email and will be used for tagging and RBAC')
param technicalContactEmail string = ''
@description('Specifies project owner objectId and will be used for tagging and RBAC')
param technicalContactId string = ''
@description('Resource group prefix. If "rg-msft-word" then "rg-msft-word-esml-common-weu-dev-001"')
param commonRGNamePrefix string = ''
@description('Optional input from Azure Devops variable - a semicolon separated string of AD users ObjectID to get RBAC on Resourcegroup "adsf,asdf" ')
param technicalAdminsObjectID string = 'null'
@description('Optional input from Azure Devops variable - a semicolon separated string of AD users ObjectID to get RBAC on Resourcegroup "adsf,asdf" ')
param technicalAdminsEmail string = 'null'
param commonResourceGroup_param string = ''
param useAdGroups bool = false
param enableAdminVM bool = false

var technicalAdminsObjectID_array = array(split(technicalAdminsObjectID,','))
var technicalAdminsEmail_array = array(split(technicalAdminsEmail,','))
var technicalAdminsObjectID_array_safe = technicalAdminsObjectID == 'null'? []: technicalAdminsObjectID_array
var technicalAdminsEmail_array_safe = technicalAdminsEmail == 'null'? []: technicalAdminsEmail_array
var subscriptionIdDevTestProd = subscription().subscriptionId

var commonResourceGroupName = commonResourceGroup_param != '' ? commonResourceGroup_param : '${commonRGNamePrefix}esml-common-${locationSuffix}-${env}${aifactorySuffixRG}' // aaa-bbb-esml-common-weu-dev-002 (31/90 chars)

module rgCommon '../../modules/resourcegroupUnmanaged.bicep' = {
  scope: subscription(subscriptionIdDevTestProd)
  name: 'CommonRG${env}-depl${commonRGNamePrefix}${env}${aifactorySuffixRG}${locationSuffix}'
  params: {
    rgName: commonResourceGroupName
    location: location
    tags: tags
  }
}

module contributorPermissions '../../modules/contributorRbac.bicep' = {
  scope: resourceGroup(subscriptionIdDevTestProd,commonResourceGroupName)
  name: 'ContributorPermissionsOnRGCmn-depl${commonRGNamePrefix}${env}${aifactorySuffixRG}${locationSuffix}'
  params: {
    //userId: technicalContactId
    userEmail: technicalContactEmail
    additionalUserIds: technicalAdminsObjectID_array_safe
    additionalUserEmails: technicalAdminsEmail_array_safe
    useAdGroups: useAdGroups
  }
  dependsOn:[
    rgCommon
  ]
}
module vmAdminLoginPermissions '../../modules/vmAdminLoginRbac.bicep' = {
  scope: resourceGroup(subscriptionIdDevTestProd,commonResourceGroupName)
  name: 'VMAdminLoginPermissions-depl${commonRGNamePrefix}${env}${aifactorySuffixRG}${locationSuffix}'
  params: {
    //userId: technicalContactId
    userEmail: technicalContactEmail
    additionalUserIds: technicalAdminsObjectID_array_safe
    additionalUserEmails: technicalAdminsEmail_array_safe
    useAdGroups: useAdGroups
  }
  dependsOn:[
    rgCommon
  ]
}

// TODO 1 - Global private link scope, for Azure Monitor, one per Dev,Test, Prod
// https://docs.microsoft.com/en-us/azure/azure-monitor/logs/private-link-configure
// 1a) ESML CMN: resource symbolicname 'microsoft.insights/privateLinkScopes@2021-07-01-preview' = {
// 1b) ESML CMN: private link to the SCOPE network
// 1c) ESML CMN: Add Each Log Analytics Workspace (dev,test,prod)
// 1d) ESML CMN: Add workspace Queries to Each Log Analytics Workspace (dev,test,prod)
// 2)  ESML Project: When creating projects "applicationInsight", connect to correct Log Analytics Workspace (dev,test,prod)

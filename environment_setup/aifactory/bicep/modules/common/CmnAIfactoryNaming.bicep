// ================================================================
// AI FACTORY NAMING CONVENTION MODULE
// This module provides standardized naming conventions for all
// AI Factory resources across all deployment phases (01-07).
// Import this module to ensure consistent resource naming.
// ================================================================

// Import types
import { aifactoryNamingType } from '../types/aifactoryNaming.bicep'

// ============== PARAMETERS ==============
@description('Environment: dev, test, prod')
@allowed(['dev', 'test', 'prod'])
param env string

param keepMIandKVsuffixAs001 bool = false
@description('Project number (e.g., "005")')
param projectNumber string

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

@description('Common resource group name prefix')
param commonRGNamePrefix string = ''

@description('User Admins OID list')
param technicalAdminsObjectID string = ''
@description('User Admins EMAIL list')
param technicalAdminsEmail string = ''
param commonResourceGroupName string
param subscriptionIdDevTestProd string
param genaiSubnetId string
param aksSubnetId string
param aks2SubnetId string = ''
param acaSubnetId string = ''
param aca2SubnetId string = ''

param postGresAdminEmails string = ''

@description('Add AI Foundry Hub with random naming for debugging/testing')
param addAIFoundryHub bool = false

@description('Add Azure Machine Learning with random naming for debugging/testing')
param addAzureMachineLearning bool = false

// ============== VARIABLES ==============
var projectName = 'prj${projectNumber}'
var cmnName = 'cmn'
var genaiName = 'genai'
var prjResourceSuffixNoDash = replace(resourceSuffix,'-','')

//var kvSuffix = keepMIandKVsuffixAs001 ? '01' : substring(resourceSuffix,2,2)
var twoNumbers = substring(resourceSuffix,2,2) // -001 -> 01
var resourceSuffixPlusOne = '-${padLeft(string(int(substring(resourceSuffix,1,3)) + 1), 3, '0')}'

// ============================================================================
// COMPUTED VARIABLES - RBAC Arrays
// ============================================================================

var technicalAdminsObjectID_array = array(split(replace(technicalAdminsObjectID,'\\s+', ''),','))
var p011_genai_team_lead_array = (empty(technicalAdminsObjectID)) ? [] : union(technicalAdminsObjectID_array,[])

var postGresAdminEmailsLocal_array = array(split(replace(postGresAdminEmails,'\\s+', ''),','))
var postGresAdminEmailsLocal = (empty(postGresAdminEmails)) ? [] : union(postGresAdminEmailsLocal_array,[])

var technicalAdminsEmail_array = array(split(technicalAdminsEmail,','))
var p011_genai_team_lead_email_array = (empty(technicalAdminsEmail)) ? [] : technicalAdminsEmail_array

// ============================================================================
// COMPUTED VARIABLES - Naming & Salt
// ============================================================================

// Salt generation for unique naming '0d-bf29-48'
var randomSalt = empty(aifactorySalt10char) || length(aifactorySalt10char) <= 5 ? substring(randomValue, 0, 10): aifactorySalt10char

resource commonResourceGroupRef 'Microsoft.Resources/resourceGroups@2024-07-01' existing = {
  name: commonResourceGroupName
  scope: subscription(subscriptionIdDevTestProd)
}

#disable-next-line BCP318
var uniqueInAIFenv = substring(uniqueString(commonResourceGroupRef.id), 0, 5)

// ============================================================================
// AI Factory - naming convention
// ============================================================================

// AI Foundry V1
// AI Foundry Hub specific names (12)
// Ensure domain name compliance: lowercase, no special chars, proper length
var cleanRandomValue = toLower(replace(replace(randomSalt, '-', ''), '_', ''))
var aifRandom = take(cleanRandomValue,2)

// aif-hub-001-eus2-dev-qoygy-001 (30) + 2 = 32
var aifWithRandom = take('aif-hub-${projectNumber}-${locationSuffix}-${env}-${uniqueInAIFenv}${aifRandom}${resourceSuffix}',64)
var aifV1HubName = addAIFoundryHub ? aifWithRandom : 'aif-hub-${projectNumber}-${locationSuffix}-${env}-${uniqueInAIFenv}${resourceSuffix}'
var aifV1ProjectName = 'aif-p-${projectNumber}-1-${locationSuffix}-${env}-${uniqueInAIFenv}${resourceSuffix}' // TODO=DONE

// AI Foundry V2 (2025):aif-V2-001-eus-dev-12345-001 = 28
//var aifV2Name = 'aif-V2-${projectNumber}-${locationSuffix}-${env}-${uniqueInAIFenv}${resourceSuffix}' // ->pend error
//var aifV2Name = take('aifV2${projectNumber}${locationSuffix}${env}',12) // (12) aifV2001eusd -> worked!

// @2025-04-01-preview
//var aifV2Name = 'aif-V2-${projectNumber}-${locationSuffix}-${env}-${uniqueInAIFenv}${resourceSuffix}' // @2025-04-01-preview (32)
var aifV2Name = take(replace(toLower('aif2${uniqueInAIFenv}${randomSalt}'), '-', ''),12) // @2025-06-01: name (12)
//var aifV2PrjName ='aif2-prj-${projectNumber}-${locationSuffix}-${env}-${uniqueInAIFenv}${prjResourceSuffixNoDash}' // Does this work?
var aifV2PrjName =take(toLower('aif2-p${projectNumber}-${uniqueInAIFenv}${randomSalt}'),12) // 64 according to doc. but is 12 chars max for project name

var aoaiName = 'aoai-${projectNumber}-${locationSuffix}-${env}-${uniqueInAIFenv}${resourceSuffix}'

// Azure Machine Learning specific names with random naming option for debugging/testing
// aml-001-eus2-dev-qoygy-001 (28) + 2 = 30
var amlWithRandom = take('aml-${projectNumber}-${locationSuffix}-${env}-${uniqueInAIFenv}${aifRandom}${resourceSuffix}',64)
var amlName = addAzureMachineLearning ? amlWithRandom : 'aml-${projectNumber}-${locationSuffix}-${env}-${uniqueInAIFenv}${resourceSuffix}'
var safeNameAISearch = take(replace(toLower('aisearch${projectName}${locationSuffix}${env}${uniqueInAIFenv}${randomSalt}${prjResourceSuffixNoDash}'), '-', ''), 64) // AzureAISearch4prj0025kxmv
var aiServicesName = take(replace(toLower('aiservices${projectName}${locationSuffix}${env}${uniqueInAIFenv}${randomSalt}${prjResourceSuffixNoDash}'), '-', ''), 64) 

// Monitoring and Insights
var dashboardInsightsName = 'AIFactory${aifactorySuffixRG}-${projectName}-insights-${env}-${uniqueInAIFenv}${resourceSuffix}'
var applicationInsightName = 'ain-${projectName}-${locationSuffix}-${env}-${uniqueInAIFenv}${resourceSuffix}'
var applicationInsightName2 = 'ain-${projectName}-${locationSuffix}-${env}-${uniqueInAIFenv}${resourceSuffixPlusOne}'

// External Services
var bingName = 'bing-${projectName}-${locationSuffix}-${env}-${uniqueInAIFenv}${resourceSuffix}'

// Container Apps
var containerAppsEnvName = 'aca-env-${projectName}-${locationSuffix}-${env}-${uniqueInAIFenv}${resourceSuffix}'
var containerAppAName = 'aca-a-${projectName}${locationSuffix}${env}${uniqueInAIFenv}${resourceSuffix}'
var containerAppWName = 'aca-w-${projectName}${locationSuffix}${env}${uniqueInAIFenv}${resourceSuffix}'

// Databases
var cosmosDBName = 'cosmos-${projectName}-${locationSuffix}-${env}-${uniqueInAIFenv}${resourceSuffix}'
var redisName ='redis-${projectName}-${locationSuffix}-${env}-${uniqueInAIFenv}${resourceSuffix}'
var postgreSQLName ='pg-flex-${projectName}-${locationSuffix}-${env}-${uniqueInAIFenv}${resourceSuffix}'
var sqlServerName ='sql-${projectName}-${locationSuffix}-${env}-${uniqueInAIFenv}${resourceSuffix}'
var sqlDBName ='sqldb-${projectName}-${locationSuffix}-${env}-${uniqueInAIFenv}${resourceSuffix}'

// Compute Services
var functionAppName = 'func-${projectName}-${locationSuffix}-${env}-${uniqueInAIFenv}${resourceSuffix}'
var webAppName = 'webapp-${projectName}-${locationSuffix}-${env}-${uniqueInAIFenv}${resourceSuffix}'
var funcAppServicePlanName = 'func-${projectName}-${locationSuffix}-${env}-${uniqueInAIFenv}${resourceSuffix}-plan'
var webbAppServicePlanName = 'webapp-${projectName}-${locationSuffix}-${env}-${uniqueInAIFenv}${resourceSuffix}-plan'
var vmName = 'dsvm-${projectName}-${locationSuffix}-${env}-${uniqueInAIFenv}${resourceSuffix}'


// Storage and Keys
var keyvaultName = 'kv-p${projectNumber}-${locationSuffix}-${env}-${uniqueInAIFenv}${twoNumbers}'
var storageAccount1001Name = replace('sa${projectName}${locationSuffix}${uniqueInAIFenv}1${prjResourceSuffixNoDash}${env}', '-', '')
var storageAccount2001Name = replace('sa${projectName}${locationSuffix}${uniqueInAIFenv}2${prjResourceSuffixNoDash}${env}', '-', '')

// Container Registries
var acrProjectName = 'acr${projectName}${genaiName}${locationSuffix}${uniqueInAIFenv}${env}${prjResourceSuffixNoDash}'
var acrCommonName = replace('acrcommon${uniqueInAIFenv}${locationSuffix}${commonResourceSuffix}${env}','-','')

// Managed Identities (with random salt for uniqueness)
var miSuffix = keepMIandKVsuffixAs001 ? '-001' : resourceSuffix
var miACAName = 'mi-aca-${projectName}-${locationSuffix}-${env}-${uniqueInAIFenv}${randomSalt}${miSuffix}'
var miPrjName = 'mi-${projectName}-${locationSuffix}-${env}-${uniqueInAIFenv}${randomSalt}${miSuffix}'

// Common Resource Group Services
var laWorkspaceName = 'la-${cmnName}-${locationSuffix}-${env}-${uniqueInAIFenv}${commonResourceSuffix}'

// ============================================================================
// COMPUTED VARIABLES - Networking subnets
// ============================================================================
var segments = split(genaiSubnetId, '/')
var genaiSubnetName = segments[length(segments) - 1] // Get the last segment, which is the subnet name
var defaultSubnet = genaiSubnetName // Pend subnet
var segmentsAKS = split(aksSubnetId, '/')
var segmentsAKS2 = split(aks2SubnetId, '/')
var aksSubnetName = segmentsAKS[length(segmentsAKS) - 1] // Get the last segment, which is the subnet name
var aks2SubnetName = segmentsAKS2[length(segmentsAKS2) - 1] // Get the last segment, which is the subnet name
var segmentsACA = split(acaSubnetId, '/')
var segmentsACA2 = split(aca2SubnetId, '/')
var acaSubnetName = segmentsACA[length(segmentsACA) - 1] // Get the last segment, which is the subnet name
var aca2SubnetName = segmentsACA2[length(segmentsACA2) - 1] // Get the last segment, which is the subnet name

var adfName = 'adf-${projectNumber}-${locationSuffix}-${env}-${uniqueInAIFenv}${resourceSuffix}'

// ============== OUTPUTS ==============

// Subnets
output genaiSubnetName string = genaiSubnetName
output aksSubnetName string = aksSubnetName
output aks2SubnetName string = aks2SubnetName
output acaSubnetName string = acaSubnetName
output aca2SubnetName string = aca2SubnetName
output defaultSubnet string = defaultSubnet // pend subnet is genai

output aoaiName string = aoaiName
output amlName string = amlName
output safeNameAISearch string = safeNameAISearch
output aiServicesName string = aiServicesName

// Monitoring and Insights
output dashboardInsightsName string = dashboardInsightsName
output applicationInsightName string = applicationInsightName
output applicationInsightName2 string = applicationInsightName2

// External Services
output bingName string = bingName

// Container Apps
output containerAppsEnvName string = containerAppsEnvName
output containerAppAName string = containerAppAName
output containerAppWName string = containerAppWName

// Databases
output cosmosDBName string = cosmosDBName
output redisName string = redisName
output postgreSQLName string = postgreSQLName
output sqlServerName string = sqlServerName
output sqlDBName string = sqlDBName

// Compute Services
output functionAppName string = functionAppName
output webAppName string = webAppName
output funcAppServicePlanName string = funcAppServicePlanName
output webbAppServicePlanName string = webbAppServicePlanName
output vmName string = vmName

// AI Foundry V1 (2023-2025) with Hub
output aifV1HubName string = aifV1HubName
output aifV1ProjectName string = aifV1ProjectName

// AI Foundry V2
output aifV2Name string = aifV2Name
output aifV2PrjName string = aifV2PrjName

// Storage and Keys
output keyvaultName string = keyvaultName
output storageAccount1001Name string = storageAccount1001Name
output storageAccount2001Name string = storageAccount2001Name

// Container Registries
output acrProjectName string = acrProjectName
output acrCommonName string = acrCommonName

// Managed Identities
output miACAName string = miACAName
output miPrjName string = miPrjName

// Common Resource Group Services
output laWorkspaceName string = laWorkspaceName

// Helper variables
output projectName string = projectName
output cmnName string = cmnName
output kvNameCommon string = 'kv-${cmnName}${env}-${uniqueInAIFenv}${commonResourceSuffix}'
output genaiName string = genaiName
output prjResourceSuffixNoDash string = prjResourceSuffixNoDash
output twoNumbers string = twoNumbers
output p011_genai_team_lead_array array = p011_genai_team_lead_array
output postGresAdminEmails array = postGresAdminEmailsLocal
output p011_genai_team_lead_email_array array = p011_genai_team_lead_email_array
output uniqueInAIFenv string = uniqueInAIFenv
output randomSalt string = randomSalt
output projectTypeESMLName string = 'esml'
output projectTypeGenAIName string = 'genai'
output aksClusterName string = 'esml${projectNumber}-${locationSuffix}-${env}'
output dataFactoryName string = adfName

// Complete naming convention output with type safety
output namingConvention aifactoryNamingType = {
  // Subnets
  genaiSubnetName: genaiSubnetName
  aksSubnetName: aksSubnetName
  aks2SubnetName: aks2SubnetName
  acaSubnetName: acaSubnetName
  aca2SubnetName: aca2SubnetName
  defaultSubnet: defaultSubnet

  // AI Foundry V1 (2023-2025)
  aifV1HubName: aifV1HubName
  aifV1ProjectName: aifV1ProjectName
  // AI Foundry V2 (2025-)
  aifV2Name: aifV2Name
  aifV2PrjName: aifV2PrjName

  aoaiName: aoaiName
  amlName: amlName
  safeNameAISearch: safeNameAISearch
  aiServicesName: aiServicesName

  // Monitoring and Insights
  dashboardInsightsName: dashboardInsightsName
  applicationInsightName: applicationInsightName
  applicationInsightName2: applicationInsightName2

  // External Services
  bingName: bingName

  // Container Apps
  containerAppsEnvName: containerAppsEnvName
  containerAppAName: containerAppAName
  containerAppWName: containerAppWName

  // Databases
  cosmosDBName: cosmosDBName
  redisName: redisName
  postgreSQLName: postgreSQLName
  sqlServerName: sqlServerName
  sqlDBName: sqlDBName

  // Compute Services
  functionAppName: functionAppName
  webAppName: webAppName
  funcAppServicePlanName: funcAppServicePlanName
  webbAppServicePlanName: webbAppServicePlanName
  vmName: vmName

  // Storage and Keys
  keyvaultName: keyvaultName
  storageAccount1001Name: storageAccount1001Name
  storageAccount2001Name: storageAccount2001Name

  // Container Registries
  acrProjectName: acrProjectName
  acrCommonName: acrCommonName

  // Managed Identities
  miACAName: miACAName
  miPrjName: miPrjName

  // Common Resource Group Services
  laWorkspaceName: laWorkspaceName
  
  // Helper variables
  projectName: projectName
  cmnName: cmnName
  kvNameCommon: 'kv-${cmnName}${env}-${uniqueInAIFenv}${commonResourceSuffix}'
  genaiName: genaiName
  prjResourceSuffixNoDash: prjResourceSuffixNoDash
  twoNumbers: twoNumbers
  p011_genai_team_lead_array: p011_genai_team_lead_array
  p011_genai_team_lead_email_array: p011_genai_team_lead_email_array
  uniqueInAIFenv: uniqueInAIFenv
  randomSalt: randomSalt
  projectTypeESMLName: 'esml'
  projectTypeGenAIName: 'genai'
  aksClusterName: 'esml${projectNumber}-${locationSuffix}-${env}'
  dataFactoryName: adfName
}

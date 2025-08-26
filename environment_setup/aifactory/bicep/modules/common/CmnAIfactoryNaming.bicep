// ================================================================
// AI FACTORY NAMING CONVENTION MODULE
// This module provides standardized naming conventions for all
// AI Factory resources across all deployment phases (01-07).
// Import this module to ensure consistent resource naming.
// ================================================================

// ============== PARAMETERS ==============
@description('Environment: dev, test, prod')
@allowed(['dev', 'test', 'prod'])
param env string

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
param acaSubnetId string

// ============== VARIABLES ==============
var projectName = 'prj${projectNumber}'
var cmnName = 'cmn'
var genaiName = 'genai'
var prjResourceSuffixNoDash = replace(resourceSuffix,'-','')
var twoNumbers = substring(resourceSuffix,2,2) // -001 -> 01
var resourceSuffixPlusOne = '-${padLeft(string(int(substring(resourceSuffix,1,3)) + 1), 3, '0')}'

// ============================================================================
// COMPUTED VARIABLES - RBAC Arrays
// ============================================================================

var technicalAdminsObjectID_array = array(split(replace(technicalAdminsObjectID,'\\s+', ''),','))
var p011_genai_team_lead_array = (empty(technicalAdminsObjectID)) ? [] : union(technicalAdminsObjectID_array,[])

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

// Core AI/ML Services
var aiHubName = 'ai-hub-${projectName}-${locationSuffix}-${env}-${uniqueInAIFenv}${resourceSuffix}'
var aifProjectName = 'ai-prj${projectNumber}-01-${locationSuffix}-${env}-${uniqueInAIFenv}${resourceSuffix}'
var aoaiName = 'aoai-${projectName}-${locationSuffix}-${env}-${uniqueInAIFenv}${resourceSuffix}'
var amlName = 'aml-${projectName}-${locationSuffix}-${env}-${uniqueInAIFenv}${resourceSuffix}'
var safeNameAISearch = replace(toLower('aisearch${projectName}${locationSuffix}${env}${uniqueInAIFenv}${resourceSuffix}'), '-', '') // AzureAISearch4prj0025kxmv
var aiServicesName = replace(toLower('aiservices${projectName}${locationSuffix}${env}${uniqueInAIFenv}${randomSalt}${prjResourceSuffixNoDash}'), '-', '') 

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

// AI Foundry
var aifName ='aif-${projectName}-${locationSuffix}-${env}-${uniqueInAIFenv}${resourceSuffix}'
var aifPrjName ='ai-${projectName}-01-${locationSuffix}-${env}-${uniqueInAIFenv}${resourceSuffix}'

// Storage and Keys
var keyvaultName = 'kv-p${projectNumber}-${locationSuffix}-${env}-${uniqueInAIFenv}${twoNumbers}'
var storageAccount1001Name = replace('sa${projectName}${locationSuffix}${uniqueInAIFenv}1${prjResourceSuffixNoDash}${env}', '-', '')
var storageAccount2001Name = replace('sa${projectName}${locationSuffix}${uniqueInAIFenv}2${prjResourceSuffixNoDash}${env}', '-', '')

// Container Registries
var acrProjectName = 'acr${projectName}${genaiName}${locationSuffix}${uniqueInAIFenv}${env}${prjResourceSuffixNoDash}'
var acrCommonName = replace('acrcommon${uniqueInAIFenv}${locationSuffix}${commonResourceSuffix}${env}','-','')

// Managed Identities (with random salt for uniqueness)
var miACAName = 'mi-aca-${projectName}-${locationSuffix}-${env}-${uniqueInAIFenv}${randomSalt}${resourceSuffix}'
var miPrjName = 'mi-${projectName}-${locationSuffix}-${env}-${uniqueInAIFenv}${randomSalt}${resourceSuffix}'

// Common Resource Group Services
var laWorkspaceName = 'la-${cmnName}-${locationSuffix}-${env}-${uniqueInAIFenv}${commonResourceSuffix}'

// AIFoundry2025
var aif2025ProjectName = 'aif-${projectName}-${locationSuffix}-${env}-${uniqueInAIFenv}${commonResourceSuffix}'

// ============================================================================
// COMPUTED VARIABLES - Networking subnets
// ============================================================================
var segments = split(genaiSubnetId, '/')
var genaiSubnetName = segments[length(segments) - 1] // Get the last segment, which is the subnet name
var defaultSubnet = genaiSubnetName
var segmentsAKS = split(aksSubnetId, '/')
var aksSubnetName = segmentsAKS[length(segmentsAKS) - 1] // Get the last segment, which is the subnet name
var segmentsACA = split(acaSubnetId, '/')
var acaSubnetName = segmentsACA[length(segmentsACA) - 1] // Get the last segment, which is the subnet name


// ============== OUTPUTS ==============

// Subnets
output genaiSubnetName string = genaiSubnetName
output aksSubnetName string = aksSubnetName
output acaSubnetName string = acaSubnetName
output defaultSubnet string = defaultSubnet

// Core AI/ML Services
output aiHubName string = aiHubName
output aifProjectName string = aifProjectName
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

// AI Foundry
output aifName string = aifName
output aifPrjName string = aifPrjName

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

// AI Foundry 2025-08->
output aif2025ProjectName string = aif2025ProjectName

// Helper variables
output projectName string = projectName
output cmnName string = cmnName
output kvNameCommon string = 'kv-${cmnName}${env}-${uniqueInAIFenv}${commonResourceSuffix}'
output genaiName string = genaiName
output prjResourceSuffixNoDash string = prjResourceSuffixNoDash
output twoNumbers string = twoNumbers
output p011_genai_team_lead_array array = p011_genai_team_lead_array
output p011_genai_team_lead_email_array array = p011_genai_team_lead_email_array
output uniqueInAIFenv string = uniqueInAIFenv
output randomSalt string = randomSalt
output projectTypeESMLName string = 'esml'
output projectTypeGenAIName string = 'genai'
output aksClusterName string = 'esml${projectNumber}-${locationSuffix}-${env}'

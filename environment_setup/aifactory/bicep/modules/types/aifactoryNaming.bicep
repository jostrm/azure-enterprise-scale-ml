// ================================================================
// AI FACTORY NAMING TYPES
// This module defines the type structure for AI Factory naming outputs
// Import this to get type safety when using naming convention results
// ================================================================

@export()
type aifactoryNamingType = {
  // Subnets
  genaiSubnetName: string
  aksSubnetName: string
  acaSubnetName: string
  defaultSubnet: string

  // AI Foundry V1 (2023-2025)
  aifV1HubName: string
  aifV1ProjectName: string
  // AI Foundry V2 (2025-)
  aifV2Name: string
  aifV2PrjName: string

  aoaiName: string
  amlName: string
  safeNameAISearch: string
  aiServicesName: string

  // Monitoring and Insights
  dashboardInsightsName: string
  applicationInsightName: string
  applicationInsightName2: string

  // External Services
  bingName: string

  // Container Apps
  containerAppsEnvName: string
  containerAppAName: string
  containerAppWName: string

  // Databases
  cosmosDBName: string
  redisName: string
  postgreSQLName: string
  sqlServerName: string
  sqlDBName: string

  // Compute Services
  functionAppName: string
  webAppName: string
  funcAppServicePlanName: string
  webbAppServicePlanName: string
  vmName: string

  // Storage and Keys
  keyvaultName: string
  storageAccount1001Name: string
  storageAccount2001Name: string

  // Container Registries
  acrProjectName: string
  acrCommonName: string

  // Managed Identities
  miACAName: string
  miPrjName: string

  // Common Resource Group Services
  laWorkspaceName: string
  
  // Helper variables
  projectName: string
  cmnName: string
  kvNameCommon: string
  genaiName: string
  prjResourceSuffixNoDash: string
  twoNumbers: string
  p011_genai_team_lead_array: array
  p011_genai_team_lead_email_array: array
  uniqueInAIFenv: string
  randomSalt: string
  projectTypeESMLName: string
  projectTypeGenAIName: string
  aksClusterName: string
}

@export()
type aifactoryNamingInput = {
  env: 'dev' | 'test' | 'prod'
  projectNumber: string
  locationSuffix: string
  commonResourceSuffix: string
  resourceSuffix: string
  aifactorySalt10char: string
  randomValue: string
  aifactorySuffixRG: string
  commonRGNamePrefix: string
  technicalAdminsObjectID: string
  technicalAdminsEmail: string
  commonResourceGroupName: string
  subscriptionIdDevTestProd: string
  genaiSubnetId: string
  aksSubnetId: string
  acaSubnetId: string
  adfName: string
}

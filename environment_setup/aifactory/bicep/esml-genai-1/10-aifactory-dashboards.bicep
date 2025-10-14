// ============================================================================
// AI Factory - Dashboard Deployment (10-aifactory-dashboards.bicep)
// ============================================================================
// This deploys Azure dashboards for the AI Factory project
// Dependencies: 01-foundation.bicep (for resource groups and naming)
// Components: Project dashboard with quick access to resources and services

targetScope = 'subscription'

// ============================================================================
// PARAMETERS - Core Configuration
// ============================================================================

@description('AI Factory version information')
param aifactoryVersionMajor int = 1
param aifactoryVersionMinor int = 22
var activeVersion = 122

@description('Diagnostic setting level for monitoring and logging')
@allowed(['gold', 'silver', 'bronze'])
param diagnosticSettingLevel string = 'silver'

// ============================================================================
// PARAMETERS - Environment & Location
// ============================================================================

@description('Environment: dev, test, or prod')
@allowed(['dev', 'test', 'prod'])
param env string

@description('Azure region location')
param location string

@description('Location suffix (e.g., "weu", "swc")')
param locationSuffix string

@description('Project number (e.g., "005")')
param projectNumber string

// ============================================================================
// PARAMETERS - Resource Groups & Naming
// ============================================================================

@description('Resource group naming')
param commonRGNamePrefix string
param aifactorySuffixRG string
param commonResourceSuffix string
param resourceSuffix string

@description('Common resource configuration')
param commonResourceGroup_param string = ''

@description('Common resource name identifier. Default is "esml-common"')
param commonResourceName string = 'esml-common'

@description('Project prefix for naming')
param projectPrefix string = 'esml-'

@description('Project suffix for naming')
param projectSuffix string = '-rg'

// ============================================================================
// PARAMETERS - RBAC & Security
// ============================================================================

@description('Technical contact information')
param technicalContactId string = ''
param technicalContactEmail string = ''
param technicalAdminsObjectID string = ''
param technicalAdminsEmail string = ''

// ============================================================================
// PARAMETERS - Networking (Required for naming convention)
// ============================================================================

@description('Required subnet IDs from subnet calculator')
param genaiSubnetId string
param aksSubnetId string
param acaSubnetId string = ''

// ============================================================================
// PARAMETERS - Random Values & Salts
// ============================================================================

@description('Random value for unique naming')
param randomValue string = ''

@description('Salt values for random naming')
param aifactorySalt10char string = ''

// ============================================================================
// PARAMETERS - Tags
// ============================================================================

@description('Resource tags')
param tags object = {}
param tagsProject object = {}

// ============================================================================
// COMPUTED VARIABLES
// ============================================================================

var subscriptionIdDevTestProd = subscription().subscriptionId
var projectName = 'prj${projectNumber}'
var commonResourceGroup = !empty(commonResourceGroup_param) ? commonResourceGroup_param : '${commonRGNamePrefix}${commonResourceName}-${locationSuffix}-${env}${aifactorySuffixRG}'
var targetResourceGroup = '${commonRGNamePrefix}${projectPrefix}${replace(projectName, 'prj', 'project')}-${locationSuffix}-${env}${aifactorySuffixRG}${projectSuffix}'

// Reference existing resource groups
resource commonResourceGroupRef 'Microsoft.Resources/resourceGroups@2024-07-01' existing = {
  name: commonResourceGroup
  scope: subscription(subscriptionIdDevTestProd)
}

resource projectResourceGroupRef 'Microsoft.Resources/resourceGroups@2024-07-01' existing = {
  name: targetResourceGroup
  scope: subscription(subscriptionIdDevTestProd)
}

// ============================================================================
// MODULE DEPLOYMENTS
// ============================================================================

// Project Dashboard
module projectDashboard '../modules/projectDash01.bicep' = {
  name: '10-dashboard-${projectName}-${uniqueString(projectResourceGroupRef.id)}'
  scope: resourceGroup(subscriptionIdDevTestProd, targetResourceGroup)
  params: {
    // Environment & Location
    env: env
    location: location
    locationSuffix: locationSuffix
    projectNumber: projectNumber
    
    // Naming & Resource Groups
    commonResourceSuffix: commonResourceSuffix
    resourceSuffix: resourceSuffix
    randomValue: randomValue
    aifactorySalt10char: aifactorySalt10char
    aifactorySuffixRG: aifactorySuffixRG
    commonRGNamePrefix: commonRGNamePrefix
    commonResourceGroupName: commonResourceGroup
    subscriptionIdDevTestProd: subscriptionIdDevTestProd
    projectPrefix: projectPrefix
    projectSuffix: projectSuffix
    
    // RBAC & Security
    technicalAdminsObjectID: technicalAdminsObjectID
    technicalAdminsEmail: technicalAdminsEmail
    
    // Networking (Required for naming convention)
    genaiSubnetId: genaiSubnetId
    aksSubnetId: aksSubnetId
    acaSubnetId: acaSubnetId
    
    // Tags
    tags: union(tags, tagsProject, {
      'AI-Factory-Phase': '10-dashboards'
      'AI-Factory-Version': '${aifactoryVersionMajor}.${aifactoryVersionMinor}'
      'Deployment-Type': 'dashboard'
    })
  }
  dependsOn: [
    projectResourceGroupRef
    commonResourceGroupRef
  ]
}

// ============================================================================
// OUTPUTS
// ============================================================================

@description('Dashboard deployment outputs')
output dashboardOutputs object = {
  // Dashboard Information
  dashboardId: projectDashboard.outputs.dashboardId
  dashboardName: projectDashboard.outputs.dashboardName
  dashboardUrl: projectDashboard.outputs.dashboardUrl
  
  // AI Foundry Information
  aiFoundryUrl: projectDashboard.outputs.aiFoundryUrl
  
  // Project Information
  projectName: projectDashboard.outputs.projectName
  projectResourceGroup: targetResourceGroup
  commonResourceGroup: commonResourceGroup
}

@description('Ready for next deployment layer')
output dashboardsComplete bool = true

@description('Dashboard access information')
output dashboardAccess object = {
  portalUrl: projectDashboard.outputs.dashboardUrl
  directAccess: 'Navigate to Azure Portal > Dashboards > ${projectDashboard.outputs.dashboardName}'
  description: 'Project dashboard with quick access to AI Factory resources and services'
}

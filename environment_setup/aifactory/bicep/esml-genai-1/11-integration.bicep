targetScope = 'subscription'

// ================================================================
// INTEGRATION SERVICES DEPLOYMENT - Phase 11 Implementation
// This file deploys integration and workflow services including:
// - Logic Apps Standard (with BYO ASE v3 support, private networking)
// - Logic App Consumption. No private endpoint support, multi-tenant. Requires additional configuration for the Logic App's Managed Identity access to read secrets from the Key Vault.
// - Event Hub for streaming data integration
// - Network isolation capabilities (ASE v3 vs multitenant)
// - Key Vault integration for secure configuration
// - Application Insights monitoring and telemetry
// - VNet integration and private endpoint support
// Logic Apps Permissions - What Logic Apps needs for keyless authentication:
//✅ Blob access → Storage Blob Data Contributor ✓
//✅ Queue access → Storage Queue Data Contributor ✓
//✅ File share access → Storage File Data SMB Share Contributor ✓
// CMK: Is not supported for these services. But storage, and keyvault for App services packages uses CMK, from other bicep.
// ================================================================

// ============== SKUs ==============
@description('App Service Plan SKU for Logic Apps hosting')
@allowed(['WS1', 'WS2', 'WS3', 'EP1', 'EP2', 'EP3', 'P1V2', 'P2V2', 'P3V2', 'P1V3', 'P2V3', 'P3V3'])
param appServicePlanSku string = 'WS1' // WS1 = Workflow Standard 1, EP = Elastic Premium, PV2/PV3 = Premium V2/V3

@description('Event Hub Namespace SKU tier')
@allowed(['Basic', 'Standard', 'Premium'])
param eventHubSkuTier string = 'Basic'

@description('Event Hub Namespace SKU capacity (throughput units)')
param eventHubSkuCapacity int = 1

@description('Diagnostic setting level for monitoring and logging')
@allowed(['gold', 'silver', 'bronze'])
param diagnosticSettingLevel string = 'silver'

// ============== PARAMETERS ==============
@allowed(['Consumption','Standard'])
param logiAppType string = 'Standard' // Consumption or Standard. Consumption does not support: Private endpoints, VNet integration, Private connectivity

// ASE v3 parameters (BYO - Bring Your Own)
param byoASEv3 bool = false // Optional, default is false. Set to true if you want to deploy ASE v3 instead of Multitenant App Service Plan.
param byoAseFullResourceId string = '' // Full resource ID of App Service Environment
param byoAseAppServicePlanRID string = '' // Full resource ID, default is empty. Set to the App Service Plan ID if you want to deploy ASE v3 instead of Multitenant App Service Plan.

// Runtime parameters for Logic Apps
@allowed([
  'dotnet'
  'node'
  'python'
  'java'
])
param runtime string = 'dotnet' // Logic Apps Standard typically uses dotnet, but can support others
@allowed([
  '3.7'
  '3.8' 
  '3.9'
  '3.10'
  '3.11'
  '3.12'
  // Node.js versions
  '18-lts'
  '20-lts'
  // Java LTS versions
  '8'
  '11'
  '17'
  '21'
  // .NET versions
  'v4.8'
  'v6.0'
  'v7.0'
  'v8.0'
])
param runtimeVersion string = 'v8.0' // Default .NET version for Logic Apps

@description('Environment: dev, test, prod')
@allowed(['dev', 'test', 'prod'])
param env string

@description('Project number (e.g., "005")')
param projectNumber string

@description('Location for all resources')
param location string

@description('Location suffix (e.g., "weu", "sdc")')
param locationSuffix string

@description('Common resource suffix (e.g., "-001")')
param commonResourceSuffix string

@description('Project-specific resource suffix')
param resourceSuffix string

@description('Random salt for unique naming')
param aifactorySalt10char string = ''
param randomValue string

@description('AI Factory suffix for resource groups')
param aifactorySuffixRG string

@description('Subscription ID for dev/test/prod')
param subscriptionIdDevTestProd string

@description('Required subnet IDs from subnet calculator: genai-1')
param genaiSubnetId string
param aksSubnetId string
param acaSubnetId string
@description('Optional subnets from subnet calculator: all')
param aca2SubnetId string = ''
param aks2SubnetId string = ''
@description('if projectype is not genai-1, but instead all')
param dbxPubSubnetName string = ''
param dbxPrivSubnetName string = ''

@description('Technical admins object ID')
param technicalAdminsObjectID string = ''

@description('Technical admins email')
param technicalAdminsEmail string = ''

@description('Enable Logic Apps deployment')
param enableLogicApps bool = false
param enableEventHubs bool = false
@description('Create if not exists')
param logicAppsExists bool = false
param eventHubsExists bool = false
@description('Enable Function App deployment')
param enableFunction bool = false
@description('Enable Web App deployment')
param enableWebApp bool = false
@description('Function App already exists (skip creation)')
param functionAppExists bool = false
@description('Web App already exists (skip creation)')
param webAppExists bool = false
@description('Enable public access with perimeter for Logic Apps')
param enablePublicAccessWithPerimeter bool = false
// Security / access
param centralDnsZoneByPolicyInHub bool = false

// Bot Service parameters
@description('Enable Azure Bot Service deployment')
param enableBotService bool = false
@description('Bot Service already exists (skip creation)')
param botServiceExists bool = false
@description('Microsoft App ID (Client ID) for bot authentication')
param botMicrosoftAppId string = ''
@description('AI Foundry agent endpoint URL for bot messaging')
param botAgentEndpoint string = ''
@description('Bot Service SKU')
@allowed(['F0', 'S1'])
param botServiceSku string = 'F0'

@description('Tags to apply to all resources')
param tags object

@description('Network environment (e.g., dev, test, prod)')
param network_env string = env

@description('VNet name with placeholder for network environment')
param vnetNameFull_param string = ''

@description('Base VNet name when no full name is provided')
param vnetNameBase string = 'vnet-cmn'

@description('VNet resource group name with placeholder for network environment')
param vnetResourceGroup_param string = ''

@description('Add AI Foundry Hub with random naming')
param addAIFoundryHub bool = false
@description('Add Azure Machine Learning with random naming for debugging/testing')
param addAzureMachineLearning bool = false

@description('Common resource group name prefix')
param commonRGNamePrefix string = ''

@description('Project prefix for resource naming')
param projectPrefix string = ''

@description('Project suffix for resource group naming')
param projectSuffix string = resourceSuffix
param useCommonACR bool = true
param useAdGroups bool = false
param commonResourceGroup_param string = ''

@description('Common resource name identifier. Default is "esml-common"')
param commonResourceName string = 'esml-common'

// Tags specific to project (separate from generic tags already present)
param tagsProject object = {}

// IP Whitelist (comma separated) for AML studio / scoring endpoints
param IPwhiteList string = ''

// Key Vault seeding / SP linking (needed for spAndMiArray)
@description('Existing Key Vault name containing SP secret for seeding')
param inputKeyvault string
param inputKeyvaultResourcegroup string
param inputKeyvaultSubscription string
@description('Secret name in Key Vault that stores Service Principal ObjectId used for seeding')
param projectServicePrincipleOID_SeedingKeyvaultName string

var projectName = 'prj${projectNumber}'
var cmnName_Static = 'cmn'
#disable-next-line BCP318
var commonResourceGroup = !empty(commonResourceGroup_param) ? commonResourceGroup_param : '${commonRGNamePrefix}${commonResourceName}-${locationSuffix}-${env}${aifactorySuffixRG}'

// ============================================================================
// SPECIAL - Get PRINICPAL ID of existing MI. Needs static name in existing
// ============================================================================
resource commonResourceGroupRef 'Microsoft.Resources/resourceGroups@2024-07-01' existing = {
  name: commonResourceGroup
  scope: subscription(subscriptionIdDevTestProd)
}
#disable-next-line BCP318
var uniqueInAIFenv_Static = substring(uniqueString(commonResourceGroupRef.id), 0, 5)

// ============== VARS ==============
var targetResourceGroup = '${commonRGNamePrefix}${projectPrefix}${replace(projectName, 'prj', 'project')}-${locationSuffix}-${env}${aifactorySuffixRG}${projectSuffix}'
var vnetName = !empty(vnetNameFull_param) ? replace(vnetNameFull_param, '<network_env>', network_env) : '${vnetNameBase}-${locationSuffix}-${env}${commonResourceSuffix}'
var vnetResourceGroupName = !empty(vnetResourceGroup_param)? replace(vnetResourceGroup_param, '<network_env>', network_env) : commonResourceGroup
var eventHubName = 'eh-${projectNumber}-${locationSuffix}-${env}-${uniqueInAIFenv_Static}${resourceSuffix}'
var logicAppsName = 'lapp-${projectNumber}-${locationSuffix}-${env}-${uniqueInAIFenv_Static}${resourceSuffix}'
var botServiceName = 'bot-${projectNumber}-${locationSuffix}-${env}-${uniqueInAIFenv_Static}${resourceSuffix}'
// Azure ML already has built-in job queuing and pipeline orchestration, can handle most ML workload queuing
// var serviceBusName = 'sb-${projectNumber}-${locationSuffix}-${env}-${uniqueInAIFenv_Static}${resourceSuffix}'

// Resource ID for the target virtual network derived from vnetName
var vnetResourceId = resourceId(subscriptionIdDevTestProd, vnetResourceGroupName, 'Microsoft.Network/virtualNetworks', vnetName)

// ASE v3 variables (same pattern as function.bicep)
var aseName = last(split(byoAseFullResourceId, '/')) // Split the resource ID by '/' and take the last segment

// Runtime and kind logic (same pattern as function.bicep)
var appKind = runtime == 'node' || runtime == 'python' || runtime == 'java' ? 'functionapp,workflowapp,linux' : 'functionapp,workflowapp'

// ============== MODULES ==============

// Import naming convention module
module namingConvention '../modules/common/CmnAIfactoryNaming.bicep' = {
  name: take('01-naming-${targetResourceGroup}', 64)
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
    commonResourceGroupName: commonResourceGroup
    commonRGNamePrefix: commonRGNamePrefix
    subscriptionIdDevTestProd: subscriptionIdDevTestProd
    genaiSubnetId: genaiSubnetId
    aksSubnetId: aksSubnetId
    acaSubnetId: acaSubnetId
    aca2SubnetId: aca2SubnetId
    aks2SubnetId: aks2SubnetId
    technicalAdminsObjectID: technicalAdminsObjectID
    technicalAdminsEmail: technicalAdminsEmail
    addAIFoundryHub: addAIFoundryHub
    addAzureMachineLearning: addAzureMachineLearning
  }
}

// Private DNS zones (mirrors phase 06, needed for AML private endpoints)
module CmnZones '../modules/common/CmnPrivateDnsZones.bicep' = {
  name: take('07-getPrivDnsZ-${targetResourceGroup}', 64)
  scope: resourceGroup(subscriptionIdDevTestProd, targetResourceGroup)
  params: {
    location: location
    // Using same RG/subscription as target (adjust if central DNS zone used)
    privDnsResourceGroupName: vnetResourceGroupName
    privDnsSubscription: subscriptionIdDevTestProd
  }
}
var privateLinksDnsZones = CmnZones.outputs.privateLinksDnsZones

// ================== AZURE ML RELATED VARIABLES (exact copy style from 06) ==================
// Random salt for unique naming - using uniqueString for deterministic salt
var randomSalt = substring(uniqueString(subscription().subscriptionId, targetResourceGroup), 0, 5)
var deploymentProjSpecificUniqueSuffix = '${projectName}${env}${randomSalt}'

// Outputs from namingConvention
var miPrjName = namingConvention.outputs.miPrjName
var miACAName = namingConvention.outputs.miACAName
var amlName = namingConvention.outputs.amlName
var laWorkspaceName = namingConvention.outputs.laWorkspaceName
var acrProjectName = namingConvention.outputs.acrProjectName
var acrCommonName = namingConvention.outputs.acrCommonName
var var_acr_cmn_or_prj = useCommonACR ? acrCommonName : acrProjectName
var genaiSubnetName = namingConvention.outputs.genaiSubnetName
var aksSubnetName = namingConvention.outputs.aksSubnetName
var genaiName = namingConvention.outputs.projectTypeGenAIName
var storageAccount1001Name = namingConvention.outputs.storageAccount1001Name
var storageAccount2001Name = namingConvention.outputs.storageAccount2001Name
var keyvaultName = namingConvention.outputs.keyvaultName
var applicationInsightName = namingConvention.outputs.applicationInsightName
var p011_genai_team_lead_array = namingConvention.outputs.p011_genai_team_lead_array

// ============== MODULE DEPLOYMENTS ==============

// 1) Create Hosting plan for Logic Apps Standard, using Azure verfied modules (AVM)
module serverFarm 'br/public:avm/res/web/serverfarm:0.5.0' = if(empty(byoAseAppServicePlanRID) && !logicAppsExists && enableLogicApps) {
  scope: resourceGroup(subscriptionIdDevTestProd, targetResourceGroup)
  name: take('11-Appfarm-LogicApps01-${deploymentProjSpecificUniqueSuffix}', 64)
  params: {
    name: 'appfarm-logicapp01'
    skuName: appServicePlanSku
    // Add ASE integration if provided
    appServiceEnvironmentResourceId: byoASEv3 && !empty(byoAseFullResourceId) ? byoAseFullResourceId : ''
    // Fix elastic worker count issues for Workflow Standard SKUs
    // For WS* SKUs, set capacity and ensure maximumElasticWorkerCount > skuCapacity
    skuCapacity: contains(appServicePlanSku, 'WS') ? 1 : contains(appServicePlanSku, 'EP') ? 1 : 1
    maximumElasticWorkerCount: contains(appServicePlanSku, 'WS') ? 10 : contains(appServicePlanSku, 'EP') ? 20 : null
  }
}

// ============== SUBNET DELEGATIONS ==============

// Subnet delegation for Web Apps and Function Apps

//module subnetDelegationServerFarmLapps '../modules/subnetDelegation.bicep' = if(!logicAppsExists && enableLogicApps && !byoASEv3) {
module subnetDelegationServerFarm '../modules/subnetDelegation.bicep' = if((!logicAppsExists && !functionAppExists && !webAppExists) && ((!enableWebApp && !enableFunction) && enableLogicApps) && !byoASEv3) {
  name: take('11-snetDelegSF1${deploymentProjSpecificUniqueSuffix}', 64)
  scope: resourceGroup(vnetResourceGroupName)
  params: {
    vnetName: vnetName
    subnetName: aksSubnetName // TODO: Have a dedicated subnet for WebApp, FunctionApp, logicAppsExists
    location: location
    vnetResourceGroupName: vnetResourceGroupName
    delegations: [
      {
        name: 'webapp-delegation'
        properties: {
          serviceName: 'Microsoft.Web/serverFarms'
        }
      }
    ]
  }
}

// 2) Use the User assigned managed Identity "miPrjName", they keyvault with name "keyvaultName", "storageAccount1001Name"

module getProjectMIPrincipalId '../modules/get-managed-identity-info.bicep' = {
  name: take('09-getMI-${deploymentProjSpecificUniqueSuffix}', 64)
  scope: resourceGroup(subscriptionIdDevTestProd, targetResourceGroup)
  params: {
    managedIdentityName: miPrjName
  }
}

// Fetch Application Insights from NamingConvention, in same target resource group
module getAppInsightsInfo '../modules/get-appinsights-info.bicep' = {
  name: take('10-getAppInsights-${deploymentProjSpecificUniqueSuffix}', 64)
  scope: resourceGroup(subscriptionIdDevTestProd, targetResourceGroup)
  params: {
    appInsightsName: applicationInsightName
  }
}

// Fetch Log analytics from Common Resource Group
var laName = 'la-${cmnName_Static}-${locationSuffix}-${env}-${uniqueInAIFenv_Static}${commonResourceSuffix}'
resource logAnalyticsWorkspace 'Microsoft.OperationalInsights/workspaces@2020-08-01' existing = {
  name: laName
  scope: commonResourceGroupRef
}

// Event Hub Namespace deployment using Azure verified modules (AVM)
module eventHub 'br/public:avm/res/event-hub/namespace:0.12.5' = if(!eventHubsExists && enableEventHubs) {
  scope: resourceGroup(subscriptionIdDevTestProd, targetResourceGroup)
  name: take('11-EventHub-${deploymentProjSpecificUniqueSuffix}', 64)
  params: {
    // Basic configuration
    name: eventHubName
    location: location
    tags: tags
    
    // SKU configuration
    skuName: eventHubSkuTier
    skuCapacity: eventHubSkuCapacity
    
    // Managed identity configuration (AVM format)
    managedIdentities: {
      systemAssigned: true
      userAssignedResourceIds: miPrjName != '' ? [resourceId(subscriptionIdDevTestProd, targetResourceGroup, 'Microsoft.ManagedIdentity/userAssignedIdentities', miPrjName)] : []
    }
    
    // Network configuration based on perimeter access
    publicNetworkAccess: enablePublicAccessWithPerimeter ? 'Enabled' : 'Disabled'
    
    // Private endpoint configuration (only if public access is disabled)
    privateEndpoints: enablePublicAccessWithPerimeter ? [] : [
      {
        name: '${eventHubName}-pend'
        customNetworkInterfaceName: '${eventHubName}-pend-nic'
        subnetResourceId: resourceId(subscriptionIdDevTestProd, vnetResourceGroupName, 'Microsoft.Network/virtualNetworks/subnets', vnetName, genaiSubnetName)
        privateDnsZoneResourceIds: [
          privateLinksDnsZones.namespace
        ]
        tags: tags
      }
    ]
    
    // Event Hubs to create within the namespace
    eventhubs: [
      {
        name: 'eh-ml-data-streaming'
        messageRetentionInDays: 1
        partitionCount: 2
        consumerGroups: [
          {
            name: 'ml-processors'
          }
          {
            name: 'analytics-consumers'
          }
        ]
      }
      {
        name: 'eh-genai-events'
        messageRetentionInDays: 1
        partitionCount: 2
        consumerGroups: [
          {
            name: 'genai-processors'
          }
        ]
      }
    ]
    
    // Authorization rules for access management
    authorizationRules: [
      {
        name: 'RootManageSharedAccessKey'
        rights: [
          'Listen'
          'Manage'
          'Send'
        ]
      }
      {
        name: 'SendOnlyKey'
        rights: [
          'Send'
        ]
      }
      {
        name: 'ListenOnlyKey'
        rights: [
          'Listen'
        ]
      }
    ]
    
    // Network rule set (only if public access is enabled with perimeter)
    networkRuleSets: enablePublicAccessWithPerimeter ? {
      defaultAction: 'Deny'
      ipRules: !empty(IPwhiteList) ? map(split(IPwhiteList, ','), ip => {
        ipMask: trim(ip)
        action: 'Allow'
      }) : []
      virtualNetworkRules: [
        {
          subnetResourceId: resourceId(subscriptionIdDevTestProd, vnetResourceGroupName, 'Microsoft.Network/virtualNetworks/subnets', vnetName, genaiSubnetName)
          ignoreMissingVnetServiceEndpoint: false
        }
      ]
    } : null
    
    // Diagnostic settings
    diagnosticSettings: [
      {
        name: 'eventHubDiagnostics'
        logAnalyticsDestinationType: 'Dedicated'
        workspaceResourceId: logAnalyticsWorkspace.id
        logCategoriesAndGroups: [
          {
            categoryGroup: 'allLogs'
            enabled: true
          }
        ]
        metricCategories: [
          {
            category: 'AllMetrics'
            enabled: true
          }
        ]
      }
    ]
  }
  dependsOn: [
    namingConvention
    CmnZones
  ]
}

// Logic App Consumption has a separate module in Azure Bicep Verified Modules
// For Logic App Standard, there is no such different resource since it’s defined as a “site” with a specific kind: ‘functionapp,workflowapp’.
module logicAppStandard 'br/public:avm/res/web/site:0.19.3' = if(logiAppType == 'Standard' && !logicAppsExists && enableLogicApps) {
  scope: resourceGroup(subscriptionIdDevTestProd, targetResourceGroup)
  name: take('11-LogicApps01-${deploymentProjSpecificUniqueSuffix}', 64)
  params: {
    // Basic configuration
    name: logicAppsName
    location: location
    kind: appKind
    tags: tags
    
    // Server farm configuration
    serverFarmResourceId: !empty(byoAseAppServicePlanRID) ? byoAseAppServicePlanRID : serverFarm!.outputs.resourceId
    
    // Managed identity configuration (AVM format)
    managedIdentities: {
      systemAssigned: true
      userAssignedResourceIds: miPrjName != '' ? [resourceId(subscriptionIdDevTestProd, targetResourceGroup, 'Microsoft.ManagedIdentity/userAssignedIdentities', miPrjName)] : []
    }
    
    // App configuration using correct AVM configs structure
    configs: [
      {
        name: 'appsettings'
        properties: {
          AzureWebJobsStorage__accountName: storageAccount1001Name
          AzureWebJobsStorage__blobServiceUri: 'https://${storageAccount1001Name}.blob.${environment().suffixes.storage}'
          AzureWebJobsStorage__queueServiceUri: 'https://${storageAccount1001Name}.queue.${environment().suffixes.storage}'
          AzureWebJobsStorage__credential: 'managedidentity'
          AzureWebJobsStorage__clientId: getProjectMIPrincipalId.outputs.clientId
          APP_KIND: 'workflowapp'
          WEBSITE_CONTENTAZUREFILECONNECTIONSTRING: 'DefaultEndpointsProtocol=https;AccountName=${storageAccount1001Name};EndpointSuffix=${environment().suffixes.storage};AccountKey='
          WEBSITE_CONTENTAZUREFILECONNECTIONSTRING__accountName: storageAccount1001Name
          WEBSITE_CONTENTAZUREFILECONNECTIONSTRING__credential: 'managedidentity'
          WEBSITE_CONTENTAZUREFILECONNECTIONSTRING__clientId: getProjectMIPrincipalId.outputs.clientId
          WEBSITE_CONTENTSHARE: '${logicAppsName}-content'
          WEBSITE_SKIP_CONTENTSHARE_VALIDATION: '1'
          FUNCTIONS_EXTENSION_VERSION: '~4'
          FUNCTIONS_WORKER_RUNTIME: runtime == 'dotnet' ? 'dotnet-isolated' : runtime
          WEBSITE_RUN_FROM_PACKAGE: '1'
          APPINSIGHTS_INSTRUMENTATIONKEY: getAppInsightsInfo.outputs.instrumentationKey
          APPLICATIONINSIGHTS_CONNECTION_STRING: getAppInsightsInfo.outputs.connectionString
          KeyVaultName: keyvaultName
          StorageAccountName: storageAccount1001Name
          EventHubNamespace: eventHubName
          AmlWorkspaceName: amlName
          AcrName: var_acr_cmn_or_prj
          GENAI_SUBNET_NAME: genaiSubnetName
          AKS_SUBNET_NAME: aksSubnetName
          VNetResourceGroupName: vnetResourceGroupName
          VNetName: vnetName
          // Runtime-specific settings (conditional based on function.bicep pattern)
          ...(runtime == 'python' ? {
            ENABLE_ORYX_BUILD: 'true'
            SCM_DO_BUILD_DURING_DEPLOYMENT: 'true'
          } : {})
        }
      }
      {
        name: 'web'
        properties: {
          http20Enabled: true
          ftpsState: 'Disabled'
          minimumElasticInstanceCount: 1
          preWarmedInstanceCount: 1
          alwaysOn: true
          linuxFxVersion: runtime == 'python' ? 'PYTHON|${runtimeVersion}' : runtime == 'node' ? 'NODE|${runtimeVersion}' : runtime == 'java' ? 'JAVA|${runtimeVersion}' : ''
          netFrameworkVersion: runtime == 'dotnet' ? runtimeVersion : null
        }
      }
    ]
    
    // Network and security configuration
    httpsOnly: true
    publicNetworkAccess: byoASEv3 ? 'Disabled' : (enablePublicAccessWithPerimeter ? 'Enabled' : 'Disabled')
    
    // Private endpoint configuration (only if public access is disabled and not using ASE v3)
    privateEndpoints: (byoASEv3 || enablePublicAccessWithPerimeter) ? [] : [
      {
        name: '${logicAppsName}-pend'
        customNetworkInterfaceName: '${logicAppsName}-pend-nic'
        subnetResourceId: resourceId(subscriptionIdDevTestProd, vnetResourceGroupName, 'Microsoft.Network/virtualNetworks/subnets', vnetName, genaiSubnetName)
        privateDnsZoneResourceIds: [
          privateLinksDnsZones.azurewebapps
        ]
        tags: tags
      }
    ]
    
    // VNet integration (only if not using ASE v3)
    virtualNetworkSubnetResourceId: byoASEv3 ? '' : (enablePublicAccessWithPerimeter ? '' : resourceId(subscriptionIdDevTestProd, vnetResourceGroupName, 'Microsoft.Network/virtualNetworks/subnets', vnetName, aksSubnetName))
  }
  dependsOn: [
    serverFarm
    namingConvention
    subnetDelegationServerFarm
  ]
}

// ============== STORAGE ROLE ASSIGNMENTS ==============
// Logic Apps uses both user-assigned and system-assigned managed identities
// Assign storage roles to both for maximum compatibility and to prevent 403 Forbidden errors

// Get the deployed Logic Apps resource to access its system-assigned identity
resource deployedLogicApp 'Microsoft.Web/sites@2023-12-01' existing = if (logiAppType == 'Standard' && !logicAppsExists && enableLogicApps) {
  name: logicAppsName
  scope: resourceGroup(subscriptionIdDevTestProd, targetResourceGroup)
}

// Assign storage roles to user-assigned managed identity (primary authentication method)
module logicAppsStorageRolesUserMI '../modules/storageRoleAssignments.bicep' = if (logiAppType == 'Standard' && !logicAppsExists && enableLogicApps) {
  scope: resourceGroup(subscriptionIdDevTestProd, targetResourceGroup)
  name: take('11-LogicAppsStorageRoles-UserMI-${deploymentProjSpecificUniqueSuffix}', 64)
  params: {
    storageAccountName: storageAccount1001Name
    principalId: getProjectMIPrincipalId.outputs.principalId
  }
  dependsOn: [
    logicAppStandard
    getProjectMIPrincipalId
  ]
}

// Assign storage roles to system-assigned managed identity (fallback/redundancy)
module logicAppsStorageRolesSystemMI '../modules/storageRoleAssignments.bicep' = if (logiAppType == 'Standard' && !logicAppsExists && enableLogicApps) {
  scope: resourceGroup(subscriptionIdDevTestProd, targetResourceGroup)
  name: take('11-LogicAppsStorageRoles-SystemMI-${deploymentProjSpecificUniqueSuffix}', 64)
  params: {
    storageAccountName: storageAccount1001Name
    principalId: deployedLogicApp!.identity.principalId
  }
  dependsOn: [
    logicAppStandard
    deployedLogicApp
  ]
}

// Logic Apps Consumption is a serverless, multi-tenant service that doesn't support VNet integration or private endpoints. If you need private connectivity, you would need to use Logic Apps Standard instead.
// Does not support: Private endpoints, VNet integration, Private connectivity
module logicAppConsumption 'br/public:avm/res/logic/workflow:0.5.3' = if(logiAppType == 'Consumption' && !logicAppsExists && enableLogicApps) {
  scope: resourceGroup(subscriptionIdDevTestProd, targetResourceGroup)
  name: take('11-LogicAppsConsumption-${deploymentProjSpecificUniqueSuffix}', 64)
  params: {
    // Basic configuration
    name: logicAppsName
    location: location
    tags: tags
    
    // Managed identity configuration (AVM format)
    managedIdentities: {
      systemAssigned: true
      userAssignedResourceIds: miPrjName != '' ? [resourceId(subscriptionIdDevTestProd, targetResourceGroup, 'Microsoft.ManagedIdentity/userAssignedIdentities', miPrjName)] : []
    }
    
    // Workflow parameters for integration with other services
    workflowParameters: {
      KeyVaultName: {
        type: 'string'
        defaultValue: keyvaultName
      }
      StorageAccountName: {
        type: 'string'
        defaultValue: storageAccount1001Name
      }
      EventHubNamespace: {
        type: 'string'
        defaultValue: eventHubName
      }
      AmlWorkspaceName: {
        type: 'string'
        defaultValue: amlName
      }
      AcrName: {
        type: 'string'
        defaultValue: var_acr_cmn_or_prj
      }
      VNetResourceGroupName: {
        type: 'string'
        defaultValue: vnetResourceGroupName
      }
      VNetName: {
        type: 'string'
        defaultValue: vnetName
      }
    }
    
    // Workflow triggers
    workflowTriggers: {
      manual: {
        type: 'Request'
        kind: 'Http'
        inputs: {
          schema: {}
        }
      }
    }
    
    // Workflow actions
    workflowActions: {
      Response: {
        type: 'Response'
        kind: 'Http'
        inputs: {
          statusCode: 200
          body: {
            message: 'Logic App Consumption workflow is ready'
            timestamp: '@{utcNow()}'
            keyVault: '@parameters(\'KeyVaultName\')'
            storage: '@parameters(\'StorageAccountName\')'
            eventHub: '@parameters(\'EventHubNamespace\')'
            amlWorkspace: '@parameters(\'AmlWorkspaceName\')'
            containerRegistry: '@parameters(\'AcrName\')'
            vnetRG: '@parameters(\'VNetResourceGroupName\')'
            vnetName: '@parameters(\'VNetName\')'
          }
        }
        runAfter: {}
      }
    }
    
    // Workflow outputs
    workflowOutputs: {}
    
    // Access control configuration for triggers
    triggersAccessControlConfiguration: enablePublicAccessWithPerimeter ? {} : {
      allowedCallerIpAddresses: [
        {
          addressRange: '0.0.0.0/0'  // Configure IP restrictions as needed
        }
      ]
    }
    
    // Integration account (optional - can be configured later)
    // integrationAccount: {
    //   id: 'integrationAccountResourceId'
    // }
    
    // State (enabled by default)
    state: 'Enabled'
  }
  dependsOn: [
    namingConvention
  ]
}

// ============================================================================
// AZURE BOT SERVICE - for Microsoft Teams integration with AI Foundry agents
// ============================================================================
module botService '../modules/botService.bicep' = if(!botServiceExists && enableBotService) {
  name: take('11-bot-${targetResourceGroup}', 64)
  scope: resourceGroup(subscriptionIdDevTestProd, targetResourceGroup)
  params: {
    botName: botServiceName
    botDisplayName: 'AI Agent Bot - ${projectNumber}'
    botDescription: 'AI Foundry Agent integrated with Microsoft Teams for ${env} environment'
    location: location
    sku: botServiceSku
    // Leave empty to auto-create managed identity (UserAssignedMSI), or pass AI Foundry agent's App ID (SingleTenant)
    microsoftAppId: botMicrosoftAppId
    microsoftAppType: empty(botMicrosoftAppId) ? 'UserAssignedMSI' : 'SingleTenant'
    microsoftAppTenantId: tenant().tenantId
    userAssignedManagedIdentityResourceId: '' // Auto-create if empty
    agentEndpoint: botAgentEndpoint
    messagingEndpoint: botAgentEndpoint
    tags: tags
    enableTeamsChannel: true
    enableDirectLineChannel: true
    enableWebChatChannel: true
    logAnalyticsWorkspaceId: logAnalyticsWorkspace.id
    diagnosticSettingLevel: diagnosticSettingLevel
    isStreamingSupported: false
  }
  dependsOn: [
    namingConvention
    logAnalyticsWorkspace
  ]
}

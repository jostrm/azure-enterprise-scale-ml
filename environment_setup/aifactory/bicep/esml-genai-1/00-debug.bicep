param location string = ''
param debug_vnetId string = ''
param projectName string = ''
param projectNumber string = ''
param env string = ''
param locationSuffix string = ''
param commonResourceGroup string = ''
param targetResourceGroup string = ''
param vnetNameFull string = ''
param vnetResourceGroupName string = ''
param common_subnet_name_local string = ''
param genaiSubnetId string = ''
param genaiSubnetName string = ''
param defaultSubnet string = ''
param aksSubnetId string = ''
param aksSubnetName string = ''
param subscriptions_subscriptionId string = ''
param vnetRule1 string = ''
param vnetRule2 string = ''
param postGreSQLExists bool = false
param keyvaultExists bool = false
param aiSearchExists bool = false

// DEBUG Parameters - All optional with default values
@description('Enable AI Services')
param DEBUG_enableAIServices bool = false

@description('Enable AI Foundry Hub')
param DEBUG_enableAIFoundryHub bool = false

@description('Enable AI Search')
param DEBUG_enableAISearch bool = false

@description('Enable Azure Machine Learning')
param DEBUG_enableAzureMachineLearning bool = false

@description('Deploy Function App')
param DEBUG_serviceSettingDeployFunction bool = true

@description('Function runtime')
param DEBUG_functionRuntime string = 'dotnet'

@description('Function version')
param DEBUG_functionVersion string = 'v7.0'

@description('Deploy Web App')
param DEBUG_serviceSettingDeployWebApp bool = true

@description('Web App runtime')
param DEBUG_webAppRuntime string = 'python'

@description('Web App runtime version')
param DEBUG_webAppRuntimeVersion string = '3.11'

@description('App Service Environment SKU')
param DEBUG_aseSku string = 'IsolatedV2'

@description('App Service Environment SKU Code')
param DEBUG_aseSkuCode string = 'I1v2'

@description('App Service Environment SKU Workers')
param DEBUG_aseSkuWorkers int = 1

@description('Deploy Container Apps')
param DEBUG_serviceSettingDeployContainerApps bool = false

@description('Deploy App Insights Dashboard')
param DEBUG_serviceSettingDeployAppInsightsDashboard bool = false

@description('Container Apps API registry image')
param DEBUG_aca_a_registry_image string = 'containerapps-default:latest'

@description('Container Apps Web registry image')
param DEBUG_aca_w_registry_image string = 'mcr.microsoft.com/azuredocs/containerapps-helloworld:latest'

@description('Deploy Bing Search')
param DEBUG_serviceSettingDeployBingSearch bool = false

@description('Deploy Cosmos DB')
param DEBUG_serviceSettingDeployCosmosDB bool = false

@description('Deploy Azure OpenAI')
param DEBUG_serviceSettingDeployAzureOpenAI bool = false

@description('Deploy Azure AI Vision')
param DEBUG_serviceSettingDeployAzureAIVision bool = false

@description('Deploy Azure Speech')
param DEBUG_serviceSettingDeployAzureSpeech bool = false

@description('Deploy AI Document Intelligence')
param DEBUG_serviceSettingDeployAIDocIntelligence bool = false

@description('Disable Contributor Access for Users')
param DEBUG_disableContributorAccessForUsers bool = false

@description('Deploy PostgreSQL')
param DEBUG_serviceSettingDeployPostgreSQL bool = false

@description('Deploy Redis Cache')
param DEBUG_serviceSettingDeployRedisCache bool = false

@description('Deploy SQL Database')
param DEBUG_serviceSettingDeploySQLDatabase bool = false

@description('Bring Your Own subnets - false means use default subnets created by pipeline')
param DEBUG_BYO_subnets bool = false

@description('Network environment prefix for dev - empty string if BYO_subnets is false')
param DEBUG_network_env_dev string = 'tst-'

@description('Network environment prefix for stage')
param DEBUG_network_env_stage string = 'tst2-'

@description('Network environment prefix for prod')
param DEBUG_network_env_prod string = 'prd-'

@description('VNet Resource Group parameter - BYOVNET example: esml-common-eus2-<network_env>001-rg')
param DEBUG_vnetResourceGroup_param string = ''

@description('VNet Name Full parameter')
param DEBUG_vnetNameFull_param string = ''

@description('Common Resource Group parameter')
param DEBUG_commonResourceGroup_param string = ''

@description('Data Lake Name parameter')
param DEBUG_datalakeName_param string = ''

@description('Key Vault Name from COMMON parameter')
param DEBUG_kvNameFromCOMMON_param string = ''

@description('Use Common ACR override')
param DEBUG_useCommonACR_override bool = true

@description('Subnet Common')
param DEBUG_subnetCommon string = ''

@description('Subnet Common Scoring')
param DEBUG_subnetCommonScoring string = ''

@description('Subnet Common Power BI Gateway')
param DEBUG_subnetCommonPowerbiGw string = ''

@description('Subnet Project GenAI')
param DEBUG_subnetProjGenAI string = ''

@description('Subnet Project AKS')
param DEBUG_subnetProjAKS string = ''

@description('Subnet Project ACA')
param DEBUG_subnetProjACA string = ''

@description('Subnet Project Databricks Public')
param DEBUG_subnetProjDatabricksPublic string = ''

@description('Subnet Project Databricks Private')
param DEBUG_subnetProjDatabricksPrivate string = ''

@description('Bring Your Own ASE v3')
param DEBUG_byoASEv3 bool = false

@description('BYO ASE Full Resource ID')
param DEBUG_byoAseFullResourceId string = ''

@description('BYO ASE App Service Plan Resource ID')
param DEBUG_byoAseAppServicePlanResourceId string = ''

@description('Enable Public GenAI Access')
param DEBUG_enablePublicGenAIAccess bool = false

@description('Allow Public Access When Behind VNet')
param DEBUG_allowPublicAccessWhenBehindVnet bool = false

@description('Enable Public Access With Perimeter')
param DEBUG_enablePublicAccessWithPerimeter bool = false

@description('Admin AI Factory Suffix RG')
param DEBUG_admin_aifactorySuffixRG string = '-008'

@description('Admin Common Resource Suffix')
param DEBUG_admin_commonResourceSuffix string = '-001'

@description('Admin Project Resource Suffix')
param DEBUG_admin_prjResourceSuffix string = '-001'

@description('AI Factory Salt')
param DEBUG_aifactory_salt string = ''

@description('Admin Project Type')
param DEBUG_admin_projectType string = 'genai-1'

@description('Project Number 000')
param DEBUG_project_number_000 string = '001'

@description('Project Service Principal App ID Seeding KV Name')
param DEBUG_project_service_principal_AppID_seeding_kv_name string = 'esml-project001-sp-id'

@description('Project Service Principal OID Seeding KV Name')
param DEBUG_project_service_principal_OID_seeding_kv_name string = 'esml-project001-sp-oid'

@description('Project Service Principal Secret Seeding KV Name')
param DEBUG_project_service_principal_Secret_seeding_kv_name string = 'esml-project001-sp-secret'

@description('Project IP Whitelist')
param DEBUG_project_IP_whitelist string = ''

@description('Deploy Model GPT-4')
param DEBUG_deployModel_gpt_4 bool = false

@description('Deploy Model Text Embedding Ada 002')
param DEBUG_deployModel_text_embedding_ada_002 bool = false

@description('Deploy Model Text Embedding 3 Large')
param DEBUG_deployModel_text_embedding_3_large bool = false

@description('Deploy Model Text Embedding 3 Small')
param DEBUG_deployModel_text_embedding_3_small bool = false

@description('Deploy Model GPT-4o Mini')
param DEBUG_deployModel_gpt_4o_mini bool = false

@description('Input Key Vault name')
param DEBUG_inputKeyvault string = ''

@description('Input Key Vault Resource Group')
param DEBUG_inputKeyvaultResourcegroup string = ''

@description('Input Key Vault Subscription')
param DEBUG_inputKeyvaultSubscription string = ''

// Use this in a resource description or as a dummy resource to see the values
resource dummyResource 'Microsoft.Resources/deploymentScripts@2020-10-01' = {
  name: 'debugScript'
  location: location
  kind: 'AzurePowerShell'
  properties: {
    azPowerShellVersion: '11.0'
    // Pass the parameters as environment variables instead of trying to interpolate them in the script
    environmentVariables: [
      {
        name: 'DEBUG_VNET_ID'
        value: debug_vnetId
      }
      {
        name: 'PROJECT_NAME'
        value: projectName
      }
      {
        name: 'PROJECT_NUMBER'
        value: projectNumber
      }
      {
        name: 'ENV_NAME'
        value: env
      }
      {
        name: 'LOCATION_SUFFIX'
        value: locationSuffix
      }
      {
        name: 'COMMON_RG'
        value: commonResourceGroup
      }
      {
        name: 'TARGET_RG'
        value: targetResourceGroup
      }
      {
        name: 'VNET_NAME_FULL'
        value: vnetNameFull
      }
      {
        name: 'VNET_RG_NAME'
        value: vnetResourceGroupName
      }
      {
        name: 'COMMON_SUBNET_NAME'
        value: common_subnet_name_local
      }
      {
        name: 'GENAI_SUBNET_ID'
        value: genaiSubnetId
      }
      {
        name: 'GENAI_SUBNET_NAME'
        value: genaiSubnetName
      }
      {
        name: 'DEFAULT_SUBNET'
        value: defaultSubnet
      }
      {
        name: 'AKS_SUBNET_ID'
        value: aksSubnetId
      }
      {
        name: 'AKS_SUBNET_NAME'
        value: aksSubnetName
      }
      {
        name: 'SUBSCRIPTION_ID'
        value: subscriptions_subscriptionId
      }
      {
        name: 'VNET_RULE_1'
        value: vnetRule1
      }
      {
        name: 'VNET_RULE_2'
        value: vnetRule2
      }
      {
        name: 'postGreSQLExists'
        value: postGreSQLExists ? 'true' : 'false'
      }
      {
        name: 'keyvaultExists'
        value: keyvaultExists ? 'true' : 'false'
      }
      {
        name: 'aiSearchExists'
        value: aiSearchExists ? 'true' : 'false'
      }
      // DEBUG Parameters
      {
        name: 'DEBUG_enableAIServices'
        value: DEBUG_enableAIServices ? 'true' : 'false'
      }
      {
        name: 'DEBUG_enableAIFoundryHub'
        value: DEBUG_enableAIFoundryHub ? 'true' : 'false'
      }
      {
        name: 'DEBUG_enableAISearch'
        value: DEBUG_enableAISearch ? 'true' : 'false'
      }
      {
        name: 'DEBUG_enableAzureMachineLearning'
        value: DEBUG_enableAzureMachineLearning ? 'true' : 'false'
      }
      {
        name: 'DEBUG_serviceSettingDeployFunction'
        value: DEBUG_serviceSettingDeployFunction ? 'true' : 'false'
      }
      {
        name: 'DEBUG_functionRuntime'
        value: DEBUG_functionRuntime
      }
      {
        name: 'DEBUG_functionVersion'
        value: DEBUG_functionVersion
      }
      {
        name: 'DEBUG_serviceSettingDeployWebApp'
        value: DEBUG_serviceSettingDeployWebApp ? 'true' : 'false'
      }
      {
        name: 'DEBUG_webAppRuntime'
        value: DEBUG_webAppRuntime
      }
      {
        name: 'DEBUG_webAppRuntimeVersion'
        value: DEBUG_webAppRuntimeVersion
      }
      {
        name: 'DEBUG_aseSku'
        value: DEBUG_aseSku
      }
      {
        name: 'DEBUG_aseSkuCode'
        value: DEBUG_aseSkuCode
      }
      {
        name: 'DEBUG_aseSkuWorkers'
        value: string(DEBUG_aseSkuWorkers)
      }
      {
        name: 'DEBUG_serviceSettingDeployContainerApps'
        value: DEBUG_serviceSettingDeployContainerApps ? 'true' : 'false'
      }
      {
        name: 'DEBUG_serviceSettingDeployAppInsightsDashboard'
        value: DEBUG_serviceSettingDeployAppInsightsDashboard ? 'true' : 'false'
      }
      {
        name: 'DEBUG_aca_a_registry_image'
        value: DEBUG_aca_a_registry_image
      }
      {
        name: 'DEBUG_aca_w_registry_image'
        value: DEBUG_aca_w_registry_image
      }
      {
        name: 'DEBUG_serviceSettingDeployBingSearch'
        value: DEBUG_serviceSettingDeployBingSearch ? 'true' : 'false'
      }
      {
        name: 'DEBUG_serviceSettingDeployCosmosDB'
        value: DEBUG_serviceSettingDeployCosmosDB ? 'true' : 'false'
      }
      {
        name: 'DEBUG_serviceSettingDeployAzureOpenAI'
        value: DEBUG_serviceSettingDeployAzureOpenAI ? 'true' : 'false'
      }
      {
        name: 'DEBUG_serviceSettingDeployAzureAIVision'
        value: DEBUG_serviceSettingDeployAzureAIVision ? 'true' : 'false'
      }
      {
        name: 'DEBUG_serviceSettingDeployAzureSpeech'
        value: DEBUG_serviceSettingDeployAzureSpeech ? 'true' : 'false'
      }
      {
        name: 'DEBUG_serviceSettingDeployAIDocIntelligence'
        value: DEBUG_serviceSettingDeployAIDocIntelligence ? 'true' : 'false'
      }
      {
        name: 'DEBUG_disableContributorAccessForUsers'
        value: DEBUG_disableContributorAccessForUsers ? 'true' : 'false'
      }
      {
        name: 'DEBUG_serviceSettingDeployPostgreSQL'
        value: DEBUG_serviceSettingDeployPostgreSQL ? 'true' : 'false'
      }
      {
        name: 'DEBUG_serviceSettingDeployRedisCache'
        value: DEBUG_serviceSettingDeployRedisCache ? 'true' : 'false'
      }
      {
        name: 'DEBUG_serviceSettingDeploySQLDatabase'
        value: DEBUG_serviceSettingDeploySQLDatabase ? 'true' : 'false'
      }
      {
        name: 'DEBUG_BYO_subnets'
        value: DEBUG_BYO_subnets ? 'true' : 'false'
      }
      {
        name: 'DEBUG_network_env_dev'
        value: DEBUG_network_env_dev
      }
      {
        name: 'DEBUG_network_env_stage'
        value: DEBUG_network_env_stage
      }
      {
        name: 'DEBUG_network_env_prod'
        value: DEBUG_network_env_prod
      }
      {
        name: 'DEBUG_vnetResourceGroup_param'
        value: DEBUG_vnetResourceGroup_param
      }
      {
        name: 'DEBUG_vnetNameFull_param'
        value: DEBUG_vnetNameFull_param
      }
      {
        name: 'DEBUG_commonResourceGroup_param'
        value: DEBUG_commonResourceGroup_param
      }
      {
        name: 'DEBUG_datalakeName_param'
        value: DEBUG_datalakeName_param
      }
      {
        name: 'DEBUG_kvNameFromCOMMON_param'
        value: DEBUG_kvNameFromCOMMON_param
      }
      {
        name: 'DEBUG_useCommonACR_override'
        value: DEBUG_useCommonACR_override ? 'true' : 'false'
      }
      {
        name: 'DEBUG_subnetCommon'
        value: DEBUG_subnetCommon
      }
      {
        name: 'DEBUG_subnetCommonScoring'
        value: DEBUG_subnetCommonScoring
      }
      {
        name: 'DEBUG_subnetCommonPowerbiGw'
        value: DEBUG_subnetCommonPowerbiGw
      }
      {
        name: 'DEBUG_subnetProjGenAI'
        value: DEBUG_subnetProjGenAI
      }
      {
        name: 'DEBUG_subnetProjAKS'
        value: DEBUG_subnetProjAKS
      }
      {
        name: 'DEBUG_subnetProjACA'
        value: DEBUG_subnetProjACA
      }
      {
        name: 'DEBUG_subnetProjDatabricksPublic'
        value: DEBUG_subnetProjDatabricksPublic
      }
      {
        name: 'DEBUG_subnetProjDatabricksPrivate'
        value: DEBUG_subnetProjDatabricksPrivate
      }
      {
        name: 'DEBUG_byoASEv3'
        value: DEBUG_byoASEv3 ? 'true' : 'false'
      }
      {
        name: 'DEBUG_byoAseFullResourceId'
        value: DEBUG_byoAseFullResourceId
      }
      {
        name: 'DEBUG_byoAseAppServicePlanResourceId'
        value: DEBUG_byoAseAppServicePlanResourceId
      }
      {
        name: 'DEBUG_enablePublicGenAIAccess'
        value: DEBUG_enablePublicGenAIAccess ? 'true' : 'false'
      }
      {
        name: 'DEBUG_allowPublicAccessWhenBehindVnet'
        value: DEBUG_allowPublicAccessWhenBehindVnet ? 'true' : 'false'
      }
      {
        name: 'DEBUG_enablePublicAccessWithPerimeter'
        value: DEBUG_enablePublicAccessWithPerimeter ? 'true' : 'false'
      }
      {
        name: 'DEBUG_admin_aifactorySuffixRG'
        value: DEBUG_admin_aifactorySuffixRG
      }
      {
        name: 'DEBUG_admin_commonResourceSuffix'
        value: DEBUG_admin_commonResourceSuffix
      }
      {
        name: 'DEBUG_admin_prjResourceSuffix'
        value: DEBUG_admin_prjResourceSuffix
      }
      {
        name: 'DEBUG_aifactory_salt'
        value: DEBUG_aifactory_salt
      }
      {
        name: 'DEBUG_admin_projectType'
        value: DEBUG_admin_projectType
      }
      {
        name: 'DEBUG_project_number_000'
        value: DEBUG_project_number_000
      }
      {
        name: 'DEBUG_project_service_principal_AppID_seeding_kv_name'
        value: DEBUG_project_service_principal_AppID_seeding_kv_name
      }
      {
        name: 'DEBUG_project_service_principal_OID_seeding_kv_name'
        value: DEBUG_project_service_principal_OID_seeding_kv_name
      }
      {
        name: 'DEBUG_project_service_principal_Secret_seeding_kv_name'
        value: DEBUG_project_service_principal_Secret_seeding_kv_name
      }
      {
        name: 'DEBUG_project_IP_whitelist'
        value: DEBUG_project_IP_whitelist
      }
      {
        name: 'DEBUG_deployModel_gpt_4'
        value: DEBUG_deployModel_gpt_4 ? 'true' : 'false'
      }
      {
        name: 'DEBUG_deployModel_text_embedding_ada_002'
        value: DEBUG_deployModel_text_embedding_ada_002 ? 'true' : 'false'
      }
      {
        name: 'DEBUG_deployModel_text_embedding_3_large'
        value: DEBUG_deployModel_text_embedding_3_large ? 'true' : 'false'
      }
      {
        name: 'DEBUG_deployModel_text_embedding_3_small'
        value: DEBUG_deployModel_text_embedding_3_small ? 'true' : 'false'
      }
      {
        name: 'DEBUG_deployModel_gpt_4o_mini'
        value: DEBUG_deployModel_gpt_4o_mini ? 'true' : 'false'
      }
      {
        name: 'DEBUG_inputKeyvault'
        value: DEBUG_inputKeyvault
      }
      {
        name: 'DEBUG_inputKeyvaultResourcegroup'
        value: DEBUG_inputKeyvaultResourcegroup
      }
      {
        name: 'DEBUG_inputKeyvaultSubscription'
        value: DEBUG_inputKeyvaultSubscription
      }
    ]
    scriptContent: '''
      Write-Host "DEBUG OUTPUT VARIABLES:"
      Write-Host "vnetId: $env:DEBUG_VNET_ID"
      Write-Host "projectName: $env:PROJECT_NAME"
      Write-Host "projectNumber: $env:PROJECT_NUMBER"
      Write-Host "env: $env:ENV_NAME"
      Write-Host "location: $env:LOCATION"
      Write-Host "locationSuffix: $env:LOCATION_SUFFIX"
      Write-Host "commonResourceGroup: $env:COMMON_RG"
      Write-Host "targetResourceGroup: $env:TARGET_RG"
      Write-Host "vnetNameFull: $env:VNET_NAME_FULL"
      Write-Host "vnetResourceGroupName: $env:VNET_RG_NAME"
      Write-Host "common_subnet_name_local: $env:COMMON_SUBNET_NAME"
      Write-Host "genaiSubnetId: $env:GENAI_SUBNET_ID"
      Write-Host "genaiSubnetName: $env:GENAI_SUBNET_NAME"
      Write-Host "defaultSubnet: $env:DEFAULT_SUBNET"
      Write-Host "aksSubnetId: $env:AKS_SUBNET_ID"
      Write-Host "aksSubnetName: $env:AKS_SUBNET_NAME"
      Write-Host "subscriptionId: $env:SUBSCRIPTION_ID"
      Write-Host "vnetRule1: $env:VNET_RULE_1"
      Write-Host "vnetRule2: $env:VNET_RULE_2"
      Write-Host "postGreSQLExists: $env:postGreSQLExists"
      Write-Host "debug_keyvaultExists: $env:keyvaultExists"
      Write-Host "debug_aiSearchExists: $env:aiSearchExists"
      
      Write-Host ""
      Write-Host "=== DEBUG PARAMETERS ==="
      Write-Host "DEBUG_enableAIServices: $env:DEBUG_enableAIServices"
      Write-Host "DEBUG_enableAIFoundryHub: $env:DEBUG_enableAIFoundryHub"
      Write-Host "DEBUG_enableAISearch: $env:DEBUG_enableAISearch"
      Write-Host "DEBUG_enableAzureMachineLearning: $env:DEBUG_enableAzureMachineLearning"
      Write-Host "DEBUG_serviceSettingDeployFunction: $env:DEBUG_serviceSettingDeployFunction"
      Write-Host "DEBUG_functionRuntime: $env:DEBUG_functionRuntime"
      Write-Host "DEBUG_functionVersion: $env:DEBUG_functionVersion"
      Write-Host "DEBUG_serviceSettingDeployWebApp: $env:DEBUG_serviceSettingDeployWebApp"
      Write-Host "DEBUG_webAppRuntime: $env:DEBUG_webAppRuntime"
      Write-Host "DEBUG_webAppRuntimeVersion: $env:DEBUG_webAppRuntimeVersion"
      Write-Host "DEBUG_aseSku: $env:DEBUG_aseSku"
      Write-Host "DEBUG_aseSkuCode: $env:DEBUG_aseSkuCode"
      Write-Host "DEBUG_aseSkuWorkers: $env:DEBUG_aseSkuWorkers"
      Write-Host "DEBUG_serviceSettingDeployContainerApps: $env:DEBUG_serviceSettingDeployContainerApps"
      Write-Host "DEBUG_serviceSettingDeployAppInsightsDashboard: $env:DEBUG_serviceSettingDeployAppInsightsDashboard"
      Write-Host "DEBUG_aca_a_registry_image: $env:DEBUG_aca_a_registry_image"
      Write-Host "DEBUG_aca_w_registry_image: $env:DEBUG_aca_w_registry_image"
      Write-Host "DEBUG_serviceSettingDeployBingSearch: $env:DEBUG_serviceSettingDeployBingSearch"
      Write-Host "DEBUG_serviceSettingDeployCosmosDB: $env:DEBUG_serviceSettingDeployCosmosDB"
      Write-Host "DEBUG_serviceSettingDeployAzureOpenAI: $env:DEBUG_serviceSettingDeployAzureOpenAI"
      Write-Host "DEBUG_serviceSettingDeployAzureAIVision: $env:DEBUG_serviceSettingDeployAzureAIVision"
      Write-Host "DEBUG_serviceSettingDeployAzureSpeech: $env:DEBUG_serviceSettingDeployAzureSpeech"
      Write-Host "DEBUG_serviceSettingDeployAIDocIntelligence: $env:DEBUG_serviceSettingDeployAIDocIntelligence"
      Write-Host "DEBUG_disableContributorAccessForUsers: $env:DEBUG_disableContributorAccessForUsers"
      Write-Host "DEBUG_serviceSettingDeployPostgreSQL: $env:DEBUG_serviceSettingDeployPostgreSQL"
      Write-Host "DEBUG_serviceSettingDeployRedisCache: $env:DEBUG_serviceSettingDeployRedisCache"
      Write-Host "DEBUG_serviceSettingDeploySQLDatabase: $env:DEBUG_serviceSettingDeploySQLDatabase"
      Write-Host "DEBUG_BYO_subnets: $env:DEBUG_BYO_subnets"
      Write-Host "DEBUG_network_env_dev: $env:DEBUG_network_env_dev"
      Write-Host "DEBUG_network_env_stage: $env:DEBUG_network_env_stage"
      Write-Host "DEBUG_network_env_prod: $env:DEBUG_network_env_prod"
      Write-Host "DEBUG_vnetResourceGroup_param: $env:DEBUG_vnetResourceGroup_param"
      Write-Host "DEBUG_vnetNameFull_param: $env:DEBUG_vnetNameFull_param"
      Write-Host "DEBUG_commonResourceGroup_param: $env:DEBUG_commonResourceGroup_param"
      Write-Host "DEBUG_datalakeName_param: $env:DEBUG_datalakeName_param"
      Write-Host "DEBUG_kvNameFromCOMMON_param: $env:DEBUG_kvNameFromCOMMON_param"
      Write-Host "DEBUG_useCommonACR_override: $env:DEBUG_useCommonACR_override"
      Write-Host "DEBUG_subnetCommon: $env:DEBUG_subnetCommon"
      Write-Host "DEBUG_subnetCommonScoring: $env:DEBUG_subnetCommonScoring"
      Write-Host "DEBUG_subnetCommonPowerbiGw: $env:DEBUG_subnetCommonPowerbiGw"
      Write-Host "DEBUG_subnetProjGenAI: $env:DEBUG_subnetProjGenAI"
      Write-Host "DEBUG_subnetProjAKS: $env:DEBUG_subnetProjAKS"
      Write-Host "DEBUG_subnetProjACA: $env:DEBUG_subnetProjACA"
      Write-Host "DEBUG_subnetProjDatabricksPublic: $env:DEBUG_subnetProjDatabricksPublic"
      Write-Host "DEBUG_subnetProjDatabricksPrivate: $env:DEBUG_subnetProjDatabricksPrivate"
      Write-Host "DEBUG_byoASEv3: $env:DEBUG_byoASEv3"
      Write-Host "DEBUG_byoAseFullResourceId: $env:DEBUG_byoAseFullResourceId"
      Write-Host "DEBUG_byoAseAppServicePlanResourceId: $env:DEBUG_byoAseAppServicePlanResourceId"
      Write-Host "DEBUG_enablePublicGenAIAccess: $env:DEBUG_enablePublicGenAIAccess"
      Write-Host "DEBUG_allowPublicAccessWhenBehindVnet: $env:DEBUG_allowPublicAccessWhenBehindVnet"
      Write-Host "DEBUG_enablePublicAccessWithPerimeter: $env:DEBUG_enablePublicAccessWithPerimeter"
      Write-Host "DEBUG_admin_aifactorySuffixRG: $env:DEBUG_admin_aifactorySuffixRG"
      Write-Host "DEBUG_admin_commonResourceSuffix: $env:DEBUG_admin_commonResourceSuffix"
      Write-Host "DEBUG_admin_prjResourceSuffix: $env:DEBUG_admin_prjResourceSuffix"
      Write-Host "DEBUG_aifactory_salt: $env:DEBUG_aifactory_salt"
      Write-Host "DEBUG_admin_projectType: $env:DEBUG_admin_projectType"
      Write-Host "DEBUG_project_number_000: $env:DEBUG_project_number_000"
      Write-Host "DEBUG_project_service_principal_AppID_seeding_kv_name: $env:DEBUG_project_service_principal_AppID_seeding_kv_name"
      Write-Host "DEBUG_project_service_principal_OID_seeding_kv_name: $env:DEBUG_project_service_principal_OID_seeding_kv_name"
      Write-Host "DEBUG_project_service_principal_Secret_seeding_kv_name: $env:DEBUG_project_service_principal_Secret_seeding_kv_name"
      Write-Host "DEBUG_project_IP_whitelist: $env:DEBUG_project_IP_whitelist"
      Write-Host "DEBUG_deployModel_gpt_4: $env:DEBUG_deployModel_gpt_4"
      Write-Host "DEBUG_deployModel_text_embedding_ada_002: $env:DEBUG_deployModel_text_embedding_ada_002"
      Write-Host "DEBUG_deployModel_text_embedding_3_large: $env:DEBUG_deployModel_text_embedding_3_large"
      Write-Host "DEBUG_deployModel_text_embedding_3_small: $env:DEBUG_deployModel_text_embedding_3_small"
      Write-Host "DEBUG_deployModel_gpt_4o_mini: $env:DEBUG_deployModel_gpt_4o_mini"
      Write-Host "DEBUG_inputKeyvault: $env:DEBUG_inputKeyvault"
      Write-Host "DEBUG_inputKeyvaultResourcegroup: $env:DEBUG_inputKeyvaultResourcegroup"
      Write-Host "DEBUG_inputKeyvaultSubscription: $env:DEBUG_inputKeyvaultSubscription"
    '''
    retentionInterval: 'PT1H'
  }
}

// Add outputs to see the values even if the deployment script fails
output debug_vnetId string = debug_vnetId
output debug_projectName string = projectName
output debug_projectNumber string = projectNumber
output debug_env string = env
output debug_location string = location
output debug_locationSuffix string = locationSuffix
output debug_commonResourceGroup string = commonResourceGroup
output debug_targetResourceGroup string = targetResourceGroup
output debug_vnetNameFull string = vnetNameFull
output debug_vnetResourceGroupName string = vnetResourceGroupName
output debug_common_subnet_name_local string = common_subnet_name_local
output debug_genaiSubnetId string = genaiSubnetId
output debug_genaiSubnetName string = genaiSubnetName
output debug_defaultSubnet string = defaultSubnet
output debug_aksSubnetId string = aksSubnetId
output debug_aksSubnetName string = aksSubnetName
output debug_vnetRule1 string = vnetRule1
output debug_vnetRule2 string = vnetRule2
output debug_postGreSQLExists bool = postGreSQLExists

output debug_keyvaultExists bool = keyvaultExists
output debug_aiSearchExists bool = aiSearchExists

// Key DEBUG parameter outputs (limited to most important ones due to 64 output limit)
output debug_DEBUG_enableAIServices bool = DEBUG_enableAIServices
output debug_DEBUG_enableAIFoundryHub bool = DEBUG_enableAIFoundryHub
output debug_DEBUG_enableAISearch bool = DEBUG_enableAISearch
output debug_DEBUG_enableAzureMachineLearning bool = DEBUG_enableAzureMachineLearning
output debug_DEBUG_serviceSettingDeployFunction bool = DEBUG_serviceSettingDeployFunction
output debug_DEBUG_serviceSettingDeployWebApp bool = DEBUG_serviceSettingDeployWebApp
output debug_DEBUG_serviceSettingDeployContainerApps bool = DEBUG_serviceSettingDeployContainerApps
output debug_DEBUG_serviceSettingDeployAzureOpenAI bool = DEBUG_serviceSettingDeployAzureOpenAI
output debug_DEBUG_BYO_subnets bool = DEBUG_BYO_subnets
output debug_DEBUG_network_env_dev string = DEBUG_network_env_dev
output debug_DEBUG_network_env_stage string = DEBUG_network_env_stage
output debug_DEBUG_network_env_prod string = DEBUG_network_env_prod
output debug_DEBUG_enablePublicGenAIAccess bool = DEBUG_enablePublicGenAIAccess
output debug_DEBUG_admin_projectType string = DEBUG_admin_projectType
output debug_DEBUG_project_number_000 string = DEBUG_project_number_000


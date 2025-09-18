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
param DEBUG_network_env string = ''

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
param DEBUG_enableFunction bool = true

@description('Function runtime')
param DEBUG_functionRuntime string = 'dotnet'

@description('Function version')
param DEBUG_functionVersion string = 'v7.0'

@description('Deploy Web App')
param DEBUG_enableWebApp bool = true

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
param DEBUG_enableContainerApps bool = false

@description('Deploy App Insights Dashboard')
param DEBUG_enableAppInsightsDashboard bool = false

@description('Container Apps API registry image')
param DEBUG_aca_a_registry_image string = 'containerapps-default:latest'

@description('Container Apps Web registry image')
param DEBUG_aca_w_registry_image string = 'mcr.microsoft.com/azuredocs/containerapps-helloworld:latest'

@description('Deploy Bing Search')
param DEBUG_enableBingSearch bool = false

@description('Deploy Cosmos DB')
param DEBUG_enableCosmosDB bool = false

@description('Deploy Azure OpenAI')
param DEBUG_enableAzureOpenAI bool = false

@description('Deploy Azure AI Vision')
param DEBUG_enableAzureAIVision bool = false

@description('Deploy Azure Speech')
param DEBUG_enableAzureSpeech bool = false

@description('Deploy AI Document Intelligence')
param DEBUG_enableAIDocIntelligence bool = false

@description('Disable Contributor Access for Users')
param DEBUG_disableContributorAccessForUsers bool = false

@description('Deploy PostgreSQL')
param DEBUG_enablePostgreSQL bool = false

@description('Deploy Redis Cache')
param DEBUG_enableRedisCache bool = false

@description('Deploy SQL Database')
param DEBUG_enableSQLDatabase bool = false

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

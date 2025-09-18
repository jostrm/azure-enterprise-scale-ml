
targetScope = 'subscription'

// ================================================================
// SAMPLE APPLICATION DEPLOYMENT - Phase 9 Implementation
// This file deploys sample applications and demonstrations including:
// - Sample chat applications
// - Demo web applications
// - Test applications for AI models
// - Sample data and configurations
// ================================================================

// ============== BOOLEAN PARAMETERS ==============

@description('Enable deployment of sample applications')
param appSampleEnabled bool = false

@description('Enable Cosmos DB for sample applications')
param cosmosDbEnabled bool = false

@description('Enable AI Search for sample applications')
param searchEnabled bool = false

@description('Enable authentication for sample applications')
param enableAuthentication bool = true

@description('Enable HTTPS only for sample applications')
param enableHttpsOnly bool = true

@description('Enable public access to sample applications')
param enablePublicAccess bool = false

@description('Enable Application Insights for sample applications')
param enableAppInsights bool = true

@description('Enable container-based deployment')
param enableContainerDeployment bool = false

@description('Enable development/debug mode')
param enableDebugMode bool = false

@description('Diagnostic setting level for monitoring and logging')
@allowed(['gold', 'silver', 'bronze'])
param diagnosticSettingLevel string = 'silver'

@description('Enable sample data seeding')
param enableSampleDataSeeding bool = true

@description('Enable API documentation (Swagger/OpenAPI)')
param enableApiDocumentation bool = true

@description('Enable rate limiting')
param enableRateLimiting bool = true

@description('Enable caching')
param enableCaching bool = false

@description('Enable monitoring and health checks')
param enableMonitoring bool = true

@description('Enable backup and disaster recovery')
param enableBackup bool = false

@description('Enable auto-scaling')
param enableAutoScaling bool = false

@description('Enable custom domains')
param enableCustomDomains bool = false

@description('Enable SSL certificates')
param enableSslCertificates bool = false

@description('Enable load balancing')
param enableLoadBalancing bool = false

// ============== FEATURE FLAGS ==============

@description('Enable experimental features')
param enableExperimentalFeatures bool = false

@description('Enable beta features')
param enableBetaFeatures bool = false

@description('Enable preview features')
param enablePreviewFeatures bool = false

@description('Enable AI model testing features')
param enableModelTesting bool = true

@description('Enable chat interface')
param enableChatInterface bool = true

@description('Enable document upload')
param enableDocumentUpload bool = true

@description('Enable real-time features')
param enableRealTime bool = false

@description('Enable multi-language support')
param enableMultiLanguage bool = false

@description('Enable offline mode')
param enableOfflineMode bool = false

// ============== SECURITY PARAMETERS ==============

@description('Enable network isolation')
param enableNetworkIsolation bool = true

@description('Enable private endpoints')
param enablePrivateEndpoints bool = true

@description('Enable managed identity authentication')
param enableManagedIdentity bool = true

@description('Enable role-based access control')
param enableRbac bool = true

@description('Enable audit logging')
param enableAuditLogging bool = true

@description('Enable encryption at rest')
param enableEncryptionAtRest bool = true

@description('Enable encryption in transit')
param enableEncryptionInTransit bool = true

// ============== STRING PARAMETERS ==============

@description('Authentication client ID')
param authClientId string = ''

@description('Authentication client secret')
@secure()
param authClientSecret string = ''

@description('Cosmos DB databases configuration')
param cosmosDatabases array = []

@description('AI GPT model deployment name')
param aiGPTModelDeployment string = ''

@description('AI embedding model deployment names')
param aiEmbeddingModelDeployment array = []

// ============== COMPUTED VARIABLES ==============

var deploySampleApp = appSampleEnabled && cosmosDbEnabled && searchEnabled && !empty(authClientId) && !empty(authClientSecret) && !empty(cosmosDatabases) && !empty(aiGPTModelDeployment) && length(aiEmbeddingModelDeployment) >= 2

var enableAdvancedFeatures = enableExperimentalFeatures || enableBetaFeatures || enablePreviewFeatures

var enableSecurityFeatures = enableNetworkIsolation && enablePrivateEndpoints && enableManagedIdentity && enableRbac

var enableProductionFeatures = enableHttpsOnly && enableMonitoring && enableAuditLogging && enableEncryptionAtRest && enableEncryptionInTransit

// ============== CONDITIONAL DEPLOYMENT ==============

// Sample App deployment will only proceed if all required conditions are met
var canDeploySampleApp = deploySampleApp && enableProductionFeatures

// ============== OUTPUTS ==============

@description('Sample application deployment status')
output sampleAppDeployed bool = canDeploySampleApp

@description('Advanced features enabled')
output advancedFeaturesEnabled bool = enableAdvancedFeatures

@description('Security features enabled')
output securityFeaturesEnabled bool = enableSecurityFeatures

@description('Production features enabled')
output productionFeaturesEnabled bool = enableProductionFeatures

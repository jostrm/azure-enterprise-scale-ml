targetScope = 'subscription'

// ================================================================
// MICROSOFT DEFENDER FOR CLOUD - SUBSCRIPTION-LEVEL PRICING CONFIGURATION
// ================================================================
// This module configures Microsoft Defender for Cloud pricing plans and extensions
// at the subscription level using the Microsoft.Security/pricings@2024-01-01 API.
//
// PRICING TIERS:
// - Free: Basic security features with limited capabilities
// - Standard: Advanced security features including threat detection, vulnerability assessments, and compliance
//
// TIER BEHAVIOR:
// - pricingTier (default: Free): Controls AI and Key Vault plans
// - advancedPricingTier (default: Standard): Controls Storage, Containers, Cloud Posture, and Virtual Machines plans
//
// ENABLE FLAGS:
// - enableAll (default: true): Master switch using OR logic - either enableAll=true OR individual plan flag=true will deploy that plan
// - Individual enable flags: Control specific Defender plans independently (e.g., enableDefenderForAI, enableDefenderForStorage)
//
// EXTENSIONS:
// - Extensions (AIPromptEvidence, OnUploadMalwareScanning, ContainerSensor, etc.) are only available with Standard tier
// - When tier is set to Free, extensions are automatically disabled to prevent deployment errors
//
// ENFORCEMENT:
// - enforce parameter: When 'True', prevents descendant scopes from overriding pricing configuration
// - Default: 'False' to allow flexibility at resource group or resource level
//
// EXAMPLE CONFIGURATIONS:
// 1. All Free tier: enableAll=true, pricingTier='Free', advancedPricingTier='Free'
// 2. Mixed tiers: enableAll=true, pricingTier='Free', advancedPricingTier='Standard' (recommended for AI workloads)
// 3. All Standard: enableAll=true, pricingTier='Standard', advancedPricingTier='Standard'
// 4. Selective: enableAll=false, then enable specific plans (e.g., enableDefenderForAI=true, enableDefenderForStorage=true)
// ================================================================

@description('Master switch to enable all Defender plans. Set to false to disable all plans regardless of individual settings.')
param enableAll bool = true

@description('Pricing tier for the AI services plan.')
@allowed(['Standard','Free'])
param pricingTier string = 'Free'

@description('Pricing tier for Storage, Containers, Cloud Posture, and Virtual Machines plans.')
@allowed(['Standard','Free'])
param advancedPricingTier string = 'Standard'

@description('Optional. Enable Microsoft Defender for AI.')
param enableDefenderForAI bool = true

@description('Optional. Enable Defender for Key Vault.')
param enableDefenderForKeyVault bool = true

@description('Optional. Enable Defender for Storage.')
param enableDefenderForStorage bool = true

@description('AI plan name.')
param aiPlanName string = 'AI'

@description('If set to True, prevents overrides and forces this pricing configuration on all descendants.')
@allowed(['True','False'])
param enforce string = 'False'

@description('Optional sub-plan for AI pricing (when applicable).')
param aiSubPlan string = ''

@description('Enable AIPromptEvidence extension for AI plan.')
param enableAIPromptEvidence bool = false

@description('Storage scanning capacity limit (GB per month per storage account).')
param storageCapGBPerMonthPerStorageAccount string = '5000'

@description('Enable OnUploadMalwareScanning extension for Storage.')
param enableStorageMalwareScanning bool = true

@description('Enable SensitiveDataDiscovery extension for Storage.')
param enableStorageSensitiveDataDiscovery bool = true

@description('Optional. Enable Defender for Containers.')
param enableDefenderForContainers bool = false

@description('Enable ContainerRegistriesVulnerabilityAssessments extension for Containers/CloudPosture.')
param enableContainerRegistriesVulnerabilityAssessments bool = false

@description('Enable ContainerSensor extension for Containers plan.')
param enableContainerSensor bool = false

@description('Enable AgentlessDiscoveryForKubernetes extension for Containers/CloudPosture.')
param enableAgentlessDiscoveryForKubernetes bool = false

@description('Optional. Enable Defender for Cloud Posture Management.')
param enableDefenderForCloudPosture bool = false

@description('Optional. Enable Defender for Virtual Machines.')
param enableDefenderForVirtualMachines bool = false

@description('Sub-plan for Virtual Machines (P1 or P2).')
@allowed(['P1','P2',''])
param vmSubPlan string = 'P1'

@description('Enable MdeDesignatedSubscription extension for VirtualMachines plan.')
param enableMdeDesignatedSubscription bool = false

// Deploy Microsoft Defender for AI at subscription level
resource defenderForAI 'Microsoft.Security/pricings@2024-01-01' = if (enableAll || enableDefenderForAI) {
  name: aiPlanName
  properties: {
    pricingTier: pricingTier
    enforce: enforce
    subPlan: !empty(aiSubPlan) ? aiSubPlan : null
    extensions: enableAIPromptEvidence ? [
      {
        name: 'AIPromptEvidence'
        isEnabled: 'True'
      }
    ] : []
  }
}

// Enable Defender for Storage (recommended for AI workloads)
resource defenderForStorage 'Microsoft.Security/pricings@2024-01-01' = if (enableAll || enableDefenderForStorage) {
  name: 'StorageAccounts'
  properties: {
    pricingTier: advancedPricingTier
    enforce: enforce
    subPlan: advancedPricingTier == 'Standard' ? 'DefenderForStorageV2' : null
    extensions: advancedPricingTier == 'Standard' ? concat(
      enableStorageMalwareScanning ? [
        {
          name: 'OnUploadMalwareScanning'
          isEnabled: 'True'
          additionalExtensionProperties: {
            CapGBPerMonthPerStorageAccount: storageCapGBPerMonthPerStorageAccount
          }
        }
      ] : [],
      enableStorageSensitiveDataDiscovery ? [
        {
          name: 'SensitiveDataDiscovery'
          isEnabled: 'True'
        }
      ] : []
    ) : []
  }
}

// Enable Defender for Key Vault
resource defenderForKeyVault 'Microsoft.Security/pricings@2024-01-01' = if (enableAll || enableDefenderForKeyVault) {
  name: 'KeyVaults'
  properties: {
    pricingTier: pricingTier
    enforce: enforce
  }
}

// Enable Defender for Containers
resource defenderForContainers 'Microsoft.Security/pricings@2024-01-01' = if (enableAll || enableDefenderForContainers) {
  name: 'Containers'
  properties: {
    pricingTier: advancedPricingTier
    enforce: enforce
    extensions: advancedPricingTier == 'Standard' ? concat(
      enableContainerRegistriesVulnerabilityAssessments ? [
        {
          name: 'ContainerRegistriesVulnerabilityAssessments'
          isEnabled: 'True'
        }
      ] : [],
      enableContainerSensor ? [
        {
          name: 'ContainerSensor'
          isEnabled: 'True'
        }
      ] : [],
      enableAgentlessDiscoveryForKubernetes ? [
        {
          name: 'AgentlessDiscoveryForKubernetes'
          isEnabled: 'True'
        }
      ] : []
    ) : []
  }
}

// Enable Defender for Cloud Posture Management
resource defenderForCloudPosture 'Microsoft.Security/pricings@2024-01-01' = if (enableAll || enableDefenderForCloudPosture) {
  name: 'CloudPosture'
  properties: {
    pricingTier: advancedPricingTier
    enforce: enforce
    extensions: (advancedPricingTier == 'Standard' && enableAgentlessDiscoveryForKubernetes) ? [
      {
        name: 'AgentlessDiscoveryForKubernetes'
        isEnabled: 'True'
      }
    ] : []
  }
}

// Enable Defender for Virtual Machines
resource defenderForVirtualMachines 'Microsoft.Security/pricings@2024-01-01' = if (enableAll || enableDefenderForVirtualMachines) {
  name: 'VirtualMachines'
  properties: {
    pricingTier: advancedPricingTier
    enforce: enforce
    subPlan: (advancedPricingTier == 'Standard' && !empty(vmSubPlan)) ? vmSubPlan : null
    extensions: (advancedPricingTier == 'Standard' && enableMdeDesignatedSubscription) ? [
      {
        name: 'MdeDesignatedSubscription'
        isEnabled: 'True'
      }
    ] : []
  }
}

@description('Defender for AI enabled.')
output defenderForAIEnabled bool = enableAll || enableDefenderForAI

@description('Defender for Storage enabled.')
output defenderForStorageEnabled bool = enableAll || enableDefenderForStorage

@description('Defender for Key Vault enabled.')
output defenderForKeyVaultEnabled bool = enableAll || enableDefenderForKeyVault

@description('AI Prompt Evidence extension enabled.')
output aiPromptEvidenceEnabled bool = enableAIPromptEvidence

@description('Storage Malware Scanning extension enabled.')
output storageMalwareScanningEnabled bool = enableStorageMalwareScanning

@description('Storage Sensitive Data Discovery extension enabled.')
output storageSensitiveDataDiscoveryEnabled bool = enableStorageSensitiveDataDiscovery

@description('Defender for Containers enabled.')
output defenderForContainersEnabled bool = enableAll || enableDefenderForContainers

@description('Container Registries Vulnerability Assessments extension enabled.')
output containerRegistriesVulnerabilityAssessmentsEnabled bool = enableContainerRegistriesVulnerabilityAssessments

@description('Container Sensor extension enabled.')
output containerSensorEnabled bool = enableContainerSensor

@description('Agentless Discovery For Kubernetes extension enabled.')
output agentlessDiscoveryForKubernetesEnabled bool = enableAgentlessDiscoveryForKubernetes

@description('Defender for Cloud Posture enabled.')
output defenderForCloudPostureEnabled bool = enableAll || enableDefenderForCloudPosture

@description('Defender for Virtual Machines enabled.')
output defenderForVirtualMachinesEnabled bool = enableAll || enableDefenderForVirtualMachines

@description('MDE Designated Subscription extension enabled.')
output mdeDesignatedSubscriptionEnabled bool = enableMdeDesignatedSubscription

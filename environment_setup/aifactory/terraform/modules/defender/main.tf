# Port of environment_setup/aifactory/bicep/esml-common/security/defender.bicep
# Every Microsoft.Security/pricings plan always exists on a subscription (Free by default), so the plans are PUT with
# azapi_update_resource: the same request as the Bicep, no "already exists" error on first apply, and never a DELETE
# on destroy (the Bicep never deletes a plan either).

# MICROSOFT DEFENDER FOR CLOUD - SUBSCRIPTION-LEVEL PRICING CONFIGURATION (subscription scope)
# - pricingTier: AI and Key Vault plans; advancedPricingTier: Storage, Containers, Cloud Posture, Virtual Machines.
# - enableAll OR the individual flag deploys a plan.
# - Extensions are only sent with the Standard tier (Free + extensions fails).
# - enforce 'True' prevents descendant scopes from overriding the pricing configuration.
#
# azapi (exact type + API version of the Bicep): azurerm_security_center_subscription_pricing (5.12.0) has
# tier/subplan/extension{name, additional_extension_properties} but no `enforce`, and it always manages the full
# extension set (sends disabled entries) instead of the exact extensions array the Bicep sends.

locals {
  subscription_id = "/subscriptions/${var.subscription_id}"

  deploy_ai              = var.enable_all || var.enable_defender_for_ai
  deploy_storage         = var.enable_all || var.enable_defender_for_storage
  deploy_key_vault       = var.enable_all || var.enable_defender_for_key_vault
  deploy_containers      = var.enable_all || var.enable_defender_for_containers
  deploy_cloud_posture   = var.enable_all || var.enable_defender_for_cloud_posture
  deploy_virtual_machine = var.enable_all || var.enable_defender_for_virtual_machines

  # Bicep "subPlan: cond ? x : null": the property is left out of the request when null.
  ai_properties = merge(
    {
      pricingTier = var.pricing_tier
      enforce     = var.enforce
      extensions = (var.pricing_tier == "Standard" && var.enable_ai_prompt_evidence) ? [
        {
          name      = "AIPromptEvidence"
          isEnabled = "True"
        }
      ] : []
    },
    var.ai_sub_plan != "" ? { subPlan = var.ai_sub_plan } : {}
  )

  storage_properties = merge(
    {
      pricingTier = var.advanced_pricing_tier
      enforce     = var.enforce
      # Bicep: advancedPricingTier == 'Standard' ? concat(malware ? [..] : [], sdd ? [..] : []) : []
      # (a filtered for-expression, because a conditional cannot mix tuples of different shapes)
      extensions = [for e in [
        {
          enabled = var.enable_storage_malware_scanning
          value = {
            name      = "OnUploadMalwareScanning"
            isEnabled = "True"
            additionalExtensionProperties = {
              CapGBPerMonthPerStorageAccount = var.storage_cap_gb_per_month_per_storage_account
            }
          }
        },
        {
          enabled = var.enable_storage_sensitive_data_discovery
          value = {
            name      = "SensitiveDataDiscovery"
            isEnabled = "True"
          }
        },
      ] : e.value if var.advanced_pricing_tier == "Standard" && e.enabled]
    },
    var.advanced_pricing_tier == "Standard" ? { subPlan = "DefenderForStorageV2" } : {}
  )

  containers_properties = {
    pricingTier = var.advanced_pricing_tier
    enforce     = var.enforce
    # Bicep: advancedPricingTier == 'Standard' ? concat(cva ? [..] : [], sensor ? [..] : [], agentless ? [..] : []) : []
    extensions = [for e in [
      { enabled = var.enable_container_registries_vulnerability_assessments, name = "ContainerRegistriesVulnerabilityAssessments" },
      { enabled = var.enable_container_sensor, name = "ContainerSensor" },
      { enabled = var.enable_agentless_discovery_for_kubernetes, name = "AgentlessDiscoveryForKubernetes" },
      ] : {
      name      = e.name
      isEnabled = "True"
    } if var.advanced_pricing_tier == "Standard" && e.enabled]
  }

  cloud_posture_properties = {
    pricingTier = var.advanced_pricing_tier
    enforce     = var.enforce
    extensions = (var.advanced_pricing_tier == "Standard" && var.enable_agentless_discovery_for_kubernetes) ? [
      {
        name      = "AgentlessDiscoveryForKubernetes"
        isEnabled = "True"
      }
    ] : []
  }

  virtual_machines_properties = merge(
    {
      pricingTier = var.advanced_pricing_tier
      enforce     = var.enforce
      extensions = (var.advanced_pricing_tier == "Standard" && var.enable_mde_designated_subscription) ? [
        {
          name      = "MdeDesignatedSubscription"
          isEnabled = "True"
        }
      ] : []
    },
    (var.advanced_pricing_tier == "Standard" && var.vm_sub_plan != "") ? { subPlan = var.vm_sub_plan } : {}
  )
}

# Deploy Microsoft Defender for AI at subscription level
resource "azapi_update_resource" "defender_for_ai" {
  count     = local.deploy_ai ? 1 : 0
  type      = "Microsoft.Security/pricings@2024-01-01"
  name      = var.ai_plan_name
  parent_id = local.subscription_id
  body = {
    properties = local.ai_properties
  }
}

# Enable Defender for Storage (recommended for AI workloads)
resource "azapi_update_resource" "defender_for_storage" {
  count     = local.deploy_storage ? 1 : 0
  type      = "Microsoft.Security/pricings@2024-01-01"
  name      = "StorageAccounts"
  parent_id = local.subscription_id
  body = {
    properties = local.storage_properties
  }
}

# Enable Defender for Key Vault
resource "azapi_update_resource" "defender_for_key_vault" {
  count     = local.deploy_key_vault ? 1 : 0
  type      = "Microsoft.Security/pricings@2024-01-01"
  name      = "KeyVaults"
  parent_id = local.subscription_id
  body = {
    properties = {
      pricingTier = var.pricing_tier
      enforce     = var.enforce
    }
  }
}

# Enable Defender for Containers
resource "azapi_update_resource" "defender_for_containers" {
  count     = local.deploy_containers ? 1 : 0
  type      = "Microsoft.Security/pricings@2024-01-01"
  name      = "Containers"
  parent_id = local.subscription_id
  body = {
    properties = local.containers_properties
  }
}

# Enable Defender for Cloud Posture Management
resource "azapi_update_resource" "defender_for_cloud_posture" {
  count     = local.deploy_cloud_posture ? 1 : 0
  type      = "Microsoft.Security/pricings@2024-01-01"
  name      = "CloudPosture"
  parent_id = local.subscription_id
  body = {
    properties = local.cloud_posture_properties
  }
}

# Enable Defender for Virtual Machines
resource "azapi_update_resource" "defender_for_virtual_machines" {
  count     = local.deploy_virtual_machine ? 1 : 0
  type      = "Microsoft.Security/pricings@2024-01-01"
  name      = "VirtualMachines"
  parent_id = local.subscription_id
  body = {
    properties = local.virtual_machines_properties
  }
}

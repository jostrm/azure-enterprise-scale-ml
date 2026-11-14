# Authentication comes from the environment (ARM_USE_OIDC, ARM_CLIENT_ID, ARM_TENANT_ID set by the workflow),
# the same federated identity azure/login uses for the Bicep deployments.
provider "azurerm" {
  features {
    key_vault {
      # The Bicep templates never purge: soft-deleted vaults and secrets stay recoverable.
      purge_soft_delete_on_destroy               = false
      purge_soft_deleted_secrets_on_destroy      = false
      recover_soft_deleted_key_vaults            = true
      recover_soft_deleted_secrets               = true
      purge_soft_deleted_keys_on_destroy         = false
      purge_soft_deleted_certificates_on_destroy = false
    }
    resource_group {
      # 11-rgCommon creates the common resource group; resources other tools add there must not be deleted.
      prevent_deletion_if_contains_resources = true
    }
  }
  subscription_id                 = local.subscription_id
  storage_use_azuread             = true
  resource_provider_registrations = "none"
}

# 13-rgLevel deploys private DNS zones and links into privDnsSubscription/privDnsResourceGroupName.
provider "azurerm" {
  alias = "private_dns"
  features {}
  subscription_id                 = module.scopes.priv_dns_subscription
  resource_provider_registrations = "none"
}

# 13-rgLevel peers an added scale set with the factory's own access hub (ownHubSubscriptionId).
provider "azurerm" {
  alias = "own_hub"
  features {}
  subscription_id                 = module.scopes.own_hub_subscription_id
  resource_provider_registrations = "none"
}

provider "azapi" {}

# Port of environment_setup/aifactory/bicep/esml-common/modules-common/kvSecretsCmn.bicep

# The Bicep copies the common service principal's App ID, object ID and secret from the seeding Key Vault
# (getSecret, resolved inside ARM) into the common Key Vault, and adds the tenant and subscription ids.
# Terraform writes them through the ARM control plane (the common vault is private) with azapi, the exact types
# and API versions of the Bicep. The three service principal values are ephemeral (read with an ephemeral
# azurerm_key_vault_secret by the root) and go in the write-only sensitive_body, so they never reach the
# plan or the state, as with getSecret. sensitive_body_version re-sends them on every run, like a Bicep re-deploy.

locals {
  key_vault_id = "/subscriptions/${var.subscription_id}/resourceGroups/${var.resource_group_name}/providers/Microsoft.KeyVault/vaults/${var.keyvault_name}"
  attributes = {
    enabled = true
    exp     = var.key_vault_secret_expiry
  }
  secret_version = { "properties.value" = tostring(var.key_vault_secret_expiry) }
}

resource "azapi_resource" "kv_secret_esml_common_sp_id" {
  type      = "Microsoft.KeyVault/vaults/secrets@2019-09-01"
  name      = var.esml_common_sp_id
  parent_id = local.key_vault_id
  body = {
    properties = {
      contentType = "ESML generated - Common service principle App ID"
      attributes  = local.attributes
    }
  }
  sensitive_body         = { properties = { value = var.esml_common_sp_id_secret } }
  sensitive_body_version = local.secret_version
}

# SP OID
resource "azapi_resource" "kv_secret_esml_common_sp_oid" {
  type      = "Microsoft.KeyVault/vaults/secrets@2019-09-01"
  name      = var.esml_common_sp_oid
  parent_id = local.key_vault_id
  body = {
    properties = {
      contentType = "ESML generated - Common service principle OBJECT ID, for RBAC in BICEP or ACL on lake"
      attributes  = local.attributes
    }
  }
  sensitive_body         = { properties = { value = var.esml_common_sp_oid_value } }
  sensitive_body_version = local.secret_version
}

# SP SECRET
resource "azapi_resource" "kv_secret_esml_common_sp_secret" {
  type      = "Microsoft.KeyVault/vaults/secrets@2019-09-01"
  name      = var.esml_common_sp_secret
  parent_id = local.key_vault_id
  body = {
    properties = {
      contentType = "ESML generated - Common service principle secret"
      attributes  = local.attributes
    }
  }
  sensitive_body         = { properties = { value = var.esml_common_sp_secret_value } }
  sensitive_body_version = local.secret_version
}

# tenant id
resource "azapi_resource" "kv_secret_tenant_id" {
  type      = "Microsoft.KeyVault/vaults/secrets@2019-09-01"
  name      = var.esml_tenant_id
  parent_id = local.key_vault_id
  body = {
    properties = {
      value       = var.esml_tenant_id_secret
      contentType = "ESML generated - tenant ID"
      attributes  = local.attributes
    }
  }
  # ARM never returns secret values; do not show them as drift.
  ignore_missing_property = true
}

# subscription id
resource "azapi_resource" "kv_secret_subscription_id" {
  type      = "Microsoft.KeyVault/vaults/secrets@2021-10-01"
  name      = var.esml_subscription_id
  parent_id = local.key_vault_id
  body = {
    properties = {
      value       = var.subscription_id
      contentType = "ESML generated - Subscription ID for current ESML environment"
      attributes  = local.attributes
    }
  }
  ignore_missing_property = true
}

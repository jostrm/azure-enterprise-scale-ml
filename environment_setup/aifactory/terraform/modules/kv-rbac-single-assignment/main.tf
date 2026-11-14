# Port of environment_setup/aifactory/bicep/modules/kvRbacSingleAssignment.bicep

# KEY VAULT RBAC SINGLE ASSIGNMENT: assigns a specific RBAC role to a single principal on a Key Vault
# (resource group scope; the vault is in var.resource_group_name of var.subscription_id).

locals {
  # Bicep 'existing' keyVault -> keyVault.id, built like resourceId()
  key_vault_id = "/subscriptions/${var.subscription_id}/resourceGroups/${var.resource_group_name}/providers/Microsoft.KeyVault/vaults/${var.key_vault_name}"

  # Deterministic GUID based on scope, principal, role (and optional suffix) to keep deployments idempotent
  # empty(assignmentName) ? guid(keyVault.id, principalId, keyVaultRoleId) : guid(keyVault.id, principalId, keyVaultRoleId, assignmentName)
  assignment_guid_args = var.assignment_name == "" ? [local.key_vault_id, var.principal_id, var.key_vault_role_id] : [local.key_vault_id, var.principal_id, var.key_vault_role_id, var.assignment_name]
  assignment_guid      = uuidv5("11fb06fb-712d-4ddd-98c7-e71bbd588830", join("-", local.assignment_guid_args))
}

resource "azurerm_role_assignment" "key_vault_role_assignment" {
  name               = local.assignment_guid
  scope              = local.key_vault_id
  role_definition_id = "/subscriptions/${var.subscription_id}/providers/Microsoft.Authorization/roleDefinitions/${var.key_vault_role_id}"
  principal_id       = var.principal_id
  principal_type     = var.principal_type
  description        = var.role_description != "" ? var.role_description : "Key Vault RBAC assignment for ${var.principal_type}"
}

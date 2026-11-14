# Port of environment_setup/aifactory/bicep/modules/kvRbacPrincipals.bicep

# KEY VAULT RBAC FOR A LIST OF PRINCIPALS (resource group scope; the vault is in var.resource_group_name).
# The Azure RBAC replacement for the former access-policy module kvCmnAccessPolicys.bicep:
# one built-in Key Vault role assignment per principal.
# Access-policy secret permissions map to roles: get or get/list -> secretsUser; get/list/set or all -> secretsOfficer.

locals {
  # loadJsonContent('common/keyVaultDefaults.json', '$.roleDefinitionIds') (copied; keep in sync with that file)
  role_definition_ids = {
    administrator               = "00482a5a-887f-4fb3-b363-3b7fe8e74483"
    secretsOfficer              = "b86a8fe4-44ce-4948-aee5-eccb2c155cd7"
    secretsUser                 = "4633458b-17de-408a-b874-0445c86b69e6"
    cryptoUser                  = "12338af0-0e69-4776-bea7-57ae8d297424"
    cryptoServiceEncryptionUser = "e147488a-f6f5-4113-8e2d-b22465e65bf6"
    certificatesOfficer         = "a4417e6f-fecd-4de8-b567-7b0420556985"
  }
  role_definition_id = local.role_definition_ids[var.key_vault_role]

  # Bicep 'existing' keyVault -> keyVault.id, built like resourceId()
  key_vault_id = "/subscriptions/${var.subscription_id}/resourceGroups/${var.resource_group_name}/providers/Microsoft.KeyVault/vaults/${var.key_vault_resource_name}"

  # Trimmed and lower-cased so ' b' from "a, b" or a secret value ending in a newline is kept, and case duplicates merge.
  # Same body as normalizedObjectIds in modules/common/objectIds.bicep.
  # A managed identity's principal id (principal_is_managed_identity) is a GUID that is only known after apply;
  # it is assigned by its own resource below, so for_each keys stay known at plan time.
  all_principals = distinct([
    for id in concat(var.principal_is_managed_identity ? [] : [var.principal_id], var.additional_principal_ids) : lower(trimspace(id))
    if lower(trimspace(id)) != "" && lower(trimspace(id)) != "null"
  ])
  # A role assignment needs the tenant's object ID, so variables-file placeholders such as '<optional>_ObjectID' or
  # '<todo>' are skipped instead of failing the deployment. GUID shape check exactly as the Bicep: 8-4-4-4-12.
  # principal_id is sensitive (Bicep @secure(), it may come from a Key Vault secret); object IDs are not secrets, and
  # for_each keys cannot be sensitive, hence nonsensitive().
  guid_principals = nonsensitive([
    for oid in local.all_principals : oid
    if length(oid) == 36 && length(replace(oid, "-", "")) == 32 && substr(oid, 8, 1) == "-" && substr(oid, 13, 1) == "-" && substr(oid, 18, 1) == "-" && substr(oid, 23, 1) == "-"
  ])
}

# Seeded like kv-rbac-single-assignment without a suffix: one name per vault, principal and role, so two templates
# that grant the same role to the same principal on the same vault never collide.
resource "azurerm_role_assignment" "role_assignments" {
  for_each = toset(local.guid_principals)

  name               = uuidv5("11fb06fb-712d-4ddd-98c7-e71bbd588830", join("-", [local.key_vault_id, each.key, local.role_definition_id]))
  scope              = local.key_vault_id
  role_definition_id = "/subscriptions/${var.subscription_id}/providers/Microsoft.Authorization/roleDefinitions/${local.role_definition_id}"
  principal_id       = each.key
  # Bicep: empty(principalType) ? null : principalType (null lets Azure resolve it)
  principal_type = var.principal_type == "" ? null : var.principal_type
  description    = "AI Factory Key Vault ${var.key_vault_role} for ${each.key}"
}

# The main principal when it is a managed identity created in the same apply (Data Factory system identity):
# same name, scope, role and description as above; the GUID filter always keeps an object id ARM issued.
resource "azurerm_role_assignment" "managed_identity" {
  count = var.principal_is_managed_identity ? 1 : 0

  name               = uuidv5("11fb06fb-712d-4ddd-98c7-e71bbd588830", join("-", [local.key_vault_id, lower(var.principal_id), local.role_definition_id]))
  scope              = local.key_vault_id
  role_definition_id = "/subscriptions/${var.subscription_id}/providers/Microsoft.Authorization/roleDefinitions/${local.role_definition_id}"
  principal_id       = var.principal_id
  principal_type     = var.principal_type == "" ? null : var.principal_type
  description        = "AI Factory Key Vault ${var.key_vault_role} for ${lower(var.principal_id)}"
}

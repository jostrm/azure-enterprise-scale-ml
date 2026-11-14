# Port of environment_setup/aifactory/bicep/modules/vmAdminLoginRbac.bicep

# Resource group scope. The Bicep does NOT look up users by email: the email is only used in a description.
# Principals are object IDs; useAdGroups only switches principalType of the additional IDs to 'Group'.

locals {
  resource_group_id = "/subscriptions/${var.subscription_id}/resourceGroups/${var.resource_group_name}"
  # Bicep 'existing' VMAdminRoleDefinition (built-in Virtual Machine Administrator Login, scope: subscription()) -> its .id
  vm_admin_role_definition_id = "/subscriptions/${var.subscription_id}/providers/Microsoft.Authorization/roleDefinitions/1c0163c0-47e6-4577-8991-ea5c82e286e4"

  main_principal_2_array = [var.user_id]
  main_email_2_array     = [var.user_email]
}

# Users or groups that will be assigned the VMAdminLogin role
resource "azurerm_role_assignment" "vm_admin_login_role" {
  for_each = toset(var.additional_user_ids)

  name               = uuidv5("11fb06fb-712d-4ddd-98c7-e71bbd588830", "${each.key}-vmadminlogin-${local.resource_group_id}")
  scope              = local.resource_group_id
  role_definition_id = local.vm_admin_role_definition_id
  principal_id       = each.key
  principal_type     = var.use_ad_groups ? "Group" : "User"
  description        = "Contributor to user ${each.key} to get VMAdminLogin"
}

# Users - disabled if not using groups
resource "azurerm_role_assignment" "vm_admin_login_role_user" {
  count = (var.use_ad_groups == false && var.user_id != "") ? length(local.main_principal_2_array) : 0

  name               = uuidv5("11fb06fb-712d-4ddd-98c7-e71bbd588830", "${local.main_principal_2_array[count.index]}-vmadminlogin-${local.resource_group_id}")
  scope              = local.resource_group_id
  role_definition_id = local.vm_admin_role_definition_id
  principal_id       = local.main_principal_2_array[count.index]
  principal_type     = "User"
  description        = "Contributor to user ${local.main_email_2_array[count.index]} to get VMAdminLogin"
}

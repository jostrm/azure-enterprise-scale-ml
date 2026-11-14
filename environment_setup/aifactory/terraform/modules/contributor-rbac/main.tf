# Port of environment_setup/aifactory/bicep/modules/contributorRbac.bicep

# Resource group scope. The Bicep does NOT look up users by email: the emails are only used in the
# role assignment descriptions. Principals are object IDs; useAdGroups only switches principalType to 'Group'.

locals {
  # resourceGroup().id / resourceGroup().name of the deployment resource group
  resource_group_id = "/subscriptions/${var.subscription_id}/resourceGroups/${var.resource_group_name}"
  # Bicep 'existing' contributorRoleDefinition (scope: subscription()) -> its .id
  contributor_role_definition_id = "/subscriptions/${var.subscription_id}/providers/Microsoft.Authorization/roleDefinitions/${var.contributor_role_id}"

  main_principal_2_array = [var.user_id]
  main_email_2_array     = [var.user_email]
}

# Bicep: [for i in range(0, length(additionalUserIds)): if(!empty(additionalUserIds)) {...}]
# Keyed by object ID (the name is seeded with it); the index is kept for the email in the description.
resource "azurerm_role_assignment" "contributor_role2user_or_group" {
  for_each = { for i, id in var.additional_user_ids : id => i }

  name               = uuidv5("11fb06fb-712d-4ddd-98c7-e71bbd588830", "${each.key}-contributor-${local.resource_group_id}")
  scope              = local.resource_group_id
  role_definition_id = local.contributor_role_definition_id
  principal_id       = each.key
  principal_type     = var.use_ad_groups ? "Group" : "User"
  # Fewer emails than object IDs is allowed: name the object ID instead of failing with an index out of bounds.
  description = "Contributor to user ${each.value < length(var.additional_user_emails) ? var.additional_user_emails[each.value] : each.key} to get Contributor on resource group: ${var.resource_group_name}"
}

# Bicep: [for i in range(0, length(main_principal_2_array)): if(useAdGroups==false && !empty(userId)) {...}] (one element)
resource "azurerm_role_assignment" "contributor_role2user" {
  count = (var.use_ad_groups == false && var.user_id != "") ? length(local.main_principal_2_array) : 0

  name               = uuidv5("11fb06fb-712d-4ddd-98c7-e71bbd588830", "${local.main_principal_2_array[count.index]}-contributor-${local.resource_group_id}")
  scope              = local.resource_group_id
  role_definition_id = local.contributor_role_definition_id
  principal_id       = local.main_principal_2_array[count.index]
  principal_type     = var.use_ad_groups ? "Group" : "User"
  description        = "Contributor to user ${local.main_email_2_array[count.index]} to get Contributor on resource group: ${var.resource_group_name}"
}

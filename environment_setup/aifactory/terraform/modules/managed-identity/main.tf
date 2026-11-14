# Port of environment_setup/aifactory/bicep/modules/mi.bicep

# Creates a user assigned MI, needed to be created before ACA, and needs to be assigned ACR Pull permissions
# to access an Azure Container Registry, before ACA. Resource group scope.

locals {
  # managedIdentity.id as ARM builds it for a resource declared in this resource group deployment
  managed_identity_id = "/subscriptions/${var.subscription_id}/resourceGroups/${var.resource_group_name}/providers/Microsoft.ManagedIdentity/userAssignedIdentities/${var.name}"
  # Bicep: resourceId('Microsoft.Authorization/roleDefinitions', '5e0b...') inside a resource-group deployment yields the
  # resource-group-qualified string; it seeds the guid() name, so it is reproduced verbatim for the name.
  cognitive_services_user_role_definition_rg_id = "/subscriptions/${var.subscription_id}/resourceGroups/${var.resource_group_name}/providers/Microsoft.Authorization/roleDefinitions/5e0bd9bd-7b93-4f28-af87-19fc36ad61bd"
  # ARM resolves that to the subscription-level role definition; azurerm gets the canonical id.
  cognitive_services_user_role_definition_id = "/subscriptions/${var.subscription_id}/providers/Microsoft.Authorization/roleDefinitions/5e0bd9bd-7b93-4f28-af87-19fc36ad61bd"
}

resource "azurerm_user_assigned_identity" "managed_identity" {
  name                = var.name
  location            = var.location
  resource_group_name = var.resource_group_name
  tags                = merge(var.tags, { "azd-service-name" = var.name })
}

# Assign the Cognitive Services User role to the user-defined managed identity used by workloads (scope: resource group)
resource "azurerm_role_assignment" "cognitive_services_user_role_assignment" {
  name               = uuidv5("11fb06fb-712d-4ddd-98c7-e71bbd588830", join("-", [local.managed_identity_id, local.cognitive_services_user_role_definition_rg_id]))
  scope              = "/subscriptions/${var.subscription_id}/resourceGroups/${var.resource_group_name}"
  role_definition_id = local.cognitive_services_user_role_definition_id
  principal_id       = azurerm_user_assigned_identity.managed_identity.principal_id
  principal_type     = "ServicePrincipal"
}

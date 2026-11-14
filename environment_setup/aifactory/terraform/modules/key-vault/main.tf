# Port of environment_setup/aifactory/bicep/modules/keyVault.bicep

# Resource group scope (the module deploys into var.resource_group_name).

locals {
  resource_group_id = "/subscriptions/${var.subscription_id}/resourceGroups/${var.resource_group_name}"
  # Bicep 'existing' vnet (scope: resourceGroup(vnetResourceGroupName)) + subnet -> subnet.id, built like resourceId()
  subnet_id = "/subscriptions/${var.subscription_id}/resourceGroups/${var.vnet_resource_group_name}/providers/Microsoft.Network/virtualNetworks/${var.vnet_name}/subnets/${var.subnet_name}"

  rules = [for rule in var.keyvault_network_policy_subnets : {
    id                               = rule
    ignoreMissingVnetServiceEndpoint = true
  }]

  key_vault_properties = merge(
    {
      enabledForDeployment         = true # VMs can retrieve certificates
      enabledForTemplateDeployment = true # ARM can retrieve values
      enableRbacAuthorization      = true # Azure RBAC on every vault; access is granted with role assignments (kv-rbac-principals)
      enabledForDiskEncryption     = false
      enableSoftDelete             = true
      enablePurgeProtection        = var.enable_purge_protection
      # If Disabled, it overrides the firewall rules: even if ip rules are present they are not honored.
      publicNetworkAccess = (var.enable_public_access_with_perimeter || var.allow_public_access_when_behind_vnet || var.enable_public_gen_ai_access) ? "Enabled" : "Disabled"
      tenantId            = var.tenant_identity
      sku = {
        name   = "standard"
        family = "A"
      }
    },
    # Bicep: softDeleteRetentionInDays: enablePurgeProtection ? soft_delete_days : null (left out when null).
    # Cannot update this later: "softDeleteRetentionInDays has been set already and it can't be modified."
    var.enable_purge_protection ? { softDeleteRetentionInDays = var.soft_delete_days } : {},
    # Bicep: networkAcls: !enablePublicAccessWithPerimeter ? {...} : null (left out when null)
    !var.enable_public_access_with_perimeter ? {
      networkAcls = {
        bypass              = "AzureServices"
        defaultAction       = var.enable_public_access_with_perimeter ? "Allow" : "Deny"
        ipRules             = var.ip_rules
        virtualNetworkRules = local.rules
      }
    } : {}
  )

  # Secrets: the list is sensitive (it carries values); the names are not, and key the resources.
  secret_names    = nonsensitive([for s in var.secrets : s.name])
  secrets_by_name = { for s in var.secrets : s.name => s }
}

# azapi (exact type + API version of the Bicep): azurerm_key_vault cannot express
# networkAcls.virtualNetworkRules[].ignoreMissingVnetServiceEndpoint = true (it always sends the rule without it, i.e.
# false, so a BYO subnet without the Microsoft.KeyVault service endpoint fails), and it makes data-plane calls
# (vault URI reachability poll, certificate contacts read) that a private vault does not need from ARM.
resource "azapi_resource" "key_vault" {
  type      = "Microsoft.KeyVault/vaults@2024-11-01"
  name      = var.keyvault_name
  parent_id = local.resource_group_id
  location  = var.location
  tags      = var.tags

  body = {
    properties = local.key_vault_properties
  }

  response_export_values = ["properties.vaultUri"]
}

# Create secrets in the Key Vault.
# azapi through the ARM control plane (Microsoft.KeyVault/vaults/secrets, exact type + API version of the Bicep): the
# vault is private (publicNetworkAccess Disabled), so a data-plane azurerm_key_vault_secret would fail from a CI runner.
resource "azapi_resource" "key_vault_secrets" {
  for_each = toset(local.secret_names)

  type      = "Microsoft.KeyVault/vaults/secrets@2024-11-01"
  name      = each.key
  parent_id = azapi_resource.key_vault.id

  body = {
    properties = {
      value       = local.secrets_by_name[each.key].value
      contentType = try(local.secrets_by_name[each.key].contentType, "text/plain")
      # Every secret expires on the shared date unless the caller sets its own exp.
      attributes = merge({
        enabled = true
        exp     = var.key_vault_secret_expiry
      }, try(local.secrets_by_name[each.key].attributes, {}))
    }
  }

  # ARM never returns the secret value; do not show it as drift.
  ignore_missing_property = true
}

resource "azurerm_private_endpoint" "pend_keyv" {
  name                          = var.private_endpoint_name
  location                      = var.location
  resource_group_name           = var.resource_group_name
  tags                          = var.tags
  subnet_id                     = local.subnet_id
  custom_network_interface_name = "${var.private_endpoint_name}-nic"

  # Bicep sets privateLinkServiceConnectionState Approved / Auto-Approved: an automatic (non-manual) connection to a
  # resource the caller owns is approved by ARM with exactly that state.
  private_service_connection {
    name                           = var.private_endpoint_name
    private_connection_resource_id = azapi_resource.key_vault.id
    subresource_names              = ["vault"]
    is_manual_connection           = false
  }

  # 13-rgLevel attaches the DNS zone group with privateDns.bicep (modules/private-dns); azurerm would remove it.
  lifecycle {
    ignore_changes = [private_dns_zone_group]
  }
}

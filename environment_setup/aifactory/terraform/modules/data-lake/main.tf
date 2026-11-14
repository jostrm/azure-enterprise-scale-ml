# Port of environment_setup/aifactory/bicep/modules/dataLake.bicep

# Resource group scope (the module deploys into var.resource_group_name).

locals {
  resource_group_id = "/subscriptions/${var.subscription_id}/resourceGroups/${var.resource_group_name}"
  # Bicep 'existing' vnet (scope: resourceGroup(vnetResourceGroupName)) + subnet -> subnet.id, built like resourceId()
  subnet_id = "/subscriptions/${var.subscription_id}/resourceGroups/${var.vnet_resource_group_name}/providers/Microsoft.Network/virtualNetworks/${var.vnet_name}/subnets/${var.subnet_name}"

  # Bicep: cmk && !empty(cmkIdentityId) ? UserAssigned { cmkIdentityId } : { type: 'None' }
  use_cmk_identity = var.cmk && var.cmk_identity_id != ""

  group_ids = [
    { name = var.blob_private_endpoint_name, gid = "blob" },
    { name = var.file_private_endpoint_name, gid = "file" },
    { name = var.dfs_private_endpoint_name, gid = "dfs" },
    { name = var.queue_private_endpoint_name, gid = "queue" },
    { name = var.table_private_endpoint_name, gid = "table" },
  ]

  encryption = merge(
    {
      keySource = var.cmk ? "Microsoft.Keyvault" : "Microsoft.Storage"
      services = {
        blob = {
          enabled = true
          keyType = "Account"
        }
        file = {
          enabled = true
          keyType = "Account"
        }
        queue = {
          enabled = true
          keyType = "Service"
        }
        table = {
          enabled = true
          keyType = "Service"
        }
      }
    },
    # Bicep: identity / keyvaultproperties are null (left out) unless cmk
    var.cmk ? {
      identity = {
        userAssignedIdentity = var.cmk_identity_id
      }
      keyvaultproperties = {
        keyname     = var.cmk_key_name
        keyvaulturi = var.cmk_key_vault_uri
      }
    } : {}
  )
}

# azapi (exact type + API version of the Bicep): azurerm_storage_account (5.12.0) cannot express
# keyPolicy.keyExpirationPeriodInDays (access keys rotation reminder), and its customer_managed_key needs a key ID
# instead of the Bicep's keyname + keyvaulturi pair. blobServices/fileServices have no standalone azurerm resource.
resource "azapi_resource" "lake" {
  type      = "Microsoft.Storage/storageAccounts@2023-05-01"
  name      = var.storage_account_name # esmldatalake002dev
  parent_id = local.resource_group_id
  location  = var.location
  tags      = var.tags

  identity {
    type         = local.use_cmk_identity ? "UserAssigned" : "None"
    identity_ids = local.use_cmk_identity ? [var.cmk_identity_id] : null
  }

  body = {
    sku = {
      name = var.sku_name
    }
    kind = "StorageV2"
    properties = {
      allowBlobPublicAccess = false
      publicNetworkAccess   = "Disabled"
      accessTier            = "Hot"
      isHnsEnabled          = true # DATALAKE
      # allowCrossTenantReplication / isNfsV3Enabled: not supported with DATALAKE (not set, as in the Bicep)
      allowSharedKeyAccess = !(contains(keys(var.tags), "AIF-Persona-Access") && lookup(var.tags, "AIF-Persona-Access", "") == "groups-v1")
      encryption           = local.encryption
      keyPolicy = {
        keyExpirationPeriodInDays = var.key_expiration_period_in_days
      }
      largeFileSharesState     = "Disabled"
      minimumTlsVersion        = "TLS1_2"
      supportsHttpsTrafficOnly = true
      networkAcls = {
        bypass        = "AzureServices"
        defaultAction = "Deny"
        ipRules = [for ip in var.ip_whitelist_array : {
          action = "Allow"
          value  = ip
        }]
        virtualNetworkRules = [for snet_id in var.virtual_network_rules_array : {
          action = "Allow"
          id     = snet_id
        }]
      }
    }
  }

  response_export_values = ["properties.networkAcls.virtualNetworkRules"]
}

# blobServices/default and fileServices/default exist as soon as the account does: PUT them with azapi_update_resource
# (same type, name and body as the Bicep child resources) instead of creating them.
resource "azapi_update_resource" "blob_services" {
  count     = length(var.containers) > 0 ? 1 : 0
  type      = "Microsoft.Storage/storageAccounts/blobServices@2023-05-01"
  name      = "default"
  parent_id = azapi_resource.lake.id

  body = {
    properties = {
      cors = {
        corsRules = var.cors_rules
      }
      deleteRetentionPolicy = {
        enabled = true
        days    = var.delete_retention_policy
      }
    }
  }
}

# Containers through the management plane (Microsoft.Storage/storageAccounts/blobServices/containers): storage_account_id,
# not the data plane, because the account has publicNetworkAccess Disabled.
resource "azurerm_storage_container" "container" {
  for_each = toset(var.containers)

  name                  = each.key
  storage_account_id    = azapi_resource.lake.id
  container_access_type = "private" # publicAccess: 'None'

  depends_on = [azapi_update_resource.blob_services]
}

resource "azapi_update_resource" "file_services" {
  count     = length(var.files) > 0 ? 1 : 0
  type      = "Microsoft.Storage/storageAccounts/fileServices@2023-05-01"
  name      = "default"
  parent_id = azapi_resource.lake.id

  body = {
    properties = {
      cors = {
        corsRules = var.cors_rules
      }
      shareDeleteRetentionPolicy = {
        enabled = true
        days    = var.delete_retention_policy
      }
    }
  }
}

# pendSaccBlob, pendSaccFile, pendSaccDfs, pendSaccQ, pendSaccTable (one private endpoint per sub-resource)
resource "azurerm_private_endpoint" "pend_sacc" {
  for_each = { for g in local.group_ids : g.gid => g.name }

  name                          = each.value
  location                      = var.location
  resource_group_name           = var.resource_group_name
  tags                          = var.tags
  subnet_id                     = local.subnet_id
  custom_network_interface_name = "${each.value}-nic"

  # Bicep sets privateLinkServiceConnectionState Approved / Auto-Approved: an automatic (non-manual) connection to a
  # resource the caller owns is approved by ARM with exactly that state.
  private_service_connection {
    name                           = each.value
    private_connection_resource_id = azapi_resource.lake.id
    subresource_names              = [each.key]
    is_manual_connection           = false
  }

  # 13-rgLevel attaches the DNS zone group with privateDns.bicep (modules/private-dns); azurerm would remove it.
  lifecycle {
    ignore_changes = [private_dns_zone_group]
  }
}

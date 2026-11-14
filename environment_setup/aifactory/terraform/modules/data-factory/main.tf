# Port of environment_setup/aifactory/bicep/modules/dataFactory.bicep
# (The Bicep imports managedIdentityAllType from br/public:avm/utl/types/avm-common-types:0.5.1 for the type of
# managedIdentities only; that type is the managed_identities variable object here.)

locals {
  project_uami_credential_name = "ls_cred_project_uami"
  subnet_ref                   = "${var.vnet_id}/subnets/${var.subnet_name}"

  group_ids = [
    {
      name = var.portal_private_endpoint_name
      gid  = "portal"
    },
    {
      name = var.runtime_private_endpoint_name
      gid  = "dataFactory"
    },
  ]

  # Merge any caller-provided UAMIs with the project UAMI (needed for the linked-service credential). union() == distinct(concat()).
  caller_user_assigned_resource_ids = var.managed_identities == null ? [] : var.managed_identities.user_assigned_resource_ids
  all_user_assigned_resource_ids = distinct(concat(
    local.caller_user_assigned_resource_ids,
    var.project_uami_resource_id == "" ? [] : [var.project_uami_resource_id],
  ))
  has_system_assigned = var.managed_identities == null ? false : var.managed_identities.system_assigned
  has_user_assigned   = length(local.all_user_assigned_resource_ids) > 0
  identity_type = (var.managed_identities == null && var.project_uami_resource_id == "") ? "SystemAssigned" : (
    local.has_system_assigned
    ? (local.has_user_assigned ? "SystemAssigned, UserAssigned" : "SystemAssigned")
    : (local.has_user_assigned ? "UserAssigned" : "None")
  )

  factory_id = azurerm_data_factory.adf.id

  deploy_ls = var.deploy_linked_services && var.project_uami_resource_id != ""
  credential_reference = {
    referenceName = local.project_uami_credential_name
    type          = "CredentialReference"
  }
}

resource "azurerm_data_factory" "adf" {
  name                   = var.name
  location               = var.location
  resource_group_name    = var.resource_group_name
  tags                   = var.tags
  public_network_enabled = var.enable_public_access_with_perimeter # publicNetworkAccess Enabled/Disabled
  # globalParameters: {} -> no global_parameter blocks.

  # Microsoft.DataFactory/factories/managedVirtualNetworks 'default' (properties {}): azurerm PUTs this child when
  # managed_virtual_network_enabled is true.
  managed_virtual_network_enabled = var.enable_managed_vnet

  # encryption: identity.userAssignedIdentity = managedIdentities.userAssignedResourceIds[0], keyName, keyVersion '',
  # vaultBaseUrl = keyVaultUri. A versionless key ID gives the same keyVersion '' and vaultBaseUrl.
  customer_managed_key_id          = var.cmk ? "${trimsuffix(var.key_vault_uri, "/")}/keys/${var.cmk_key_name}" : null
  customer_managed_key_identity_id = var.cmk ? var.managed_identities.user_assigned_resource_ids[0] : null

  # identity type 'None' -> no identity block.
  dynamic "identity" {
    for_each = local.identity_type == "None" ? [] : [local.identity_type]
    content {
      type         = identity.value
      identity_ids = local.has_user_assigned ? local.all_user_assigned_resource_ids : null
    }
  }
}

# Managed VNet + AutoResolve managed Integration Runtime. Declaring AutoResolveIntegrationRuntime with a
# managedVirtualNetwork reference makes ADF's default IR run inside the managed VNet, so linked services that use it
# (the default) route through the managed private endpoints below.
# azapi: azurerm_data_factory_integration_runtime_azure always sends dataFlowProperties (compute_type, core_count,
# time_to_live_min, cleanup defaults); the Bicep sends only computeProperties.location = 'AutoResolve'.
resource "azapi_resource" "adf_auto_resolve_ir" {
  count     = var.enable_managed_vnet ? 1 : 0
  type      = "Microsoft.DataFactory/factories/integrationRuntimes@2018-06-01"
  name      = "AutoResolveIntegrationRuntime"
  parent_id = local.factory_id
  body = {
    properties = {
      type = "Managed"
      managedVirtualNetwork = {
        type          = "ManagedVirtualNetworkReference"
        referenceName = "default"
      }
      typeProperties = {
        computeProperties = {
          location = "AutoResolve"
        }
      }
    }
  }
}

# Managed private endpoints (egress to the data stores). Pending until approved on each target resource - emitted
# via the managed_private_endpoints output. Created one after the other, as in the Bicep.
resource "azurerm_data_factory_managed_private_endpoint" "mpe_key_vault" {
  count              = var.enable_managed_vnet && var.managed_pe_key_vault_resource_id != "" ? 1 : 0
  name               = "mpe_keyvault"
  data_factory_id    = local.factory_id
  target_resource_id = var.managed_pe_key_vault_resource_id
  subresource_name   = "vault"

  depends_on = [azapi_resource.adf_auto_resolve_ir]
}

resource "azurerm_data_factory_managed_private_endpoint" "mpe_storage" {
  count              = var.enable_managed_vnet && var.managed_pe_storage_resource_id != "" ? 1 : 0
  name               = "mpe_storage_lake"
  data_factory_id    = local.factory_id
  target_resource_id = var.managed_pe_storage_resource_id
  subresource_name   = "dfs"

  depends_on = [azapi_resource.adf_auto_resolve_ir, azurerm_data_factory_managed_private_endpoint.mpe_key_vault]
}

resource "azurerm_data_factory_managed_private_endpoint" "mpe_cosmos" {
  count              = var.enable_managed_vnet && var.managed_pe_cosmos_resource_id != "" ? 1 : 0
  name               = "mpe_cosmosdb"
  data_factory_id    = local.factory_id
  target_resource_id = var.managed_pe_cosmos_resource_id
  subresource_name   = "Sql"

  depends_on = [azapi_resource.adf_auto_resolve_ir, azurerm_data_factory_managed_private_endpoint.mpe_storage]
}

resource "azurerm_data_factory_managed_private_endpoint" "mpe_function" {
  count              = var.enable_managed_vnet && var.enable_function_linked_service && var.managed_pe_function_resource_id != "" ? 1 : 0
  name               = "mpe_function"
  data_factory_id    = local.factory_id
  target_resource_id = var.managed_pe_function_resource_id
  subresource_name   = "sites"

  depends_on = [azapi_resource.adf_auto_resolve_ir, azurerm_data_factory_managed_private_endpoint.mpe_cosmos]
}

# Credential (ManagedIdentity) referencing the project UAMI
resource "azurerm_data_factory_credential_user_managed_identity" "adf_project_uami_credential" {
  count           = local.deploy_ls ? 1 : 0
  name            = local.project_uami_credential_name
  data_factory_id = local.factory_id
  identity_id     = var.project_uami_resource_id
}

# Linked Services (authenticated via the project UAMI credential).
# azapi: the azurerm linked-service resources (key_vault, data_lake_storage_gen2, cosmosdb, azure_function) cannot
# reference a factory credential (typeProperties.credential CredentialReference) nor use authentication 'MSI' with a
# credential for AzureFunction.
resource "azapi_resource" "ls_key_vault" {
  count     = local.deploy_ls && var.linked_service_key_vault_name != "" ? 1 : 0
  type      = "Microsoft.DataFactory/factories/linkedservices@2018-06-01"
  name      = "ls_keyvault"
  parent_id = local.factory_id
  body = {
    properties = {
      type        = "AzureKeyVault"
      description = "Key Vault linked service (project UAMI)"
      typeProperties = {
        baseUrl    = "https://${var.linked_service_key_vault_name}${var.key_vault_dns_suffix}/"
        credential = local.credential_reference
      }
    }
  }

  depends_on = [azurerm_data_factory_credential_user_managed_identity.adf_project_uami_credential]
}

resource "azapi_resource" "ls_storage" {
  count     = local.deploy_ls && var.linked_service_storage_account_name != "" ? 1 : 0
  type      = "Microsoft.DataFactory/factories/linkedservices@2018-06-01"
  name      = "ls_storage_lake"
  parent_id = local.factory_id
  body = {
    properties = {
      type        = "AzureBlobFS"
      description = "ADLS Gen2 storage linked service (project UAMI)"
      typeProperties = {
        url        = "https://${var.linked_service_storage_account_name}.dfs.${var.storage_suffix}"
        credential = local.credential_reference
      }
    }
  }

  depends_on = [azurerm_data_factory_credential_user_managed_identity.adf_project_uami_credential]
}

resource "azapi_resource" "ls_cosmos" {
  count     = local.deploy_ls && var.linked_service_cosmos_db_name != "" && var.linked_service_cosmos_db_database != "" ? 1 : 0
  type      = "Microsoft.DataFactory/factories/linkedservices@2018-06-01"
  name      = "ls_cosmosdb"
  parent_id = local.factory_id
  body = {
    properties = {
      type        = "CosmosDb"
      description = "Cosmos DB linked service (project UAMI)"
      typeProperties = {
        accountEndpoint = "https://${var.linked_service_cosmos_db_name}.documents.azure.com:443/"
        database        = var.linked_service_cosmos_db_database
        credential      = local.credential_reference
      }
    }
  }

  depends_on = [azurerm_data_factory_credential_user_managed_identity.adf_project_uami_credential]
}

resource "azapi_resource" "ls_function" {
  count     = local.deploy_ls && var.enable_function_linked_service && var.linked_service_function_app_name != "" && var.linked_service_function_resource_id != "" ? 1 : 0
  type      = "Microsoft.DataFactory/factories/linkedservices@2018-06-01"
  name      = "ls_function"
  parent_id = local.factory_id
  body = {
    properties = {
      type        = "AzureFunction"
      description = "Azure Function linked service (project UAMI)"
      typeProperties = {
        functionAppUrl = "https://${var.linked_service_function_app_name}.azurewebsites.net"
        authentication = "MSI"
        resourceId     = var.linked_service_function_resource_id
        credential     = local.credential_reference
      }
    }
  }

  depends_on = [azurerm_data_factory_credential_user_managed_identity.adf_project_uami_credential]
}

# Private endpoints (portal + dataFactory), only when public access is off.
resource "azurerm_private_endpoint" "pend_adf" {
  for_each                      = var.enable_public_access_with_perimeter ? {} : { for obj in local.group_ids : obj.gid => obj }
  name                          = "${var.name}-${each.key}-pend"
  location                      = var.location
  resource_group_name           = var.resource_group_name
  tags                          = var.tags
  subnet_id                     = local.subnet_ref
  custom_network_interface_name = "${var.name}-${each.key}-pend-nic"

  # privateLinkServiceConnectionState Approved/'Auto-Approved' is set by the platform for an automatic
  # (non-manual) connection; azurerm has no argument for it.
  private_service_connection {
    name                           = "${var.name}-${each.key}-pend"
    private_connection_resource_id = azurerm_data_factory.adf.id
    subresource_names              = [each.key]
    is_manual_connection           = false
  }

  # The DNS zone group is attached by the private-dns module (dns_config output), as in the Bicep.
  lifecycle {
    ignore_changes = [private_dns_zone_group]
  }
}

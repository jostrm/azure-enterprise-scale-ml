# Port of environment_setup/aifactory/bicep/esml-common/modules-common/vNetCommon.bicep

# azapi with the Bicep's exact types/API versions: the subnets set serviceEndpoints[].locations (Microsoft.KeyVault
# pinned to [location]), which neither azurerm_virtual_network inline `subnet` nor azurerm_subnet (5.12.0) can express
# (they only have service + network_identifier). The new-vNet path keeps the subnets inline in the vNet body, i.e. the
# same single PUT as the Bicep.

locals {
  resource_group_id = "/subscriptions/${var.subscription_id}/resourceGroups/${var.resource_group_name}"
  # resourceId('Microsoft.Network/virtualNetworks', vnetNameFull): same id for the created and the 'existing' (BYO) vNet
  vnet_id = "${local.resource_group_id}/providers/Microsoft.Network/virtualNetworks/${var.vnet_name_full}"

  # 'existing' NSGs (deployed by the nsg-* modules in the same resource group) -> built resource ids.
  # The Bicep's "nsg.id == '' ? null : { id: nsg.id }" is always the object form: a resourceId() is never empty.
  nsg_common_id         = "${local.resource_group_id}/providers/Microsoft.Network/networkSecurityGroups/nsg-${var.common_subnet_name}"
  nsg_bastion_id        = "${local.resource_group_id}/providers/Microsoft.Network/networkSecurityGroups/nsg-${var.common_bastion_subnet_name}"
  nsg_pbi_id            = "${local.resource_group_id}/providers/Microsoft.Network/networkSecurityGroups/nsg-${var.common_pbi_subnet_name}"
  nsg_common_scoring_id = "${local.resource_group_id}/providers/Microsoft.Network/networkSecurityGroups/nsg-${var.common_subnet_name}-scoring"

  pbi_settings = {
    cidr = var.common_pbi_subnet_cidr
    delegations = [
      "Microsoft.PowerPlatform/vnetaccesslinks"
    ]
    service_endpoints = []
  }
  # '${toLower(split(split(delegation, '.')[0], '/')[0])}-del-${substring(uniqueString(common_pbi_subnet_name),0,12)}'
  pbi_delegation_name = "${lower(split("/", split(".", local.pbi_settings.delegations[0])[0])[0])}-del-${substr(module.unique_pbi_subnet_name.value, 0, 12)}"

  byo = var.byo_vnet || var.byo_subnet

  # Subnet property objects, shared by the inline (new vNet) and the BYO (separate subnet resources) paths.
  common_subnet_properties = {
    addressPrefix = var.common_subnet_cidr
    serviceEndpoints = [ # Note: If only used to TRAIN models, we can have a separate SCORING subnet, with ServiceEndpoints
      {
        locations = [
          var.location
        ]
        service = "Microsoft.KeyVault"
      },
      {
        service = "Microsoft.Storage" # Needed IF we want to add the subnet to the DATALAKE firewall ("virtualNetworkRules")
      },
      {
        service = "Microsoft.CognitiveServices" # Needed for AI Foundry V2 (2025)
      },
    ]
    networkSecurityGroup = {
      id = local.nsg_common_id
    }
    privateEndpointNetworkPolicies    = "Disabled"
    privateLinkServiceNetworkPolicies = "Disabled"
  }
  scoring_subnet_properties = { # Note: Here we need ServiceEndpoints (KV, Storage. Optional: ContainerRegistry)
    addressPrefix                     = var.common_subnet_scoring_cidr
    privateEndpointNetworkPolicies    = "Disabled"
    privateLinkServiceNetworkPolicies = "Disabled"
    serviceEndpoints = [
      {
        service = "Microsoft.KeyVault" # Needed: KV and Storage for AKS and Batch scoring
      },
      {
        service = "Microsoft.ContainerRegistry" # Optional
      },
      {
        service = "Microsoft.Storage"
      },
    ]
    networkSecurityGroup = {
      id = local.nsg_common_scoring_id
    }
  }
  pbi_subnet_properties = {
    addressPrefix    = var.common_pbi_subnet_cidr
    serviceEndpoints = []
    delegations = [
      {
        properties = {
          serviceName = local.pbi_settings.delegations[0]
        }
        name = local.pbi_delegation_name
      },
    ]
    networkSecurityGroup = {
      id = local.nsg_pbi_id
    }
  }
  bastion_subnet_properties = {
    addressPrefix    = var.common_bastion_subnet_cidr
    serviceEndpoints = []
    delegations      = []
    networkSecurityGroup = {
      id = local.nsg_bastion_id
    }
  }
}

module "unique_pbi_subnet_name" {
  source = "../arm-unique-string"
  values = [var.common_pbi_subnet_name]
}

# Create new vNet with subnets when byoVnet and byoSubnet are both false
resource "azapi_resource" "virtual_network" {
  count = !var.byo_vnet && !var.byo_subnet ? 1 : 0

  type      = "Microsoft.Network/virtualNetworks@2021-03-01"
  name      = var.vnet_name_full
  parent_id = local.resource_group_id
  location  = var.location
  tags      = var.tags

  body = {
    properties = {
      addressSpace = {
        addressPrefixes = [
          var.common_vnet_cidr
        ]
      }
      subnets = [
        {
          name       = var.common_subnet_name
          properties = local.common_subnet_properties
        },
        {
          name       = "${var.common_subnet_name}-scoring"
          properties = local.scoring_subnet_properties
        },
        {
          name       = var.common_pbi_subnet_name
          properties = local.pbi_subnet_properties
        },
        {
          name       = var.common_bastion_subnet_name
          properties = local.bastion_subnet_properties
        },
      ]
    }
  }
}

# Reference existing vNet when byoVnet or byoSubnet is true: parent_id = local.vnet_id (built id, no read).
# Create subnets in existing vNet when byoVnet or byoSubnet is true (sequential, like the Bicep dependsOn chain).
resource "azapi_resource" "subnet1_byo" {
  count = local.byo ? 1 : 0

  type      = "Microsoft.Network/virtualNetworks/subnets@2021-03-01"
  name      = var.common_subnet_name
  parent_id = local.vnet_id

  body = {
    properties = local.common_subnet_properties
  }
}

resource "azapi_resource" "subnet2_byo" {
  count = local.byo ? 1 : 0

  type      = "Microsoft.Network/virtualNetworks/subnets@2021-03-01"
  name      = "${var.common_subnet_name}-scoring"
  parent_id = local.vnet_id

  body = {
    properties = local.scoring_subnet_properties
  }

  depends_on = [azapi_resource.subnet1_byo] # Ensure sequential creation to avoid conflicts
}

resource "azapi_resource" "subnet3_byo" {
  count = local.byo ? 1 : 0

  type      = "Microsoft.Network/virtualNetworks/subnets@2021-03-01"
  name      = var.common_pbi_subnet_name
  parent_id = local.vnet_id

  body = {
    properties = local.pbi_subnet_properties
  }

  depends_on = [azapi_resource.subnet2_byo]
}

resource "azapi_resource" "subnet4_byo" {
  count = local.byo ? 1 : 0

  type      = "Microsoft.Network/virtualNetworks/subnets@2021-03-01"
  name      = var.common_bastion_subnet_name
  parent_id = local.vnet_id

  body = {
    properties = local.bastion_subnet_properties
  }

  depends_on = [azapi_resource.subnet3_byo]
}

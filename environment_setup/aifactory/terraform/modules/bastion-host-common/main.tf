# Port of environment_setup/aifactory/bicep/esml-common/modules-common/bastionHostCommon.bicep

locals {
  public_ip_address_name = "ip-${var.name}"
}

resource "azurerm_public_ip" "ip_adress" {
  name                = local.public_ip_address_name
  location            = var.location
  resource_group_name = var.resource_group_name
  sku                 = "Standard"
  sku_tier            = "Regional"
  allocation_method   = "Static"
  tags                = var.tags
}

resource "azurerm_bastion_host" "bastion_cmn" {
  name                   = var.name
  location               = var.location
  resource_group_name    = var.resource_group_name
  tags                   = var.tags
  sku                    = "Standard"
  copy_paste_enabled     = true # disableCopyPaste: false
  file_copy_enabled      = true
  shareable_link_enabled = false
  tunneling_enabled      = true
  ip_connect_enabled     = false
  scale_units            = var.scale_units # 2-50 VM instances
  # Bicep dnsName: 'string' is a read-only ARM property (ignored by ARM); azurerm exposes dns_name as computed only.
  # Bicep ipConfigurations[0].id: 'IpConfBastion' is not a resource ID and is ignored by ARM.

  ip_configuration {
    name                 = "IpConf"
    subnet_id            = var.subnet_id
    public_ip_address_id = azurerm_public_ip.ip_adress.id
  }
}

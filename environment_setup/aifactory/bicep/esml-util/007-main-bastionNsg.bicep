
var common_subnet_name = 'snet-esml-cmn-001'

// Edit below
param default_common_bastion_subnet_cidr string = '10.XX.YY.0/26'
param default_tags object = {
  'Application Name': 'Enterprise Scale ML (ESML)'
  'BA ID': 'NA'
  'BCIO': 'Robin'
  'Business Area': 'NA'
  'Cost Center': '123345'
  'Resource Managed By':'The Riddler'
  'TechnicalContact': 'batman@gothamcity.dc'
  'Description': 'ESML Project in the ESML AI Factory'
}

param tags object = default_tags
param common_bastion_subnet_cidr string = default_common_bastion_subnet_cidr

// nsg-snet-esml-cmn-001
module nsgCommon '../../azure-enterprise-scale-ml/environment_setup/aifactory/bicep/esml-common/modules-common/nsgCommon.bicep' = {
  name: 'nsg-${common_subnet_name}'
  scope: resourceGroup()
  params: {
    name: 'nsg-${common_subnet_name}'
    tags: tags
    location:'westeurope'
    bastionIpRange: common_bastion_subnet_cidr
  }
}

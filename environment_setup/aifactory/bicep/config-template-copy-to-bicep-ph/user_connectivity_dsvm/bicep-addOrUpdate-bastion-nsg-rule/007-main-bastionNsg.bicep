
var common_subnet_name = 'snet-esml-cmn-001'

// Edit below
var common_bastion_subnet_cidr_v = '10.XX.YY.0/26'
var tags = {
  'Application Name': 'Enterprise Scale ML (ESML)'
  'BA ID': 'NA'
  'BCIO': 'Robin'
  'Business Area': 'NA'
  'Cost Center': '123345'
  'Resource Managed By':'The Riddler'
  'TechnicalContact': 'batman@gothamcity.dc'
  'Description': 'ESML Project in the ESML AI Factory'
  'DatabricksUIPrivate':'NO, vNet injected, using Azure backbone, data plane'
  'AMLStudioUIPrivate':'YES, private endpoints. Azure backbone 100%'
}


// nsg-snet-esml-cmn-001
module nsgCommon '../../esml-common/modules-common/nsgCommon.bicep' = {
  name: 'nsg-${common_subnet_name}'
  scope: resourceGroup()
  params: {
    name: 'nsg-${common_subnet_name}'
    tags: tags
    location:'westeurope'
    bastionIpRange: common_bastion_subnet_cidr_v
  }
}

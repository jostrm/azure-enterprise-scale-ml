@description('(Required) Specifies the name of the keyvault that is created')
param keyvaultName string

@description('(Required) Specifies the tags that will be associated with keyvault resources')
param tags object

@description('(Required) Specifies the tenant which the keyvault belongs to')
param tenantIdentity string 

@description('(Optional) Specifies an object containing network policies')
param keyvaultNetworkPolicySubnets array = []

@description('(Optional) Specifies an array of objects containing access policies')
param accessPolicies array = []

@description('(Required) Specifies the virtual network id associated with private endpoint')
param vnetId string

@description('(Required) Specifies the subnet name that will be associated with the private endpoint')
param subnetName string

@description('(Required) Specifies the private endpoint name')
param privateEndpointName string

@description('(Optional) Specifies an array of objects containing ip rules')
param ipRules array = []
@description('(Optional) Specifies number of days to keep keyvault if deleted. Retention: 7-30 days. ESML defaults to 7 days')
param soft_delete_days int = 7
@description('(Optional) Specifies number of days to keep keyvault if deleted. Retention: 7-30 days. ESML defaults to 7 days')
param enablePurgeProtection bool = true

@description('Location')
param location string =  resourceGroup().location

var subnetRef = '${vnetId}/subnets/${subnetName}'

resource keyVault 'Microsoft.KeyVault/vaults@2019-09-01' = {
  name: keyvaultName
  tags: tags
  location: location
  properties: {
    enabledForDeployment: true          // VMs can retrieve certificates
    enabledForTemplateDeployment: true  // ARM can retrieve values
    enableRbacAuthorization: false       // Using RBAC
    enabledForDiskEncryption: false
    enableSoftDelete: true
    softDeleteRetentionInDays:soft_delete_days
    enablePurgeProtection: enablePurgeProtection
    tenantId: tenantIdentity
    networkAcls: {
      bypass: 'AzureServices'
      defaultAction: 'Deny'
      ipRules: ipRules
      virtualNetworkRules: [for rule in keyvaultNetworkPolicySubnets: {
        id: rule
        ignoreMissingVnetServiceEndpoint: false
      }]
    }
    accessPolicies: accessPolicies
    sku: {
      name: 'standard'
      family: 'A'
    }
  }
}

resource pendKeyv 'Microsoft.Network/privateEndpoints@2020-07-01' = {
  name: privateEndpointName
  location: location
  tags: tags
  properties: {
    subnet: {
      id: subnetRef
      name: subnetName
    }
    privateLinkServiceConnections: [
      {
        id: 'string'
        properties: {
          privateLinkServiceId: keyVault.id
          groupIds: [
            'vault'
          ]
          privateLinkServiceConnectionState: {
            status: 'Approved'
            description: 'Compliance with network design'
          }
        }
        name: 'string'
      }
    ]
  }
}

output keyvaultId string = keyVault.id
output keyvaultName string = keyVault.name
output keyvaultUri string = keyVault.properties.vaultUri
output dnsConfig array = [
  {
    name: pendKeyv.name
    type: 'vault'
    id: keyVault.id
  }
]

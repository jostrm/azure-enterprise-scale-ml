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
param location string
param enablePublicAccessWithPerimeter bool = false
param enablePublicGenAIAccess bool = false
param vnetName string
param vnetResourceGroupName string

//var subnetRef = '${vnetId}/subnets/${subnetName}'

resource vnet 'Microsoft.Network/virtualNetworks@2024-05-01' existing = {
  name: vnetName
  scope: resourceGroup(vnetResourceGroupName)
}

resource subnet 'Microsoft.Network/virtualNetworks/subnets@2024-05-01' existing = {
  name: subnetName
  parent: vnet
}
var rules = [for rule in keyvaultNetworkPolicySubnets: {
  id: rule
  ignoreMissingVnetServiceEndpoint: true
}]

resource keyVault 'Microsoft.KeyVault/vaults@2023-07-01' = {
  name: keyvaultName
  tags: tags
  location: location
  properties: {
    enabledForDeployment: true          // VMs can retrieve certificates
    enabledForTemplateDeployment: true  // ARM can retrieve values
    enableRbacAuthorization: false       // Using RBAC
    enabledForDiskEncryption: false
    enableSoftDelete: true
    softDeleteRetentionInDays:enablePurgeProtection?soft_delete_days: null // Cannot update this: The property "softDeleteRetentionInDays" has been set already and it can't be modified.
    enablePurgeProtection: enablePurgeProtection
    publicNetworkAccess: ((enablePublicGenAIAccess && !empty(ipRules)) || enablePublicAccessWithPerimeter)?'Enabled':'Disabled'
    // Above, if Disabled, will override the set firewall rules, meaning that even if the firewall rules are present, ip allowed, we will not honor the rules.
    tenantId: tenantIdentity
    networkAcls: !enablePublicAccessWithPerimeter?{
      bypass: 'AzureServices'
      defaultAction: enablePublicAccessWithPerimeter? 'Allow':'Deny' 
      ipRules: ipRules
      virtualNetworkRules: rules
    }:null
    accessPolicies: accessPolicies
    sku: {
      name: 'standard'
      family: 'A'
    }
  }
}

resource pendKeyv 'Microsoft.Network/privateEndpoints@2023-04-01' = {
  name: privateEndpointName
  location: location
  tags: tags
  properties: {
    subnet: {
      id: subnet.id
    }
    customNetworkInterfaceName: '${privateEndpointName}-nic'
    privateLinkServiceConnections: [
      {
        name: privateEndpointName
        properties: {
          privateLinkServiceId: keyVault.id
          groupIds: [
            'vault'
          ]
          privateLinkServiceConnectionState: {
            status: 'Approved'
            description: 'Auto-Approved'
            actionsRequired: 'None'
          }
        }
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

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

resource keyVault 'Microsoft.KeyVault/vaults@2023-07-01' = if(enablePurgeProtection){
  name: keyvaultName
  tags: tags
  location: location
  properties: {
    enabledForDeployment: true          // VMs can retrieve certificates
    enabledForTemplateDeployment: true  // ARM can retrieve values
    enableRbacAuthorization: false       // Using RBAC
    enabledForDiskEncryption: false
    enableSoftDelete: true
    softDeleteRetentionInDays:soft_delete_days // Cannot update this: The property "softDeleteRetentionInDays" has been set already and it can't be modified.
    enablePurgeProtection: enablePurgeProtection
    publicNetworkAccess: 'Enabled' //'Disabled' This will override the set firewall rules, meaning that even if the firewall rules are present, ip allowed, we will not honor the rules.
    tenantId: tenantIdentity
    networkAcls: {
      bypass: 'AzureServices'
      defaultAction: 'Deny'
      ipRules: ipRules
      virtualNetworkRules: [for rule in keyvaultNetworkPolicySubnets: {
        id: rule
        ignoreMissingVnetServiceEndpoint: true // tomten false to true
      }]
    }
    accessPolicies: accessPolicies
    sku: {
      name: 'standard'
      family: 'A'
    }
  }
}
resource keyVault2 'Microsoft.KeyVault/vaults@2023-07-01' = if(!enablePurgeProtection){
  name: keyvaultName
  tags: tags
  location: location
  properties: {
    enabledForDeployment: true          // VMs can retrieve certificates
    enabledForTemplateDeployment: true  // ARM can retrieve values
    enableRbacAuthorization: false       // Using RBAC
    enabledForDiskEncryption: false
    enableSoftDelete: false
    enablePurgeProtection: false
    publicNetworkAccess: 'Enabled' //'Disabled' This will override the set firewall rules, meaning that even if the firewall rules are present, ip allowed, we will not honor the rules.
    tenantId: tenantIdentity
    networkAcls: {
      bypass: 'AzureServices'
      defaultAction: 'Deny'
      ipRules: ipRules
      virtualNetworkRules: [for rule in keyvaultNetworkPolicySubnets: {
        id: rule
        ignoreMissingVnetServiceEndpoint: true // tomten false to true
      }]
    }
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
      id: subnetRef
      name: subnetName
    }
    customNetworkInterfaceName: '${privateEndpointName}-nic'
    privateLinkServiceConnections: [
      {
        name: privateEndpointName
        properties: {
          privateLinkServiceId: (enablePurgeProtection==true)? keyVault.id: keyVault2.id
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

output keyvaultId string = (enablePurgeProtection==true)? keyVault.id: keyVault2.id
output keyvaultName string = (enablePurgeProtection==true)? keyVault.name: keyVault2.name
output keyvaultUri string =(enablePurgeProtection==true)? keyVault.properties.vaultUri: keyVault2.properties.vaultUri
output dnsConfig array = [
  {
    name: pendKeyv.name
    type: 'vault'
    id: (enablePurgeProtection==true)? keyVault.id: keyVault2.id
  }
]

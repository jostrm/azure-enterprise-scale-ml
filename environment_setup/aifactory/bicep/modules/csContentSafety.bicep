@description('ResourceID of subnet for private endpoints')
param subnetName string
param vnetName string
param csSKU string = 'S0'
param location string
param contentsafetyName string
param kind string = 'ContentSafety'
param publicNetworkAccess bool = true
param vnetRules array = []
param ipRules array = []
param pendCogSerName string
param restore bool
param vnetResourceGroupName string
param enablePublicAccessWithPerimeter bool = false

//param vnetId string
//param subnetName string
//var subnetRef = '${vnetId}/subnets/${subnetName}'
resource vnet 'Microsoft.Network/virtualNetworks@2024-05-01' existing = {
  name: vnetName
  scope: resourceGroup(vnetResourceGroupName)
}

resource subnet 'Microsoft.Network/virtualNetworks/subnets@2024-05-01' existing = {
  name: subnetName
  parent: vnet
}
var nameCleaned = toLower(replace(contentsafetyName, '-', ''))

var rules = [for rule in vnetRules: {
  id: rule
  ignoreMissingVnetServiceEndpoint: true
}]

resource contentSafetyAccount 'Microsoft.CognitiveServices/accounts@2024-10-01' = {
  name: contentsafetyName
  location: location
  kind: kind
  identity: {
    type: 'SystemAssigned'
  }
  sku: {
    name: csSKU
  }
  properties: {
    customSubDomainName: nameCleaned
    publicNetworkAccess: publicNetworkAccess || enablePublicAccessWithPerimeter? 'Enabled': 'Disabled'
    restore: restore
    restrictOutboundNetworkAccess: publicNetworkAccess || enablePublicAccessWithPerimeter? false:true
    networkAcls: !enablePublicAccessWithPerimeter ? {
      bypass:'AzureServices'
      defaultAction: 'Deny' // 'Allow':'Deny' // If not Deny, then ipRules will be ignored.
      virtualNetworkRules: rules
      ipRules: ipRules
    } : null
  }
  
}

resource pendCognitiveServices 'Microsoft.Network/privateEndpoints@2023-04-01' = if(!enablePublicAccessWithPerimeter){
  location: location
  name: '${contentsafetyName}-pend'
  properties: {
    subnet: {
      id: subnet.id
    }
    customNetworkInterfaceName: '${contentsafetyName}-pend-nic'
    privateLinkServiceConnections: [
      {
        name: '${contentsafetyName}-pend'
        properties: {
          privateLinkServiceId: contentSafetyAccount.id
          groupIds: [
            'account'
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

output name string = contentSafetyAccount.name
output resourceId string = contentSafetyAccount.id
//output principalId string = contentSafetyAccount.identity.principalId // Error, "The template output 'principalId' is not valid: The language expression property 'identity' doesn't exist,

output dnsConfig array = [
  {
    name:!enablePublicAccessWithPerimeter? pendCognitiveServices.name: ''
    type: 'cognitiveservices'
    id:contentSafetyAccount.id
    groupid:'account'
  }
]

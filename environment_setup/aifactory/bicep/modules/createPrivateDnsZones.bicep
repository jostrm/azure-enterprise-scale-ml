param privDnsSubscription string
param privDnsResourceGroup string
param vNetName string
param vNetResourceGroup string
param location string
param allGlobal bool = false
var locationGlobal = 'global' // Using default Microsoft Private DNS, they are registered in global. (you can change this, but need to register, see ref01 )

param privateLinksDnsZones array = [
  {
    id: '/subscriptions/${privDnsSubscription}/resourceGroups/${privDnsResourceGroup}/providers/Microsoft.Network/privateDnsZones/privatelink.blob.${environment().suffixes.storage}'
    name: 'privatelink.blob.${environment().suffixes.storage}'
  }
  {
    id: '/subscriptions/${privDnsSubscription}/resourceGroups/${privDnsResourceGroup}/providers/Microsoft.Network/privateDnsZones/privatelink.file.${environment().suffixes.storage}'
    name: 'privatelink.file.${environment().suffixes.storage}'
  }
  {
    id: '/subscriptions/${privDnsSubscription}/resourceGroups/${privDnsResourceGroup}/providers/Microsoft.Network/privateDnsZones/privatelink.dfs.${environment().suffixes.storage}'
    name: 'privatelink.dfs.${environment().suffixes.storage}'
  }
  {
    id: '/subscriptions/${privDnsSubscription}/resourceGroups/${privDnsResourceGroup}/providers/Microsoft.Network/privateDnsZones/privatelink.queue.${environment().suffixes.storage}'
    name: 'privatelink.queue.${environment().suffixes.storage}'
  }
  {
    id: '/subscriptions/${privDnsSubscription}/resourceGroups/${privDnsResourceGroup}/providers/Microsoft.Network/privateDnsZones/privatelink.table.${environment().suffixes.storage}'
    name: 'privatelink.table.${environment().suffixes.storage}'
  }
  {
    id: '/subscriptions/${privDnsSubscription}/resourceGroups/${privDnsResourceGroup}/providers/Microsoft.Network/privateDnsZones/privatelink.azurecr.io'
    name: 'privatelink.azurecr.io'
  }
  {
    id: '/subscriptions/${privDnsSubscription}/resourceGroups/${privDnsResourceGroup}/providers/Microsoft.Network/privateDnsZones/${location}.data.privatelink.azurecr.io'
    name: '${location}.data.privatelink.azurecr.io'
  }
  {
    id: '/subscriptions/${privDnsSubscription}/resourceGroups/${privDnsResourceGroup}/providers/Microsoft.Network/privateDnsZones/privatelink.vaultcore.azure.net'
    name: 'privatelink.vaultcore.azure.net'
  }
  {
    id: '/subscriptions/${privDnsSubscription}/resourceGroups/${privDnsResourceGroup}/providers/Microsoft.Network/privateDnsZones/privatelink.api.azureml.ms'
    name: 'privatelink.api.azureml.ms'
  }
  {
    id: '/subscriptions/${privDnsSubscription}/resourceGroups/${privDnsResourceGroup}/providers/Microsoft.Network/privateDnsZones/privatelink.notebooks.azure.net'
    name: 'privatelink.notebooks.azure.net'
  }
  {
    id: '/subscriptions/${privDnsSubscription}/resourceGroups/${privDnsResourceGroup}/providers/Microsoft.Network/privateDnsZones/privatelink.datafactory.azure.net'
    name: 'privatelink.datafactory.azure.net'
  }
  {
    id: '/subscriptions/${privDnsSubscription}/resourceGroups/${privDnsResourceGroup}/providers/Microsoft.Network/privateDnsZones/privatelink.adf.azure.com'
    name: 'privatelink.adf.azure.com'
  }
  {
    id: '/subscriptions/${privDnsSubscription}/resourceGroups/${privDnsResourceGroup}/providers/Microsoft.Network/privateDnsZones/privatelink.openai.azure.com'
    name: 'privatelink.openai.azure.com'
  }
  {
    id: '/subscriptions/${privDnsSubscription}/resourceGroups/${privDnsResourceGroup}/providers/Microsoft.Network/privateDnsZones/privatelink.cognitiveservices.azure.com'
    name: 'privatelink.cognitiveservices.azure.com'
  }
  {
    id: '/subscriptions/${privDnsSubscription}/resourceGroups/${privDnsResourceGroup}/providers/Microsoft.Network/privateDnsZones/privatelink.search.windows.net'
    name: 'privatelink.search.windows.net'
  }
  {
    id: '/subscriptions/${privDnsSubscription}/resourceGroups/${privDnsResourceGroup}/providers/Microsoft.Network/privateDnsZones/scm.privatelink.azurewebsites.net'
    name: 'scm.privatelink.azurewebsites.net'
  }
  {
    id: '/subscriptions/${privDnsSubscription}/resourceGroups/${privDnsResourceGroup}/providers/Microsoft.Network/privateDnsZones/privatelink.azurewebsites.net'
    name: 'privatelink.azurewebsites.net'
  }
  {
    id: '/subscriptions/${privDnsSubscription}/resourceGroups/${privDnsResourceGroup}/providers/Microsoft.Network/privateDnsZones/privatelink.documents.azure.com'
    name: 'privatelink.documents.azure.com'
  }
  {
    id: '/subscriptions/${privDnsSubscription}/resourceGroups/${privDnsResourceGroup}/providers/Microsoft.Network/privateDnsZones/privatelink.azuredatabricks.net'
    name: 'privatelink.azuredatabricks.net'
  }
  {
    id: '/subscriptions/${privDnsSubscription}/resourceGroups/${privDnsResourceGroup}/providers/Microsoft.Network/privateDnsZones/privatelink.servicebus.windows.net'
    name: 'privatelink.servicebus.windows.net'
  }
  {
    id: '/subscriptions/${privDnsSubscription}/resourceGroups/${privDnsResourceGroup}/providers/Microsoft.Network/privateDnsZones/privatelink.eventgrid.azure.net'
    name: 'privatelink.eventgrid.azure.net'
  }
  {
    id: '/subscriptions/${privDnsSubscription}/resourceGroups/${privDnsResourceGroup}/providers/Microsoft.Network/privateDnsZones/privatelink.monitor.azure.com'
    name: 'privatelink.monitor.azure.com'
  }
  {
    id: '/subscriptions/${privDnsSubscription}/resourceGroups/${privDnsResourceGroup}/providers/Microsoft.Network/privateDnsZones/privatelink.oms.opinsights.azure.com'
    name: 'privatelink.oms.opinsights.azure.com'
  }
  {
    id: '/subscriptions/${privDnsSubscription}/resourceGroups/${privDnsResourceGroup}/providers/Microsoft.Network/privateDnsZones/privatelink.ods.opinsights.azure.com'
    name: 'privatelink.ods.opinsights.azure.com'
  }
  {
    id: '/subscriptions/${privDnsSubscription}/resourceGroups/${privDnsResourceGroup}/providers/Microsoft.Network/privateDnsZones/privatelink.agentsvc.azure-automation.net'
    name: 'privatelink.agentsvc.azure-automation.net'
  }
]

resource vnet 'Microsoft.Network/virtualNetworks@2024-05-01' existing = {
  name: vNetName
  scope: resourceGroup(vNetResourceGroup)
}

resource privateDnsZones 'Microsoft.Network/privateDnsZones@2024-06-01' = [for zone in privateLinksDnsZones: {
  name: zone.name
  location: (zone.name != '${location}.data.privatelink.azurecr.io' || allGlobal)? locationGlobal: location
  properties: {}
  // etag:''
  // tags:tags
}]

resource filePrivateDnsZoneVnetLinkLoop 'Microsoft.Network/privateDnsZones/virtualNetworkLinks@2024-06-01'  =[for i in range(0, length(privateLinksDnsZones)): {
  dependsOn:[
    privateDnsZones[i]
  ]
  name: '${privateDnsZones[i].name}/${uniqueString(privateDnsZones[i].id)}'
  location: (privateDnsZones[i].name != '${location}.data.privatelink.azurecr.io' || allGlobal)? locationGlobal: location
  properties: {
    registrationEnabled: false // Is auto-registration of virtual machine records in the virtual network in the Private DNS zone enabled?
    resolutionPolicy: 'NxDomainRedirect' // The resolution policy for the private DNS zone. Possible values include: 'Default', 'NxDomainRedirect'
    virtualNetwork: {
      id: vnet.id
    }
  }
}]

param privDnsSubscription string
param privDnsResourceGroup string
param location string

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

resource privateDnsZones 'Microsoft.Network/privateDnsZones@2020-06-01' = [for zone in privateLinksDnsZones: {
  name: zone.name
  location: 'global'
  properties: {}
}]

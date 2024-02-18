@description('Specifies the name of the log analytics workspace')
param name string

@description('Specifies a key valuue pair object that represents the tags applied to log analytics workspace')
param tags object

@description('Specifies the location of the log analytics workspace')
param location string
@allowed([
  'Free'
  'Standalone'
  'PerNode'
  'PerGB2018'
])
@description('Service Tier: Free, Standalone, PerNode, or PerGB2018')
param sku string ='PerGB2018' //'Standalone'


@minValue(7)
@maxValue(730)
@description('Number of days of retention. Free plans can only have 7 days, Standalone and Log Analytics plans include 30 days for free')
param logAnalyticsWkspRentationDays int = 30

resource alyt 'Microsoft.OperationalInsights/workspaces@2020-08-01' = {
  name: name
  tags: tags
  location: location
  properties: {
    sku: {
      name: sku
    }
    retentionInDays: logAnalyticsWkspRentationDays
    workspaceCapping: {
      dailyQuotaGb: -1
    }
    publicNetworkAccessForIngestion: 'Enabled'
    publicNetworkAccessForQuery: 'Disabled'
  }
}

var keyObj = listKeys(resourceId('Microsoft.OperationalInsights/workspaces', name), '2020-10-01')

// output logAnalyticsWkspId string = wsSearch.id
output logAnalyticsWkspId string = alyt.id
output primarySharedKey string = keyObj.primarySharedKey
output secondarySharedKey string = keyObj.secondarySharedKey

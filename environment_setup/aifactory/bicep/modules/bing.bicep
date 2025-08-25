metadata description = 'Creates a Bing Search Grounding instance.'
param name string
param location string = 'global'
param sku string = 'G1' // G1
param tags object

//resource bing 'Microsoft.Bing/accounts@2020-06-10' = {
#disable-next-line BCP081
resource bing 'Microsoft.Bing/accounts@2025-05-01-preview' = {
  name: name
  location: location
  //type: 'Microsoft.Bing/accounts'
  kind: 'Bing.Grounding'
  // "[if(contains(parameters('tagValues'), 'Microsoft.Bing/accounts'), parameters('tagValues')['Microsoft.Bing/accounts'], json('{}'))]",
  tags: (contains(tags, 'Microsoft.Bing/accounts') ? tags['Microsoft.Bing/accounts'] : json('{}'))
  sku: {
    name: sku
  }
  properties: {
    responsibleAiNotice: 'Acknowledged'
    statisticsEnabled: false
    restrictOutboundNetworkAccess: false
    publicNetworkAccess: 'Enabled' // Disabled
  }
}

#disable-next-line outputs-should-not-contain-secrets
output bingApiKey string = bing.listKeys().key1
output endpoint string = 'https://api.bing.microsoft.com/'
output bingName string = bing.name

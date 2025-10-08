metadata description = 'Creates a Bing Search Grounding instance.'

@description('The name of the Bing Search resource')
param name string
param nameCustom string = '${name}-custom'

@description('The location where the Bing Search resource should be deployed')
param location string = 'global'

@description('The SKU for standard Bing Search')
param sku string = 'G1' // G1

@description('The SKU for custom Bing Search')
param skuCustom string = 'G2'

@description('Tags to apply to the resources')
param tags object

@description('Whether to enable Bing Custom Search')
param enableBingCustomSearch bool = false

@description('Whether to enable standard Bing Search')
param enableBing bool = false

//resource bing 'Microsoft.Bing/accounts@2020-06-10' = {
#disable-next-line BCP081
resource bing 'Microsoft.Bing/accounts@2025-05-01-preview' = if(enableBing){
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
    //responsibleAiNotice: 'Acknowledged'
    statisticsEnabled: false
    //restrictOutboundNetworkAccess: false
    //publicNetworkAccess: 'Enabled' // Disabled
  }
}

#disable-next-line BCP081
resource bingCustomSearch 'Microsoft.Bing/accounts@2020-06-10' = if(enableBingCustomSearch){
  name: nameCustom
  location: location
  kind: 'Bing.GroundingCustomSearch'
  tags: (contains(tags, 'Microsoft.Bing/accounts') ? tags['Microsoft.Bing/accounts'] : json('{}'))
  sku: {
    name: skuCustom
  }
  properties: {
    responsibleAiNotice: 'Acknowledged'
    statisticsEnabled: false
  }
}

#disable-next-line BCP422 outputs-should-not-contain-secrets
output bingApiKey string = enableBing ? bing.listKeys().key1 : ''
#disable-next-line BCP422 outputs-should-not-contain-secrets
output bingCustomSearchApiKey string = enableBingCustomSearch ? bingCustomSearch.listKeys().key1 : ''
output endpoint string = 'https://api.bing.microsoft.com/'
output bingName string = enableBing ? bing.name : ''
output bingCustomSearchName string = enableBingCustomSearch ? bingCustomSearch.name : ''

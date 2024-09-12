param csSKU string = 'S0'
param location string
param contentsafetyName string

resource contentsafetyaccount 'Microsoft.CognitiveServices/accounts@2022-03-01' = {
  name: contentsafetyName
  location: location
  kind: 'ContentSafety'
  sku: {
    name: csSKU
  }
  properties: {
  }
}

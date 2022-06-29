targetScope = 'subscription'

param rgName string
param location string
param tags object

//Why? to avoid this error message: "The managed by property of the resource group cannot be changed from its current value"
//When? If RG created with contactperson A, and other person B is set to ContactPerson, and RG needs update - error will occur if trycing to update RG.
resource commonResourceUnManaged 'Microsoft.Resources/resourceGroups@2021-04-01' = {
  name: rgName
  location: location
  tags: tags
}
output rgId string = commonResourceUnManaged.id



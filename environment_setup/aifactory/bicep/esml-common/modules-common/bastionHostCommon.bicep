@description('tags')
param tags object
@description('Name of the BASTION host')
param name string 
@description('location')
param location string = 'westeurope'
@description('2-50 VMs to support')
param scaleUnits int = 3
@description('subnet resourceId for Bastion host')
param subnetId string

var publicIpAddressName = 'ip-${name}'
resource ipAdress 'Microsoft.Network/publicIPAddresses@2021-03-01' = {
  name: publicIpAddressName
  location: location
  sku:{
    name:'Standard'
    tier:'Regional'
  }
  tags: tags
  properties:{
    publicIPAllocationMethod:'Static'
  }
}

resource bastionCmn 'Microsoft.Network/bastionHosts@2021-05-01' = {
  name: name
  location: location
  tags: tags
  sku: {
    name: 'Standard'
  }
  properties: {
    disableCopyPaste: false
    dnsName: 'string'
    enableFileCopy: true
    enableShareableLink: true
    enableTunneling: true
    enableIpConnect: false // true?
    ipConfigurations: [
      {
        id: 'IpConfBastion'
        name: 'IpConf'
        properties: {
          privateIPAllocationMethod: 'Dynamic'
          publicIPAddress: {
            id: ipAdress.id
          }
          subnet: {
            id: subnetId
          }
        }
      }
    ]
    scaleUnits: scaleUnits // 2-50 VM instances
  }
  dependsOn:[]
}

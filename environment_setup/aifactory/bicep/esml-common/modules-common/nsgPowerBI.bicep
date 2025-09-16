@description('Specifies the name of the NSG, network security group')
param name string

@description('Specifies the location where the  network security group should be deployed. Defaults to resourceGroup.location')
param location string

@description('Specifies the tags that should be applied to the network security group')
param tags object
param enableFlowLogs bool = true
param storageAccountId string = ''
param networkWatcherName string = 'NetworkWatcher_${location}'
param networkWatcherResourceGroup string = 'NetworkWatcherRG'
param flowLogRetentionDays int = 30

resource pbiNsg 'Microsoft.Network/networkSecurityGroups@2020-06-01' = {
  name: name
  location: location
  tags: tags
  properties: {
    securityRules: [
      // --- Inbound --- https://docs.microsoft.com/en-us/power-bi/enterprise/service-security-private-links
 
      // --- Outbound --- 
       {
        name: 'AzureActiveDirectory'
        properties: {
          description: 'Optional'
          protocol: 'Tcp'
          sourcePortRange: '*'
          destinationPortRange: '*'
          sourceAddressPrefix: '*'
          destinationAddressPrefix: 'AzureActiveDirectory'
          access: 'Allow'
          priority: 130
          direction: 'Outbound'
        }
      }
       {
        name: 'AzureStorageAccount'
        properties: {
          description: 'Optional'
          protocol: 'Tcp'
          sourcePortRange: '*'
          destinationPortRange: '443'
          sourceAddressPrefix: '*'
          destinationAddressPrefix: 'Storage.${location}'
          access: 'Allow'
          priority: 160
          direction: 'Outbound'
        }
      }
      {
        name: 'AzureFrontDoor'
        properties: {
          description: 'Optional'
          protocol: 'Tcp'
          sourcePortRange: '*'
          destinationPortRange: '443'
          sourceAddressPrefix: '*'
          destinationAddressPrefix: 'AzureFrontDoor.FrontEnd'
          access: 'Allow'
          priority: 170
          direction: 'Outbound'
        }
      }
    ]
  }
}

// NSG Flow Logs - Note: This requires Network Watcher to exist in the target region
resource nsgFlowLog 'Microsoft.Network/networkWatchers/flowLogs@2023-05-01' = if (enableFlowLogs && !empty(storageAccountId)) {
  name: '${networkWatcherName}/flowlog-${name}'
  location: location
  tags: tags
  properties: {
    targetResourceId: pbiNsg.id
    storageId: storageAccountId
    enabled: true
    retentionPolicy: {
      days: flowLogRetentionDays
      enabled: true
    }
    format: {
      type: 'JSON'
      version: 2
    }
  }
}

output nsgId string = pbiNsg.id
output flowLogId string = enableFlowLogs && !empty(storageAccountId) ? nsgFlowLog.id : ''

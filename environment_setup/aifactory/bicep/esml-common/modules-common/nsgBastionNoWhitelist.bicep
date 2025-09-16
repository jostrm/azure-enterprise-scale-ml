@description('Specifies the name of the NSG, network security group')
param name string

@description('Specifies the location where the network security group should be deployed. Defaults to resourceGroup.location')
param location string

@description('Specifies the tags that should be applied to the network security group')
param tags object

@description('Optional:Whitelist IP addresses from project members to see keyvault, and to connect via Bastion')
param IPwhiteList_Array string[] = []
param enableFlowLogs bool = true
param storageAccountId string = ''
param networkWatcherName string = 'NetworkWatcher_${location}'
param networkWatcherResourceGroup string = 'NetworkWatcherRG'
param flowLogRetentionDays int = 30

resource bastionNsg 'Microsoft.Network/networkSecurityGroups@2020-06-01' = {
  name: name
  location: location
  tags: tags
  properties: {
    securityRules: [
      // --- Inbound ---
      {
        name: 'Bastion_GatewayManagerInbound'
        properties: {
            description: 'Required for Bastion control plane'
            protocol: 'Tcp'
            sourcePortRange: '*'
            destinationPortRange: '443'
            sourceAddressPrefix: 'GatewayManager'
            destinationAddressPrefix: '*'
            access: 'Allow'
            priority: 530
            direction: 'Inbound'
            sourcePortRanges: []
            destinationPortRanges: []
            sourceAddressPrefixes: []
            destinationAddressPrefixes: []
        }
      }
      {
        name: 'Bastion_AzureLoadBalancerInbound'
        properties: {
            description: 'This enables Azure Load Balancer to detect connectivity'
            protocol: 'Tcp'
            sourcePortRange: '*'
            destinationPortRange: '443'
            sourceAddressPrefix: 'AzureLoadBalancer'
            destinationAddressPrefix: '*'
            access: 'Allow'
            priority: 540
            direction: 'Inbound'
            sourcePortRanges: []
            destinationPortRanges: []
            sourceAddressPrefixes: []
            destinationAddressPrefixes: []
        }
      }
      {
        name: 'Bastion_HostCommunication'
        properties: {
            description: 'Data plane communication for Azure Bastion'
            protocol: '*'
            sourcePortRange: '*'
            sourceAddressPrefix: 'VirtualNetwork'
            destinationAddressPrefix: '*'
            access: 'Allow'
            priority: 550
            direction: 'Inbound'
            sourcePortRanges: []
            destinationPortRanges: [
              '8080'
              '5701'
            ]
            sourceAddressPrefixes: []
            destinationAddressPrefixes: []
        }
      }
      // --- Outbound --- 
      {
        name: 'Bastion_SshOutbound'
        properties: {
            description: 'Reach  target VMs over private IP, to other target VM subnets for port 3389 and 22'
            protocol: '*'
            sourcePortRange: '*'
            sourceAddressPrefix: '*'
            destinationAddressPrefix: 'VirtualNetwork'
            access: 'Allow'
            priority: 140
            direction: 'Outbound'
            sourcePortRanges: []
            destinationPortRanges: [
              '22'
              '3389'
            ]
            sourceAddressPrefixes: []
            destinationAddressPrefixes: []
        }
      }
      {
        name: 'Bastion_AzureCloudOutbound'
        properties: {
            description: 'Bastion needs to be able to connect to various public endpoints within Azure for storing logs.'
            protocol: 'Tcp'
            sourcePortRange: '*'
            destinationPortRange: '443'
            sourceAddressPrefix: '*'
            destinationAddressPrefix: 'AzureCloud'
            access: 'Allow'
            priority: 150
            direction: 'Outbound'
            sourcePortRanges: []
            destinationPortRanges: []
            sourceAddressPrefixes: []
            destinationAddressPrefixes: []
        }
      }
      {
        name: 'Bastion_Communication'
        properties: {
            description: 'Data plane communication for Azure Bastion'
            protocol: '*'
            sourcePortRange: '*'
            sourceAddressPrefix: 'VirtualNetwork'
            destinationAddressPrefix: 'VirtualNetwork'
            access: 'Allow'
            priority: 160
            direction: 'Outbound'
            sourcePortRanges: []
            destinationPortRanges: [
              '8080'
              '5701'
            ]
            sourceAddressPrefixes: []
            destinationAddressPrefixes: []
        }
      }
      {
        name: 'Bastion_GetSessionInformation'
        properties: {
            description: 'Bastion needs to be able to communicate with the Internet for session and certificate validation'
            protocol: '*'
            sourcePortRange: '*'
            destinationPortRange: '80'
            sourceAddressPrefix: '*'
            destinationAddressPrefix: 'Internet'
            access: 'Allow'
            priority: 170
            direction: 'Outbound'
            sourcePortRanges: []
            destinationPortRanges: []
            sourceAddressPrefixes: []
            destinationAddressPrefixes: []
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
    targetResourceId: bastionNsg.id
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

output bastionNsgId string = bastionNsg.id
output flowLogId string = enableFlowLogs && !empty(storageAccountId) ? nsgFlowLog.id : ''

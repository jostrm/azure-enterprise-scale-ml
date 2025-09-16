/*
Azure Function App Network Security Group Rules
For Azure Function App (Premium plan with VNet integration), these security rules allow the service to function properly:

Inbound Rules
- HTTP/HTTPS traffic to Function App (ports 80/443)
- Azure Load Balancer traffic
- Function App management traffic (port 454 for SCM/Kudu)
- Default deny to block all other inbound traffic

Outbound Rules
- Access to Azure SQL (port 1433)
- Access to Azure Storage (HTTPS)
- Access to Azure Active Directory (HTTPS)
- Access to Application Insights (HTTPS)
- Access to Event Hub/Service Bus (HTTPS)
- Access to Azure Key Vault (HTTPS)
- General outbound internet access for dependencies (HTTPS)
*/

param name string
param location string
param tags object
param enableFlowLogs bool = true
param storageAccountId string = ''
param networkWatcherName string = 'NetworkWatcher_${location}'
param networkWatcherResourceGroup string = 'NetworkWatcherRG'
param flowLogRetentionDays int = 30

resource functionAppNSG 'Microsoft.Network/networkSecurityGroups@2020-06-01' = {
  name: name
  location: location
  tags: tags
  properties: {
    securityRules: [
      // --- Inbound ---
      {
        name: 'Allow-HTTP-HTTPS'
        properties: {
          description: 'Allow HTTP/HTTPS traffic to Function App'
          protocol: 'Tcp'
          sourcePortRange: '*'
          destinationPortRanges: [
            '80'
            '443'
          ]
          sourceAddressPrefix: '*'
          destinationAddressPrefix: '*'
          access: 'Allow'
          priority: 100
          direction: 'Inbound'
        }
      }
      {
        name: 'Allow-AzureLoadBalancer'
        properties: {
          description: 'Allow Azure Load Balancer inbound traffic'
          protocol: '*'
          sourcePortRange: '*'
          destinationPortRange: '*'
          sourceAddressPrefix: 'AzureLoadBalancer'
          destinationAddressPrefix: '*'
          access: 'Allow'
          priority: 110
          direction: 'Inbound'
        }
      }
      {
        name: 'Allow-AppService-Management'
        properties: {
          description: 'Allow Function App management traffic'
          protocol: 'Tcp'
          sourcePortRange: '*'
          destinationPortRange: '454'
          sourceAddressPrefix: 'AppService'
          destinationAddressPrefix: '*'
          access: 'Allow'
          priority: 120
          direction: 'Inbound'
        }
      }
      {
        name: 'Deny-All-Inbound'
        properties: {
          description: 'Deny all other inbound traffic'
          protocol: '*'
          sourcePortRange: '*'
          destinationPortRange: '*'
          sourceAddressPrefix: '*'
          destinationAddressPrefix: '*'
          access: 'Deny'
          priority: 4096
          direction: 'Inbound'
        }
      }
      // --- Outbound ---
      {
        name: 'Allow-SQL'
        properties: {
          description: 'Allow access to Azure SQL'
          protocol: 'Tcp'
          sourcePortRange: '*'
          destinationPortRange: '1433'
          sourceAddressPrefix: '*'
          destinationAddressPrefix: 'Sql'
          access: 'Allow'
          priority: 100
          direction: 'Outbound'
        }
      }
      {
        name: 'Allow-Storage'
        properties: {
          description: 'Allow access to Azure Storage'
          protocol: 'Tcp'
          sourcePortRange: '*'
          destinationPortRange: '443'
          sourceAddressPrefix: '*'
          destinationAddressPrefix: 'Storage'
          access: 'Allow'
          priority: 110
          direction: 'Outbound'
        }
      }
      {
        name: 'Allow-AAD'
        properties: {
          description: 'Allow access to Azure Active Directory'
          protocol: 'Tcp'
          sourcePortRange: '*'
          destinationPortRange: '443'
          sourceAddressPrefix: '*'
          destinationAddressPrefix: 'AzureActiveDirectory'
          access: 'Allow'
          priority: 120
          direction: 'Outbound'
        }
      }
      {
        name: 'Allow-AppInsights-AzureMonitor'
        properties: {
          description: 'Allow access to Application Insights'
          protocol: 'Tcp'
          sourcePortRange: '*'
          destinationPortRanges: ['1886', '443']
          sourceAddressPrefix: '*'
          destinationAddressPrefix: 'AzureMonitor'
          access: 'Allow'
          priority: 130
          direction: 'Outbound'
        }
      }
      {
        name: 'Allow-EventHub'
        properties: {
          description: 'Allow access to Event Hub'
          protocol: 'Tcp'
          sourcePortRange: '*'
          destinationPortRange: '443'
          sourceAddressPrefix: '*'
          destinationAddressPrefix: 'EventHub'
          access: 'Allow'
          priority: 140
          direction: 'Outbound'
        }
      }
      {
        name: 'Allow-KeyVault'
        properties: {
          description: 'Allow access to Key Vault'
          protocol: 'Tcp'
          sourcePortRange: '*'
          destinationPortRange: '443'
          sourceAddressPrefix: '*'
          destinationAddressPrefix: 'AzureKeyVault'
          access: 'Allow'
          priority: 150
          direction: 'Outbound'
        }
      }
      {
        name: 'Allow-Internet'
        properties: {
          description: 'Allow general outbound internet access for dependencies'
          protocol: 'Tcp'
          sourcePortRange: '*'
          destinationPortRange: '443'
          sourceAddressPrefix: '*'
          destinationAddressPrefix: 'Internet'
          access: 'Allow'
          priority: 160
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
    targetResourceId: functionAppNSG.id
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

output id string = functionAppNSG.id
output flowLogId string = enableFlowLogs && !empty(storageAccountId) ? nsgFlowLog.id : ''

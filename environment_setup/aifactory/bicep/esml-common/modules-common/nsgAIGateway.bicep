/*
API Management Network Security Group Rules
For API Management, you need specific security rules that allow the service to function properly. Here's the standard set of NSG rules needed:

Inbound Rules
Management endpoint access (for portal and management API)
Azure infrastructure load balancer
AllowAzureTrafficManager (only for external)
Developer portal and gateway access
Client connectivity to gateway
Outbound Rules
Access to Azure SQL
Access to Azure Storage
Access to Azure Event Hubs
Dependencies for Git
Health and monitoring dependencies
Azure Active Directory and Azure Key Vault
AllowMonitoring (for monitoring and diagnostics)
*/

param name string
param location string
param tags object

resource aiGatewayNsg 'Microsoft.Network/networkSecurityGroups@2020-06-01' = {
  name: name
  location: location
  tags: tags
  properties: {
    securityRules: [
      // --- Inbound ---
      {
        name: 'Client-Communication-To-API-Gateway'
        properties: {
          description: 'Client communication to API Gateway'
          protocol: 'Tcp'
          sourcePortRange: '*'
          destinationPortRange: '443'
          //destinationPortRanges: ['80', '443']
          sourceAddressPrefix: 'Internet'
          destinationAddressPrefix: 'VirtualNetwork'
          access: 'Allow'
          priority: 3000
          direction: 'Inbound'
        }
      }
      {
        name: 'Management-Endpoint'
        properties: {
          description: 'Allow management endpoint for API management'
          protocol: 'Tcp'
          sourcePortRange: '*'
          destinationPortRange: '3443'
          sourceAddressPrefix: 'ApiManagement'
          destinationAddressPrefix: 'VirtualNetwork'
          access: 'Allow'
          priority: 3010
          direction: 'Inbound'
        }
      }
      {
        name: 'Azure-Infrastructure-Load-Balancer'
        properties: {
          description: 'Allow Azure Infrastructure Load Balancer'
          protocol: 'Tcp'
          sourcePortRange: '*'
          destinationPortRange: '6390'
          sourceAddressPrefix: 'AzureLoadBalancer'
          destinationAddressPrefix: 'VirtualNetwork'
          access: 'Allow'
          priority: 3020
          direction: 'Inbound'
        }
      }
      {
        name: 'AllowAzureTrafficManager' //Only External
        properties: {
            protocol: 'Tcp'
            sourcePortRange: '*'
            destinationPortRange: '443'
            sourceAddressPrefix: 'AzureTrafficManager'
            destinationAddressPrefix: 'VirtualNetwork'
            access: 'Allow'
            priority: 3030
            direction: 'Inbound'
        }
      }
      
      // --- Outbound --- 
      {
        name: 'Azure-SQL-Access'
        properties: {
          description: 'Access to Azure SQL'
          protocol: 'Tcp'
          sourcePortRange: '*'
          destinationPortRange: '1433'
          sourceAddressPrefix: 'VirtualNetwork'
          destinationAddressPrefix: 'Sql'
          access: 'Allow'
          priority: 3000
          direction: 'Outbound'
        }
      }
      {
        name: 'Azure-Storage-Access'
        properties: {
          description: 'Access to Azure Storage'
          protocol: 'Tcp'
          sourcePortRange: '*'
          destinationPortRange: '443'
          sourceAddressPrefix: 'VirtualNetwork'
          destinationAddressPrefix: 'Storage'
          access: 'Allow'
          priority: 3010
          direction: 'Outbound'
        }
      }
      {
        name: 'Azure-KeyVault-Access'
        properties: {
          description: 'Access to Azure Key Vault'
          protocol: 'Tcp'
          sourcePortRange: '*'
          destinationPortRange: '443'
          sourceAddressPrefix: 'VirtualNetwork'
          destinationAddressPrefix: 'AzureKeyVault'
          access: 'Allow'
          priority: 3020
          direction: 'Outbound'
        }
      }
      {
        name: 'Azure-EventHub-Access'
        properties: {
          description: 'Access to Azure Event Hub'
          protocol: 'Tcp'
          sourcePortRange: '*'
          destinationPortRange: '5671-5672'
          sourceAddressPrefix: 'VirtualNetwork'
          destinationAddressPrefix: 'EventHub'
          access: 'Allow'
          priority: 3030
          direction: 'Outbound'
        }
      }
      {
        name: 'Internet-Dependency-Access'
        properties: {
          description: 'Access to dependencies hosted on Internet'
          protocol: 'Tcp'
          sourcePortRange: '*'
          destinationPortRange: '443'
          sourceAddressPrefix: 'VirtualNetwork'
          destinationAddressPrefix: 'Internet'
          access: 'Allow'
          priority: 3040
          direction: 'Outbound'
        }
      }
      {
        name: 'AllowMonitor'
        properties: {
            protocol: 'Tcp'
            sourcePortRange: '*'
            destinationPortRanges: ['1886', '443']
            sourceAddressPrefix: 'AzureMonitor'
            destinationAddressPrefix: 'VirtualNetwork'
            access: 'Allow'
            priority: 3050
            direction: 'Outbound'
        }
    }
    ]
  }
}

output id string = aiGatewayNsg.id

// DNS Forwarder Configuration for Azure Private Endpoints
// This module configures DNS forwarding to Azure DNS Virtual Server (168.63.129.16)

@description('Virtual Network name where DNS forwarding will be configured')
param vnetName string

@description('Resource group name containing the virtual network')
param vnetResourceGroupName string

@description('Location for resources')
param location string = resourceGroup().location

@description('Enable DNS forwarding to Azure DNS (168.63.129.16)')
param enableAzureDnsForwarding bool = true

@description('Custom DNS servers to configure (include 168.63.129.16 for Azure DNS)')
param customDnsServers array = ['168.63.129.16']

@description('List of private endpoint domains to configure forwarding for')
param privateEndpointDomains array = [
  'privatelink.openai.azure.com'
  'privatelink.cognitiveservices.azure.com'
  'privatelink.blob.${environment().suffixes.storage}'
  'privatelink.file.${environment().suffixes.storage}'
  'privatelink.documents.azure.com'
  'privatelink.search.windows.net'
  'privatelink.services.ai.azure.com'
  'privatelink.postgres.database.azure.com'
  'privatelink.redis.cache.windows.net'
  'privatelink.sql.${environment().suffixes.sqlServerHostname}'
]

// Reference existing VNet
resource vnet 'Microsoft.Network/virtualNetworks@2023-04-01' existing = {
  name: vnetName
  scope: resourceGroup(vnetResourceGroupName)
}

// Configure VNet with custom DNS servers including Azure DNS
resource vnetDnsConfig 'Microsoft.Network/virtualNetworks@2023-04-01' = if (enableAzureDnsForwarding) {
  name: vnetName
  location: location
  properties: {
    addressSpace: vnet.properties.addressSpace
    subnets: vnet.properties.subnets
    dhcpOptions: {
      dnsServers: customDnsServers
    }
  }
}

// Output configuration details
output configuredDnsServers array = enableAzureDnsForwarding ? customDnsServers : []
output privateEndpointDomains array = privateEndpointDomains
output azureDnsVirtualServer string = '168.63.129.16'

// Instructions for manual DNS server configuration
output dnsForwardingInstructions object = {
  azureDnsVirtualServer: '168.63.129.16'
  description: 'Configure your DNS servers to forward queries for the following domains to 168.63.129.16'
  domains: privateEndpointDomains
  windowsInstructions: 'Use Add-DnsServerConditionalForwarderZone PowerShell cmdlet'
  bindInstructions: 'Add conditional forwarding zones to named.conf'
}

metadata description = 'Creates an Azure SQL Server instance with a SQL Database'
param serverName string
param location string
param tags object
param keyvaultName string
param vnetName string
param subnetNamePend string
param vnetResourceGroupName string
param createPrivateEndpoint bool
param skuObject object
param version string = '12.0' // SQL Server version, default is 12.0
param minimalTlsVersion string = '1.3' // Minimal TLS version, default is 1.2

param appUser string = 'aifactory-user'
param sqlAdmin string = 'aifactory-admin'
param databaseName string ='aifdb'
param connectionStringKey string = 'aifactory-proj-sqldb-con-string'

@secure()
param sqlAdminPassword string = ''
@secure()
param appUserPassword string = ''

@description('An array of IP firewall rules to apply. Example: [ { "name": "AllowAzureServices", "startIpAddress": "0.0.0.0", "endIpAddress": "0.0.0.0" }, { "name": "AllowMyDevIP", "startIpAddress": "YOUR_IP", "endIpAddress": "YOUR_IP" } ]')
param sqlServerAllowedIpRules array = []
param allowAzureIPsFirewall bool = !createPrivateEndpoint
param allowAllIPsFirewall bool = false
param allowedSingleIPs array = []

var connectionString = 'Server=${sqlServer.properties.fullyQualifiedDomainName}; Database=${sqlServer::database.name}; User=${appUser}'
var seed = uniqueString(resourceGroup().id, subscription().subscriptionId, deployment().name)
var uppercaseLetter = substring(toUpper(seed), 0, 1)
var lowercaseLetter = substring(toLower(seed), 1, 1)
var numbers = substring(seed, 2, 4)
var specialChar = '!@#$'
var randomSpecialChar = substring(specialChar, length(seed) % length(specialChar), 1)
var randomSpecialChar2 = substring(specialChar, length(seed) % length(specialChar), 1)
var adminPwd = empty(sqlAdminPassword)? '${uppercaseLetter}${lowercaseLetter}${randomSpecialChar}${numbers}${guid(deployment().name)}': sqlAdminPassword
var userPwd = empty(appUserPassword)? '${uppercaseLetter}${lowercaseLetter}${randomSpecialChar2}${numbers}${guid(deployment().name)}': appUserPassword

resource sqlServer 'Microsoft.Sql/servers@2024-05-01-preview' = {
  name: serverName
  location: location
  tags: tags
  identity: {
    type: 'SystemAssigned'
  }
  properties: {
    version: version
    minimalTlsVersion: minimalTlsVersion
    publicNetworkAccess: createPrivateEndpoint? 'Disabled': 'Enabled'
    restrictOutboundNetworkAccess: createPrivateEndpoint? 'Enabled':'Disabled'
    administratorLogin: sqlAdmin
    administratorLoginPassword: adminPwd
  }

  resource database 'databases' = {
    name: databaseName
    location: location
    sku: !empty(skuObject) ? {
    name: skuObject.name // Ensure 'name' is provided in skuObject
    family: skuObject.family // Optional: Add other properties if needed
    size: skuObject.size // Optional: Add other properties if needed
    tier: skuObject.tier // Optional: Add other properties if needed
    capacity: skuObject.capacity // Optional: Add other properties if applicable
  } : {
    name: 'Basic' // Default SKU name
    tier: 'Basic' // Default tier
    capacity: 5 // Default capacity
    //family: 'Gen5' // Default family
  }
  }

  resource firewallAll 'firewallRules' = if(allowAllIPsFirewall && !createPrivateEndpoint) {
    name: 'sql-all-fw-rule' // Consider a more generic name if it's truly for all IPs
    properties: {
      // Allow all clients
      // Note: range [0.0.0.0-0.0.0.0] means "allow all Azure-hosted clients only".
      // This is not sufficient, because we also want to allow direct access from developer machine, for debugging purposes.
      startIpAddress: '0.0.0.1' // This allows almost all IPs, but not Azure Services specifically by this rule.
      endIpAddress: '255.255.255.254'
    }
  }
  resource firewallAzureServices 'firewallRules' = if(allowAzureIPsFirewall&& !createPrivateEndpoint){ // Changed condition to use allowAzureIPsFirewall
    name: 'sql-allow-azure-services-fw-rule' // Renamed for clarity
    properties: {
      startIpAddress: '0.0.0.0'
      endIpAddress: '0.0.0.0'
    }
  }
  resource firewallSingle 'firewallRules' = [for ip in allowedSingleIPs: if(!createPrivateEndpoint) {
    name: 'sql-allow-single-${replace(ip, '.', '')}'
    properties: {
      startIpAddress: ip
      endIpAddress: ip
    }
  }]
  // Specific IP firewall rules based on the parameter
  resource serverIpFirewallRules 'firewallRules' = [for ipRule in sqlServerAllowedIpRules: {
    name: ipRule.name
    properties: {
      startIpAddress: ipRule.startIpAddress
      endIpAddress: ipRule.endIpAddress
    }
  }]
  // Add a virtual network rule if a subnet ID is provided
  resource serverVNetRule 'virtualNetworkRules' = if (!empty(subnetNamePend) && !createPrivateEndpoint) {
    name: 'vnetrule-${last(split(subnetPend.id, '/'))}' // Auto-generate a name
    properties: {
      virtualNetworkSubnetId: subnetPend.id
      // Set to true if the VNet service endpoint for Microsoft.Sql might not be configured on the subnet yet.
      // If false (default) and the service endpoint is missing, the rule creation might fail.
      ignoreMissingVnetServiceEndpoint: true
    }
  }
}

resource keyVault 'Microsoft.KeyVault/vaults@2023-07-01' existing = {
  name: keyvaultName
}

resource sqlAdminPasswordSecret 'Microsoft.KeyVault/vaults/secrets@2023-07-01' = {
  parent: keyVault
  name: 'sqlAdminPassword'
  properties: {
    value: adminPwd
    contentType: 'text/plain'
    attributes: {
      enabled: true
    }
  }
}

resource appUserPasswordSecret 'Microsoft.KeyVault/vaults/secrets@2023-07-01' = {
  parent: keyVault
  name: 'appUserPassword'
  properties: {
    value: userPwd
    contentType: 'text/plain'
    attributes: {
      enabled: true
    }
  }
}

resource sqlAzureConnectionStringSercret 'Microsoft.KeyVault/vaults/secrets@2023-07-01' = {
  parent: keyVault
  name: connectionStringKey
  properties: {
    value: '${connectionString}; Password=${userPwd}'
    contentType: 'text/plain'
    attributes: {
      enabled: true
    }
  }
}

resource vnet 'Microsoft.Network/virtualNetworks@2024-05-01' existing = {
  name: vnetName
  scope: resourceGroup(vnetResourceGroupName)
}

resource subnetPend 'Microsoft.Network/virtualNetworks/subnets@2024-05-01' existing = {
  name: subnetNamePend
  parent: vnet
}

resource pendPostgresServer 'Microsoft.Network/privateEndpoints@2024-05-01' = if(createPrivateEndpoint) {
  name: 'pend-sqlServer-SQLDatabaseIn-${serverName}'
  location: location
  properties: {
    subnet: {
      id: subnetPend.id
    }
    privateLinkServiceConnections: [
      {
        name: 'pend-sqlServer-SQLDatabaseIn-${serverName}'
        properties: {
          privateLinkServiceId: sqlServer.id
          groupIds: [
            'sqlServer'
          ]
          privateLinkServiceConnectionState: {
            status: 'Approved'
            description: 'Auto-Approved'
            actionsRequired: 'None'
          }
        }
      }
    ]
  }
}

output connectionStringKey string = connectionStringKey
output databaseName string = sqlServer::database.name

output dnsConfig array = [
  {
    name: createPrivateEndpoint? sqlServer.name: ''
    type: 'sql'
    id:createPrivateEndpoint? sqlServer.id: ''
  }
]

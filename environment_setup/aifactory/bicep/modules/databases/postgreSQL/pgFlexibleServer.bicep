metadata description = 'Creates an Azure Database for PostgreSQL - Flexible Server.'
param name string
param location string
param tags object
param sku object 
param storage object
param version string
param administratorLogin string = 'aifactoryadmin'
param resourceExists bool = false
param useAdGroups bool = false // If true, the principalType will be set to 'Group' for role assignments
@secure()
@description('Administrator login password. If not provided, a random password will be generated.')
param administratorLoginPassword string = ''
param databaseNames array = ['aifdb']
param allowAzureIPsFirewall bool = false
param allowAllIPsFirewall bool = true
param allowedSingleIPs array = []
param tenantId string
param vnetName string
param subnetNamePend string
param vnetResourceGroupName string
param createPrivateEndpoint bool
param entraIdPrincipleAdmin string = 'jostrm_microsoft.com#EXT#@MngEnvMCAP806050.onmicrosoft.com'
@description('The name of an existing keyvault, that it will be used to store secrets (connection string)' )
param keyvaultName string
param connectionStringKey string = 'aifactory-proj-postgresqlflex-con-string'
param systemAssignedIdentity bool = false // Enables system assigned managed identity on the resource
param userAssignedIdentities object = {} // Optional. The ID(s) to assign to the resource.

var identityType = systemAssignedIdentity 
  ? (!empty(userAssignedIdentities) ? 'SystemAssigned, UserAssigned' : 'SystemAssigned') 
  : (!empty(userAssignedIdentities) ? 'UserAssigned' : 'None')

var identity = identityType != 'None' ? {
  type: identityType
  userAssignedIdentities: !empty(userAssignedIdentities) ? userAssignedIdentities : {}
} : {}

var seed = uniqueString(resourceGroup().id, subscription().subscriptionId, deployment().name)
var uppercaseLetter = substring(toUpper(seed), 0, 1)
var lowercaseLetter = substring(toLower(seed), 1, 1)
var numbers = substring(seed, 2, 4)
var specialChar = '!@#$'
var randomSpecialChar = substring(specialChar, length(seed) % length(specialChar), 1)
var loginPwd = empty(administratorLoginPassword)? '${uppercaseLetter}${lowercaseLetter}${randomSpecialChar}${numbers}${guid(deployment().name)}': administratorLoginPassword

// Add error handling for empty databaseNames
var defaultDbName = 'aifdb' // Default database name
var dbNameToUse = !empty(databaseNames) ? first(databaseNames) : defaultDbName

resource flexibleServers_mypgfrelx001_name_resource 'Microsoft.DBforPostgreSQL/flexibleServers@2024-11-01-preview' = {
  name: name
  location: location //'Sweden Central'
  sku: {
    name: 'Standard_B2s'
    tier: 'Burstable'
  }
  properties: {
    replica: {
      role: 'Primary'
    }
    storage: {
      iops: 120
      tier: 'P4'
      storageSizeGB: 32
      autoGrow: 'Disabled'
    }
    network: {
      publicNetworkAccess: createPrivateEndpoint? 'Disabled': 'Enabled'
    }
    dataEncryption: {
      type: 'SystemManaged'
    }
    authConfig: {
      activeDirectoryAuth: 'Enabled'
      passwordAuth: 'Enabled'
      tenantId: tenantId
    }
    version: '16'
    administratorLogin: administratorLogin
    administratorLoginPassword: loginPwd
    availabilityZone: '1'
    backup: {
      backupRetentionDays: 7
      geoRedundantBackup: 'Disabled'
    }
    highAvailability: {
      mode: 'Disabled'
    }
    maintenanceWindow: {
      customWindow: 'Disabled'
      dayOfWeek: 0
      startHour: 0
      startMinute: 0
    }
    replicationRole: 'Primary'
  }
}
resource flexibleServers_mypgfrelx001_name_4dd75919_56b3_4e7e_a265_dc96f9cd4a58 'Microsoft.DBforPostgreSQL/flexibleServers/administrators@2024-11-01-preview' = {
  parent: flexibleServers_mypgfrelx001_name_resource
  name: '4dd75919-56b3-4e7e-a265-dc96f9cd4a58'
  properties: {
    principalType: useAdGroups?'Group': 'User'
    principalName: entraIdPrincipleAdmin
    tenantId: tenantId
  }
}

resource flexibleServers_mypgfrelx001_name_postgres 'Microsoft.DBforPostgreSQL/flexibleServers/databases@2024-11-01-preview' = {
  parent: flexibleServers_mypgfrelx001_name_resource
  name: dbNameToUse
  properties: {
    charset: 'UTF8'
    collation: 'en_US.utf8'
  }
}

resource flexibleServers_mypgfrelx001_name_AllowAll_2025_5_23_18_6_32 'Microsoft.DBforPostgreSQL/flexibleServers/firewallRules@2024-11-01-preview' = {
  parent: flexibleServers_mypgfrelx001_name_resource
  name: 'AllowAll_2025-5-23_18-6-32'
  properties: {
    startIpAddress: '0.0.0.0'
    endIpAddress: '255.255.255.255'
  }
}

resource flexibleServers_mypgfrelx001_name_AllowAllAzureServicesAndResourcesWithinAzureIps_2025_5_23_18_8_9 'Microsoft.DBforPostgreSQL/flexibleServers/firewallRules@2024-11-01-preview' = {
  parent: flexibleServers_mypgfrelx001_name_resource
  name: 'AllowAllAzureServicesAndResourcesWithinAzureIps_2025-5-23_18-8-9'
  properties: {
    startIpAddress: '0.0.0.0'
    endIpAddress: '0.0.0.0'
  }
}
/*
resource postgresServer 'Microsoft.DBforPostgreSQL/flexibleServers@2024-08-01' = {
 location: location
  tags: tags
  name: name
  identity: identity
  sku: sku
  properties: {
    version: version
    administratorLogin: administratorLogin
    administratorLoginPassword: loginPwd
    storage: storage
    highAvailability: {
      mode: 'Disabled'
    }
  }

  resource database 'databases' = [for name in databaseNames:{
    name: name
  }]

  resource firewall_all 'firewallRules' = if (allowAllIPsFirewall) {
    name: 'allow-all-IPs'
    properties: {
      startIpAddress: '0.0.0.0'
      endIpAddress: '255.255.255.255'
    }
  }

  resource firewall_azure 'firewallRules' = if (allowAzureIPsFirewall) {
    name: 'allow-all-azure-internal-IPs'
    properties: {
      startIpAddress: '0.0.0.0'
      endIpAddress: '0.0.0.0'
    }
  }

  resource firewall_single 'firewallRules' = [for ip in allowedSingleIPs: {
    name: 'allow-single-${replace(ip, '.', '')}'
    properties: {
      startIpAddress: ip
      endIpAddress: ip
    }
  }]
}

*/

resource vnet 'Microsoft.Network/virtualNetworks@2024-05-01' existing = {
  name: vnetName
  scope: resourceGroup(vnetResourceGroupName)
}

resource subnetPend 'Microsoft.Network/virtualNetworks/subnets@2024-05-01' existing = {
  name: subnetNamePend
  parent: vnet
}

resource pendPostgresServer 'Microsoft.Network/privateEndpoints@2024-05-01' = if(createPrivateEndpoint) {
  name: 'pend-postgreSQLFlexibleServer-${name}'
  location: location
  properties: {
    subnet: {
      id: subnetPend.id
    }
    privateLinkServiceConnections: [
      {
        name: 'pend-postgreSQLFlexibleServer-${name}'
        properties: {
          privateLinkServiceId: flexibleServers_mypgfrelx001_name_resource.id
          groupIds: [
            'flexibleServers'
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

resource keyVault 'Microsoft.KeyVault/vaults@2023-07-01' existing = {
  name: keyvaultName
}

resource pgflexConnectionStringSecret 'Microsoft.KeyVault/vaults/secrets@2023-07-01' = {
  parent: keyVault
  name: connectionStringKey
  properties: {
    value: 'Server=${flexibleServers_mypgfrelx001_name_resource.properties.fullyQualifiedDomainName};Database=${dbNameToUse};Port=5432;User Id=${administratorLogin};Password=${loginPwd};Ssl Mode=Require;'
    contentType: 'text/plain'
    attributes: {
      enabled: true
    }
  }
}

output POSTGRES_DOMAIN_NAME string = flexibleServers_mypgfrelx001_name_resource.properties.fullyQualifiedDomainName
output name string = flexibleServers_mypgfrelx001_name_resource.name
output dnsConfig array = [
  {
    name: createPrivateEndpoint? flexibleServers_mypgfrelx001_name_resource.name: ''
    type: 'postgres'
    id: createPrivateEndpoint? flexibleServers_mypgfrelx001_name_resource.id: ''
  }
]

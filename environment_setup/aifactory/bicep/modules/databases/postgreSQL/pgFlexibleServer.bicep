metadata description = 'Creates an Azure Database for PostgreSQL - Flexible Server.'
param name string
param location string
param tags object
param sku object = {
    name: 'Standard_B2s'
    tier: 'Burstable'
}
param storage object = {
      iops: 120
      tier: 'P4'
      storageSizeGB: 32
      autoGrow: 'Disabled'
}
param version string = '16' // PostgreSQL version, default is 16
param administratorLogin string = 'aifactoryadmin'
param resourceExists bool = false
param useAdGroups bool = false // If true, the principalType will be set to 'Group' for role assignments
@secure()
@description('Administrator login password. If not provided, a random password will be generated.')
param administratorLoginPassword string = ''
param databaseNames array = ['aifdb']
param allowAzureIPsFirewall bool = false
param allowAllIPsFirewall bool = false
param allowedSingleIPs array = []
param tenantId string
param vnetName string
param subnetNamePend string
param vnetResourceGroupName string
param createPrivateEndpoint bool
param entraIdPrincipleAdmin string = ''
@description('The name of an existing keyvault, that it will be used to store secrets (connection string)' )
param keyvaultName string
param connectionStringKey string = 'aifactory-proj-postgresqlflex-con-string'
param systemAssignedIdentity bool = false // Enables system assigned managed identity on the resource
param userAssignedIdentities object = {} // Optional. The ID(s) to assign to the resource.
param highAvailability object = {
  mode: 'Disabled' // Default to Disabled, can be overridden
}
param availabilityZone string = '1' // Default to zone 1, can be overridden
param useCMK bool = false // If true, enables customer managed key for encryption
@description('The key vault key ID for customer managed key encryption. Required when useCMK is true.')
param keyVaultKeyId string = ''
@description('The user assigned identity ID for customer managed key encryption. Required when useCMK is true.')
param cmkUserAssignedIdentityId string = ''

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

resource postgreSQLFlex 'Microsoft.DBforPostgreSQL/flexibleServers@2024-11-01-preview' = {
  name: name
  location: location //'Sweden Central'
  sku: sku
  properties: {
    replica: {
      role: 'Primary'
    }
    storage: storage
    network: {
      publicNetworkAccess: createPrivateEndpoint? 'Disabled': 'Enabled'
    }
    dataEncryption: useCMK ? {
      type: 'AzureKeyVault'
      primaryKeyURI: keyVaultKeyId
      primaryUserAssignedIdentityId: cmkUserAssignedIdentityId
    } : {
      type: 'SystemManaged'
    }
    authConfig: {
      activeDirectoryAuth: 'Enabled'
      passwordAuth: 'Enabled'
      tenantId: tenantId
    }
    version: version
    administratorLogin: administratorLogin
    administratorLoginPassword: loginPwd
    availabilityZone: '1'
    backup: {
      backupRetentionDays: 7
      geoRedundantBackup: 'Disabled'
    }
    highAvailability: highAvailability
    maintenanceWindow: {
      customWindow: 'Disabled'
      dayOfWeek: 0
      startHour: 0
      startMinute: 0
    }
    replicationRole: 'Primary'
  }
  resource firewall_single 'firewallRules' = [for ip in allowedSingleIPs: if(!createPrivateEndpoint){
    name: 'allow-single-${replace(ip, '.', '')}'
    properties: {
      startIpAddress: ip
      endIpAddress: ip
    }
  }]

}

resource flexibleServers_mypgfrelx001_name_postgres 'Microsoft.DBforPostgreSQL/flexibleServers/databases@2024-11-01-preview' = {
  parent: postgreSQLFlex
  name: dbNameToUse
  properties: {
    charset: 'UTF8'
    collation: 'en_US.utf8'
  }
  dependsOn: [
    postgreSQLFlex
  ]
}

resource flexibleServers_mypgfrelx001_name_AllowAll_2025_5_23_18_6_32 'Microsoft.DBforPostgreSQL/flexibleServers/firewallRules@2024-11-01-preview'  = if (allowAllIPsFirewall &&!createPrivateEndpoint) {
  parent: postgreSQLFlex
  name: 'AllowAll_2025-5-23_18-6-32'
  properties: {
    startIpAddress: '0.0.0.0'
    endIpAddress: '255.255.255.255'
  }
  dependsOn: [
    postgreSQLFlex
  ]
}

resource flexibleServers_mypgfrelx001_name_AllowAllAzureServicesAndResourcesWithinAzureIps_2025_5_23_18_8_9 'Microsoft.DBforPostgreSQL/flexibleServers/firewallRules@2024-11-01-preview' = if (allowAzureIPsFirewall &&!createPrivateEndpoint) {
  parent: postgreSQLFlex
  name: 'AllowAllAzureServicesAndResourcesWithinAzureIps_2025-5-23_18-8-9'
  properties: {
    startIpAddress: '0.0.0.0'
    endIpAddress: '0.0.0.0'
  }
  dependsOn: [
    postgreSQLFlex
  ]
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
          privateLinkServiceId: postgreSQLFlex.id
          groupIds: [
            'postgresqlServer'
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
    value: 'Server=${postgreSQLFlex.properties.fullyQualifiedDomainName};Database=${dbNameToUse};Port=5432;User Id=${administratorLogin};Password=${loginPwd};Ssl Mode=Require;'
    contentType: 'text/plain'
    attributes: {
      enabled: true
    }
  }
}

var keyVaultPermissions = {
  secrets: [ 
    'get'
    'wrap key'
    'unwrap key'
  ]
}

resource keyVaultAccessPolicyAdditionalGroup 'Microsoft.KeyVault/vaults/accessPolicies@2023-07-01' = if(useCMK)  {
  parent:keyVault
  name:'add'
  properties: {
    accessPolicies: [{
      objectId: postgreSQLFlex.identity.principalId
      permissions: keyVaultPermissions
      tenantId: subscription().tenantId
    }]
  }
}

output POSTGRES_DOMAIN_NAME string = postgreSQLFlex.properties.fullyQualifiedDomainName
output name string = postgreSQLFlex.name
output dnsConfig array = [
  {
    name: createPrivateEndpoint? pendPostgresServer.name: ''
    type: 'postgres'
    id: createPrivateEndpoint? postgreSQLFlex.id: ''
  }
]

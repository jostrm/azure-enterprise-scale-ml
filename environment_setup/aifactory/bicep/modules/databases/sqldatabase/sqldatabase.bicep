metadata description = 'Creates an Azure SQL Server instance with a SQL Database'
param serverName string
param location string
param tags object
param keyvaultName string
param vnetName string
param subnetNamePend string
param vnetResourceGroupName string
param createPrivateEndpoint bool

param appUser string = 'aifactory-user'
param sqlAdmin string = 'aifactory-admin'
param databaseName string ='aifdb'
param connectionStringKey string = 'aifactory-proj-sqldb-con-string'

@secure()
param sqlAdminPassword string
@secure()
param appUserPassword string

var connectionString = 'Server=${sqlServer.properties.fullyQualifiedDomainName}; Database=${sqlServer::database.name}; User=${appUser}'

resource sqlServer 'Microsoft.Sql/servers@2022-05-01-preview' = {
  name: serverName
  location: location
  tags: tags
  properties: {
    version: '12.0'
    minimalTlsVersion: '1.2'
    publicNetworkAccess: 'Enabled'
    administratorLogin: sqlAdmin
    administratorLoginPassword: sqlAdminPassword
  }

  resource database 'databases' = {
    name: databaseName
    location: location
  }

  resource firewall 'firewallRules' = {
    name: 'Azure Services'
    properties: {
      // Allow all clients
      // Note: range [0.0.0.0-0.0.0.0] means "allow all Azure-hosted clients only".
      // This is not sufficient, because we also want to allow direct access from developer machine, for debugging purposes.
      startIpAddress: '0.0.0.1'
      endIpAddress: '255.255.255.254'
    }
  }
}

resource sqlDeploymentScript 'Microsoft.Resources/deploymentScripts@2020-10-01' = {
  name: '${serverName}-deployment-script'
  location: location
  kind: 'AzureCLI'
  properties: {
    azCliVersion: '2.37.0'
    retentionInterval: 'PT1H' // Retain the script resource for 1 hour after it ends running
    timeout: 'PT5M' // Five minutes
    cleanupPreference: 'OnSuccess'
    environmentVariables: [
      {
        name: 'APPUSERNAME'
        value: appUser
      }
      {
        name: 'APPUSERPASSWORD'
        secureValue: appUserPassword
      }
      {
        name: 'DBNAME'
        value: databaseName
      }
      {
        name: 'DBSERVER'
        value: sqlServer.properties.fullyQualifiedDomainName
      }
      {
        name: 'SQLCMDPASSWORD'
        secureValue: sqlAdminPassword
      }
      {
        name: 'SQLADMIN'
        value: sqlAdmin
      }
    ]

    scriptContent: '''
wget https://github.com/microsoft/go-sqlcmd/releases/download/v0.8.1/sqlcmd-v0.8.1-linux-x64.tar.bz2
tar x -f sqlcmd-v0.8.1-linux-x64.tar.bz2 -C .

cat <<SCRIPT_END > ./initDb.sql
drop user if exists ${APPUSERNAME}
go
create user ${APPUSERNAME} with password = '${APPUSERPASSWORD}'
go
alter role db_owner add member ${APPUSERNAME}
go
SCRIPT_END

./sqlcmd -S ${DBSERVER} -d ${DBNAME} -U ${SQLADMIN} -i ./initDb.sql
    '''
  }
}

resource keyVault 'Microsoft.KeyVault/vaults@2023-07-01' existing = {
  name: keyvaultName
}

resource sqlAdminPasswordSecret 'Microsoft.KeyVault/vaults/secrets@2023-07-01' = {
  parent: keyVault
  name: 'sqlAdminPassword'
  properties: {
    value: sqlAdminPassword
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
    value: appUserPassword
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
    value: '${connectionString}; Password=${appUserPassword}'
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

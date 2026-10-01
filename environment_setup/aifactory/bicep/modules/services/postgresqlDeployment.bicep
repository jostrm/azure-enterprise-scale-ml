targetScope = 'subscription'

param context object
param deploymentSuffix string
param location string
param tagsProject object = {}
param postgreSQLSKU object
param postgreSQLStorage object = {
  storageSizeGB: 32
}
param postgreSQLVersion string = '17'
param postgreSQLHighAvailability object = {
  mode: 'Disabled'
}
param postgresAvailabilityZone string = ''
param useAdGroups bool = false
param usersOrAdGroupArray array = []
param servicePrincipleAndMIArray array = []
param adminNames array = []
param enablePublicAccessWithPerimeter bool = false
param centralDnsZoneByPolicyInHub bool = false
@allowed(['gold', 'silver', 'bronze'])
param diagnosticSettingLevel string = 'silver'
param cmk bool = false
param cmkKeyName string = ''
param admin_bicep_kv_fw string = ''
param admin_bicep_kv_fw_rg string = ''
param admin_bicep_input_keyvault_subscription string = ''

var cmkKvBaseUriRaw = cmk ? reference(resourceId(admin_bicep_input_keyvault_subscription, admin_bicep_kv_fw_rg, 'Microsoft.KeyVault/vaults', admin_bicep_kv_fw), '2022-07-01').vaultUri : ''
var cmkKvBaseUri = cmk && endsWith(cmkKvBaseUriRaw, '/') ? substring(cmkKvBaseUriRaw, 0, length(cmkKvBaseUriRaw) - 1) : cmkKvBaseUriRaw
var cmkIdentityId = resourceId(context.subscriptionId, context.targetResourceGroup, 'Microsoft.ManagedIdentity/userAssignedIdentities', context.names.miPrjName)

// Keep this nested deployment name stable across attempts: it is the password-generation seed.
module postgreSQL '../databases/postgreSQL/pgFlexibleServer.bicep' = {
  name: take('04-PostgreSQL4${deploymentSuffix}', 64)
  scope: resourceGroup(context.subscriptionId, context.targetResourceGroup)
  params: {
    name: context.names.postgreSQLName
    location: location
    tags: tagsProject
    vnetName: context.vnetName
    vnetResourceGroupName: context.vnetResourceGroupName
    subnetNamePend: context.names.defaultSubnet
    keyvaultName: context.names.keyvaultName
    createPrivateEndpoint: !enablePublicAccessWithPerimeter
    sku: postgreSQLSKU
    storage: postgreSQLStorage
    version: postgreSQLVersion
    tenantId: tenant().tenantId
    useAdGroups: useAdGroups
    highAvailability: postgreSQLHighAvailability
    availabilityZone: postgresAvailabilityZone
    useCMK: cmk
    keyVaultKeyId: cmk ? '${cmkKvBaseUri}/keys/${cmkKeyName}' : ''
    cmkUserAssignedIdentityId: cmk ? cmkIdentityId : ''
  }
}

module rbac '../databases/postgreSQL/pgFlexibleServerRbac.bicep' = {
  name: take('04-PostgreSQLRbac4${deploymentSuffix}', 64)
  scope: resourceGroup(context.subscriptionId, context.targetResourceGroup)
  params: {
    postgreSqlServerName: context.names.postgreSQLName
    useAdGroups: useAdGroups
    usersOrAdGroupArray: usersOrAdGroupArray
    servicePrincipleAndMIArray: servicePrincipleAndMIArray
    adminNames: adminNames
  }
  dependsOn: [
    postgreSQL
  ]
}

module privateDns '../privateDns.bicep' = if (!centralDnsZoneByPolicyInHub && !enablePublicAccessWithPerimeter) {
  name: take('04-privDnsPGres${deploymentSuffix}', 64)
  scope: resourceGroup(context.subscriptionId, context.targetResourceGroup)
  params: {
    dnsConfig: postgreSQL.outputs.dnsConfig
    privateLinksDnsZones: context.privateLinksDnsZones
  }
}

module diagnostics '../diagnostics/postgresqlDiagnostics.bicep' = {
  name: take('04-diagPostgreSQL-${deploymentSuffix}', 64)
  scope: resourceGroup(context.subscriptionId, context.targetResourceGroup)
  params: {
    postgresqlServerName: context.names.postgreSQLName
    logAnalyticsWorkspaceId: resourceId(context.subscriptionId, context.commonResourceGroup, 'Microsoft.OperationalInsights/workspaces', context.names.laWorkspaceName)
    diagnosticSettingLevel: diagnosticSettingLevel
  }
  dependsOn: [
    postgreSQL
  ]
}

output name string = postgreSQL.outputs.name
output POSTGRES_DOMAIN_NAME string = postgreSQL.outputs.POSTGRES_DOMAIN_NAME
output dnsConfig array = postgreSQL.outputs.dnsConfig

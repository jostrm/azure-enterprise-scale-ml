@minLength(3)
@maxLength(24)
@description('Specifies the name of the storage')
param storageAccountName string
@description('Specifies the id of the virtual network used for private endpoints')
param vnetId string
@description('Specifies the id of the subnet used for the private endpoints')
param subnetName string
@description('Common resource group')
param commonResourceGroup string
@description('Common default subnet')
param common_subnet_name string

///////////////////
var newSubnetID = '${vnetId}/subnets/${subnetName}'
var subscriptionIdDevTestProd = subscription().id

/* MERGE virtualNetworkRules to Existing DATALAKE - Add Databricks public SubNet */
//var keepDatalakeName = '${commonLakeNamePrefix}esmldatalake${replace(commonResourceSuffix,'-','')}${env}'
var keepDatalakeName = storageAccountName

resource commonResourceGroupRef 'Microsoft.Resources/resourceGroups@2021-04-01' existing = {
  name: commonResourceGroup
  scope:subscription(subscriptionIdDevTestProd)
}

resource esmlCommonLake 'Microsoft.Storage/storageAccounts@2021-04-01' existing = {
  name: keepDatalakeName
  scope:resourceGroup(subscriptionIdDevTestProd,commonResourceGroup)
}

var existingRules = esmlCommonLake.properties.networkAcls.virtualNetworkRules
var keepSku = esmlCommonLake.sku.name
var keepLocation = esmlCommonLake.location
var keepTags = esmlCommonLake.tags

var virtualNetworkRules2Add = [
  {
    id: newSubnetID
    action: 'Allow'
    state: 'succeeded'
  }
]
var mergeVirtualNetworkRulesMerged = concat(existingRules, virtualNetworkRules2Add)

param lakeContainerName string
module dataLake '../modules/dataLake.bicep' = {
  scope: resourceGroup(subscriptionIdDevTestProd,commonResourceGroup) // resourceGroup(commonResourceGroup)
  name: 'StorageAccountUpdateVirtualNetworkRulesOnLake'
  params: {
    storageAccountName: keepDatalakeName
    containerName: lakeContainerName // Only update VirtualNetworkRulesMerged...we dont want to trigger a new RESOURCE creation of container
    skuName: keepSku
    location: keepLocation
    vnetId: vnetId
    subnetName: common_subnet_name
    blobPrivateEndpointName: 'pend-${keepDatalakeName}-blob-to-vnt-esmlcmn'
    filePrivateEndpointName: 'pend-${keepDatalakeName}-file-to-vnt-esmlcmn'
    dfsPrivateEndpointName: 'pend-${keepDatalakeName}-dfs-to-vnt-esmlcmn'
    tags: keepTags
    virtualNetworkRules: mergeVirtualNetworkRulesMerged
    //subnetName2AddAsVnetRule: dbxPubSubnetName
  }
  dependsOn: [
    commonResourceGroupRef
  ]
}

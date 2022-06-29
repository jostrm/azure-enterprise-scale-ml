@description('Specifies the name of the databricks instance that is deployed')
param name string

@description('Specifies the location to where databricks is deployed')
param location string

@allowed([
  'standard'
  'premium'
])
@description('Specifies the name of the SKU used for databricks')
param skuName string

@description('Specifies the id of the management resource group for databricks')
param managedResourceGroupId string

@description('Specifies the private subnet name for databricks')
param databricksPrivateSubnet string

@description('Specifies the public subnet name for databricks')
param databricksPublicSubnet string

@description('Specifies the virtual network id where databrick subnets are present')
param vnetId string

@description('Specifies the tags that should be deployed to databricks resources')
param tags object

// TODO: optional
@description('TODO')
param amlWorkspaceId string

// https://docs.microsoft.com/en-us/azure/templates/microsoft.databricks/2018-04-01/workspaces?tabs=bicep
resource dataBricks 'Microsoft.Databricks/workspaces@2021-04-01-preview' = {
  name: name
  location: location
  tags: tags
  sku: {
    name: skuName
  }
  properties: {
    managedResourceGroupId: managedResourceGroupId
    parameters: {
      customPrivateSubnetName: {
        value: databricksPrivateSubnet
      }
      customPublicSubnetName: {
        value: databricksPublicSubnet
      }
      customVirtualNetworkId: {
        value: vnetId
      }
      amlWorkspaceId: {
        value: amlWorkspaceId
      }
      enableNoPublicIp: {
        value: false
      }
      natGatewayName: {
        value: 'nat-gateway'
      }
      prepareEncryption: {
        value: false
      }
      publicIpName: {
        value: 'nat-gw-public-ip'
      }
      requireInfrastructureEncryption: {
        value: false
      }
    }
  }
}
output databricksId string = dataBricks.id
output databricks_workspace_id string = dataBricks.id
output databricks_workspaceUrl string = dataBricks.properties.workspaceUrl
output databricks_dbfs_storage_accountName string = dataBricks.properties.parameters.storageAccountName.value


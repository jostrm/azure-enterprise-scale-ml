
// TODO: Assets
// 1) Databricks, default cluster: small-mlprj002-dev-azureml-rt-7.3
// - Standard_D12_v2 8GB | No autoscaling | 3 workers | 7.3 LTS |  Cluster mode:Standard | 
// - libs (pypi: aml): azureml-sdk[databricks]
// - libs (maven: xml): HyukjinKwon:spark-xml:0.1.1-s_2.10
// 2) Databricks, IMPORT notebooks
// 3) Link KV as secret scope: "#secrets/createScope"
// - esml-prj-secretscope

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

// TODO
@description('TODO')
param amlWorkspaceId string
var esmlProjectSecretscopeAKV = 'esml-prj-secretscope'  // Manage Principal All users

resource databricksPrivate 'Microsoft.Databricks/workspaces@2021-04-01-preview' = {
  name: name
  location: location
  tags: tags
  sku: {
    name: skuName
  }
  
  properties: {
    publicNetworkAccess: 'Disabled' // value to disabled to access workspace only via private link.
    requiredNsgRules: 'AllRules' // ['AllRules','NoAzureDatabricksRules' 'NoAzureServiceRules']  whether data plane (clusters) to control plane communication happen over private endpoint. 
    managedResourceGroupId: managedResourceGroupId
    parameters: {
      amlWorkspaceId: {
        value: amlWorkspaceId
      }
      customPrivateSubnetName: {
        value: databricksPrivateSubnet
      }
      customPublicSubnetName: {
        value: databricksPublicSubnet
      }
      customVirtualNetworkId: {
        value: vnetId
      }
      enableNoPublicIp: {
        value: true
      }
      natGatewayName: {
        value: 'nat-gateway'
      }
      prepareEncryption: {
        value: false
      }
      requireInfrastructureEncryption: {
        value: false
      }
    }
  }
}
output databricksId string = databricksPrivate.id
output databricks_workspace_id string = databricksPrivate.id
output databricks_workspaceUrl string = databricksPrivate.properties.workspaceUrl
output databricks_dbfs_storage_accountName string = databricksPrivate.properties.parameters.storageAccountName.value

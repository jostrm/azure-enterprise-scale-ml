
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

@description('(Required) Specifies the subnet name that will be associated with the private endpoint')
param subnetName string

@description('(Required) Specifies the private endpoint name')
param privateEndpointName string

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

@description('Indicates whether to retain or remove the AzureDatabricks outbound NSG rule - possible values are AllRules or NoAzureDatabricksRules.')
@allowed([
  'AllRules'
  'NoAzureDatabricksRules'
])
param requiredNsgRules string = 'NoAzureDatabricksRules'

// TODO
@description('TODO')
param amlWorkspaceId string
var esmlProjectSecretscopeAKV = 'esml-prj-secretscope'  // Manage Principal All users
var subnetRef = '${vnetId}/subnets/${subnetName}'

// TODO: https://github.com/Azure/azure-quickstart-templates/tree/master/quickstarts/microsoft.databricks/databricks-all-in-one-template-for-vnet-injection-privateendpoint

resource databricksPrivate 'Microsoft.Databricks/workspaces@2024-05-01' = {
  name: name
  location: location
  tags: tags
  sku: {
    name: skuName
  }
  
  properties: {
    publicNetworkAccess: 'Disabled' // value to disabled to access workspace only via private link.
    requiredNsgRules: 'AllRules' // ['AllRules','NoAzureDatabricksRules' 'NoAzureServiceRules'] 'NoAzureServiceRules' value is for internal use only. whether data plane (clusters) to control plane communication happen over private endpoint. 
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

resource privateEndpoint 'Microsoft.Network/privateEndpoints@2021-08-01' = {
  name: privateEndpointName
  location: location
  properties: {
    subnet: {
      id: subnetRef
      name: subnetName
    }
    privateLinkServiceConnections: [
      {
        name: privateEndpointName
        properties: {
          privateLinkServiceId: databricksPrivate.id
          groupIds: [
            'databricks_ui_api'
          ]
          privateLinkServiceConnectionState: {
            status: 'Approved'
            description: 'Compliance with network design'
          }
        }
        
      }
    ]
  }
}

output databricksId string = databricksPrivate.id
output databricks_workspace_id string = databricksPrivate.id
output databricks_workspaceUrl string = databricksPrivate.properties.workspaceUrl
output databricks_dbfs_storage_accountName string = databricksPrivate.properties.parameters.storageAccountName.value

output dnsConfig array = [
  {
    name: privateEndpoint.name
    type: 'azuredatabricks'
    id: databricksPrivate.id
    groupid:'databricks_ui_api'
  }
]


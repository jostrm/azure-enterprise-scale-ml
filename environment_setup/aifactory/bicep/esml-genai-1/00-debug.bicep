param location string = ''
param debug_vnetId string = ''
param projectName string = ''
param projectNumber string = ''
param env string = ''
param locationSuffix string = ''
param commonResourceGroup string = ''
param targetResourceGroup string = ''
param vnetNameFull string = ''
param vnetResourceGroupName string = ''
param common_subnet_name_local string = ''
param genaiSubnetId string = ''
param genaiSubnetName string = ''
param defaultSubnet string = ''
param aksSubnetId string = ''
param aksSubnetName string = ''
param subscriptions_subscriptionId string = ''
param vnetRule1 string = ''
param vnetRule2 string = ''
param postGreSQLExists bool = false
param keyvaultExists bool = false
param aiSearchExists bool = false

// Use this in a resource description or as a dummy resource to see the values
resource dummyResource 'Microsoft.Resources/deploymentScripts@2020-10-01' = {
  name: 'debugScript'
  location: location
  kind: 'AzurePowerShell'
  properties: {
    azPowerShellVersion: '11.0'
    // Pass the parameters as environment variables instead of trying to interpolate them in the script
    environmentVariables: [
      {
        name: 'DEBUG_VNET_ID'
        value: debug_vnetId
      }
      {
        name: 'PROJECT_NAME'
        value: projectName
      }
      {
        name: 'PROJECT_NUMBER'
        value: projectNumber
      }
      {
        name: 'ENV_NAME'
        value: env
      }
      {
        name: 'LOCATION_SUFFIX'
        value: locationSuffix
      }
      {
        name: 'COMMON_RG'
        value: commonResourceGroup
      }
      {
        name: 'TARGET_RG'
        value: targetResourceGroup
      }
      {
        name: 'VNET_NAME_FULL'
        value: vnetNameFull
      }
      {
        name: 'VNET_RG_NAME'
        value: vnetResourceGroupName
      }
      {
        name: 'COMMON_SUBNET_NAME'
        value: common_subnet_name_local
      }
      {
        name: 'GENAI_SUBNET_ID'
        value: genaiSubnetId
      }
      {
        name: 'GENAI_SUBNET_NAME'
        value: genaiSubnetName
      }
      {
        name: 'DEFAULT_SUBNET'
        value: defaultSubnet
      }
      {
        name: 'AKS_SUBNET_ID'
        value: aksSubnetId
      }
      {
        name: 'AKS_SUBNET_NAME'
        value: aksSubnetName
      }
      {
        name: 'SUBSCRIPTION_ID'
        value: subscriptions_subscriptionId
      }
      {
        name: 'VNET_RULE_1'
        value: vnetRule1
      }
      {
        name: 'VNET_RULE_2'
        value: vnetRule2
      }
      {
        name: 'postGreSQLExists'
        value: postGreSQLExists ? 'true' : 'false'
      }
      {
        name: 'keyvaultExists'
        value: keyvaultExists ? 'true' : 'false'
      }
      {
        name: 'aiSearchExists'
        value: aiSearchExists ? 'true' : 'false'
      }
    ]
    scriptContent: '''
      Write-Host "DEBUG OUTPUT VARIABLES:"
      Write-Host "vnetId: $env:DEBUG_VNET_ID"
      Write-Host "projectName: $env:PROJECT_NAME"
      Write-Host "projectNumber: $env:PROJECT_NUMBER"
      Write-Host "env: $env:ENV_NAME"
      Write-Host "location: $env:LOCATION"
      Write-Host "locationSuffix: $env:LOCATION_SUFFIX"
      Write-Host "commonResourceGroup: $env:COMMON_RG"
      Write-Host "targetResourceGroup: $env:TARGET_RG"
      Write-Host "vnetNameFull: $env:VNET_NAME_FULL"
      Write-Host "vnetResourceGroupName: $env:VNET_RG_NAME"
      Write-Host "common_subnet_name_local: $env:COMMON_SUBNET_NAME"
      Write-Host "genaiSubnetId: $env:GENAI_SUBNET_ID"
      Write-Host "genaiSubnetName: $env:GENAI_SUBNET_NAME"
      Write-Host "defaultSubnet: $env:DEFAULT_SUBNET"
      Write-Host "aksSubnetId: $env:AKS_SUBNET_ID"
      Write-Host "aksSubnetName: $env:AKS_SUBNET_NAME"
      Write-Host "subscriptionId: $env:SUBSCRIPTION_ID"
      Write-Host "vnetRule1: $env:VNET_RULE_1"
      Write-Host "vnetRule2: $env:VNET_RULE_2"
      Write-Host "postGreSQLExists: $env:postGreSQLExists"
      Write-Host "debug_keyvaultExists: $env:keyvaultExists"
      Write-Host "debug_aiSearchExists: $env:aiSearchExists"
    '''
    retentionInterval: 'PT1H'
  }
}

// Add outputs to see the values even if the deployment script fails
output debug_vnetId string = debug_vnetId
output debug_projectName string = projectName
output debug_projectNumber string = projectNumber
output debug_env string = env
output debug_location string = location
output debug_locationSuffix string = locationSuffix
output debug_commonResourceGroup string = commonResourceGroup
output debug_targetResourceGroup string = targetResourceGroup
output debug_vnetNameFull string = vnetNameFull
output debug_vnetResourceGroupName string = vnetResourceGroupName
output debug_common_subnet_name_local string = common_subnet_name_local
output debug_genaiSubnetId string = genaiSubnetId
output debug_genaiSubnetName string = genaiSubnetName
output debug_defaultSubnet string = defaultSubnet
output debug_aksSubnetId string = aksSubnetId
output debug_aksSubnetName string = aksSubnetName
output debug_vnetRule1 string = vnetRule1
output debug_vnetRule2 string = vnetRule2
output debug_postGreSQLExists bool = postGreSQLExists

output debug_keyvaultExists bool = keyvaultExists
output debug_aiSearchExists bool = aiSearchExists


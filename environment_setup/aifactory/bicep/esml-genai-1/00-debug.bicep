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

// Use this in a resource description or as a dummy resource to see the values
resource dummyResource 'Microsoft.Resources/deploymentScripts@2020-10-01' = {
  name: 'debugScript'
  location: location
  kind: 'AzurePowerShell'
  properties: {
    azPowerShellVersion: '3.0'
    scriptContent: '''
      Write-Host "DEBUG OUTPUT VARIABLES:"
      Write-Host "vnetId: ${debug_vnetId}"
      Write-Host "projectName: ${projectName}"
      Write-Host "projectNumber: ${projectNumber}"
      Write-Host "env: ${env}"
      Write-Host "location: ${location}"
      Write-Host "locationSuffix: ${locationSuffix}"
      Write-Host "commonResourceGroup: ${commonResourceGroup}"
      Write-Host "targetResourceGroup: ${targetResourceGroup}"
      Write-Host "vnetNameFull: ${vnetNameFull}"
      Write-Host "vnetResourceGroupName: ${vnetResourceGroupName}"
      Write-Host "common_subnet_name_local: ${common_subnet_name_local}"
      Write-Host "genaiSubnetId: ${genaiSubnetId}"
      Write-Host "genaiSubnetName: ${genaiSubnetName}" 
      Write-Host "defaultSubnet: ${defaultSubnet}"
      Write-Host "aksSubnetId: ${aksSubnetId}" 
      Write-Host "aksSubnetName: ${aksSubnetName}"
      Write-Host "aksSubnetName: ${subscriptions_subscriptionId}"
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

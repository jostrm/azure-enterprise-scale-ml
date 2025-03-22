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

// Use this in a resource description or as a dummy resource to see the values
resource dummyResource 'Microsoft.Resources/deploymentScripts@2020-10-01' = {
  name: 'debugScript'
  location: location
  kind: 'AzurePowerShell'
  properties: {
    azPowerShellVersion: '3.0'
    scriptContent: '''
      Write-Output "DEBUG OUTPUT VARIABLES:"
      Write-Output "vnetId: ${debug_vnetId}"
      Write-Output "projectName: ${projectName}"
      Write-Output "projectNumber: ${projectNumber}"
      Write-Output "env: ${env}"
      Write-Output "location: ${location}"
      Write-Output "locationSuffix: ${locationSuffix}"
      Write-Output "commonResourceGroup: ${commonResourceGroup}"
      Write-Output "targetResourceGroup: ${targetResourceGroup}"
      Write-Output "vnetNameFull: ${vnetNameFull}"
      Write-Output "vnetResourceGroupName: ${vnetResourceGroupName}"
      Write-Output "common_subnet_name_local: ${common_subnet_name_local}"
      Write-Output "genaiSubnetId: ${genaiSubnetId}"
      Write-Output "genaiSubnetName: ${genaiSubnetName}" 
      Write-Output "defaultSubnet: ${defaultSubnet}"
      Write-Output "aksSubnetId: ${aksSubnetId}" 
      Write-Output "aksSubnetName: ${aksSubnetName}"
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

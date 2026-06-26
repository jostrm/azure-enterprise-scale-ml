@description('Specifies the name of the Azure Machine Learning workspace')
param name string
param uniqueDepl string
param uniqueSalt5char string
param locationSuffix string
param projectNumber string
param location string
param env string
param tags object

@description('Subnet id for the AKS cluster')
param aksSubnetId string
@description('Subnet name for AKS load balancer')
param aksSubnetName string
param aksServiceCidr string = '10.0.0.0/16'
param aksDnsServiceIP string = '10.0.0.10'
param aksDockerBridgeCidr string = '172.17.0.1/16'
param aksExists bool = false

@description('Specifies the SKU name for the AKS cluster')
@allowed([
  'Base'
  'Standard'
])
param aksSkuName string = 'Base'
param aksLoadBalancerSku string = 'standard'

@description('Specifies the SKU tier for the AKS cluster')
@allowed([
  'Free'
  'Standard'
  'Premium'
])
param aksSkuTier string = 'Standard'

param aksEnablePrivateCluster bool = true
param aksManagedOutboundIPs int = 1
@allowed(['loadBalancer', 'userDefinedRouting', 'managedNATGateway', 'userAssignedNATGateway'])
param aksOutboundType string = 'loadBalancer'
param aksPrivateDNSZone string = 'system'
param kubernetesVersionAndOrchestrator string
param aksVmSku_dev string
param aksVmSku_testProd string
param aksNodes_dev int
param aksNodes_testProd int

@description('AKS own SSL on private cluster. MS auto SSL is not possible if private cluster')
param ownSSL string = 'disabled'

@description('Enable Customer Managed Keys (CMK) encryption')
param cmk bool = false
@description('Name of the Customer Managed Key in Key Vault')
param cmkKeyName string = ''
param kvName string

var aksName = 'aks${projectNumber}-${locationSuffix}-${env}'
var aksResourceId = '${subscription().id}/resourceGroups/${resourceGroup().name}/providers/Microsoft.ContainerService/managedClusters/${aksName}'
var nodeResourceGroupName = 'aks-${resourceGroup().name}'
var desName = 'des-${name}'
var desKeyName = '${cmkKeyName}-des'
var tagKeys = items(tags)
var limitedTags = length(tagKeys) > 12 ? toObject(take(tagKeys, 12), item => item.key, item => item.value) : tags

resource azureMLWorkspace 'Microsoft.MachineLearningServices/workspaces@2025-07-01-preview' existing = {
  name: name
}

resource existingKeyvault 'Microsoft.KeyVault/vaults@2023-07-01' existing = {
  name: kvName
}

module aksDesKey 'keyVaultKey.bicep' = if (cmk && !empty(cmkKeyName) && !aksExists && !empty(aksSubnetId)) {
  name: take('AKS-DES-Key-${uniqueDepl}', 64)
  params: {
    keyVaultName: kvName
    keyName: desKeyName
    kty: 'RSA'
    keySize: 2048
    keyOps: [
      'encrypt'
      'decrypt'
      'wrapKey'
      'unwrapKey'
    ]
  }
}

module aksDiskEncryptionSet 'diskEncryptionSet.bicep' = if (cmk && !empty(cmkKeyName) && !aksExists && !empty(aksSubnetId)) {
  name: take('AKS-DES-${uniqueDepl}', 64)
  params: {
    desName: desName
    location: location
    keyVaultId: existingKeyvault.id
    keyUrl: aksDesKey!.outputs.keyUriWithVersion
    tags: tags
  }
  dependsOn: [
    aksDesKey
  ]
}

module aksDesKvRbac 'kvRbacSingleAssignment.bicep' = if (cmk && !empty(cmkKeyName) && !aksExists && !empty(aksSubnetId)) {
  name: take('AKS-DES-RBAC-${uniqueDepl}', 64)
  params: {
    keyVaultName: kvName
    principalId: aksDiskEncryptionSet!.outputs.desPrincipalId
    keyVaultRoleId: 'e147488a-f6f5-4113-8e2d-b22465e65bf6'
    principalType: 'ServicePrincipal'
    assignmentName: 'aks-des-kv-${uniqueSalt5char}'
    roleDescription: 'Allows Disk Encryption Set to access Key Vault for AKS disk encryption'
  }
  dependsOn: [
    aksDiskEncryptionSet
  ]
}

module aksDev 'aksCluster.bicep' = if(env == 'dev' && !aksExists && !empty(aksSubnetId)) {
  name: take('Amlv2-AKS-D${uniqueDepl}', 64)
  params: {
    name: aksName
    tags: limitedTags
    location: location
    skuName: aksSkuName
    skuTier: aksSkuTier
    aksExists: aksExists
    kubernetesVersion: kubernetesVersionAndOrchestrator
    dnsPrefix: '${aksName}-dns'
    enableRbac: true
    nodeResourceGroup: nodeResourceGroupName
    aksDnsServiceIP: aksDnsServiceIP
    aksServiceCidr: aksServiceCidr
    outboundType: aksOutboundType
    privateDNSZone: aksPrivateDNSZone
    cmk: cmk
    diskEncryptionSetID: cmk && !empty(cmkKeyName) ? aksDiskEncryptionSet!.outputs.desId : ''
    agentPoolProfiles: [
      {
        name: toLower('agentpool')
        count: aksNodes_dev
        vmSize: aksVmSku_dev
        osType: 'Linux'
        osSKU: 'Ubuntu'
        mode: 'System'
        vnetSubnetID: aksSubnetId
        type: 'VirtualMachineScaleSets'
        maxPods: 30
        orchestratorVersion: kubernetesVersionAndOrchestrator
        osDiskSizeGB: 128
      }
    ]
    enablePrivateCluster: aksEnablePrivateCluster
    managedOutboundIPs: aksManagedOutboundIPs
    loadBalancerSku: aksLoadBalancerSku
  }
  dependsOn: [
    ...(cmk && !empty(cmkKeyName) ? [aksDesKvRbac] : [])
  ]
}

module aksTestProd 'aksCluster.bicep' = if((env == 'test' || env == 'prod') && !aksExists && !empty(aksSubnetId)) {
  name: take('Amlv2-AKS-TP${uniqueDepl}', 64)
  params: {
    name: aksName
    tags: limitedTags
    location: location
    skuName: aksSkuName
    skuTier: aksSkuTier
    aksExists: aksExists
    kubernetesVersion: kubernetesVersionAndOrchestrator
    dnsPrefix: '${aksName}-dns'
    enableRbac: true
    nodeResourceGroup: nodeResourceGroupName
    aksDnsServiceIP: aksDnsServiceIP
    aksServiceCidr: aksServiceCidr
    outboundType: aksOutboundType
    privateDNSZone: aksPrivateDNSZone
    cmk: cmk
    diskEncryptionSetID: cmk && !empty(cmkKeyName) ? aksDiskEncryptionSet!.outputs.desId : ''
    agentPoolProfiles: [
      {
        name: 'agentpool'
        count: aksNodes_testProd
        vmSize: aksVmSku_testProd
        osType: 'Linux'
        osSKU: 'Ubuntu'
        mode: 'System'
        vnetSubnetID: aksSubnetId
        type: 'VirtualMachineScaleSets'
        maxPods: 30
        orchestratorVersion: kubernetesVersionAndOrchestrator
      }
    ]
    enablePrivateCluster: aksEnablePrivateCluster
    managedOutboundIPs: aksManagedOutboundIPs
    loadBalancerSku: aksLoadBalancerSku
  }
  dependsOn: [
    ...(cmk && !empty(cmkKeyName) ? [aksDesKvRbac] : [])
  ]
}

resource machineLearningCompute 'Microsoft.MachineLearningServices/workspaces/computes@2024-10-01-preview' = if(ownSSL == 'disabled' && env == 'dev' && !empty(aksSubnetId)) {
  name: aksName
  parent: azureMLWorkspace
  location: location
  properties: {
    computeType: 'AKS'
    computeLocation: location
    description: 'Serve model ONLINE inference on AKS powered webservice. Defaults: Dev=${aksVmSku_dev}. TestProd=${aksVmSku_testProd}'
    resourceId: aksResourceId
    properties: union({
      agentCount: 1
      clusterPurpose: 'DevTest'
      agentVmSize: aksVmSku_dev
      loadBalancerType: 'InternalLoadBalancer'
    }, !aksExists ? {
      aksNetworkingConfiguration: {
        subnetId: aksSubnetId
        dnsServiceIP: aksDnsServiceIP
        dockerBridgeCidr: aksDockerBridgeCidr
        serviceCidr: aksServiceCidr
      }
      loadBalancerSubnet: aksSubnetName
    } : {})
  }
  dependsOn: [
    ...(!aksExists ? [aksDev] : [])
  ]
}

resource machineLearningComputeTestProd 'Microsoft.MachineLearningServices/workspaces/computes@2024-10-01-preview' = if(ownSSL == 'disabled' && (env == 'test' || env == 'prod') && !empty(aksSubnetId)) {
  name: aksName
  parent: azureMLWorkspace
  location: location
  properties: {
    computeType: 'AKS'
    computeLocation: location
    description: 'Serve model ONLINE inference on AKS powered webservice. Defaults: Dev=${aksVmSku_dev}. TestProd=${aksVmSku_testProd}'
    resourceId: aksResourceId
    properties: union({
      agentCount: 3
      clusterPurpose: 'FastProd'
      agentVmSize: aksVmSku_testProd
      loadBalancerType: 'InternalLoadBalancer'
    }, !aksExists ? {
      aksNetworkingConfiguration: {
        subnetId: aksSubnetId
        dnsServiceIP: aksDnsServiceIP
        dockerBridgeCidr: aksDockerBridgeCidr
        serviceCidr: aksServiceCidr
      }
      loadBalancerSubnet: aksSubnetName
    } : {})
  }
  dependsOn: [
    ...(!aksExists ? [aksTestProd] : [])
  ]
}

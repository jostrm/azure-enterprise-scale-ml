@description('Specifies the name of the AKS cluster')
param name string

@description('Specifies the tags that should be applied to aks resources')
param tags object

@description('Specifies location were aks resources should be deployed')
param location string

@description('Specifies version of kubernetes on the AKS cluster')
param kubernetesVersion string

@description('Specifies the DNS prefix for the AKS cluster')
param dnsPrefix string

@description('Specifies if RBAC permission model should be enabled or not')
param enableRbac bool

@description('Specifies agent pool profile settings in a array with hashmaps format')
param agentPoolProfiles array

@description('Specifies the name of the resource group that is used for node pool resources')
param nodeResourceGroup string

resource aksCluster 'Microsoft.ContainerService/managedClusters@2021-03-01' = {
  name: name
  tags: tags
  location: location
  identity: {
    type: 'SystemAssigned'
  }
  properties: {
    kubernetesVersion: kubernetesVersion
    dnsPrefix: dnsPrefix
    enableRBAC: enableRbac
    agentPoolProfiles: agentPoolProfiles
    nodeResourceGroup: nodeResourceGroup
    networkProfile: {
      networkPlugin: 'kubenet'
      serviceCidr: '10.0.0.0/16'
      dnsServiceIP: '10.0.0.10'
      dockerBridgeCidr: '172.17.0.1/16'
      loadBalancerSku: 'standard'
    }
    apiServerAccessProfile: {
      enablePrivateCluster: true
    }
  }
  
}

output aksId string = aksCluster.id

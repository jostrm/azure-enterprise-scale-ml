@description('Specifies the name of the AKS cluster')
param name string
// ============== SKUs ==============
@description('Specifies the SKU name for the AKS cluster')
@allowed([
  'Base'
  'Standard'
])
param skuName string = 'Base'

@description('Specifies the SKU tier for the AKS cluster')
@allowed([
  'Free'
  'Standard'
  'Premium'
])
param skuTier string = 'Standard'
// ============== SKUs ==============
@description('Specifies the tags that should be applied to aks resources')
param tags object

@description('Specifies location were aks resources should be deployed')
param location string

@description('Specifies version of kubernetes on the AKS cluster')
param kubernetesVersion string

@description('Specifies the DNS prefix for the AKS cluster')
param dnsPrefix string

@description('Specifies if RBAC permission model should be enabled or not')
param enableRbac bool = true
@description('Specifies if LOCAL accounts in kubernetes permission model should be enabled or not')
param disableLocalAccounts bool = false
@description('Specifies if AzureRbac accounts in kubernetes permission model should be enabled or not. 2022-11 needs to be false, since Azure ML')
param enableAzureRbac bool = false
@allowed([
  'loadBalancer'
  'userDefinedRouting'
  'none'
])
param outboundType string = 'loadBalancer' // 'userDefinedRouting' + Azure firewall on subnet if you want private IP: https://learn.microsoft.com/en-us/azure/aks/egress-outboundtype

@description('Specifies agent pool profile settings in a array with hashmaps format')
param agentPoolProfiles array

@description('Specifies the name of the resource group that is used for node pool resources')
param nodeResourceGroup string

param aksServiceCidr string = '10.0.0.0/16'
param aksDnsServiceIP string = '10.0.0.10'
param aksExists bool = false
//param privateDNSZone string
//param authorizedIPRanges array

//skuName: 'basic' // basic -> 2023-02-01: 'base'
//skuTier: 'paid' // free, paid -> 2023-02-01: free, standard
resource aksCluster 'Microsoft.ContainerService/managedClusters@2021-03-01' = if(!aksExists) {
  name: name
  tags: tags
  location: location
  sku: {
    name: skuName
    tier: skuTier
  }
  identity: {
    type: 'SystemAssigned'
  }
  properties: {
    kubernetesVersion: kubernetesVersion
    dnsPrefix: dnsPrefix
    disableLocalAccounts:disableLocalAccounts
    enableRBAC: enableRbac
    agentPoolProfiles: agentPoolProfiles
    nodeResourceGroup: nodeResourceGroup
    networkProfile: {
      networkPlugin: 'azure'//'kubenet'
      outboundType: outboundType // 'userDefinedRouting' if you want private IP
      serviceCidr: aksServiceCidr
      dnsServiceIP: aksDnsServiceIP
      dockerBridgeCidr: '172.17.0.1/16'
      loadBalancerSku: 'standard'
    }
    apiServerAccessProfile: { // https://learn.microsoft.com/en-us/azure/aks/egress-outboundtype
      enablePrivateCluster: true // The egress mode is default ourbound_type=loadBalancer, which requires a public IP. you can change this with outbound_type=userDefinedRouting and Azure Firewall
    }
  }
  
}

output aksId string = aksCluster.id
